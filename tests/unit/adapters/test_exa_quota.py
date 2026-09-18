"""Unit tests for ExaAdapter quota tracking, spend ledger, and monthly budget.

Covers the Brave-like delta on top of the opt-in ledger: published-pricing
fallback when ``costDollars`` is absent (actual telemetry always wins),
manual starting credits with budget precedence, and OBSERVED exhaustion
snapshots for 402/429.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from exa_py.api import CostDollars, Result, SearchResponse

from freesearch.adapters.exa import ExaAdapter, _next_month_start
from freesearch.models.contracts import (
    QuotaSnapshot,
    QuotaSource,
    SearchRequest,
    UnitKind,
    UsageEvent,
    UsageOperation,
    UsageStatus,
    is_soft_quota_zero,
)


class _FakeClient:
    pass


class _FakeSDKClient:
    async def aclose(self) -> None:
        pass


class _FakeSDK:
    def __init__(self) -> None:
        self.client = _FakeSDKClient()
        self.search_response: object = None
        self.contents_response: object = None

    async def search(self, **kwargs: object) -> object:
        return self.search_response

    async def get_contents(self, urls: object, **kwargs: object) -> object:
        return self.contents_response


class _DirectRunner:
    async def run(self, provider: str, operation) -> object:
        return await operation()


class _MockRepository:
    def __init__(
        self,
        events: list[UsageEvent] | None = None,
        latest_quota: QuotaSnapshot | None = None,
    ) -> None:
        self._events = events or []
        self._latest = latest_quota

    async def list_usage(self, provider: str, since: datetime | None = None) -> list[UsageEvent]:
        return [
            e
            for e in self._events
            if e.provider == provider and (since is None or e.observed_at >= since)
        ]

    async def latest_quota(self, provider: str) -> QuotaSnapshot | None:
        if self._latest and self._latest.provider == provider:
            return self._latest
        return None


def _make_adapter(*, budget: Decimal | None = None, credits: Decimal | None = None) -> ExaAdapter:
    sdk = _FakeSDK()
    return ExaAdapter(
        _FakeClient(),
        runner=_DirectRunner(),
        sdk_client=sdk,
        monthly_budget=budget,
        manual_starting_credits=credits,
    )


def _make_search_response(cost_total: float = 0.007) -> SearchResponse:
    return SearchResponse(
        results=[
            Result(
                id="doc-1",
                url="https://example.com/test",
                title="Test Title",
                text="Test snippet text",
                highlights=["Test snippet"],
                score=0.95,
            )
        ],
        resolved_search_type=None,
        auto_date=None,
        cost_dollars=CostDollars(total=cost_total),
    )


# --- Budget Configuration & Validation ----------------------------------------


def test_default_adapter_is_unbudgeted_opt_in() -> None:
    adapter = ExaAdapter(_FakeClient(), runner=_DirectRunner(), sdk_client=_FakeSDK())
    assert adapter._monthly_budget is None


@pytest.mark.asyncio
async def test_default_adapter_quota_is_estimated_unknown() -> None:
    adapter = ExaAdapter(_FakeClient(), runner=_DirectRunner(), sdk_client=_FakeSDK())
    snapshot = await adapter.quota()
    assert snapshot is not None
    assert snapshot.source is QuotaSource.ESTIMATED
    assert snapshot.remaining is None
    assert snapshot.limit is None
    assert snapshot.metadata["limit_source"] is None
    assert snapshot.reset_at is not None


def test_unbudgeted_adapter_returns_none_quota() -> None:
    adapter = _make_adapter(budget=None)
    assert adapter._monthly_budget is None


@pytest.mark.asyncio
async def test_unbudgeted_adapter_quota_is_estimated_unknown() -> None:
    adapter = _make_adapter(budget=None)
    snapshot = await adapter.quota()
    assert snapshot is not None
    assert snapshot.source is QuotaSource.ESTIMATED
    assert snapshot.remaining is None
    assert snapshot.limit is None


def test_budget_rejection_of_invalid_types() -> None:
    with pytest.raises(ValueError, match="exact Decimal input"):
        _make_adapter(budget=10.5)  # float

    with pytest.raises(ValueError, match="exact Decimal input"):
        _make_adapter(budget=True)  # bool

    with pytest.raises(ValueError, match="finite and non-negative"):
        _make_adapter(budget=Decimal("-5.00"))


def test_dynamic_set_monthly_budget() -> None:
    adapter = _make_adapter(budget=None)
    assert adapter._monthly_budget is None

    adapter.set_monthly_budget(Decimal("15.00"))
    assert adapter._monthly_budget == Decimal("15.00")

    adapter.set_monthly_budget(None)
    assert adapter._monthly_budget is None


# --- Spend Tracking & Quota Calculation ---------------------------------------


@pytest.mark.asyncio
async def test_budgeted_quota_calculation() -> None:
    adapter = _make_adapter(budget=Decimal("10.00"))
    snapshot = await adapter.quota()
    assert snapshot is not None
    assert snapshot.provider == "exa"
    assert snapshot.limit == Decimal("10.00")
    assert snapshot.remaining == Decimal("10.00")
    assert snapshot.unit_kind is UnitKind.USD
    assert snapshot.display_unit == "USD"
    assert snapshot.source is QuotaSource.ESTIMATED
    assert snapshot.metadata["spend_usd"] == Decimal("0")
    assert snapshot.metadata["window"] == "monthly"
    assert snapshot.reset_at is not None


@pytest.mark.asyncio
async def test_search_accumulates_exact_usd_spend() -> None:
    adapter = _make_adapter(budget=Decimal("10.00"))
    sdk: _FakeSDK = adapter._sdk
    sdk.search_response = _make_search_response(0.007)

    response = await adapter.search(SearchRequest(query="ai news"))
    assert response.usage is not None
    assert response.usage.units == Decimal("0.007")
    assert response.usage.unit_kind is UnitKind.USD

    # Update through quota_after_success
    snapshot = adapter.quota_after_success(response)
    assert snapshot is not None
    assert snapshot.limit == Decimal("10.00")
    assert snapshot.remaining == Decimal("9.993")
    assert snapshot.metadata["spend_usd"] == Decimal("0.007")

    # Second search
    sdk.search_response = _make_search_response(0.005)
    response2 = await adapter.search(SearchRequest(query="more news"))
    snapshot2 = adapter.quota_after_success(response2)
    assert snapshot2 is not None
    assert snapshot2.remaining == Decimal("9.988")
    assert snapshot2.metadata["spend_usd"] == Decimal("0.012")


@pytest.mark.asyncio
async def test_spend_clamped_at_zero_when_exceeding_budget() -> None:
    adapter = _make_adapter(budget=Decimal("0.010"))
    sdk: _FakeSDK = adapter._sdk
    sdk.search_response = _make_search_response(0.015)

    response = await adapter.search(SearchRequest(query="test"))
    snapshot = adapter.quota_after_success(response)
    assert snapshot is not None
    assert snapshot.remaining == Decimal("0")
    assert snapshot.metadata["spend_usd"] == Decimal("0.015")


# --- Error Handling & Soft Zero ------------------------------------------------


def test_quota_after_error_402_produces_observed_zero() -> None:
    adapter = _make_adapter(budget=Decimal("10.00"))
    snapshot = adapter.quota_after_error(402)
    assert snapshot is not None
    assert snapshot.source is QuotaSource.OBSERVED
    assert snapshot.remaining == Decimal("0")
    assert snapshot.limit == Decimal("10.00")
    assert snapshot.reset_at is None
    assert snapshot.metadata["soft_zero"] is True
    assert snapshot.metadata["exhaustion"] is True
    assert snapshot.metadata["exhaustion_status"] == 402
    assert snapshot.metadata["limit_source"] == "monthly_budget"


def test_quota_after_error_402_without_limit_invents_no_limit() -> None:
    adapter = _make_adapter(budget=None)
    snapshot = adapter.quota_after_error(402)
    assert snapshot is not None
    assert snapshot.source is QuotaSource.OBSERVED
    assert snapshot.remaining == Decimal("0")
    assert snapshot.limit is None
    assert snapshot.metadata["limit_source"] is None


def test_quota_after_error_429_produces_observed_zero() -> None:
    adapter = _make_adapter(budget=Decimal("10.00"))
    snapshot = adapter.quota_after_error(429)
    assert snapshot is not None
    assert snapshot.source is QuotaSource.OBSERVED
    assert snapshot.remaining == Decimal("0")
    assert snapshot.metadata["exhaustion"] is True
    assert snapshot.metadata["exhaustion_status"] == 429


@pytest.mark.parametrize("status", [400, 401, 403, 500, None])
def test_quota_after_error_other_statuses_pass_through(status: int | None) -> None:
    adapter = _make_adapter(budget=Decimal("10.00"))
    assert adapter.quota_after_error(status) is None
    assert adapter._soft_zero is False


@pytest.mark.asyncio
async def test_exhaustion_then_quota_view_is_estimated_soft_zero() -> None:
    adapter = _make_adapter(budget=Decimal("10.00"))
    adapter.quota_after_error(402)

    view = await adapter.quota()

    assert view.source is QuotaSource.ESTIMATED
    assert view.remaining == Decimal("0")
    assert is_soft_quota_zero("exa", view) is True


@pytest.mark.asyncio
async def test_subsequent_success_clears_soft_zero() -> None:
    adapter = _make_adapter(budget=Decimal("10.00"))
    adapter.quota_after_error(402)
    assert adapter._soft_zero is True

    sdk: _FakeSDK = adapter._sdk
    sdk.search_response = _make_search_response(0.005)
    response = await adapter.search(SearchRequest(query="test"))

    snapshot = adapter.quota_after_success(response)
    assert snapshot is not None
    assert adapter._soft_zero is False
    assert snapshot.metadata.get("soft_zero") is False


# --- Hydration & Calendar Rollover --------------------------------------------


@pytest.mark.asyncio
async def test_hydrate_quota_reconstructs_current_month_spend() -> None:
    now = datetime.now(UTC)
    month_start = datetime(now.year, now.month, 1, tzinfo=UTC)

    # Past events: one from last month, two from this month
    last_month = month_start - timedelta(days=5)
    events = [
        UsageEvent(
            provider="exa",
            operation=UsageOperation.SEARCH,
            units=Decimal("0.050"),
            unit_kind=UnitKind.USD,
            status=UsageStatus.SUCCESS,
            observed_at=last_month,
        ),
        UsageEvent(
            provider="exa",
            operation=UsageOperation.SEARCH,
            units=Decimal("0.007"),
            unit_kind=UnitKind.USD,
            status=UsageStatus.SUCCESS,
            observed_at=month_start + timedelta(hours=2),
        ),
        UsageEvent(
            provider="exa",
            operation=UsageOperation.FETCH,
            units=Decimal("0.003"),
            unit_kind=UnitKind.USD,
            status=UsageStatus.SUCCESS,
            observed_at=month_start + timedelta(hours=5),
        ),
    ]

    repo = _MockRepository(events=events)
    adapter = _make_adapter(budget=Decimal("10.00"))

    snapshot = await adapter.hydrate_quota(repo)
    assert snapshot is not None
    assert snapshot.limit == Decimal("10.00")
    # Only current month events (0.007 + 0.003 = 0.010) counted
    assert snapshot.remaining == Decimal("9.990")
    assert snapshot.metadata["spend_usd"] == Decimal("0.010")


@pytest.mark.asyncio
async def test_month_rollover_resets_ledger() -> None:
    adapter = _make_adapter(budget=Decimal("10.00"))
    adapter._spend = Decimal("5.00")
    adapter._ledger_month = datetime(2026, 8, 1, tzinfo=UTC)

    now = datetime(2026, 9, 15, 12, 0, 0, tzinfo=UTC)
    snapshot = adapter._current_snapshot(now=now)
    assert snapshot is not None
    assert snapshot.remaining == Decimal("10.00")
    assert snapshot.metadata["spend_usd"] == Decimal("0")
    assert adapter._ledger_month == datetime(2026, 9, 1, tzinfo=UTC)


@pytest.mark.parametrize(
    ("observed", "expected"),
    [
        (datetime(2026, 12, 15, 12, 0, 0, tzinfo=UTC), datetime(2027, 1, 1, tzinfo=UTC)),
        (datetime(2026, 1, 31, 23, 59, 59, tzinfo=UTC), datetime(2026, 2, 1, tzinfo=UTC)),
        (datetime(2026, 2, 28, 0, 0, 0, tzinfo=UTC), datetime(2026, 3, 1, tzinfo=UTC)),
    ],
)
def test_next_month_start_rolls_over_year_boundary(observed: datetime, expected: datetime) -> None:
    assert _next_month_start(observed) == expected


# --- Pricing fallback (costDollars absent) ------------------------------------


def _fallback_result(index: int, summary: str | None = None) -> Result:
    fields: dict[str, object] = {
        "id": f"doc-{index}",
        "url": f"https://example.com/{index}",
        "title": f"Doc {index}",
        "text": f"Body {index}",
    }
    if summary is not None:
        fields["summary"] = summary
    return Result(**fields)


def _make_costless_search_response(results: list[Result]) -> SearchResponse:
    return SearchResponse(
        results=results, resolved_search_type=None, auto_date=None, cost_dollars=None
    )


def _make_costless_contents_response(results: list[Result]) -> SearchResponse:
    return SearchResponse(
        results=results, resolved_search_type=None, auto_date=None, cost_dollars=None
    )


@pytest.mark.asyncio
async def test_search_fallback_prices_base_for_ten_or_fewer_results() -> None:
    adapter = _make_adapter(budget=Decimal("10.00"))
    sdk: _FakeSDK = adapter._sdk
    sdk.search_response = _make_costless_search_response(
        [_fallback_result(1), _fallback_result(2), _fallback_result(3)]
    )

    response = await adapter.search(SearchRequest(query="fallback"))

    assert response.usage is not None
    assert response.usage.operation is UsageOperation.SEARCH
    assert response.usage.units == Decimal("0.007")
    assert response.usage.unit_kind is UnitKind.USD
    assert response.usage.metadata["provenance"] == "exa_pricing_fallback"
    assert response.usage.metadata["result_count"] == 3
    assert response.usage.metadata["summary_count"] == 0


@pytest.mark.asyncio
async def test_search_fallback_prices_zero_results_at_base() -> None:
    adapter = _make_adapter(budget=Decimal("10.00"))
    sdk: _FakeSDK = adapter._sdk
    sdk.search_response = _make_costless_search_response([])

    response = await adapter.search(SearchRequest(query="empty"))

    assert response.usage is not None
    assert response.usage.units == Decimal("0.007")
    assert response.total_results == 0


@pytest.mark.asyncio
async def test_search_fallback_prices_results_over_ten() -> None:
    adapter = _make_adapter(budget=Decimal("10.00"))
    sdk: _FakeSDK = adapter._sdk
    sdk.search_response = _make_costless_search_response(
        [_fallback_result(index) for index in range(12)]
    )

    response = await adapter.search(SearchRequest(query="many"))

    assert response.usage is not None
    assert response.usage.units == Decimal("0.009")
    assert response.usage.metadata["result_count"] == 12


@pytest.mark.asyncio
async def test_search_fallback_prices_non_empty_summaries_only() -> None:
    adapter = _make_adapter(budget=Decimal("10.00"))
    sdk: _FakeSDK = adapter._sdk
    sdk.search_response = _make_costless_search_response(
        [
            _fallback_result(1, summary="First summary."),
            _fallback_result(2, summary=""),
            _fallback_result(3),
        ]
    )

    response = await adapter.search(SearchRequest(query="summaries"))

    assert response.usage is not None
    assert response.usage.units == Decimal("0.008")
    assert response.usage.metadata["summary_count"] == 1


@pytest.mark.asyncio
async def test_search_fallback_math_is_decimal_exact() -> None:
    adapter = _make_adapter(budget=Decimal("10.00"))
    sdk: _FakeSDK = adapter._sdk
    sdk.search_response = _make_costless_search_response(
        [_fallback_result(index, summary=f"Summary {index}.") for index in range(12)]
    )

    response = await adapter.search(SearchRequest(query="exact"))

    assert response.usage is not None
    assert isinstance(response.usage.units, Decimal)
    # 0.007 base + 2 extra results + 12 summaries, summed without float drift.
    assert response.usage.units == Decimal("0.021")


@pytest.mark.asyncio
async def test_measured_cost_beats_fallback_regardless_of_counts() -> None:
    adapter = _make_adapter(budget=Decimal("10.00"))
    sdk: _FakeSDK = adapter._sdk
    sdk.search_response = _make_search_response(0.0042)
    sdk.search_response.results.extend(_fallback_result(index) for index in range(1, 12))

    response = await adapter.search(SearchRequest(query="measured"))

    assert response.usage is not None
    assert response.usage.units == Decimal("0.0042")
    assert "provenance" not in response.usage.metadata


@pytest.mark.asyncio
async def test_contents_fallback_prices_single_text_page() -> None:
    from freesearch.models.contracts import FetchRequest

    adapter = _make_adapter(budget=Decimal("10.00"))
    sdk: _FakeSDK = adapter._sdk
    sdk.contents_response = _make_costless_contents_response([_fallback_result(1, summary=None)])

    response = await adapter.fetch(FetchRequest(url="https://example.com/1"))

    assert response.usage is not None
    assert response.usage.operation is UsageOperation.FETCH
    assert response.usage.units == Decimal("0.001")
    assert response.usage.metadata["provenance"] == "exa_pricing_fallback"


@pytest.mark.asyncio
async def test_contents_fallback_prices_every_returned_page() -> None:
    from freesearch.models.contracts import FetchRequest

    adapter = _make_adapter(budget=Decimal("10.00"))
    sdk: _FakeSDK = adapter._sdk
    sdk.contents_response = _make_costless_contents_response(
        [_fallback_result(1), _fallback_result(2), _fallback_result(3)]
    )

    response = await adapter.fetch(FetchRequest(url="https://example.com/2"))

    assert response.usage is not None
    assert response.usage.units == Decimal("0.003")
    assert response.usage.metadata["page_count"] == 3


@pytest.mark.asyncio
async def test_fallback_spend_accumulates_into_monthly_sum() -> None:
    adapter = _make_adapter(budget=Decimal("10.00"))
    sdk: _FakeSDK = adapter._sdk
    sdk.search_response = _make_costless_search_response([_fallback_result(1)])
    first = await adapter.search(SearchRequest(query="one"))
    adapter.quota_after_success(first)

    sdk.search_response = _make_search_response(0.005)
    second = await adapter.search(SearchRequest(query="two"))
    snapshot = adapter.quota_after_success(second)

    assert snapshot.metadata["spend_usd"] == Decimal("0.012")
    assert snapshot.remaining == Decimal("9.988")


# --- Manual starting credits --------------------------------------------------


@pytest.mark.asyncio
async def test_manual_credits_take_precedence_over_monthly_budget() -> None:
    adapter = _make_adapter(budget=Decimal("10.00"), credits=Decimal("5.00"))
    snapshot = await adapter.quota()
    assert snapshot.limit == Decimal("5.00")
    assert snapshot.remaining == Decimal("5.00")
    assert snapshot.source is QuotaSource.ESTIMATED
    assert snapshot.metadata["limit_source"] == "manual_starting_credits"


@pytest.mark.asyncio
async def test_manual_credits_minus_spend_clamps_at_zero() -> None:
    adapter = _make_adapter(credits=Decimal("0.010"))
    sdk: _FakeSDK = adapter._sdk
    sdk.search_response = _make_search_response(0.015)

    response = await adapter.search(SearchRequest(query="over"))
    snapshot = adapter.quota_after_success(response)

    assert snapshot.limit == Decimal("0.010")
    assert snapshot.remaining == Decimal("0")
    assert snapshot.metadata["spend_usd"] == Decimal("0.015")


@pytest.mark.asyncio
async def test_explicit_none_credits_falls_back_to_monthly_budget() -> None:
    adapter = _make_adapter(budget=Decimal("10.00"), credits=None)
    snapshot = await adapter.quota()
    assert snapshot.limit == Decimal("10.00")
    assert snapshot.remaining == Decimal("10.00")
    assert snapshot.metadata["limit_source"] == "monthly_budget"


@pytest.mark.asyncio
async def test_set_manual_credits_round_trip_preserves_spend() -> None:
    adapter = _make_adapter(budget=Decimal("10.00"))
    sdk: _FakeSDK = adapter._sdk
    sdk.search_response = _make_search_response(0.007)
    response = await adapter.search(SearchRequest(query="spend"))
    adapter.quota_after_success(response)

    adapter.set_manual_starting_credits(Decimal("5.00"))
    snapshot = await adapter.quota()
    assert snapshot.limit == Decimal("5.00")
    assert snapshot.remaining == Decimal("4.993")
    assert snapshot.metadata["spend_usd"] == Decimal("0.007")

    adapter.set_manual_starting_credits(None)
    reverted = await adapter.quota()
    assert reverted.limit == Decimal("10.00")
    assert reverted.remaining == Decimal("9.993")


# --- Provenance + calendar aggregation ----------------------------------------


def test_exa_adapter_source_never_authoritative() -> None:
    root = Path(__file__).resolve().parents[3]
    text = (root / "src" / "freesearch" / "adapters" / "exa.py").read_text(encoding="utf-8")
    assert "AUTHORITATIVE" not in text


@pytest.mark.asyncio
async def test_snapshot_sources_stay_estimated_or_observed() -> None:
    adapter = _make_adapter(budget=Decimal("10.00"))
    normal = await adapter.quota()
    exhausted = adapter.quota_after_error(429)
    assert exhausted is not None
    assert {normal.source, exhausted.source} <= {
        QuotaSource.ESTIMATED,
        QuotaSource.OBSERVED,
    }


@pytest.mark.asyncio
async def test_december_to_january_snapshot_resets_monthly_spend() -> None:
    adapter = _make_adapter(budget=Decimal("10.00"))
    adapter._spend = Decimal("4.00")
    adapter._ledger_month = datetime(2026, 12, 1, tzinfo=UTC)

    snapshot = adapter._current_snapshot(now=datetime(2027, 1, 10, tzinfo=UTC))

    assert snapshot.remaining == Decimal("10.00")
    assert snapshot.metadata["spend_usd"] == Decimal("0")
    assert adapter._ledger_month == datetime(2027, 1, 1, tzinfo=UTC)
