"""Provider control-plane service and REST router (Stage 5).

This module is the control surface's service layer: it resolves effective
provider configuration (defaults <- env JSON <- persisted), applies the
persisted routing policy, resolves secret presence without ever exposing or
persisting raw keys, and serves the ``/api/v1`` endpoints. Provider keys
are written only through the injected :class:`SecretStore`; fingerprints are
derived in memory and are the only secret-adjacent value ever persisted.
"""

import os
import time
from contextlib import suppress
from datetime import UTC, datetime
from hashlib import sha256
from typing import Any, Literal

from dotenv import dotenv_values
from fastapi import FastAPI, HTTPException, Request
from pydantic import ValidationError

from freesearch.adapters.base import ProviderAdapter
from freesearch.adapters.registry import adapter_factory
from freesearch.configuration.provider_config import (
    ProviderConfig,
    ProviderConfigUpdate,
    get_provider_configs,
)
from freesearch.infrastructure.http import create_async_client
from freesearch.infrastructure.logging import redact_secrets
from freesearch.infrastructure.secrets import PROVIDER_ENV_VARS, ProviderName, SecretStore
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
    QuotaSource,
    RoutingConfigResponse,
    RoutingConfigUpdate,
    SecretPresence,
    SecretStatusResponse,
    SetSecretRequest,
    manual_quota_remaining,
    manual_quota_remaining_percent,
)
from freesearch.persistence.storage import SQLiteRepository
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

SecretSource = Literal["environment", "dotenv", "keyring", "none"]

_ROUTING_KEY = "routing"

_MANUAL_QUOTA_PREFIX = "manual_quota:"


