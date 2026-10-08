"""Read-only monitoring telemetry: recording and JSON snapshot reads.

Recording is best-effort by contract: a monitoring failure must never fail the
user-facing request it observes, so every repository write is wrapped and
swallowed with a payload-free warning. Reads assemble the ``StatsResponse``
contract served by ``/stats`` and the ``DashboardResponse`` contract served by
``/dashboard``: the same snapshot plus a ``generated_at`` instant, serialized
as JSON for the future React dashboard. Every entry is a privacy projection,
so request ids, metadata, query text, and diagnostic messages never leave the
storage layer.
"""

import asyncio
import inspect
import logging
import math
import os
import time
from collections.abc import Awaitable, Callable, Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from pydantic import AwareDatetime, model_serializer

from freesearch.adapters.base import ProviderAdapter
from freesearch.adapters.brave import COST_USD_PER_REQUEST, FREE_CREDITS_USD, brave_spend_usd
from freesearch.infrastructure.secrets import AsyncSecretStore, ProviderName
from freesearch.models.contracts import (
    ContractModel,
    FetchResponse,
    HealthStatus,
    ProviderHealth,
    QuotaSnapshot,
    SearchResponse,
    UnitKind,
    UsageEvent,
    UsageOperation,
    UsageStatus,
    is_soft_quota_zero,
)
from freesearch.persistence.storage import LegacyUsageTotal, SQLiteRepository, UsageTotal

logger = logging.getLogger(__name__)

CANONICAL_PROVIDER_NAMES: frozenset[str] = frozenset(provider.value for provider in ProviderName)

MONITORING_NOTICE = (
    "Usage, quota, and health shown here are local-observed only; vendor /usage "
    # The en dash below is contractual: the monitoring tests assert the
    # "10 to 15 min" vendor-lag wording with an en dash verbatim.
    "endpoints lag 10–15 min, so balances can drift until reconciliation runs."  # noqa: RUF001
)
DEFAULT_RECENT_LIMIT: int = 20
MAX_RECENT_LIMIT: int = 100
DEFAULT_DB_FILENAME: str = "freesearch.db"
DB_ENV_VAR: str = "FREESEARCH_DB"
# Vendor quota endpoints are account reads, not request instrumentation.
QUOTA_POLL_TTL_SECONDS: int = 120
QUOTA_FAILURE_BACKOFF_SECONDS: int = 5
_quota_poll_cache: dict[tuple[int, int], datetime] = {}
_quota_failure_cache: dict[tuple[int, int], datetime] = {}
_quota_poll_locks: dict[tuple[int, int], asyncio.Lock] = {}


def _quota_ttl_seconds() -> int:
    raw = os.environ.get("FREESEARCH_QUOTA_POLL_TTL_SECONDS")
    try:
        configured = int(raw) if raw is not None else QUOTA_POLL_TTL_SECONDS
    except ValueError:
        configured = QUOTA_POLL_TTL_SECONDS
    return max(60, min(300, configured))


def _quota_failure_backoff_seconds() -> int:
    raw = os.environ.get("FREESEARCH_QUOTA_FAILURE_BACKOFF_SECONDS")
    try:
        configured = int(raw) if raw is not None else QUOTA_FAILURE_BACKOFF_SECONDS
    except ValueError:
        configured = QUOTA_FAILURE_BACKOFF_SECONDS
    return max(1, min(30, configured))


def clear_quota_poll_cache(
    repository: SQLiteRepository | None = None,
    adapters: Sequence[ProviderAdapter] = (),
) -> None:
    """Evict bounded-poll state when a repository or adapter generation closes."""

    if repository is None and not adapters:
        _quota_poll_cache.clear()
        _quota_failure_cache.clear()
        _quota_poll_locks.clear()
        return
    repository_id = id(repository) if repository is not None else None
    adapter_ids = {id(adapter) for adapter in adapters}
    all_keys = set(_quota_poll_cache) | set(_quota_failure_cache) | set(_quota_poll_locks)
    keys = [
        key
        for key in all_keys
        if (repository_id is None or key[0] == repository_id)
        and (not adapter_ids or key[1] in adapter_ids)
    ]
    for key in keys:
        _quota_poll_cache.pop(key, None)
        _quota_failure_cache.pop(key, None)
        _quota_poll_locks.pop(key, None)


