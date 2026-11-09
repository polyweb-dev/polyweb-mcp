"""Provider control-plane service and REST router (Stage 5).

This module is the control surface's service layer: it resolves effective
provider configuration (defaults <- env JSON <- persisted), applies the
persisted routing policy, resolves secret presence without ever exposing or
persisting raw keys, and serves the ``/api/v1`` endpoints. Provider keys
are written only through the injected :class:`SecretStore`; fingerprints are
derived in memory and are the only secret-adjacent value ever persisted.
"""

import time
from contextlib import suppress
from datetime import UTC, datetime
from decimal import Decimal
from hashlib import sha256
from typing import Annotated, Any, Literal

from fastapi import Depends, FastAPI, HTTPException, Request
from pydantic import ConfigDict, ValidationError, model_validator

from freesearch.adapters.base import ProviderAdapter
from freesearch.configuration.provider_config import (
    ProviderConfigUpdate,
)
from freesearch.infrastructure.logging import redact_secrets
from freesearch.infrastructure.secrets import AsyncSecretStore, ProviderName
from freesearch.models.contracts import (
    BreakerState,
    CircuitBreakerState,
    CircuitBreakerStatusResponse,
    HealthStatus,
    ManualQuota,
    ManualQuotaResponse,
    ManualQuotaUpdate,
    ProviderHealth,
    ProviderPriceRead,
    ProviderStatusResponse,
    ProviderTestResponse,
    RoutingConfigResponse,
    RoutingConfigUpdate,
    SecretPresence,
)
from freesearch.models.users import UserPrincipal
from freesearch.persistence.projects import ProjectRepository
from freesearch.persistence.storage import SQLiteRepository
from freesearch.routers.auth import current_principal, require_admin, require_control_reader
from freesearch.routers.control_errors import control_repository
from freesearch.services.manual_quota import clear_manual_quota as clear_shared_manual_quota
from freesearch.services.manual_quota import load_manual_quota as load_shared_manual_quota
from freesearch.services.manual_quota import manual_quota_response
from freesearch.services.manual_quota import persist_manual_quota as persist_shared_manual_quota
from freesearch.services.monitoring import latency_p95_ms
from freesearch.services.projects import ProjectService
from freesearch.services.provider_runtime import (
    effective_provider_config,
    patch_provider_config,
    persist_routing_config,
    read_runtime_setting,
    routing_policy,
)
from freesearch.services.provider_runtime import (
    store_get as _store_get,
)
from freesearch.services.routing_order import catalog_call_costs

SecretSource = Literal["encrypted_db", "none"]


def _catalog_patch_schema(schema: dict[str, Any]) -> None:
    schema.get("properties", {}).pop("priority", None)


class CatalogProviderUpdate(ProviderConfigUpdate):
    """Provider catalog writes exclude the legacy system priority."""

    model_config = ConfigDict(json_schema_extra=_catalog_patch_schema)

    @model_validator(mode="before")
    @classmethod
    def _reject_priority(cls, value: Any) -> Any:
        if isinstance(value, dict) and "priority" in value:
            raise ValueError("provider priority is no longer supported")
        return value


#: Live system-scope gates. ``require_admin`` requires the common service's
#: ``system.settings.write`` permission for every control mutation and provider
#: OAuth handler; ``require_control_reader`` requires ``system.settings.read``
#: for sanitized reads. Both answer 401 before 403, and both run before any
#: provider call or persistence write. Provider OAuth status follows its side
#: effects, not its HTTP verb, so the GET requires the write gate.
_AdminPrincipal = Annotated[UserPrincipal, Depends(require_admin)]
_ReaderPrincipal = Annotated[UserPrincipal, Depends(require_control_reader)]

_ROUTING_KEY = "routing"

_MANUAL_QUOTA_PREFIX = "manual_quota:"


async def _price_reader(request: Request) -> UserPrincipal:
    principal = current_principal(request)
    repository = control_repository(request)
    async with repository.session() as session:
        vault_access = await ProjectRepository(session).user_can_use_vault(principal.id)
    if not vault_access and not await ProjectService(repository).list_projects(
        principal, include_archived=False
    ):
        raise HTTPException(
            status_code=403, detail="provider prices require vault or project access"
        )
    return principal


