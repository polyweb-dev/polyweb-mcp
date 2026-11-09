"""Transport-independent provider runtime seam (TASK-000042).

Everything a request path needs to resolve *provider* state lives here, so the
REST API and the MCP server share one source and services never import a
transport module: effective provider configuration (defaults <- env JSON <-
persisted configuration plus its per-process cache), the routing policy read,
the canonical config materialization and per-credential adapter construction.

Secret material flows only through :class:`SecretStr`/store interfaces and is
never logged. Control-plane mutations keep registering provider configuration
in ``routers.control``; this module is the shared read/build seam.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
from collections.abc import Callable, Mapping, Sequence
from contextlib import suppress
from decimal import Decimal
from typing import TYPE_CHECKING, Any

import httpx
from pydantic import SecretStr, ValidationError

from freesearch.adapters.base import ProviderAdapter
from freesearch.configuration.provider_config import (
    ProviderConfig,
    ProviderConfigError,
    ProviderConfigUpdate,
    get_provider_configs,
    system_support_mask,
)
from freesearch.infrastructure.secrets import AsyncSecretStore, ProviderName
from freesearch.models.contracts import RoutingConfigResponse
from freesearch.models.provider_access import ALL_BITS, validate_mask
from freesearch.models.provider_limits import ProviderObservationScope
from freesearch.persistence.storage import (
    SQLiteRepository,
    register_setting_listener,
)

if TYPE_CHECKING:
    from freesearch.services.provider_limits import ProviderLimitsService

logger = logging.getLogger(__name__)

_ROUTING_KEY = "routing"


# ------------------------------------------------------------------- secrets


async def store_get(store: AsyncSecretStore, name: str) -> str | None:
    """Read one vault entry from sync or async stores, degrading failures to ``None``."""

    try:
        value = store.get(name)
        return await value if inspect.isawaitable(value) else value
    except Exception:
        return None


def build_adapter_with_secret(
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


# ------------------------------------------------------ configuration cache

_CONFIG_CACHE: dict[tuple[int, str], ProviderConfig] = {}
_CONFIG_STAMPS: dict[tuple[int, str], str] = {}
_CONFIG_VALIDATED: dict[tuple[int, str], bool] = {}
_CACHE_PATHS: dict[int, str] = {}
_POLICY_CACHE: dict[int, RoutingConfigResponse] = {}
_POLICY_STAMPS: dict[int, str] = {}


def _setting_stamp(value: Any) -> str:
    """Canonical value token: equivalent JSON produces equivalent configuration."""

    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


async def _durable_setting_stamp(
    repository: SQLiteRepository | None, key: str, *, strict: bool = False
) -> str | None:
    """Validate caches against a fresh, settings-specific transaction."""

    if repository is None:
        return None
    try:
        return _setting_stamp(await repository.runtime_setting_snapshot(key))
    except Exception:
        if strict:
            raise
        return None


def _remember_path(repository: SQLiteRepository) -> None:
    with suppress(OSError, ValueError):
        _CACHE_PATHS[id(repository)] = str(repository.database_path)


def clear_config_cache(
    repository: SQLiteRepository | None = None, provider: str | None = None
) -> None:
    """Clear cached provider and policy configurations.

    A repository-scoped clear also evicts every other handle of the same
    database file in this process, because the durable write is visible to all
    of them.
    """

    if repository is None:
        if provider is None:
            _CONFIG_CACHE.clear()
            _CONFIG_STAMPS.clear()
            _CONFIG_VALIDATED.clear()
            _CACHE_PATHS.clear()
            _POLICY_CACHE.clear()
            _POLICY_STAMPS.clear()
        else:
            for key in [k for k in _CONFIG_CACHE if k[1] == provider]:
                _CONFIG_CACHE.pop(key, None)
                _CONFIG_STAMPS.pop(key, None)
                _CONFIG_VALIDATED.pop(key, None)
    else:
        repo_id = id(repository)
        try:
            path = str(repository.database_path)
        except (OSError, ValueError):
            path = None
        repo_ids = {repo_id}
        if path is not None:
            repo_ids |= {cached_id for cached_id, cached in _CACHE_PATHS.items() if cached == path}
        for cached_id in repo_ids:
            _POLICY_CACHE.pop(cached_id, None)
            _POLICY_STAMPS.pop(cached_id, None)
            if provider is None:
                for key in [k for k in _CONFIG_CACHE if k[0] == cached_id]:
                    _CONFIG_CACHE.pop(key, None)
                    _CONFIG_STAMPS.pop(key, None)
                    _CONFIG_VALIDATED.pop(key, None)
            else:
                key = (cached_id, provider)
                _CONFIG_CACHE.pop(key, None)
                _CONFIG_STAMPS.pop(key, None)
                _CONFIG_VALIDATED.pop(key, None)


def _on_setting_changed(repo: Any, key: str) -> None:
    clear_config_cache(repo)


register_setting_listener(_on_setting_changed)


async def read_runtime_setting(
    repository: SQLiteRepository | None, key: str, *, strict: bool = False
) -> Any:
    """Read a runtime setting, degrading repository failures to ``None``.

    Non-strict reads are best-effort like monitoring reads: a repository that
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