class ProviderUsageTotal(ContractModel):
    """Aggregated usage units for one provider and operation."""

    provider: str
    operation: UsageOperation
    total_units: Decimal
    event_count: int
    unit_kind: UnitKind | None = None

    @model_serializer(mode="wrap")
    def _serialize_compat(self, handler: Any) -> Any:
        payload = handler(self)
        _drop_unknown_units(payload)
        return payload


class RecentUsageEntry(ContractModel):
    """Privacy-projected recent usage event: no request id, no metadata."""

    provider: str
    operation: UsageOperation
    units: Decimal
    observed_at: datetime
    latency_ms: int | None = None
    status: UsageStatus = UsageStatus.SUCCESS
    unit_kind: UnitKind | None = None
    display_unit: str | None = None

    @model_serializer(mode="wrap")
    def _serialize_compat(self, handler: Any) -> Any:
        payload = handler(self)
        _drop_unknown_units(payload)
        return payload


class LatestHealthEntry(ContractModel):
    """Privacy-projected health observation: no diagnostic message."""

    provider: str
    status: HealthStatus
    checked_at: datetime


def _drop_unknown_units(payload: dict[str, Any]) -> None:
    if payload.get("unit_kind") is None:
        payload.pop("unit_kind", None)
        payload.pop("display_unit", None)


class StatsResponse(ContractModel):
    """Read-only monitoring snapshot served by the stats and dashboard reads."""

    notice: str
    usage_totals: list[ProviderUsageTotal]
    recent_usage: list[RecentUsageEntry]
    latest_quota: list[QuotaSnapshot]
    latest_health: list[LatestHealthEntry]

    @model_serializer(mode="wrap")
    def _serialize_compat(self, handler: Any) -> Any:
        payload = handler(self)
        for snapshot in payload.get("latest_quota", []):
            _drop_unknown_units(snapshot)
        for total in payload.get("usage_totals", []):
            _drop_unknown_units(total)
        for event in payload.get("recent_usage", []):
            _drop_unknown_units(event)
        return payload


class DashboardResponse(StatsResponse):
    """JSON dashboard snapshot: the stats read plus its generation instant."""

    generated_at: AwareDatetime


def resolve_database_path(database: str | Path | None = None) -> Path:
    """Return the telemetry database path: env override, argument, then default."""

    from_environment = os.environ.get(DB_ENV_VAR)
    if from_environment:
        return Path(from_environment)
    if database is not None:
        return Path(database)
    return Path(DEFAULT_DB_FILENAME)


def _response_instant(response: SearchResponse | FetchResponse) -> datetime:
    """Return the instant the adapter produced ``response``.

    ``response.usage.observed_at`` is authoritative when the adapter reported
    usage. Without a usage event a fetch still carries ``document.fetched_at``;
    anything else falls back to the recording time.
    """

    if response.usage is not None:
        return response.usage.observed_at
    if isinstance(response, FetchResponse):
        return response.document.fetched_at
    return datetime.now(UTC)


def _estimated_gap_event(response: SearchResponse | FetchResponse) -> UsageEvent | None:
    """Turn an explicit vendor-metering gap into a local estimated event."""

    gap = response.usage_gap
    if not isinstance(gap, dict):
        return None
    raw_units = gap.get("units")
    try:
        units = raw_units if isinstance(raw_units, Decimal) else Decimal(str(raw_units))
    except (ArithmeticError, TypeError, ValueError):
        return None
    if not units.is_finite() or units < 0:
        return None
    operation = (
        UsageOperation.SEARCH if isinstance(response, SearchResponse) else UsageOperation.FETCH
    )
    return UsageEvent(
        provider=response.provider,
        operation=operation,
        units=units,
        unit_kind=UnitKind.USD,
        display_unit="USD",
        observed_at=_response_instant(response),
        metadata={"estimated": True, "metering_gap": True},
    )


