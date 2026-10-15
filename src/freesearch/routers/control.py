"""Provider control-plane service and REST router (Stage 5).

This module is the control surface's service layer: it resolves effective
provider configuration (defaults <- env JSON <- persisted), applies the
persisted routing policy, resolves secret presence without ever exposing or
persisting raw keys, and serves the ``/api/v1`` endpoints. Provider keys
are written only through the injected :class:`SecretStore`; fingerprints are
derived in memory and are the only secret-adjacent value ever persisted.
"""

import asyncio
import inspect
import time
from collections.abc import Callable
from contextlib import suppress
from datetime import UTC, datetime
from decimal import Decimal
from hashlib import sha256
from typing import Annotated, Any, Literal

import httpx
from fastapi import Depends, FastAPI, HTTPException, Request
from pydantic import SecretStr, ValidationError

from freesearch.adapters.base import ProviderAdapter
from freesearch.adapters.registry import adapter_factory
from freesearch.configuration.provider_config import (
    ProviderConfig,
    ProviderConfigError,
    ProviderConfigUpdate,
    get_provider_configs,
    system_support_mask,
)
from freesearch.infrastructure.http import create_async_client
from freesearch.infrastructure.logging import redact_secrets
from freesearch.infrastructure.secrets import AsyncSecretStore, ProviderName
from freesearch.models.contracts import (
    BreakerState,
    CircuitBreakerState,
    CircuitBreakerStatusResponse,
    CostPreset,
    HealthStatus,
    ManualQuota,
    ManualQuotaResponse,
    ManualQuotaUpdate,
    ProviderHealth,
    ProviderStatusResponse,
    ProviderTestResponse,
    RoutingConfigResponse,
    RoutingConfigUpdate,
    SecretPresence,
    SecretStatusResponse,
    SetSecretRequest,
)
from freesearch.models.provider_access import ALL_BITS, validate_mask
from freesearch.models.provider_limits import AuthMode
from freesearch.models.users import UserPrincipal
from freesearch.persistence.storage import SQLiteRepository, register_setting_listener
from freesearch.routers.auth import require_admin, require_control_reader
from freesearch.services.manual_quota import clear_manual_quota as clear_shared_manual_quota
from freesearch.services.manual_quota import load_manual_quota as load_shared_manual_quota
from freesearch.services.manual_quota import manual_quota_response
from freesearch.services.manual_quota import persist_manual_quota as persist_shared_manual_quota
from freesearch.services.monitoring import latency_p95_ms
from freesearch.services.parallel_oauth import (
    PARALLEL_API_BASE_URL,
    PARALLEL_PLATFORM_BASE_URL,
    DeviceCodeResponse,
    OAuthAlreadyPaired,
    OAuthStatusResponse,
    disconnect_oauth,
    query_oauth_status,
    start_device_flow,
)

SecretSource = Literal["encrypted_db", "none"]

#: Role gates from the approved P1a matrix. ``require_admin`` guards every
#: control mutation and every provider OAuth handler; ``require_control_reader``
#: guards the sanitized reads. Both answer 401 before 403, and both run before
#: any provider call or persistence write. Provider OAuth status follows its side
#: effects, not its HTTP verb, so the GET requires Admin.
_AdminPrincipal = Annotated[UserPrincipal, Depends(require_admin)]
_ReaderPrincipal = Annotated[UserPrincipal, Depends(require_control_reader)]

_ROUTING_KEY = "routing"

_MANUAL_QUOTA_PREFIX = "manual_quota:"