def register_control_routes(app: FastAPI) -> None:
    """Register the control-plane endpoints on ``app`` under ``/api/v1``.

    Routes are registered directly on the application router (rather than via
    ``include_router``) so every entry in ``app.routes`` stays a plain route
    with a ``path`` attribute.
    """

    @app.get("/api/v1/provider-prices", response_model=list[ProviderPriceRead])
    async def list_provider_prices(
        _principal: Annotated[UserPrincipal, Depends(_price_reader)],
    ) -> list[ProviderPriceRead]:
        entries: list[ProviderPriceRead] = []
        for provider in ProviderName:
            costs = catalog_call_costs(provider.value)
            keyless_costs = catalog_call_costs(provider.value, keyless=True)
            entries.append(
                ProviderPriceRead(
                    provider_id=provider.value,
                    call_cost_usd=costs,
                    keyless_call_cost_usd=keyless_costs,
                    free=bool(costs) and all(cost == 0 for cost in costs.values()),
                    keyless=bool(keyless_costs),
                )
            )
        return entries

    @app.get("/api/v1/providers", response_model=list[ProviderStatusResponse])
    async def list_providers(
        _principal: _ReaderPrincipal, request: Request
    ) -> list[ProviderStatusResponse]:
        """Enumerate every canonical provider with its current control state."""

        repository: SQLiteRepository | None = request.app.state.repository
        entries = [
            await _provider_entry(
                repository,
                name,
                request.app.state.secret_store,
            )
            for name in ProviderName
        ]
        return sorted(entries, key=lambda entry: entry.provider_id)

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
        update: CatalogProviderUpdate | None = None,
    ) -> ProviderStatusResponse:
        """Merge a partial provider config update onto the effective record.

        The body is optional so an unknown provider identifier always surfaces
        as 404 even when the caller sends no JSON body at all. The merge runs
        inside one atomic read-modify-write transaction.
        """

        name = _require_provider(provider_id)
        repository: SQLiteRepository | None = request.app.state.repository
        await patch_provider_config(repository, name, update or ProviderConfigUpdate())
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
            max_attempts=update.max_attempts
            if update.max_attempts is not None
            else current.max_attempts,
        )
        await persist_routing_config(repository, merged)
        return merged

    _register_manual_quota_routes(app)


def _register_manual_quota_routes(app: FastAPI) -> None:
    """Register billing anchors; Exa allowance also seeds its local quota."""

    @app.get(
        "/api/v1/providers/{provider_id}/manual-quota",
        response_model=ManualQuotaResponse | None,
    )
    async def get_manual_quota(
        _principal: _AdminPrincipal, provider_id: str, request: Request
    ) -> ManualQuotaResponse | None:
        """Return the operator-entered billing anchor; never touches routing."""

        name = _require_provider(provider_id)
        return await load_manual_quota(request.app.state.repository, name)

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


def secret_fingerprint(provider: str, key: str) -> str:
    """Return the stable masked fingerprint for ``key``; never the key itself."""

    prefix = provider[:3].upper()
    suffix = sha256(key.encode()).hexdigest()[-4:]
    return f"{prefix}_{'•' * 8}{suffix}"


SecretBackend = AsyncSecretStore


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


def _breaker_key(provider: ProviderName) -> str:
    return f"provider.{provider.value}.breaker"


async def load_breaker(
    repository: SQLiteRepository | None, provider: ProviderName
) -> CircuitBreakerState:
    """Return the persisted breaker state, defaulting to a closed circuit."""

    payload = await read_runtime_setting(repository, _breaker_key(provider))
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
    repository: SQLiteRepository | None, provider: str, *, has_key: bool
) -> ProviderHealth | None:
    """Return the newest health observation; read failures degrade to ``None``.

    Calls through live system or project credentials record credential-scoped
    observations, so the newer of those and the provider-wide observation is
    the provider's last real result. The provider-wide observation counts
    only while the legacy store holds a key, since nothing else backs it.
    """

    if repository is None:
        return None
    try:
        through_credential = await repository.latest_live_credential_health(provider)
        provider_wide = await repository.latest_health(provider) if has_key else None
    except Exception:
        return None
    candidates = [health for health in (through_credential, provider_wide) if health is not None]
    return max(candidates, key=lambda health: health.checked_at, default=None)


async def _provider_entry(
    repository: SQLiteRepository | None,
    provider: ProviderName,
    store: SecretBackend,
) -> ProviderStatusResponse:
    """Assemble one provider's control-plane status entry."""

    config = await effective_provider_config(repository, provider)
    breaker = await load_breaker(repository, provider)
    key, _source = await _resolve_secret(provider, store)
    has_key = key is not None or provider in (ProviderName.KEENABLE, ProviderName.TAVILY)
    health = await _latest_health(repository, provider.value, has_key=has_key)
    return ProviderStatusResponse(
        provider_id=provider.value,
        enabled=config.enabled,
        enable_mask=config.enable_mask,
        support_mask=config.support_mask,
        call_cost_usd=catalog_call_costs(provider.value),
        keyless_call_cost_usd=catalog_call_costs(provider.value, keyless=True),
        health=health.status if health is not None else None,
        health_checked_at=health.checked_at if health is not None else None,
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


def _restart_hint(provider: str) -> str:
    """Return the actionable 503 detail for an unconstructed provider."""

    return (
        f"provider {provider} has no administrative probe adapter; "
        "create and bind a credential in the project credentials surface"
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
    """Probe an explicitly injected adapter; credentials use their A4 surface.

    Provider configuration remains available without any global credential.
    No provider-name secret is read and no implicit keyless adapter is built.
    """
    routes: list[ProviderAdapter] = request.app.state._routes
    adapter = next((route for route in routes if route.name == provider.value), None)
    if adapter is None:
        raise HTTPException(status_code=503, detail=_restart_hint(provider.value))
    return adapter