async def record_response_telemetry(
    repository: SQLiteRepository | None,
    response: SearchResponse | FetchResponse,
    *,
    latency_ms: int | None = None,
    status: UsageStatus = UsageStatus.SUCCESS,
) -> None:
    """Persist ``response.usage`` and a healthy observation; never raise.

    Telemetry failures are logged without payload, response content, or
    exception text (which may embed query or URL data) and then swallowed, so a
    monitoring outage can never fail the user request being observed. Usage and
    health persistence are independent: a rejected usage write must never skip
    the healthy observation. When usage is present, the measured ``latency_ms``
    and ``status`` are attached to the stored event.
    """

    if repository is None:
        return
    try:
        usage = response.usage or _estimated_gap_event(response)
        if usage is not None:
            measured = usage.model_copy(update={"latency_ms": latency_ms, "status": status})
            await repository.record_usage(measured)
    except Exception:
        logger.warning("response telemetry could not be persisted")
    try:
        await repository.record_health(
            ProviderHealth(
                provider=response.provider,
                status=HealthStatus.HEALTHY,
                checked_at=_response_instant(response),
                message=None,
            )
        )
    except Exception:
        logger.warning("response telemetry could not be persisted")


async def record_failure_telemetry(
    repository: SQLiteRepository | None, *, provider: str | None
) -> None:
    """Persist a degraded health observation for ``provider``; never raise.

    This helper records health only; the zero-unit failure usage event is
    written by :func:`_record_failure_usage` from :func:`tracked_call`.
    """

    if repository is None or provider is None:
        return
    try:
        await repository.record_health(
            ProviderHealth(
                provider=provider,
                status=HealthStatus.DEGRADED,
                checked_at=datetime.now(UTC),
                message=None,
            )
        )
    except Exception:
        logger.warning("failure telemetry could not be persisted")


async def _record_failure_usage(
    repository: SQLiteRepository | None,
    *,
    provider: str,
    operation: UsageOperation,
    latency_ms: int | None,
) -> None:
    """Persist a zero-unit failure usage event for a failed call; never raise."""

    if repository is None:
        return
    try:
        await repository.record_usage(
            UsageEvent(
                provider=provider,
                operation=operation,
                units=Decimal("0"),
                observed_at=datetime.now(UTC),
                latency_ms=latency_ms,
                status=UsageStatus.FAILURE,
            )
        )
    except Exception:
        logger.warning("failure usage telemetry could not be persisted")


def _elapsed_ms(started_at: float) -> int:
    """Return whole milliseconds elapsed since ``started_at`` (never negative)."""

    return int((time.perf_counter() - started_at) * 1000)


def _measured_latency_ms(adapter_name: str, latency_ms: int) -> int | None:
    """Attach the measured latency only for the canonical provider surface.

    Usage rows recorded through :func:`tracked_call` for canonical providers
    (the control plane and routing registry) carry the measured latency and
    status; adapters outside that registry (synthetic doubles and custom
    integrations) keep the verbatim usage contract pinned by the Stage 4.5
    ledger tests. Direct :func:`record_response_telemetry` callers are never
    instrumented.
    """

    return latency_ms if adapter_name in CANONICAL_PROVIDER_NAMES else None


async def tracked_call[ResponseT: (SearchResponse, FetchResponse)](
    repository: SQLiteRepository | None,
    adapter: ProviderAdapter,
    call: Callable[[ProviderAdapter], Awaitable[ResponseT]],
    *,
    operation: UsageOperation,
) -> ResponseT:
    """Await ``call(adapter)`` recording success and failure telemetry around it.

    A routing failure never reaches this helper, so it records no telemetry.
    Adapter failures record a zero-unit failure usage event with the measured
    latency plus a degraded observation, then re-raise the original error;
    successful responses record the measured latency and success status with
    their usage event (when present) and a healthy observation.
    """

    started_at = time.perf_counter()
    try:
        response = await call(adapter)
    except Exception as exc:
        await _record_failure_usage(
            repository,
            provider=adapter.name,
            operation=operation,
            latency_ms=_measured_latency_ms(adapter.name, _elapsed_ms(started_at)),
        )
        await record_failure_telemetry(repository, provider=adapter.name)
        status = getattr(getattr(exc, "error", None), "status_code", None)
        await _record_adapter_quota(
            repository, adapter, "quota_after_error", status, operation=operation
        )
        raise
    await record_response_telemetry(
        repository,
        response,
        latency_ms=_measured_latency_ms(adapter.name, _elapsed_ms(started_at)),
    )
    await _record_adapter_quota(
        repository, adapter, "quota_after_success", response, operation=operation
    )
    return response