def register_control_routes(app: FastAPI) -> None:
    """Register the control-plane endpoints on ``app`` under ``/api/v1``.

    Routes are registered directly on the application router (rather than via
    ``include_router``) so every entry in ``app.routes`` stays a plain route
    with a ``path`` attribute.
    """

    @app.get("/api/v1/providers", response_model=list[ProviderStatusResponse])
    async def list_providers(request: Request) -> list[ProviderStatusResponse]:
        """Enumerate every canonical provider with its current control state."""

        repository: SQLiteRepository | None = request.app.state.repository
        policy = await routing_policy(repository)
        entries = [
            await _provider_entry(repository, name, request.app.state.secret_store)
            for name in ProviderName
        ]
        ordered = sorted(entries, key=lambda entry: (entry.priority, entry.provider_id))
        if policy.cost_optimization_preset is CostPreset.FREE_FIRST:
            return _free_first_order(ordered)
        return ordered

    @app.get("/api/v1/providers/{provider_id}", response_model=ProviderStatusResponse)
    async def get_provider(provider_id: str, request: Request) -> ProviderStatusResponse:
        """Return one canonical provider's control-plane status entry."""

        name = _require_provider(provider_id)
        repository: SQLiteRepository | None = request.app.state.repository
        return await _provider_entry(repository, name, request.app.state.secret_store)

    @app.patch("/api/v1/providers/{provider_id}", response_model=ProviderStatusResponse)
    async def patch_provider(
        provider_id: str,
        request: Request,
        update: ProviderConfigUpdate | None = None,
    ) -> ProviderStatusResponse:
        """Merge a partial provider config update onto the effective record.

        The body is optional so an unknown provider identifier always surfaces
        as 404 even when the caller sends no JSON body at all.
        """

        name = _require_provider(provider_id)
        repository: SQLiteRepository | None = request.app.state.repository
        current = await effective_provider_config(repository, name)
        merged = (update or ProviderConfigUpdate()).apply_to(current)
        await persist_provider_config(repository, name, merged)
        return await _provider_entry(repository, name, request.app.state.secret_store)

    @app.post("/api/v1/providers/{provider_id}/test", response_model=ProviderTestResponse)
    async def test_provider(provider_id: str, request: Request) -> ProviderTestResponse:
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
        provider_id: str, request: Request
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
        provider_id: str, body: SetSecretRequest, request: Request
    ) -> SecretStatusResponse:
        """Store the key write-only, then report the effective secret status.

        The raw key goes only to the secret store. The response resolves the
        effective key/source afterwards (environment and ``.env`` outrank the
        store), so a shadowing environment or ``.env`` key is visible through
        its source label and masked fingerprint instead of being silently
        overridden by the write.
        """

        name = _require_provider(provider_id)
        raw_key = body.key.get_secret_value()
        request.app.state.secret_store.set(name.value, raw_key)
        now = datetime.now(UTC)
        key, source = _resolve_secret(name, request.app.state.secret_store)
        fingerprint = secret_fingerprint(name.value, key) if key is not None else None
        await persist_secret_record(request.app.state.repository, name, fingerprint, now)
        return SecretStatusResponse(
            provider=name.value,
            presence=_secret_presence(name, key),
            fingerprint=fingerprint,
            updated_at=now,
            source=source,
        )

    @app.delete("/api/v1/providers/{provider_id}/secret", response_model=SecretStatusResponse)
    async def delete_secret(provider_id: str, request: Request) -> SecretStatusResponse:
        """Remove the stored key idempotently, then report the effective status.

        Higher-precedence keys (environment, ``.env``) survive the deletion and
        are reported with their source; when nothing resolves the response
        reports ``source="none"`` with no fingerprint.
        """

        name = _require_provider(provider_id)
        store: SecretStore = request.app.state.secret_store
        store.delete(name.value)
        now = datetime.now(UTC)
        key, source = _resolve_secret(name, store)
        fingerprint = secret_fingerprint(name.value, key) if key is not None else None
        await persist_secret_record(request.app.state.repository, name, fingerprint, now)
        return SecretStatusResponse(
            provider=name.value,
            presence=_secret_presence(name, key),
            fingerprint=fingerprint,
            updated_at=now,
            source=source,
        )

    @app.get("/api/v1/routing/config", response_model=RoutingConfigResponse)
    async def get_routing_config(request: Request) -> RoutingConfigResponse:
        """Return the persisted global routing defaults."""

        return await routing_policy(request.app.state.repository)

    @app.put("/api/v1/routing/config", response_model=RoutingConfigResponse)
    async def put_routing_config(
        update: RoutingConfigUpdate, request: Request
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
    """Register the routing-neutral billing-anchor overlay routes."""

    @app.get(
        "/api/v1/providers/{provider_id}/manual-quota",
        response_model=ManualQuotaResponse,
    )
    async def get_manual_quota(provider_id: str, request: Request) -> ManualQuotaResponse:
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
        provider_id: str, update: ManualQuotaUpdate, request: Request
    ) -> ManualQuotaResponse:
        """Store the billing anchor and return the ESTIMATED capacity view."""

        name = _require_provider(provider_id)
        return await persist_manual_quota(
            request.app.state.repository, name, update, datetime.now(UTC)
        )

    @app.delete("/api/v1/providers/{provider_id}/manual-quota", status_code=204)
    async def delete_manual_quota(provider_id: str, request: Request) -> None:
        """Clear the billing anchor idempotently; the overlay never steers routing."""

        name = _require_provider(provider_id)
        await clear_manual_quota(request.app.state.repository, name)


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
    async def start_oauth_device_code(provider_id: str, request: Request) -> DeviceCodeResponse:
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
    async def oauth_status(provider_id: str, request: Request) -> OAuthStatusResponse:
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
    async def delete_oauth(provider_id: str, request: Request) -> None:
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


def _store_get(store: SecretStore, name: str) -> str | None:
    """Read ``name`` from the store, degrading store failures to ``None``."""

    with suppress(Exception):
        return store.get(name)
    return None


def _resolve_secret(provider: ProviderName, store: SecretStore) -> tuple[str | None, SecretSource]:
    """Resolve a provider key as process environment -> ``.env`` -> store.

    Precedence mirrors :class:`~freesearch.secrets.ProviderSecretResolver`, so
    control-plane presence matches actual adapter construction. Only the
    requested provider's variable is read from ``.env`` (relative to the
    working directory) and ``.env`` is never written; unreadable files and
    store read failures degrade to absent.
    """

    env_var = PROVIDER_ENV_VARS[provider]
    environment_value = os.environ.get(env_var)
    if environment_value:
        return environment_value, "environment"
    with suppress(OSError, UnicodeDecodeError):
        dotenv_value = dotenv_values(".env").get(env_var)
        if dotenv_value:
            return dotenv_value, "dotenv"
    stored_value = _store_get(store, provider.value)
    if stored_value:
        return stored_value, "keyring"
    return None, "none"