def register_control_routes(app: FastAPI) -> None:
    """Register the control-plane endpoints on ``app`` under ``/api/v1``.

    Routes are registered directly on the application router (rather than via
    ``include_router``) so every entry in ``app.routes`` stays a plain route
    with a ``path`` attribute.
    """

    @app.get("/api/v1/providers", response_model=list[ProviderStatusResponse])
    async def list_providers(
        _principal: _ReaderPrincipal, request: Request
    ) -> list[ProviderStatusResponse]:
        """Enumerate every canonical provider with its current control state."""

        repository: SQLiteRepository | None = request.app.state.repository
        policy = await routing_policy(repository)
        entries = [
            await _provider_entry(
                repository,
                name,
                request.app.state.secret_store,
            )
            for name in ProviderName
        ]
        ordered = sorted(entries, key=lambda entry: (entry.priority, entry.provider_id))
        if policy.cost_optimization_preset is CostPreset.FREE_FIRST:
            return _free_first_order(ordered)
        return ordered

    @app.get("/api/v1/providers/{provider_id}", response_model=ProviderStatusResponse)
    async def get_provider(
        _principal: _ReaderPrincipal, provider_id: str, request: Request
    ) -> ProviderStatusResponse:
        """Return one canonical provider's control-plane status entry."""

        name = _require_provider(provider_id)
        repository: SQLiteRepository | None = request.app.state.repository
        return await _provider_entry(repository, name, request.app.state.secret_store)

    @app.patch("/api/v1/providers/{provider_id}", response_model=ProviderStatusResponse)
    async def patch_provider(
        _principal: _AdminPrincipal,
        provider_id: str,
        request: Request,
        update: ProviderConfigUpdate | None = None,
    ) -> ProviderStatusResponse:
        """Merge a partial provider config update onto the effective record.

        The body is optional so an unknown provider identifier always surfaces
        as 404 even when the caller sends no JSON body at all. The merge runs
        inside one atomic read-modify-write transaction.
        """

        name = _require_provider(provider_id)
        repository: SQLiteRepository | None = request.app.state.repository
        await patch_provider_config(repository, name, update or ProviderConfigUpdate())
        if name is ProviderName.TAVILY:
            # A Tavily PATCH may change the rail or the PAYGO choice, so the
            # live adapter is rebuilt against the merged record on demand.
            with suppress(HTTPException):
                await _ensure_provider_adapter(request, name, force_rebuild=True)
        return await _provider_entry(repository, name, request.app.state.secret_store)

    @app.post("/api/v1/providers/{provider_id}/test", response_model=ProviderTestResponse)
    async def test_provider(
        _principal: _AdminPrincipal, provider_id: str, request: Request
    ) -> ProviderTestResponse:
        """Run a timed health probe; UNKNOWN counts as ok with explanatory detail."""

        name = _require_provider(provider_id)
        adapter = await _ensure_provider_adapter(request, name)
        started_at = time.perf_counter()
        try:
            observation = await adapter.health()
        except Exception as exc:
            return ProviderTestResponse(
                provider=name.value,
                ok=False,
                status=HealthStatus.UNAVAILABLE,
                latency_ms=_elapsed_ms(started_at),
                detail=redact_secrets(str(exc)) or "health probe failed",
                checked_at=datetime.now(UTC),
            )
        return ProviderTestResponse(
            provider=name.value,
            ok=observation.status is not HealthStatus.UNAVAILABLE,
            status=observation.status,
            latency_ms=_elapsed_ms(started_at),
            detail=_probe_detail(observation.status),
            checked_at=observation.checked_at,
        )

    @app.post(
        "/api/v1/providers/{provider_id}/circuit-breaker/reset",
        response_model=CircuitBreakerStatusResponse,
    )
    async def reset_circuit_breaker(
        _principal: _AdminPrincipal, provider_id: str, request: Request
    ) -> CircuitBreakerStatusResponse:
        """Persist a closed breaker state and report it; idempotent."""

        name = _require_provider(provider_id)
        now = datetime.now(UTC)
        await persist_breaker(request.app.state.repository, name, BreakerState.CLOSED, now)
        return CircuitBreakerStatusResponse(
            provider=name.value, state=BreakerState.CLOSED, updated_at=now
        )

    @app.put("/api/v1/providers/{provider_id}/secret", response_model=SecretStatusResponse)
    async def put_secret(
        _principal: _AdminPrincipal,
        provider_id: str,
        body: SetSecretRequest,
        request: Request,
    ) -> SecretStatusResponse:
        """Store the key write-only in the encrypted vault and report its status."""

        name = _require_provider(provider_id)
        raw_key = body.key.get_secret_value()
        store = request.app.state.secret_store
        await _store_set(store, name.value, raw_key)
        now = datetime.now(UTC)
        key, source = await _resolve_secret(name, store)
        fingerprint = secret_fingerprint(name.value, key) if key is not None else None
        await persist_secret_record(request.app.state.repository, name, fingerprint, now)
        with suppress(HTTPException):
            await _ensure_provider_adapter(request, name, force_rebuild=True)
        await _notify_credential_change(request, name)
        return SecretStatusResponse(
            provider=name.value,
            presence=_secret_presence(name, key),
            fingerprint=fingerprint,
            updated_at=now,
            source=source,
        )

    @app.delete("/api/v1/providers/{provider_id}/secret", response_model=SecretStatusResponse)
    async def delete_secret(
        _principal: _AdminPrincipal, provider_id: str, request: Request
    ) -> SecretStatusResponse:
        """Remove the encrypted vault key idempotently and report its status."""

        name = _require_provider(provider_id)
        store = request.app.state.secret_store
        await _store_delete(store, name.value)
        now = datetime.now(UTC)
        key, source = await _resolve_secret(name, store)
        fingerprint = secret_fingerprint(name.value, key) if key is not None else None
        await persist_secret_record(request.app.state.repository, name, fingerprint, now)
        await _eject_provider_adapter(request, name)
        await _notify_credential_change(request, name)
        repo: SQLiteRepository | None = request.app.state.repository
        if (
            repo is not None
            and key is None
            and name is not ProviderName.KEENABLE
            and name is not ProviderName.TAVILY
        ):
            with suppress(Exception):
                await repo.record_health(
                    ProviderHealth(
                        provider=name.value,
                        status=HealthStatus.UNAVAILABLE,
                        checked_at=now,
                        message="API key deleted",
                    )
                )
        return SecretStatusResponse(
            provider=name.value,
            presence=_secret_presence(name, key),
            fingerprint=fingerprint,
            updated_at=now,
            source=source,
        )

    @app.get("/api/v1/routing/config", response_model=RoutingConfigResponse)
    async def get_routing_config(
        _principal: _ReaderPrincipal, request: Request
    ) -> RoutingConfigResponse:
        """Return the persisted global routing defaults."""

        return await routing_policy(request.app.state.repository)

    @app.put("/api/v1/routing/config", response_model=RoutingConfigResponse)
    async def put_routing_config(
        _principal: _AdminPrincipal, update: RoutingConfigUpdate, request: Request
    ) -> RoutingConfigResponse:
        """Merge and persist a routing-policy update; omitted fields are kept."""

        repository: SQLiteRepository | None = request.app.state.repository
        current = await routing_policy(repository)
        merged = RoutingConfigResponse(
            fallback_policy=update.fallback_policy or current.fallback_policy,
            cost_optimization_preset=update.cost_optimization_preset
            or current.cost_optimization_preset,
            max_attempts=update.max_attempts
            if update.max_attempts is not None
            else current.max_attempts,
        )
        await persist_routing_config(repository, merged)
        return merged

    _register_manual_quota_routes(app)
    _register_oauth_routes(app)


