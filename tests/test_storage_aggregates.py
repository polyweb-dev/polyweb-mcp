"""Boundary tests for the Stage 4.5 SQLite usage aggregate reads."""

import tempfile
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest_asyncio

from freesearch.contracts import UsageEvent, UsageOperation
from freesearch.storage import SQLiteRepository


@pytest_asyncio.fixture
async def repository() -> AsyncIterator[SQLiteRepository]:
    with tempfile.NamedTemporaryFile(
        prefix="freesearch-aggregates-",
        suffix=".db",
        dir=Path.cwd(),
        delete=False,
    ) as temporary_file:
        db_path = Path(temporary_file.name)
    db = await SQLiteRepository.open(db_path)
    try:
        yield db
    finally:
        await db.close()
        db_path.unlink(missing_ok=True)


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
        await repository.record_usage(event)

    totals = await repository.usage_totals()
    assert [
        (total.provider, total.operation, total.total_units, total.event_count) for total in totals
    ] == [
        ("alpha", UsageOperation.FETCH, Decimal("7.250000"), 1),
        ("alpha", UsageOperation.SEARCH, Decimal("123.456790"), 2),
        ("beta", UsageOperation.SEARCH, Decimal("2.500000"), 1),
    ]

    plus_two = timezone(timedelta(hours=2))
    since_totals = await repository.usage_totals(
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
        await repository.record_usage(event)

    recent = await repository.recent_usage(limit=3)
    assert recent == [newest, same_time_second, same_time_first]
    assert len(recent) == 3
    assert [event.observed_at for event in recent] == [
        newest.observed_at,
        same_time_second.observed_at,
        same_time_first.observed_at,
    ]