def _secret_presence(provider: ProviderName, key: str | None) -> SecretPresence:
    """Return presence: configured, keyless public (Keenable), or missing."""

    if key is not None:
        return SecretPresence.CONFIGURED
    if provider is ProviderName.KEENABLE:
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


async def _safe_runtime_setting(repository: SQLiteRepository | None, key: str) -> Any:
    """Read a runtime setting, degrading repository failures to ``None``.

    Control reads are best-effort like monitoring reads: a repository that
    cannot serve runtime settings (or does not implement them) yields the
    configuration defaults instead of failing the request.
    """

    if repository is None:
        return None
    try:
        return await repository.get_runtime_setting(key)
    except Exception:
        return None


async def effective_provider_config(
    repository: SQLiteRepository | None, provider: ProviderName
) -> ProviderConfig:
    """Return defaults <- env JSON <- persisted configuration for ``provider``.

    The base record comes from :func:`get_provider_configs` (defaults merged
    with ``FREESEARCH_PROVIDER_CONFIG_OVERRIDES``); a persisted record wins
    over it by applying the stored full config as a total update. A persisted
    payload that fails strict validation (corrupt or outdated shape) is
    self-healed: every read seam degrades to the base record instead of
    failing the request, mirroring :func:`routing_policy` and
    :func:`load_breaker`.
    """

    base = get_provider_configs()[provider]
    payload = _config_payload(await _safe_runtime_setting(repository, _provider_key(provider)))
    if payload is None:
        return base
    with suppress(ValidationError):
        return ProviderConfigUpdate.model_validate(payload).apply_to(base)
    return base


async def effective_config_for_name(
    repository: SQLiteRepository | None, name: str
) -> ProviderConfig:
    """Canonical-name wrapper for request-path lookups; unknown names default."""

    try:
        provider = ProviderName(name)
    except ValueError:
        return ProviderConfig()
    return await effective_provider_config(repository, provider)


async def persist_provider_config(
    repository: SQLiteRepository | None, provider: ProviderName, config: ProviderConfig
) -> None:
    """Persist the full merged provider configuration record; nothing without a repo."""

    if repository is None:
        return
    payload = {
        "config": {
            "enabled": config.enabled,
            "priority": config.priority,
            "free_tier_estimates": {
                operation.value: str(units)
                for operation, units in config.free_tier_estimates.items()
            },
            "reset_schedule": config.reset_schedule,
            "parallel_free_seed_usd": (
                str(config.parallel_free_seed_usd)
                if config.parallel_free_seed_usd is not None
                else None
            ),
        }
    }
    await repository.set_runtime_setting(_provider_key(provider), payload)


async def routing_policy(repository: SQLiteRepository | None) -> RoutingConfigResponse:
    """Return the persisted routing policy or its defaults; corrupt data defaults."""

    payload = await _safe_runtime_setting(repository, _ROUTING_KEY)
    if isinstance(payload, dict):
        with suppress(ValidationError):
            return RoutingConfigResponse.model_validate(payload)
    return RoutingConfigResponse()


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
    """Build the ESTIMATED capacity view with Decimal-exact derived fields."""

    return ManualQuotaResponse(
        provider=provider.value,
        billing_start=quota.billing_start,
        billing_end=quota.billing_end,
        allowance=quota.allowance,
        current_usage=quota.current_usage,
        remaining=manual_quota_remaining(quota.allowance, quota.current_usage),
        remaining_percent=manual_quota_remaining_percent(quota.allowance, quota.current_usage),
        source=QuotaSource.ESTIMATED,
        updated_at=updated_at,
        note=quota.note,
    )