def _register_manual_quota_routes(app: FastAPI) -> None:
    """Register billing anchors; Exa allowance also seeds its local quota."""

    @app.get(
        "/api/v1/providers/{provider_id}/manual-quota",
        response_model=ManualQuotaResponse,
    )
    async def get_manual_quota(
        _principal: _ReaderPrincipal, provider_id: str, request: Request
    ) -> ManualQuotaResponse:
        """Return the operator-entered billing anchor; never touches routing."""

        name = _require_provider(provider_id)
        stored = await load_manual_quota(request.app.state.repository, name)
        if stored is None:
            raise HTTPException(status_code=404, detail=f"no manual quota for {provider_id!r}")
        return stored

    @app.put(
        "/api/v1/providers/{provider_id}/manual-quota",
        response_model=ManualQuotaResponse,
    )
    async def put_manual_quota(
        _principal: _AdminPrincipal,
        provider_id: str,
        update: ManualQuotaUpdate,
        request: Request,
    ) -> ManualQuotaResponse:
        """Store the billing anchor and return the ESTIMATED capacity view."""

        name = _require_provider(provider_id)
        response = await persist_manual_quota(
            request.app.state.repository, name, update, datetime.now(UTC)
        )
        await _apply_exa_manual_credits(request, name, update.allowance)
        await _notify_manual_anchor(request, name, response)
        return response

    @app.delete("/api/v1/providers/{provider_id}/manual-quota", status_code=204)
    async def delete_manual_quota(
        _principal: _AdminPrincipal, provider_id: str, request: Request
    ) -> None:
        """Clear the billing anchor and any Exa manual-credit limit idempotently."""

        name = _require_provider(provider_id)
        await clear_manual_quota(request.app.state.repository, name)
        await _apply_exa_manual_credits(request, name, None)
        await _notify_manual_anchor(request, name, None)


async def _notify_manual_anchor(
    request: Request, provider: ProviderName, anchor: ManualQuotaResponse | None
) -> None:
    """Project a manual native anchor into the provider limit store.

    The anchor is an operator estimate, so it never replaces a fresh
    authoritative vendor observation, and a deletion restores the unknown state
    instead of a manufactured zero balance.
    """

    limits = getattr(request.app.state, "limits", None)
    if limits is None:
        return
    with suppress(Exception):
        await limits.apply_manual_anchor(provider.value, anchor)


async def _notify_credential_change(request: Request, provider: ProviderName) -> None:
    """Invalidate stale credential generations in the provider limit store."""

    limits = getattr(request.app.state, "limits", None)
    if limits is None:
        return
    with suppress(Exception):
        await limits.credential_changed(provider.value)


async def _apply_exa_manual_credits(
    request: Request, provider: ProviderName, credits: Decimal | None
) -> None:
    """Persist and apply Exa prepaid credits through the atomic partial seam."""
    if provider is not ProviderName.EXA:
        return
    await patch_provider_config(
        request.app.state.repository,
        provider,
        ProviderConfigUpdate(exa_manual_starting_credits_usd=credits),
    )
    routes: list[ProviderAdapter] = request.app.state._routes
    adapter = next((route for route in routes if route.name == provider.value), None)
    setter = getattr(adapter, "set_manual_starting_credits", None)
    if callable(setter):
        setter(credits)


def _require_oauth_provider(provider_id: str) -> ProviderName:
    """Return PARALLEL for OAuth routes; other known providers are unsupported."""

    name = _require_provider(provider_id)
    if name is not ProviderName.PARALLEL:
        raise HTTPException(status_code=404, detail=f"oauth-not-supported for {provider_id!r}")
    return name


def _oauth_base_urls(request: Request) -> tuple[str, str]:
    """Return the injectable OAuth base URLs, defaulting to the Parallel hosts."""

    platform_base = getattr(request.app.state, "oauth_platform_base_url", None)
    api_base = getattr(request.app.state, "oauth_api_base_url", None)
    return (
        platform_base or PARALLEL_PLATFORM_BASE_URL,
        api_base or PARALLEL_API_BASE_URL,
    )


def _register_oauth_routes(app: FastAPI) -> None:
    """Register the Parallel OAuth device-flow routes (frozen contract)."""

    @app.post(
        "/api/v1/providers/{provider_id}/oauth/device-code",
        response_model=DeviceCodeResponse,
    )
    async def start_oauth_device_code(
        _principal: _AdminPrincipal, provider_id: str, request: Request
    ) -> DeviceCodeResponse:
        """Initiate a device flow; 409 while paired, never destructive on 409."""

        _require_oauth_provider(provider_id)
        platform_base, api_base = _oauth_base_urls(request)
        provided = getattr(request.app.state, "oauth_http_client", None)
        try:
            if provided is not None:
                return await start_device_flow(
                    secret_store=request.app.state.secret_store,
                    repository=request.app.state.repository,
                    http_client=provided,
                    platform_base_url=platform_base,
                    api_base_url=api_base,
                )
            async with create_async_client() as client:
                return await start_device_flow(
                    secret_store=request.app.state.secret_store,
                    repository=request.app.state.repository,
                    http_client=client,
                    platform_base_url=platform_base,
                    api_base_url=api_base,
                )
        except OAuthAlreadyPaired as exc:
            raise HTTPException(
                status_code=409, detail=redact_secrets(str(exc)) or "oauth already paired"
            ) from None
        except Exception as exc:
            raise HTTPException(
                status_code=502, detail=redact_secrets(str(exc)) or "oauth flow failed"
            ) from None

    @app.get(
        "/api/v1/providers/{provider_id}/oauth/status",
        response_model=OAuthStatusResponse,
    )
    async def oauth_status(
        _principal: _AdminPrincipal, provider_id: str, request: Request
    ) -> OAuthStatusResponse:
        """Report pairing status with one bounded token attempt unless terminal."""

        _require_oauth_provider(provider_id)
        platform_base, api_base = _oauth_base_urls(request)
        provided = getattr(request.app.state, "oauth_http_client", None)
        try:
            if provided is not None:
                return await query_oauth_status(
                    secret_store=request.app.state.secret_store,
                    repository=request.app.state.repository,
                    http_client=provided,
                    platform_base_url=platform_base,
                    api_base_url=api_base,
                )
            async with create_async_client() as client:
                return await query_oauth_status(
                    secret_store=request.app.state.secret_store,
                    repository=request.app.state.repository,
                    http_client=client,
                    platform_base_url=platform_base,
                    api_base_url=api_base,
                )
        except Exception as exc:
            raise HTTPException(
                status_code=502, detail=redact_secrets(str(exc)) or "oauth status failed"
            ) from None

    @app.delete("/api/v1/providers/{provider_id}/oauth", status_code=204)
    async def delete_oauth(_principal: _AdminPrincipal, provider_id: str, request: Request) -> None:
        """Revoke bearer material before deleting it; idempotent."""

        _require_oauth_provider(provider_id)
        platform_base, api_base = _oauth_base_urls(request)
        provided = getattr(request.app.state, "oauth_http_client", None)
        with suppress(Exception):
            if provided is not None:
                await disconnect_oauth(
                    secret_store=request.app.state.secret_store,
                    repository=request.app.state.repository,
                    http_client=provided,
                    platform_base_url=platform_base,
                    api_base_url=api_base,
                )
            else:
                async with create_async_client() as client:
                    await disconnect_oauth(
                        secret_store=request.app.state.secret_store,
                        repository=request.app.state.repository,
                        http_client=client,
                        platform_base_url=platform_base,
                        api_base_url=api_base,
                    )