async def refresh_quotas(
    repository: SQLiteRepository | None,
    adapters: Sequence[ProviderAdapter],
    *,
    force: bool = False,
    now: datetime | None = None,
    secret_store: AsyncSecretStore | None = None,
) -> list[QuotaSnapshot]:
    """Poll quota-capable adapters once per bounded TTL and persist snapshots."""

    if repository is None:
        return []
    observed_at = now or datetime.now(UTC)
    snapshots: list[QuotaSnapshot] = []
    for adapter in adapters:
        try:
            if not adapter.capabilities.quota:
                continue
            snapshot = await _poll_one_quota(repository, adapter, force, observed_at)
        except Exception:
            logger.warning("quota poll could not be completed")
            continue
        if snapshot is not None:
            snapshots.append(snapshot)
    try:
        oauth_snapshot = await _poll_parallel_oauth_balance(repository, observed_at, secret_store)
    except Exception:
        logger.warning("quota poll could not be completed")
        oauth_snapshot = None
    if oauth_snapshot is not None:
        snapshots.append(oauth_snapshot)
    return snapshots


async def _poll_parallel_oauth_balance(
    repository: SQLiteRepository,
    observed_at: datetime,
    secret_store: AsyncSecretStore | None,
) -> QuotaSnapshot | None:
    """Poll the paired Parallel Account API balance without touching adapter quotas."""

    from freesearch.services.parallel_oauth import poll_oauth_balance_snapshot

    return await poll_oauth_balance_snapshot(repository, now=observed_at, secret_store=secret_store)


async def _poll_one_quota(
    repository: SQLiteRepository,
    adapter: ProviderAdapter,
    force: bool,
    observed_at: datetime,
) -> QuotaSnapshot | None:
    cache_key = (id(repository), id(adapter))
    lock = _quota_poll_locks.setdefault(cache_key, asyncio.Lock())
    was_running = lock.locked()
    async with lock:
        failure_at = _quota_failure_cache.get(cache_key)
        if failure_at is not None:
            backoff = timedelta(seconds=_quota_failure_backoff_seconds())
            if observed_at - failure_at < backoff:
                try:
                    return await repository.latest_quota(adapter.name)
                except Exception:
                    return None
            _quota_failure_cache.pop(cache_key, None)
        cached_at = _quota_poll_cache.get(cache_key)
        ttl = _quota_ttl_seconds()
        within_ttl = cached_at is not None and observed_at - cached_at < timedelta(seconds=ttl)
        if within_ttl and (not force or was_running):
            try:
                return await repository.latest_quota(adapter.name)
            except Exception:
                return None
        try:
            snapshot = await adapter.quota()
        except Exception:
            _quota_failure_cache[cache_key] = observed_at
            return None
        if snapshot is None:
            return None
        try:
            await repository.record_quota(snapshot)
        except Exception:
            _quota_failure_cache[cache_key] = observed_at
            return None
        _quota_failure_cache.pop(cache_key, None)
        _quota_poll_cache[cache_key] = observed_at
        return snapshot


def normalize_degenerate_quota(snapshot: QuotaSnapshot) -> QuotaSnapshot:
    """Return a copy that treats a zero quota limit as unknown."""

    if snapshot.limit == Decimal("0"):
        return snapshot.model_copy(update={"remaining": None, "limit": None, "reset_at": None})
    return snapshot.model_copy()


async def effective_quota(
    repository: SQLiteRepository | None, provider: str
) -> QuotaSnapshot | None:
    """Return the routable quota view, expiring Parallel's soft zero on success."""

    if repository is None:
        return None
    snapshot = await repository.latest_quota(provider)
    if snapshot is None:
        return None
    snapshot = normalize_degenerate_quota(snapshot)
    if snapshot.remaining != Decimal("0") or not is_soft_quota_zero(provider, snapshot):
        return snapshot
    try:
        events = await repository.list_usage(provider=provider)
    except Exception:
        return snapshot
    successful = [
        event
        for event in events
        if event.status is UsageStatus.SUCCESS and event.observed_at > snapshot.observed_at
    ]
    if successful:
        cleared = snapshot.model_copy(
            update={
                "remaining": None,
                "observed_at": max(event.observed_at for event in successful),
                "metadata": {**snapshot.metadata, "soft_zero": False},
            }
        )
        await repository.record_quota(cleared)
        return cleared
    return snapshot