async def load_manual_quota(
    repository: SQLiteRepository | None, provider: ProviderName
) -> ManualQuotaResponse | None:
    """Return the stored billing anchor view, or None when absent/corrupt."""

    payload = await _safe_runtime_setting(repository, _manual_quota_key(provider))
    if not isinstance(payload, dict):
        return None
    raw_updated_at = payload.get("updated_at")
    quota_payload = {
        key: payload.get(key)
        for key in (
            "billing_start",
            "billing_end",
            "allowance",
            "current_usage",
            "note",
        )
    }
    try:
        quota = ManualQuota.model_validate(quota_payload)
        updated_at = (
            datetime.fromisoformat(str(raw_updated_at)) if isinstance(raw_updated_at, str) else None
        )
    except (ValidationError, ValueError):
        return None
    if updated_at is None:
        return None
    return _manual_quota_response(provider, quota, updated_at)


async def persist_manual_quota(
    repository: SQLiteRepository | None,
    provider: ProviderName,
    update: ManualQuotaUpdate,
    now: datetime,
) -> ManualQuotaResponse:
    """Persist the billing anchor and return its ESTIMATED capacity view."""

    quota = ManualQuota.model_validate(update.model_dump(mode="json"))
    if repository is not None:
        await repository.set_runtime_setting(
            _manual_quota_key(provider),
            {
                "billing_start": quota.billing_start.isoformat(),
                "billing_end": quota.billing_end.isoformat(),
                "allowance": str(quota.allowance),
                "current_usage": str(quota.current_usage),
                "note": quota.note,
                "updated_at": _iso(now),
            },
        )
    return _manual_quota_response(provider, quota, now)


async def clear_manual_quota(repository: SQLiteRepository | None, provider: ProviderName) -> None:
    """Clear the billing anchor idempotently; unknown providers never reach here."""

    if repository is None:
        return
    await repository.set_runtime_setting(_manual_quota_key(provider), None)


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
    repository: SQLiteRepository | None, provider: ProviderName, store: SecretStore
) -> ProviderStatusResponse:
    """Assemble one provider's control-plane status entry."""

    config = await effective_provider_config(repository, provider)
    breaker = await load_breaker(repository, provider)
    health = await _latest_health(repository, provider.value)
    key, _source = _resolve_secret(provider, store)
    return ProviderStatusResponse(
        provider_id=provider.value,
        enabled=config.enabled,
        priority=config.priority,
        health=health.status if health is not None else None,
        circuit_breaker=breaker,
        latency_p95_ms=await latency_p95_ms(repository, provider.value),
        secret_presence=_secret_presence(provider, key),
        free_tier_estimates=config.free_tier_estimates,
        reset_schedule=config.reset_schedule,
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
        f"provider {provider} is not constructed: set its API key and restart "
        "the API server to build it"
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


async def _ensure_provider_adapter(request: Request, provider: ProviderName) -> ProviderAdapter:
    """Return the provider's adapter, constructing it on demand when possible.

    Construction happens under the app control lock and only when the provider
    is enabled and a key resolves from the control plane's environment/store
    surface (Keenable's keyless public tier counts). A constructed adapter is
    appended once and never rebuilt, so teardown races are impossible; the MCP
    server's generation refcount is untouched.
    """

    app = request.app
    routes: list[ProviderAdapter] = app.state._routes
    async with app.state._control_lock:
        existing = next((route for route in routes if route.name == provider.value), None)
        if existing is not None:
            return existing
        config = await effective_provider_config(app.state.repository, provider)
        if not config.enabled:
            raise HTTPException(
                status_code=503,
                detail=f"provider {provider.value} is disabled; enable it before testing",
            )
        key, _source = _resolve_secret(provider, app.state.secret_store)
        if key is None and provider is not ProviderName.KEENABLE:
            raise HTTPException(status_code=503, detail=_restart_hint(provider.value))
        factory = adapter_factory(provider.value)
        if factory is None:
            raise HTTPException(status_code=503, detail=_restart_hint(provider.value))
        try:
            adapter = factory(app.state._client)
        except Exception:
            raise HTTPException(status_code=503, detail=_restart_hint(provider.value)) from None
        routes.append(adapter)
        return adapter