def secret_fingerprint(provider: str, key: str) -> str:
    """Return the stable masked fingerprint for ``key``; never the key itself."""

    prefix = provider[:3].upper()
    suffix = sha256(key.encode()).hexdigest()[-4:]
    return f"{prefix}_{'•' * 8}{suffix}"


SecretBackend = AsyncSecretStore


async def _store_get(store: SecretBackend, name: str) -> str | None:
    """Read sync or async stores, degrading storage failures to ``None``."""

    try:
        value = store.get(name)
        return await value if inspect.isawaitable(value) else value
    except Exception:
        return None


async def _store_set(store: SecretBackend, name: str, value: str) -> None:
    result = store.set(name, value)
    if inspect.isawaitable(result):
        await result


async def _store_delete(store: SecretBackend, name: str) -> None:
    result = store.delete(name)
    if inspect.isawaitable(result):
        await result


async def _resolve_secret(
    provider: ProviderName, store: SecretBackend
) -> tuple[str | None, SecretSource]:
    """Resolve a provider key from the encrypted vault only."""

    stored_value = await _store_get(store, provider.value)
    return (stored_value, "encrypted_db") if stored_value else (None, "none")


def _secret_presence(provider: ProviderName, key: str | None) -> SecretPresence:
    """Return presence: configured, keyless public (Keenable, Tavily), or missing.

    Tavily joins Keenable on the keyless public tier: a missing key is an
    available public transport, never a missing-credential condition.
    """

    if key is not None:
        return SecretPresence.CONFIGURED
    if provider is ProviderName.KEENABLE or provider is ProviderName.TAVILY:
        return SecretPresence.KEYLESS_PUBLIC
    return SecretPresence.MISSING


def _require_provider(provider_id: str) -> ProviderName:
    """Return the canonical provider for ``provider_id`` or raise 404."""

    try:
        return ProviderName(provider_id)
    except ValueError:
        raise HTTPException(status_code=404, detail=f"unknown provider {provider_id!r}") from None


def _iso(value: datetime) -> str:
    """Return a UTC, lexicographically sortable ISO timestamp."""

    return value.astimezone(UTC).isoformat()


def _elapsed_ms(started_at: float) -> int:
    """Return whole milliseconds elapsed since ``started_at`` (never negative)."""

    return int((time.perf_counter() - started_at) * 1000)


def _provider_key(provider: ProviderName) -> str:
    return f"provider.{provider.value}"


def _breaker_key(provider: ProviderName) -> str:
    return f"provider.{provider.value}.breaker"


def _secret_key(provider: ProviderName) -> str:
    return f"secret.{provider.value}"


def _config_payload(payload: Any) -> dict[str, Any] | None:
    """Return the stored provider-config mapping from a runtime-setting payload."""

    if not isinstance(payload, dict):
        return None
    config = payload.get("config")
    return config if isinstance(config, dict) else None


async def _safe_runtime_setting(
    repository: SQLiteRepository | None, key: str, *, strict: bool = False
) -> Any:
    """Read a runtime setting, degrading repository failures to ``None``.

    Control reads are best-effort like monitoring reads: a repository that
    cannot serve runtime settings (or does not implement them) yields the
    configuration defaults instead of failing the request. Strict callers are
    request paths, so they observe the repository error instead.
    """

    if repository is None:
        return None
    try:
        return await repository.get_runtime_setting(key)
    except Exception:
        if strict:
            raise
        return None


def _provider_base(provider: ProviderName) -> ProviderConfig:
    """Return the base record with the system support mask applied."""

    base = get_provider_configs()[provider]
    return base.model_copy(update={"support_mask": system_support_mask(provider)})


def _reconciled_config(provider: ProviderName, config: ProviderConfig) -> ProviderConfig:
    """Return ``config`` with the system support mask applied."""

    return config.model_copy(update={"support_mask": system_support_mask(provider)})


def _decode_stored_access(payload: dict[str, Any]) -> dict[str, Any]:
    """Decode a legacy stored global value into an enable mask."""

    if "enabled" not in payload:
        return dict(payload)
    if "enable_mask" in payload or "support_mask" in payload:
        raise ValueError("ambiguous stored provider access values")
    legacy = payload["enabled"]
    if not isinstance(legacy, bool):
        raise ValueError("stored provider global value must be Boolean")
    decoded = dict(payload)
    decoded.pop("enabled")
    decoded["enable_mask"] = ALL_BITS if legacy else 0
    return decoded


