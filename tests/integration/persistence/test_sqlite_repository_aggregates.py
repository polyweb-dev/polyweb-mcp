"""Boundary tests for the Stage 4.5 SQLite usage aggregate reads."""

import gc
import time
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest_asyncio

from polyweb.models.contracts import (
    AGGREGATED_PROVIDER,
    CostSource,
    UnitKind,
    UsageCost,
    UsageEvent,
    UsageOperation,
    UsageStatus,
)
from polyweb.persistence.storage import SQLiteRepository
from tests.fixtures.execution import seed_execution_project


def _unlink_with_retries(path: Path, *, attempts: int = 20) -> None:
    """Remove a test database after Windows releases delayed SQLite handles."""

    for attempt in range(attempts):
        try:
            path.unlink()
        except FileNotFoundError:
            return
        except PermissionError:
            if attempt == attempts - 1:
                raise
            gc.collect()
            time.sleep(0.05)
        else:
            return


@pytest_asyncio.fixture
async def repository(tmp_path: Path) -> AsyncIterator[SQLiteRepository]:
    db_path = tmp_path / "aggregates.db"
    db = await SQLiteRepository.open(db_path)
    try:
        yield db
    finally:
        await db.close()
        _unlink_with_retries(db_path)


def _event(
    provider: str,
    operation: UsageOperation,
    units: str,
    observed_at: datetime,
) -> UsageEvent:
    return UsageEvent(
        provider=provider,
        operation=operation,
        units=Decimal(units),
        observed_at=observed_at,
        metadata={"tokens": 1},
    )


async def test_usage_totals_are_decimal_exact_grouped_since_filtered_and_ordered(
    repository: SQLiteRepository,
) -> None:
    t0 = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
    events = [
        _event("alpha", UsageOperation.SEARCH, "123.456789", t0),
        _event("alpha", UsageOperation.SEARCH, "0.000001", t0 + timedelta(seconds=1)),
        _event("alpha", UsageOperation.FETCH, "7.250000", t0 + timedelta(seconds=2)),
        _event("beta", UsageOperation.SEARCH, "2.500000", t0 + timedelta(seconds=3)),
    ]
    for event in events:
        await repository.record_usage(event, attribution=await seed_execution_project(repository))

    totals = await repository.installation_usage_totals()
    assert [
        (total.provider, total.operation, total.total_units, total.event_count) for total in totals
    ] == [
        ("alpha", UsageOperation.FETCH, Decimal("7.250000"), 1),
        ("alpha", UsageOperation.SEARCH, Decimal("123.456790"), 2),
        ("beta", UsageOperation.SEARCH, Decimal("2.500000"), 1),
    ]

    plus_two = timezone(timedelta(hours=2))
    since_totals = await repository.installation_usage_totals(
        since=datetime(2026, 1, 1, 2, 0, 1, tzinfo=plus_two)
    )
    assert [
        (total.provider, total.operation, total.total_units, total.event_count)
        for total in since_totals
    ] == [
        ("alpha", UsageOperation.FETCH, Decimal("7.250000"), 1),
        ("alpha", UsageOperation.SEARCH, Decimal("0.000001"), 1),
        ("beta", UsageOperation.SEARCH, Decimal("2.500000"), 1),
    ]


def _kind_event(
    provider: str,
    units: str,
    kind: UnitKind | None,
    *,
    status: UsageStatus = UsageStatus.SUCCESS,
) -> UsageEvent:
    return UsageEvent(
        provider=provider,
        operation=UsageOperation.SEARCH,
        units=Decimal(units),
        unit_kind=kind,
        observed_at=datetime(2026, 1, 1, tzinfo=UTC),
        status=status,
    )


def _reported(usd: str) -> UsageCost:
    return UsageCost(usd=Decimal(usd), source=CostSource.REPORTED)


def _estimated(usd: str) -> UsageCost:
    return UsageCost(usd=Decimal(usd), source=CostSource.ESTIMATED)


async def test_usage_totals_sum_cost_flag_estimates_count_unpriced_and_skip_aggregated(
    repository: SQLiteRepository,
) -> None:
    recorded: list[tuple[UsageEvent, UsageCost | None]] = [
        (_kind_event("exa", "0.007", UnitKind.USD), _reported("0.007")),
        (_kind_event("exa", "0.001", UnitKind.USD), _reported("0.001")),
        (_kind_event("brave", "1", UnitKind.REQUEST), _estimated("0.005")),
        (_kind_event("brave", "1", UnitKind.REQUEST), None),
        (_kind_event("brave", "0", UnitKind.REQUEST, status=UsageStatus.FAILURE), None),
        (_kind_event("tavily", "2", UnitKind.CREDIT), None),
        (_kind_event("legacy", "3", None), None),
        (_kind_event(AGGREGATED_PROVIDER, "0", None), None),
    ]
    attribution = await seed_execution_project(repository)
    for event, cost in recorded:
        await repository.record_usage(event, attribution=attribution, cost=cost)

    totals = await repository.installation_usage_totals()

    assert [
        (
            total.provider,
            total.event_count,
            total.cost_usd,
            total.cost_estimated,
            total.unpriced_event_count,
        )
        for total in totals
    ] == [
        ("brave", 2, Decimal("0.005"), True, 1),
        ("exa", 2, Decimal("0.008"), False, 0),
        ("tavily", 1, None, False, 1),
        ("legacy", 1, None, False, 1),
    ]
    recent = await repository.recent_installation_usage(limit=20)
    assert AGGREGATED_PROVIDER in {event.provider for event in recent}


async def test_usage_total_stays_estimated_when_a_reported_cost_follows_an_estimate(
    repository: SQLiteRepository,
) -> None:
    attribution = await seed_execution_project(repository)
    await repository.record_usage(
        _kind_event("exa", "0.007", UnitKind.USD), attribution=attribution, cost=_estimated("0.007")
    )
    await repository.record_usage(
        _kind_event("exa", "0.001", UnitKind.USD), attribution=attribution, cost=_reported("0.001")
    )

    totals = await repository.installation_usage_totals()

    assert [(total.provider, total.cost_usd, total.cost_estimated) for total in totals] == [
        ("exa", Decimal("0.008"), True)
    ]


async def test_recent_usage_is_newest_first_and_respects_limit(
    repository: SQLiteRepository,
) -> None:
    t0 = datetime(2026, 1, 1, tzinfo=UTC)
    older = _event("older", UsageOperation.SEARCH, "1", t0)
    middle = _event("middle", UsageOperation.SEARCH, "2", t0 + timedelta(seconds=1))
    same_time_first = _event("same-first", UsageOperation.SEARCH, "3", t0 + timedelta(seconds=2))
    same_time_second = _event("same-second", UsageOperation.SEARCH, "4", t0 + timedelta(seconds=2))
    newest = _event("newest", UsageOperation.SEARCH, "5", t0 + timedelta(seconds=3))
    for event in (older, middle, same_time_first, same_time_second, newest):
        await repository.record_usage(event, attribution=await seed_execution_project(repository))

    recent = await repository.recent_installation_usage(limit=3)
    assert recent == [newest, same_time_second, same_time_first]
    assert len(recent) == 3
    assert [event.observed_at for event in recent] == [
        newest.observed_at,
        same_time_second.observed_at,
        same_time_first.observed_at,
    ]
