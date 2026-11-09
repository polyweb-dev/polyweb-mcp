"""Calendar UTC budget window boundaries."""

from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from freesearch.configuration.provider_limits import provider_limit_defaults
from freesearch.models.contracts import (
    ProviderError,
    SearchRequest,
    SearchResponse,
    UnitKind,
    UsageEvent,
    UsageOperation,
)
from freesearch.models.provider_limits import AuthMode, LimitOperation
from freesearch.services.pool_budget import actual_price, failure_price, request_price, window_start


@pytest.mark.parametrize(
    ("instant", "period", "expected"),
    [
        (datetime(2024, 3, 1, tzinfo=UTC), 86400, "2024-03-01"),
        (datetime(2024, 3, 1, 1, tzinfo=timezone(timedelta(hours=2))), 86400, "2024-02-29"),
        (datetime(2024, 3, 3, 23, 59, tzinfo=UTC), 604800, "2024-02-26"),
        (datetime(2024, 3, 4, tzinfo=UTC), 604800, "2024-03-04"),
        (datetime(2024, 2, 29, 23, 59, tzinfo=UTC), 2592000, "2024-02-01"),
        (datetime(2024, 3, 1, tzinfo=UTC), None, "2024-03-01"),
    ],
)
def test_calendar_window_start(instant: datetime, period: int | None, expected: str) -> None:
    assert window_start(instant, period) == expected


def test_window_rejects_naive_time_and_unknown_period() -> None:
    with pytest.raises(ValueError):
        window_start(datetime(2024, 1, 1), 86400)
    with pytest.raises(ValueError):
        window_start(datetime(2024, 1, 1, tzinfo=UTC), 1)


def test_request_and_reported_prices_follow_the_selected_rail() -> None:
    records = provider_limit_defaults()
    record = next(
        r for r in records if r.provider == "exa" and r.operation is LimitOperation.SEARCH
    )
    request = SearchRequest(query="test", limit=100)
    assert request_price(record, request) == Decimal("0.097")
    tavily = next(
        r
        for r in records
        if r.provider == "tavily"
        and r.operation is LimitOperation.SEARCH
        and r.auth_mode is AuthMode.KEYLESS
    )
    assert request_price(tavily, request) == 0
    keyed = next(
        r
        for r in records
        if r.provider == "tavily"
        and r.operation is LimitOperation.SEARCH
        and r.auth_mode is AuthMode.KEYED
    )
    assert request_price(keyed, SearchRequest(query="test", mode="advanced")) == Decimal("0.016")
    keenable = next(
        r
        for r in records
        if r.provider == "keenable"
        and r.operation is LimitOperation.SEARCH
        and r.auth_mode is AuthMode.KEYLESS
    )
    assert request_price(keenable, request) == 0
    unknown = record.model_copy(update={"budget": None})
    assert request_price(unknown, request) is None
    response = SearchResponse(
        provider="exa",
        query="test",
        results=[],
        usage=UsageEvent(
            provider="exa",
            operation=UsageOperation.SEARCH,
            units=Decimal("0.023"),
            unit_kind=UnitKind.USD,
            observed_at=datetime.now(UTC),
        ),
    )
    assert actual_price(record, response) == Decimal("0.023")
    error = ProviderError(
        provider="exa",
        code="upstream_error",
        message="failed",
        retryable=False,
        details={"actual_usd": "0.012"},
    )
    assert failure_price(record, error) == Decimal("0.012")
    assert failure_price(record, error.model_copy(update={"details": {}})) is None