def _merge_stored_config(base: ProviderConfig, stored: dict[str, Any]) -> ProviderConfig:
    """Merge stored fields onto ``base`` and validate the merged record.

    The stored support mask is validated here, before system reconciliation.
    """

    merged = base.model_dump()
    estimates = stored.get("free_tier_estimates")
    if isinstance(estimates, dict):
        merged["free_tier_estimates"].update(estimates)
    for name, value in stored.items():
        if name == "free_tier_estimates":
            continue
        merged[name] = value
    return ProviderConfig.model_validate(merged)


def _stored_access(provider: ProviderName, payload: dict[str, Any]) -> dict[str, Any]:
    """Return the payload with decoded and validated access values.

    A legacy global Boolean decodes into all enable bits. An ambiguous,
    non-Boolean, or out-of-range access value raises :class:`ProviderConfigError`.
    The caller then keeps the valid stored access choice through
    :func:`_fallback_config`.
    """

    try:
        decoded = _decode_stored_access(payload)
        if "enable_mask" in decoded:
            decoded["enable_mask"] = validate_mask(decoded["enable_mask"], field="enable_mask")
        if "support_mask" in decoded:
            decoded["support_mask"] = validate_mask(decoded["support_mask"], field="support_mask")
    except ValueError as error:
        raise ProviderConfigError(
            f"invalid stored access value for provider {provider.value}"
        ) from error
    return decoded


def _fallback_config(
    provider: ProviderName, base: ProviderConfig, payload: dict[str, Any]
) -> ProviderConfig:
    """Return ``base`` with any valid stored access choice preserved.

    An invalid non-access field keeps the current base fallback behavior. An
    invalid access value falls back to the base masks.
    """

    enable = payload.get("enable_mask")
    if enable is None and isinstance(payload.get("enabled"), bool):
        enable = ALL_BITS if payload["enabled"] else 0
    if enable is None:
        return base
    try:
        validated = validate_mask(enable, field="enable_mask")
    except ValueError:
        return base
    return _reconciled_config(provider, base.model_copy(update={"enable_mask": validated}))


def _current_config(
    provider: ProviderName, base: ProviderConfig, payload: dict[str, Any]
) -> ProviderConfig:
    """Return the current stored record for a read-modify-write callback.

    A bad non-access field keeps the base value for that field. The valid
    stored access choice survives, so a later write cannot reset the admin bits.
    """

    try:
        stored = _stored_access(provider, payload)
    except ProviderConfigError:
        return _fallback_config(provider, base, payload)
    try:
        return _merge_stored_config(base, stored)
    except (ValidationError, ValueError):
        return _fallback_config(provider, base, stored)


def _provider_payload(config: ProviderConfig) -> dict[str, Any]:
    """Return the stored runtime-setting payload for one provider record."""

    return {
        "config": {
            "enable_mask": config.enable_mask,
            "support_mask": config.support_mask,
            "priority": config.priority,
            "free_tier_estimates": {
                operation.value: str(units)
                for operation, units in config.free_tier_estimates.items()
            },
            "reset_schedule": config.reset_schedule,
            "parallel_free_seed_usd": _decimal_text(config.parallel_free_seed_usd),
            "exa_monthly_budget_usd": _decimal_text(config.exa_monthly_budget_usd),
            "exa_manual_starting_credits_usd": _decimal_text(
                config.exa_manual_starting_credits_usd
            ),
            "tavily_key_environment": config.tavily_key_environment,
            "tavily_paygo_enabled": config.tavily_paygo_enabled,
        }
    }


def _decimal_text(value: Decimal | None) -> str | None:
    """Return the stored text of an optional Decimal."""

    return str(value) if value is not None else None


_CONFIG_CACHE: dict[tuple[int, str], ProviderConfig] = {}
_POLICY_CACHE: dict[int, RoutingConfigResponse] = {}


def clear_config_cache(
    repository: SQLiteRepository | None = None, provider: str | None = None
) -> None:
    """Clear cached provider and policy configurations."""

    if repository is None:
        if provider is None:
            _CONFIG_CACHE.clear()
            _POLICY_CACHE.clear()
        else:
            for key in [k for k in _CONFIG_CACHE if k[1] == provider]:
                _CONFIG_CACHE.pop(key, None)
    else:
        repo_id = id(repository)
        _POLICY_CACHE.pop(repo_id, None)
        if provider is None:
            for key in [k for k in _CONFIG_CACHE if k[0] == repo_id]:
                _CONFIG_CACHE.pop(key, None)
        else:
            _CONFIG_CACHE.pop((repo_id, provider), None)


def _on_setting_changed(repo: Any, key: str) -> None:
    clear_config_cache(repo)


register_setting_listener(_on_setting_changed)