async def effective_quotas_batch(
    repository: SQLiteRepository | None, providers: Sequence[str]
) -> dict[str, QuotaSnapshot]:
    """Return the routable quota view for each requested provider in one batch."""

    if repository is None or not providers:
        return {}
    raw_snapshots = await repository.latest_quota_batch(providers)
    quotas: dict[str, QuotaSnapshot] = {}
    for provider, snapshot in raw_snapshots.items():
        snapshot = normalize_degenerate_quota(snapshot)
        if snapshot.remaining == Decimal("0") and is_soft_quota_zero(provider, snapshot):
            try:
                events = await repository.list_usage(provider=provider)
                successful = [
                    event
                    for event in events
                    if event.status is UsageStatus.SUCCESS
                    and event.observed_at > snapshot.observed_at
                ]
                if successful:
                    cleared = snapshot.model_copy(
                        update={
                            "remaining": None,
                            "observed_at": max(event.observed_at for event in successful),
                            "metadata": {**snapshot.metadata, "soft_zero": False},
                        }
                    )
                    await repository.record_quota(cleared)
                    snapshot = cleared
            except Exception:
                pass
        quotas[provider] = snapshot
    return quotas


async def _record_adapter_quota(
    repository: SQLiteRepository | None,
    adapter: ProviderAdapter,
    method_name: str,
    argument: object,
    *,
    operation: UsageOperation | None = None,
) -> None:
    """Persist local quota state exposed by an adapter without vendor polling."""

    if repository is None:
        return
    if adapter.name == "parallel" and await _parallel_oauth_owns_snapshot(repository):
        return
    method = getattr(adapter, method_name, None)
    if not callable(method):
        return
    try:
        parameters = inspect.signature(method).parameters
        if operation is not None and "operation" in parameters:
            result = method(argument, operation=operation)
        else:
            result = method(argument)
        snapshot = await result if inspect.isawaitable(result) else result
        if isinstance(snapshot, QuotaSnapshot):
            await repository.record_quota(snapshot)
    except Exception:
        logger.warning("local quota state could not be persisted")


async def _parallel_oauth_owns_snapshot(repository: SQLiteRepository) -> bool:
    """Return True while the AUTHORITATIVE OAuth balance owns the Parallel snapshot."""

    try:
        from freesearch.services.parallel_oauth import is_oauth_ready

        return await is_oauth_ready(repository)
    except Exception:
        return False


async def latency_p95_ms(
    repository: SQLiteRepository | None, provider: str, *, window: int = 100
) -> int | None:
    """Return the nearest-rank 95th percentile latency for ``provider``.

    Samples are the last ``window`` measured (non-null) latencies in the usage
    ledger. ``None`` is reported when no samples exist; read failures degrade
    to ``None`` without raising.
    """

    if repository is None:
        return None
    try:
        samples = await repository.recent_latencies(provider, limit=window)
    except Exception:
        logger.warning("latency sample read could not be collected")
        return None
    if not samples:
        return None
    ordered = sorted(samples)
    rank = math.ceil(0.95 * len(ordered))
    return ordered[rank - 1]


async def collect_stats(
    repository: SQLiteRepository | None,
    *,
    adapter_names: Sequence[str] = (),
    recent_limit: int = DEFAULT_RECENT_LIMIT,
) -> StatsResponse:
    """Read the monitoring snapshot; every read path is failure-safe."""

    if repository is None:
        return _empty_stats()
    try:
        totals = await repository.usage_totals()
        recent = await repository.recent_usage(limit=recent_limit)
        providers = sorted(
            set(adapter_names)
            | {total.provider for total in totals}
            | {event.provider for event in recent}
        )
        latest_quota = await _latest_quotas(repository, providers, totals=totals)
        latest_health = await _latest_health(repository, providers)
    except Exception:
        logger.warning("monitoring reads could not be collected")
        return _empty_stats()
    return StatsResponse(
        notice=MONITORING_NOTICE,
        usage_totals=_contract_totals(totals),
        recent_usage=_contract_recent(recent),
        latest_quota=latest_quota,
        latest_health=_contract_health(latest_health),
    )


