"""Unit tests for ExaAdapter quota tracking, spend ledger, and monthly budget."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from exa_py.api import CostDollars, Result, SearchResponse

from freesearch.adapters.exa import EXA_DEFAULT_MONTHLY_BUDGET_USD, ExaAdapter
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

    async def search(self, **kwargs: object) -> object:
        return self.search_response


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


def _make_adapter(*, budget: Decimal | None = None) -> ExaAdapter:
    sdk = _FakeSDK()
    return ExaAdapter(
        _FakeClient(),
        runner=_DirectRunner(),
        sdk_client=sdk,
        monthly_budget=budget,
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


def test_default_monthly_budget_constant() -> None:
    assert Decimal("10.00") == EXA_DEFAULT_MONTHLY_BUDGET_USD


def test_default_adapter_has_default_monthly_budget() -> None:
    adapter = ExaAdapter(_FakeClient(), runner=_DirectRunner(), sdk_client=_FakeSDK())
    assert adapter._monthly_budget == EXA_DEFAULT_MONTHLY_BUDGET_USD


def test_unbudgeted_adapter_returns_none_quota() -> None:
    adapter = _make_adapter(budget=None)
    assert adapter._monthly_budget is None


@pytest.mark.asyncio
async def test_unbudgeted_adapter_quota_is_none() -> None:
    adapter = _make_adapter(budget=None)
    assert await adapter.quota() is None


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


def test_quota_after_error_402_triggers_soft_zero() -> None:
    adapter = _make_adapter(budget=Decimal("10.00"))
    snapshot = adapter.quota_after_error(402)
    assert snapshot is not None
    assert snapshot.remaining == Decimal("0")
    assert snapshot.metadata["soft_zero"] is True
    assert is_soft_quota_zero("exa", snapshot) is True


def test_quota_after_error_429_is_transient() -> None:
    adapter = _make_adapter(budget=Decimal("10.00"))
    snapshot = adapter.quota_after_error(429)
    assert snapshot is None


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