async def effective_provider_config(
    repository: SQLiteRepository | None, provider: ProviderName, *, strict: bool = False
) -> ProviderConfig:
    """Return defaults <- env JSON <- persisted configuration for ``provider``.

    The base record comes from :func:`get_provider_configs` (defaults merged
    with ``FREESEARCH_PROVIDER_CONFIG_OVERRIDES``); a persisted record wins
    over it by applying the stored fields onto it. A stored legacy global
    value decodes into all enable bits before the merge.

    A payload with an invalid access value is self-healed on a non-strict read
    and raises :class:`ProviderConfigError` on a strict read. A payload with an
    invalid non-access field keeps the base value for that field and preserves
    the valid stored access choice on both read modes.

    The system support mask always wins. A stored record with a stale support
    mask or a missing mask pair is written back through the atomic
    runtime-setting helper. That write is best-effort, so a store error cannot
    fail the read.
    """

    base = _provider_base(provider)
    payload = _config_payload(
        await _safe_runtime_setting(repository, _provider_key(provider), strict=strict)
    )
    if payload is None:
        await _reconcile_provider_config(repository, provider)
        return base
    try:
        stored = _stored_access(provider, payload)
    except ProviderConfigError:
        if strict:
            raise
        return _fallback_config(provider, base, payload)
    try:
        config = _merge_stored_config(base, stored)
    except (ValidationError, ValueError):
        return _fallback_config(provider, base, stored)
    if _needs_reconciliation(stored, system_support_mask(provider)):
        await _reconcile_provider_config(repository, provider)
    return _reconciled_config(provider, config)


def _needs_reconciliation(stored: dict[str, Any], support_mask: int) -> bool:
    """Return whether the stored record needs a support or mask write."""

    if "enable_mask" not in stored or "support_mask" not in stored:
        return True
    return bool(stored["support_mask"] != support_mask)


async def _reconcile_provider_config(
    repository: SQLiteRepository | None, provider: ProviderName
) -> None:
    """Write the reconciled record for ``provider`` on a best-effort basis.

    The write is a persistence side effect. The caller already holds the
    reconciled in-memory record, so a store error (for example a held write
    lock) must not fail a read request. The next read retries the write.
    """

    if repository is None:
        return

    def _merge(current_json: Any) -> Any:
        current = _config_payload(current_json)
        base = _provider_base(provider)
        config = base if current is None else _current_config(provider, base, current)
        return _provider_payload(_reconciled_config(provider, config))

    with suppress(Exception):
        await repository.update_runtime_setting(_provider_key(provider), _merge)
        clear_config_cache(repository, provider.value)


async def patch_provider_config(
    repository: SQLiteRepository | None,
    provider: ProviderName,
    update: ProviderConfigUpdate,
) -> ProviderConfig:
    """Apply the explicit fields of ``update`` inside one atomic merge.

    The callback decodes the newest stored record, applies only the explicit
    update fields, sets the support mask from the system map, and removes the
    old stored Boolean. A complete ``enable_mask`` replaces every enable bit.
    A bad non-access field keeps the base value and preserves the valid stored
    access choice.
    """

    base = _provider_base(provider)
    if repository is None:
        return _reconciled_config(provider, update.apply_to(base))
    outcome: dict[str, ProviderConfig] = {}

    def _merge(current_json: Any) -> Any:
        current = _config_payload(current_json)
        start = base if current is None else _current_config(provider, base, current)
        config = _reconciled_config(provider, update.apply_to(start))
        outcome["config"] = config
        return _provider_payload(config)

    await repository.update_runtime_setting(_provider_key(provider), _merge)
    clear_config_cache(repository, provider.value)
    return outcome["config"]


async def initialize_provider_configs(repository: SQLiteRepository | None) -> None:
    """Materialize a canonical configuration record for every provider.

    REST and MCP call this before they accept requests. An injected repository
    without a lifespan is covered by the canonical read path, which
    initializes a missing record on demand. A ``None`` repository writes
    nothing.
    """

    if repository is None:
        return
    for provider in ProviderName:
        await _reconcile_provider_config(repository, provider)


async def effective_config_for_name(
    repository: SQLiteRepository | None, name: str, *, strict: bool = False
) -> ProviderConfig:
    """Canonical-name wrapper for request-path lookups; unknown names default."""

    if repository is not None:
        cache_key = (id(repository), name)
        cached = _CONFIG_CACHE.get(cache_key)
        if cached is not None:
            return cached

    try:
        provider = ProviderName(name)
    except ValueError:
        return ProviderConfig()
    config = await effective_provider_config(repository, provider, strict=strict)
    if repository is not None:
        _CONFIG_CACHE[(id(repository), name)] = config
    return config


async def persist_provider_config(
    repository: SQLiteRepository | None, provider: ProviderName, config: ProviderConfig
) -> None:
    """Persist the full merged provider configuration record; nothing without a repo."""

    if repository is None:
        return
    await repository.set_runtime_setting(_provider_key(provider), _provider_payload(config))
    clear_config_cache(repository, provider.value)


async def routing_policy(repository: SQLiteRepository | None) -> RoutingConfigResponse:
    """Return the persisted routing policy or its defaults; corrupt data defaults."""

    if repository is not None:
        cached = _POLICY_CACHE.get(id(repository))
        if cached is not None:
            return cached
    payload = await _safe_runtime_setting(repository, _ROUTING_KEY)
    policy = RoutingConfigResponse()
    if isinstance(payload, dict):
        with suppress(ValidationError):
            policy = RoutingConfigResponse.model_validate(payload)
    if repository is not None:
        _POLICY_CACHE[id(repository)] = policy
    return policy


async def persist_routing_config(
    repository: SQLiteRepository | None, policy: RoutingConfigResponse
) -> None:
    """Persist the routing policy; ``max_attempts`` is stored-validated-deferred.

    The value is validated (``ge=1``) and stored for the future resilience
    wiring; runner construction is deliberately untouched this round.
    """

    if repository is None:
        return
    await repository.set_runtime_setting(_ROUTING_KEY, policy.model_dump(mode="json"))
    _POLICY_CACHE.pop(id(repository), None)


async def load_breaker(
    repository: SQLiteRepository | None, provider: ProviderName
) -> CircuitBreakerState:
    """Return the persisted breaker state, defaulting to a closed circuit."""

    payload = await _safe_runtime_setting(repository, _breaker_key(provider))
    if isinstance(payload, dict):
        with suppress(ValidationError):
            return CircuitBreakerState.model_validate(payload)
    return CircuitBreakerState(state=BreakerState.CLOSED, updated_at=datetime.now(UTC))


