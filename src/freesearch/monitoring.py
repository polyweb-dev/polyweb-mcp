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

import logging
import os
from collections.abc import Awaitable, Callable, Sequence
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from pydantic import AwareDatetime

from freesearch.adapters.base import ProviderAdapter
from freesearch.contracts import (
    ContractModel,
    FetchResponse,
    HealthStatus,
    ProviderHealth,
    QuotaSnapshot,
    SearchResponse,
    UsageEvent,
    UsageOperation,
)
from freesearch.storage import SQLiteRepository, UsageTotal

logger = logging.getLogger(__name__)

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


class ProviderUsageTotal(ContractModel):
    """Aggregated usage units for one provider and operation."""

    provider: str
    operation: UsageOperation
    total_units: Decimal
    event_count: int


class RecentUsageEntry(ContractModel):
    """Privacy-projected recent usage event: no request id, no metadata."""

    provider: str
    operation: UsageOperation
    units: Decimal
    observed_at: datetime


class LatestHealthEntry(ContractModel):
    """Privacy-projected health observation: no diagnostic message."""

    provider: str
    status: HealthStatus
    checked_at: datetime


class StatsResponse(ContractModel):
    """Read-only monitoring snapshot served by the stats and dashboard reads."""

    notice: str
    usage_totals: list[ProviderUsageTotal]
    recent_usage: list[RecentUsageEntry]
    latest_quota: list[QuotaSnapshot]
    latest_health: list[LatestHealthEntry]


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


async def record_response_telemetry(
    repository: SQLiteRepository | None,
    response: SearchResponse | FetchResponse,
) -> None:
    """Persist ``response.usage`` and a healthy observation; never raise.

    Telemetry failures are logged without payload, response content, or
    exception text (which may embed query or URL data) and then swallowed, so a
    monitoring outage can never fail the user request being observed. Usage and
    health persistence are independent: a rejected usage write must never skip
    the healthy observation.
    """

    if repository is None:
        return
    try:
        if response.usage is not None:
            await repository.record_usage(response.usage)
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
    """Persist a degraded health observation for ``provider``; never raise."""

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


async def tracked_call[ResponseT: (SearchResponse, FetchResponse)](
    repository: SQLiteRepository | None,
    adapter: ProviderAdapter,
    call: Callable[[ProviderAdapter], Awaitable[ResponseT]],
) -> ResponseT:
    """Await ``call(adapter)`` recording success and failure telemetry around it.

    A routing failure never reaches this helper, so it records no telemetry.
    Adapter failures record a degraded observation and re-raise the original
    error; successful responses record usage and a healthy observation.
    """

    try:
        response = await call(adapter)
    except Exception:
        await record_failure_telemetry(repository, provider=adapter.name)
        raise
    await record_response_telemetry(repository, response)
    return response


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
        latest_quota = await _latest_quotas(repository, providers)
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


async def _latest_quotas(
    repository: SQLiteRepository, providers: Sequence[str]
) -> list[QuotaSnapshot]:
    """Return each provider's newest quota snapshot, keeping its provenance."""

    snapshots: list[QuotaSnapshot] = []
    for provider in providers:
        snapshot = await repository.latest_quota(provider)
        if snapshot is not None:
            snapshots.append(snapshot)
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


def _contract_totals(totals: Sequence[UsageTotal]) -> list[ProviderUsageTotal]:
    """Convert storage usage totals into their contract model."""

    return [
        ProviderUsageTotal(
            provider=total.provider,
            operation=total.operation,
            total_units=total.total_units,
            event_count=total.event_count,
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