def _provider_key(provider: ProviderName) -> str:
    return f"provider.{provider.value}"


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
    The caller then keeps the valid stored access choice through a fallback.
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


def _config_payload(payload: Any) -> dict[str, Any] | None:
    """Return the stored provider-config mapping from a runtime-setting payload."""

    if not isinstance(payload, dict):
        return None
    config = payload.get("config")
    return config if isinstance(config, dict) else None


def _decimal_text(value: Decimal | None) -> str | None:
    """Return the stored text of an optional Decimal."""

    return str(value) if value is not None else None


def _provider_payload(config: ProviderConfig) -> dict[str, Any]:
    """Return the stored runtime-setting payload for one provider record."""

    return {
        "config": {
            "enable_mask": config.enable_mask,
            "support_mask": config.support_mask,
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

    value = await read_runtime_setting(repository, _provider_key(provider), strict=strict)
    return await _config_from_snapshot(repository, provider, value, strict=strict)


async def _config_from_snapshot(
    repository: SQLiteRepository | None, provider: ProviderName, value: Any, *, strict: bool
) -> ProviderConfig:
    """Decode exactly the durable value used as the cache's consistency token."""

    base = _provider_base(provider)
    payload = _config_payload(value)
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


async def initialize_provider_configs(repository: SQLiteRepository | None) -> None:
    """Materialize a canonical configuration record for every provider.

    Both transports call this before they accept requests. An injected
    repository without a lifespan is covered by the canonical read path, which
    initializes a missing record on demand. A ``None`` repository writes
    nothing.
    """

    if repository is None:
        return
    from freesearch.services.pool_materializer import ensure_keyless_credentials, materialize_pools
    from freesearch.services.project_routing import seed_legacy_orders

    async with repository.session() as session:
        await ensure_keyless_credentials(session)
        await materialize_pools(session)
        await session.commit()
    await seed_legacy_orders(repository)
    for provider in ProviderName:
        await _reconcile_provider_config(repository, provider)


async def effective_config_for_name(
    repository: SQLiteRepository | None, name: str, *, strict: bool = False
) -> ProviderConfig:
    """Canonical-name wrapper for request-path lookups; unknown names default."""

    try:
        provider = ProviderName(name)
    except ValueError:
        return ProviderConfig()
    for _ in range(8):
        before = await _durable_setting_stamp(repository, _provider_key(provider), strict=strict)
        cache_key = (id(repository), name)
        cached = _CONFIG_CACHE.get(cache_key)
        if strict and not _CONFIG_VALIDATED.get(cache_key, False):
            cached = None
        if cached is not None and before is not None and _CONFIG_STAMPS.get(cache_key) == before:
            return cached
        value = await read_runtime_setting(repository, _provider_key(provider), strict=strict)
        config = await _config_from_snapshot(repository, provider, value, strict=strict)
        after = await _durable_setting_stamp(repository, _provider_key(provider), strict=strict)
        if after is not None and _setting_stamp(value) != after:
            continue
        if repository is not None and after is not None:
            _CONFIG_CACHE[cache_key] = config
            _CONFIG_STAMPS[cache_key] = after
            _CONFIG_VALIDATED[cache_key] = strict
            _remember_path(repository)
        return config
    raise ProviderConfigError("provider configuration changed repeatedly during lookup")


async def persist_provider_config(
    repository: SQLiteRepository | None, provider: ProviderName, config: ProviderConfig
) -> None:
    """Persist the full merged provider configuration record; nothing without a repo."""

    if repository is None:
        return
    await repository.set_runtime_setting(_provider_key(provider), _provider_payload(config))
    clear_config_cache(repository, provider.value)
    await _refresh_keyless_bindings(repository, provider)


async def _refresh_keyless_bindings(repository: SQLiteRepository, provider: ProviderName) -> None:
    from freesearch.services.pool_materializer import KEYLESS_PROVIDERS, materialize_pools

    if provider.value in KEYLESS_PROVIDERS:
        async with repository.session() as session:
            await materialize_pools(session)
            await session.commit()


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
    await _refresh_keyless_bindings(repository, provider)
    return outcome["config"]


async def routing_policy(repository: SQLiteRepository | None) -> RoutingConfigResponse:
    """Return the persisted routing policy or its defaults; corrupt data defaults."""

    for _ in range(8):
        before = await _durable_setting_stamp(repository, _ROUTING_KEY)
        cached = _POLICY_CACHE.get(id(repository))
        if (
            cached is not None
            and before is not None
            and _POLICY_STAMPS.get(id(repository)) == before
        ):
            return cached
        payload = await read_runtime_setting(repository, _ROUTING_KEY)
        policy = RoutingConfigResponse()
        if isinstance(payload, dict):
            with suppress(ValidationError):
                policy = RoutingConfigResponse.model_validate(payload)
        after = await _durable_setting_stamp(repository, _ROUTING_KEY)
        if after is not None and _setting_stamp(payload) != after:
            continue
        if repository is not None and after is not None:
            _POLICY_CACHE[id(repository)] = policy
            _POLICY_STAMPS[id(repository)] = after
            _remember_path(repository)
        return policy
    raise ProviderConfigError("routing policy changed repeatedly during lookup")


async def persist_routing_config(
    repository: SQLiteRepository | None, policy: RoutingConfigResponse
) -> None:
    """Persist the routing policy.

    ``max_attempts`` (validated ``ge=1``) is the execution hop limit: a
    chained request attempts at most that many distinct provider legs.
    Runner construction is untouched.
    """

    if repository is None:
        return
    await repository.set_runtime_setting(_ROUTING_KEY, policy.model_dump(mode="json"))
    _POLICY_CACHE.pop(id(repository), None)
    _POLICY_STAMPS.pop(id(repository), None)


# ------------------------------------------------- adapter quota seeding


def _quota_state_changed(current: Any, projected: Any) -> bool:
    if current is None:
        return True
    return any(
        getattr(current, field, None) != getattr(projected, field, None)
        for field in (
            "source",
            "remaining",
            "limit",
            "reset_at",
            "unit_kind",
            "display_unit",
            "metadata",
        )
    )


# ------------------------------------------------- background quota polling

_BACKGROUND_TASKS: set[asyncio.Task[Any]] = set()


def schedule_quota_refresh(
    repository: SQLiteRepository | None,
    adapters: Sequence[ProviderAdapter],
    secret_store: AsyncSecretStore | None,
    *,
    scopes: Mapping[int, ProviderObservationScope] | None = None,
    limits: ProviderLimitsService | None = None,
) -> asyncio.Task[Any] | None:
    """Schedule asynchronous quota polling out-of-band without blocking the request hot path."""

    if repository is None or not adapters:
        return None
    from freesearch.services.monitoring import refresh_quotas

    try:
        loop = asyncio.get_running_loop()
        task = loop.create_task(
            refresh_quotas(
                repository, adapters, secret_store=secret_store, scopes=scopes, limits=limits
            )
        )
        _BACKGROUND_TASKS.add(task)
        task.add_done_callback(_BACKGROUND_TASKS.discard)
        return task
    except RuntimeError:
        return None


__all__ = [
    "_BACKGROUND_TASKS",
    "build_adapter_with_secret",
    "clear_config_cache",
    "effective_config_for_name",
    "effective_provider_config",
    "initialize_provider_configs",
    "patch_provider_config",
    "persist_provider_config",
    "persist_routing_config",
    "read_runtime_setting",
    "routing_policy",
    "schedule_quota_refresh",
    "store_get",
]