def _brave_request_success_total(
    totals: Sequence[UsageTotal | LegacyUsageTotal],
) -> Decimal:
    """Sum Brave REQUEST success units without mixing other dimensions."""
    total = Decimal("0")
    for item in totals:
        if item.provider != "brave":
            continue
        if getattr(item, "unit_kind", None) is not UnitKind.REQUEST:
            continue
        total += item.total_units
    return total


def _enrich_brave_snapshot(snapshot: QuotaSnapshot, success_total: Decimal) -> QuotaSnapshot:
    """Attach derived USD spend metadata without touching throttle fields."""
    if snapshot.provider != "brave":
        return snapshot
    metadata: dict[str, Any] = dict(snapshot.metadata)
    metadata.setdefault("cost_per_req", COST_USD_PER_REQUEST)
    metadata.setdefault("allowance_usd", FREE_CREDITS_USD)
    try:
        metadata["spend_usd"] = brave_spend_usd(success_total)
    except (ArithmeticError, TypeError, ValueError):
        return snapshot.model_copy(update={"metadata": metadata})
    return snapshot.model_copy(update={"metadata": metadata})


async def _latest_quotas(
    repository: SQLiteRepository,
    providers: Sequence[str],
    *,
    totals: Sequence[UsageTotal | LegacyUsageTotal] | None = None,
) -> list[QuotaSnapshot]:
    """Return each provider's newest quota snapshot, keeping its provenance."""
    if totals is None:
        try:
            totals = await repository.usage_totals()
        except Exception:
            totals = []
    brave_total = _brave_request_success_total(totals)
    snapshots: list[QuotaSnapshot] = []
    for provider in providers:
        snapshot = await repository.latest_quota(provider)
        if snapshot is not None:
            normalized = normalize_degenerate_quota(snapshot)
            if normalized.provider == "brave":
                normalized = _enrich_brave_snapshot(normalized, brave_total)
            snapshots.append(normalized)
    return snapshots


async def _latest_health(
    repository: SQLiteRepository, providers: Sequence[str]
) -> list[ProviderHealth]:
    """Return each provider's newest health observation."""

    observations: list[ProviderHealth] = []
    for provider in providers:
        observation = await repository.latest_health(provider)
        if observation is not None:
            observations.append(observation)
    return observations


def _contract_totals(
    totals: Sequence[UsageTotal | LegacyUsageTotal],
) -> list[ProviderUsageTotal]:
    """Convert storage usage totals into their contract model."""

    return [
        ProviderUsageTotal(
            provider=total.provider,
            operation=total.operation,
            total_units=total.total_units,
            event_count=total.event_count,
            unit_kind=getattr(total, "unit_kind", None),
        )
        for total in totals
    ]


def _contract_recent(events: Sequence[UsageEvent]) -> list[RecentUsageEntry]:
    """Convert usage events into their privacy-projected entry model."""

    return [
        RecentUsageEntry(
            provider=event.provider,
            operation=event.operation,
            units=event.units,
            observed_at=event.observed_at,
            latency_ms=event.latency_ms,
            status=event.status,
            unit_kind=event.unit_kind,
            display_unit=event.display_unit,
        )
        for event in events
    ]


def _contract_health(observations: Sequence[ProviderHealth]) -> list[LatestHealthEntry]:
    """Convert health observations into their privacy-projected entry model."""

    return [
        LatestHealthEntry(
            provider=observation.provider,
            status=observation.status,
            checked_at=observation.checked_at,
        )
        for observation in observations
    ]


def _empty_stats() -> StatsResponse:
    """Return the empty monitoring snapshot used before any read succeeds."""

    return StatsResponse(
        notice=MONITORING_NOTICE,
        usage_totals=[],
        recent_usage=[],
        latest_quota=[],
        latest_health=[],
    )