async def persist_breaker(
    repository: SQLiteRepository | None,
    provider: ProviderName,
    state: BreakerState,
    now: datetime,
) -> None:
    """Persist the breaker state and its update instant."""

    if repository is None:
        return
    await repository.set_runtime_setting(
        _breaker_key(provider), {"state": state.value, "updated_at": _iso(now)}
    )


async def persist_secret_record(
    repository: SQLiteRepository | None,
    provider: ProviderName,
    fingerprint: str | None,
    now: datetime,
) -> None:
    """Persist the masked fingerprint bookkeeping record; never a raw key."""

    if repository is None:
        return
    await repository.set_runtime_setting(
        _secret_key(provider), {"fingerprint": fingerprint, "updated_at": _iso(now)}
    )


def _manual_quota_key(provider: ProviderName) -> str:
    """Return the runtime-settings key for a provider billing anchor."""

    return f"{_MANUAL_QUOTA_PREFIX}{provider.value}"


def _manual_quota_response(
    provider: ProviderName, quota: ManualQuota, updated_at: datetime
) -> ManualQuotaResponse:
    """Delegate the ESTIMATED capacity view to the shared anchor service."""

    return manual_quota_response(provider, quota, updated_at)


async def load_manual_quota(
    repository: SQLiteRepository | None, provider: ProviderName
) -> ManualQuotaResponse | None:
    """Delegate the stored billing anchor read to the shared anchor service."""

    return await load_shared_manual_quota(repository, provider)


async def persist_manual_quota(
    repository: SQLiteRepository | None,
    provider: ProviderName,
    update: ManualQuotaUpdate,
    now: datetime,
) -> ManualQuotaResponse:
    """Delegate the billing anchor write to the shared anchor service."""

    return await persist_shared_manual_quota(repository, provider, update, now)


async def clear_manual_quota(repository: SQLiteRepository | None, provider: ProviderName) -> None:
    """Clear the billing anchor idempotently; unknown providers never reach here."""

    await clear_shared_manual_quota(repository, provider)


async def _latest_health(
    repository: SQLiteRepository | None, provider: str
) -> ProviderHealth | None:
    """Return the newest health observation; read failures degrade to ``None``."""

    if repository is None:
        return None
    try:
        return await repository.latest_health(provider)
    except Exception:
        return None


async def _provider_entry(
    repository: SQLiteRepository | None,
    provider: ProviderName,
    store: SecretBackend,
) -> ProviderStatusResponse:
    """Assemble one provider's control-plane status entry."""

    config = await effective_provider_config(repository, provider)
    breaker = await load_breaker(repository, provider)
    health = await _latest_health(repository, provider.value)
    key, _source = await _resolve_secret(provider, store)
    reported_health = health.status if health is not None else None
    if key is None and provider not in (ProviderName.KEENABLE, ProviderName.TAVILY):
        reported_health = None
    return ProviderStatusResponse(
        provider_id=provider.value,
        enabled=config.enabled,
        enable_mask=config.enable_mask,
        support_mask=config.support_mask,
        priority=config.priority,
        health=reported_health,
        circuit_breaker=breaker,
        latency_p95_ms=await latency_p95_ms(repository, provider.value),
        secret_presence=_secret_presence(provider, key),
        free_tier_estimates=config.free_tier_estimates,
        reset_schedule=config.reset_schedule,
        # The confirmed stored environment readback rides only on Tavily;
        # every other provider keeps the null default.
        tavily_key_environment=(
            config.tavily_key_environment if provider is ProviderName.TAVILY else None
        ),
    )


def _free_first_order(
    ordered: list[ProviderStatusResponse],
) -> list[ProviderStatusResponse]:
    """Pin Keenable to the front when the cost preset is ``free_first``."""

    pinned = [entry for entry in ordered if entry.provider_id == "keenable"]
    rest = [entry for entry in ordered if entry.provider_id != "keenable"]
    return pinned + rest


def _restart_hint(provider: str) -> str:
    """Return the actionable 503 detail for an unconstructed provider."""

    return (
        f"provider {provider} is not configured: store a key in the encrypted vault "
        f"(PUT /api/v1/providers/{provider}/secret)"
    )


def _probe_detail(status: HealthStatus) -> str | None:
    """Return the explanatory detail for an unproven or failed probe."""

    if status is HealthStatus.UNKNOWN:
        return (
            "provider health is unknown: no live connectivity probe is implemented for this adapter"
        )
    if status is HealthStatus.UNAVAILABLE:
        return "provider reported unavailable: the endpoint is not reachable"
    return None


def _build_with_resolved_secret(
    factory: Callable[..., ProviderAdapter],
    client: httpx.AsyncClient | None,
    key: str | None,
    *,
    config: ProviderConfig | None = None,
) -> ProviderAdapter:
    """Pass a resolved key only to constructors that explicitly accept it.

    A constructor that also accepts ``key_environment`` (Tavily) receives the
    resolved key together with the explicit non-secret rail and PAYGO
    configuration, so a keyless build still gets its configured access mode
    instead of the constructor defaults.
    """

    parameters = inspect.signature(factory).parameters
    if "key_environment" in parameters:
        return factory(
            client,
            api_key=SecretStr(key) if key is not None else None,
            key_environment=config.tavily_key_environment if config else "dev",
            paygo_enabled=config.tavily_paygo_enabled if config else False,
        )
    if key is not None and "api_key" in parameters:
        return factory(client, api_key=SecretStr(key))
    return factory(client)


async def _eject_provider_adapter(request: Request, provider: ProviderName) -> None:
    """Eject or rebuild an adapter after its secret is removed from the vault.

    For non-keyless providers, any live adapter is removed from app routes and closed.
    For Keenable and Tavily, if enabled, the adapter reverts to the keyless
    public tier instead.
    """

    app = request.app
    routes: list[ProviderAdapter] = getattr(app.state, "_routes", None) or []
    lock: asyncio.Lock | None = getattr(app.state, "_control_lock", None)

    async def _eject() -> None:
        existing = next((route for route in routes if route.name == provider.value), None)
        existing_client = getattr(existing, "_client", None)
        if existing is not None:
            routes.remove(existing)
            await existing.aclose()
        if provider is ProviderName.KEENABLE or provider is ProviderName.TAVILY:
            config = await effective_provider_config(app.state.repository, provider)
            if config.enabled:
                factory = adapter_factory(provider.value)
                if factory is not None:
                    client = getattr(app.state, "_client", None) or existing_client
                    if client is None:
                        client = create_async_client()
                        app.state._client = client
                    with suppress(Exception):
                        adapter = _build_with_resolved_secret(
                            factory, client, None, config=config
                        )
                        if provider is ProviderName.KEENABLE:
                            _apply_keenable_limits(app, adapter)
                        routes.append(adapter)

    if lock is not None:
        async with lock:
            await _eject()
    else:
        await _eject()


def _tavily_rebuild_needed(
    existing: ProviderAdapter, key: str | None, config: ProviderConfig
) -> bool:
    """Return whether the live Tavily adapter no longer matches its build inputs.

    A rebuild is due when the resolved key state changed the auth rail, or
    when the explicit key-environment / PAYGO configuration differs from the
    values the adapter was built with.
    """

    expected_mode = AuthMode.KEYED if key is not None else AuthMode.KEYLESS
    return bool(
        existing.limit_auth_mode != expected_mode
        or getattr(existing, "key_environment", "dev") != config.tavily_key_environment
        or bool(getattr(existing, "paygo_enabled", False)) != bool(config.tavily_paygo_enabled)
    )


async def _apply_tavily_limits(
    app: FastAPI, config: ProviderConfig, adapter: ProviderAdapter
) -> None:
    """Project the built Tavily adapter's rail into the app limit store."""

    limits = getattr(app.state, "limits", None)
    if limits is not None:
        with suppress(Exception):
            await limits.apply_tavily_config(config, auth_mode=adapter.limit_auth_mode)


def _apply_keenable_limits(app: FastAPI, adapter: ProviderAdapter) -> None:
    """Project the built Keenable adapter's rail into the app limit store."""

    limits = getattr(app.state, "limits", None)
    if limits is not None:
        limits.apply_keenable_auth_mode(adapter.limit_auth_mode)


async def _ensure_provider_adapter(
    request: Request, provider: ProviderName, *, force_rebuild: bool = False
) -> ProviderAdapter:
    """Return the provider's adapter, constructing it on demand when possible.

    Construction happens under the app control lock and only when the provider
    is enabled and its vault key resolves (Keenable's and Tavily's keyless
    public tiers count). A constructed adapter is appended once and never
    rebuilt unless its key status changes (e.g. key added/removed), its Tavily
    rail configuration changed, or force_rebuild is True; the MCP server's
    generation refcount is untouched.
    """

    app = request.app
    routes: list[ProviderAdapter] = app.state._routes
    async with app.state._control_lock:
        existing = next((route for route in routes if route.name == provider.value), None)
        key, _source = await _resolve_secret(provider, app.state.secret_store)

        if existing is not None and not force_rebuild:
            if provider is ProviderName.KEENABLE:
                is_keyed = key is not None
                has_quota = bool(existing.capabilities.quota)
                if is_keyed == has_quota:
                    return existing
            elif provider is ProviderName.TAVILY:
                current = await effective_provider_config(app.state.repository, provider)
                if not _tavily_rebuild_needed(existing, key, current):
                    return existing
            else:
                return existing

        existing_client = getattr(existing, "_client", None)
        if existing is not None:
            routes.remove(existing)
            await existing.aclose()

        config = await effective_provider_config(app.state.repository, provider)
        if not config.enabled:
            raise HTTPException(
                status_code=503,
                detail=f"provider {provider.value} is disabled; enable it before testing",
            )
        if key is None and provider not in (ProviderName.KEENABLE, ProviderName.TAVILY):
            raise HTTPException(status_code=503, detail=_restart_hint(provider.value))
        factory = adapter_factory(provider.value)
        if factory is None:
            raise HTTPException(status_code=503, detail=_restart_hint(provider.value))
        client = getattr(app.state, "_client", None) or existing_client
        if client is None:
            client = create_async_client()
            app.state._client = client
        try:
            adapter = _build_with_resolved_secret(factory, client, key, config=config)
        except Exception:
            raise HTTPException(status_code=503, detail=_restart_hint(provider.value)) from None
        _apply_provider_budget_setters(adapter, config)
        if provider is ProviderName.TAVILY:
            await _apply_tavily_limits(app, config, adapter)
        elif provider is ProviderName.KEENABLE:
            _apply_keenable_limits(app, adapter)
        routes.append(adapter)
        return adapter


def _apply_provider_budget_setters(adapter: ProviderAdapter, config: ProviderConfig) -> None:
    """Seed the optional native-budget setters from the effective configuration."""

    parallel_setter = getattr(adapter, "set_free_seed", None)
    if callable(parallel_setter):
        parallel_setter(config.parallel_free_seed_usd)
    exa_setter = getattr(adapter, "set_monthly_budget", None)
    if callable(exa_setter):
        exa_setter(config.exa_monthly_budget_usd)
    credits_setter = getattr(adapter, "set_manual_starting_credits", None)
    if callable(credits_setter):
        credits_setter(config.exa_manual_starting_credits_usd)
