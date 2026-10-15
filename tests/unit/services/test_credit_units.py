"""Synthetic S0 unit tests for exact CRD arithmetic (K=0.001).

All fixtures are synthetic. No provider builders, no vendor I/O, no DB.
Reference: PLAN rev5 scale K=Decimal("0.001"), rev6 S0 core slice.
"""

from decimal import Decimal

import pytest

from freesearch.models.contracts import UnitKind
from freesearch.models.provider_limits import (
    AuthMode,
    BudgetBlock,
    BudgetModel,
    CRDPriceProfile,
    CRDState,
    LimitOperation,
    NativeDebit,
    NativePool,
    ProviderLimitRecord,
    RateBlock,
)
from freesearch.services.credit_units import (
    crd_state,
    crd_view,
    effective_crd,
    native_to_crd,
    possible_standard_calls,
    priced_crd_debit,
    project_shared_crd_views,
    request_cost_crd,
    request_native_cost,
    shared_pool_funds,
    spendable_crd,
)

REF = Decimal("0.001")


def _profile(price: str | Decimal | None, ref: str | Decimal = "0.001") -> CRDPriceProfile:
    """Build a synthetic conversion profile with an explicit reference."""
    if price is None:
        native: Decimal | None = None
    elif isinstance(price, Decimal):
        native = price
    else:
        native = Decimal(price)
    reference = ref if isinstance(ref, Decimal) else Decimal(ref)
    return CRDPriceProfile(reference_usd_per_crd=reference, native_usd_per_unit=native)


def _pool(
    remaining: str | Decimal | None,
    unit: UnitKind,
    pool_id: str = "synth:keyed:usd",
) -> NativePool:
    """Build a synthetic native pool with an exact remaining balance."""
    if remaining is None:
        value: Decimal | None = None
    elif isinstance(remaining, Decimal):
        value = remaining
    else:
        value = Decimal(remaining)
    return NativePool(
        pool_id=pool_id,
        provider="synth",
        auth_mode=AuthMode.KEYED,
        native_unit=unit,
        remaining=value,
    )


def _record(
    provider: str = "synth",
    operation: LimitOperation = LimitOperation.SEARCH,
    budget_model: BudgetModel | None = BudgetModel.USD,
    native_cost: str | Decimal | None = "0.005",
    *,
    auth_mode: AuthMode = AuthMode.KEYED,
    native_unit: UnitKind | None = UnitKind.USD,
    priced: bool = True,
    supported: bool = True,
    transport_available: bool = True,
    price: str | Decimal | None = None,
    pool_id: str | None = "synth:keyed:usd",
    rate: RateBlock | None = None,
) -> ProviderLimitRecord:
    """Build a synthetic catalog record without provider defaults."""
    budget = None
    if budget_model is not None and native_cost is not None:
        cost = native_cost if isinstance(native_cost, Decimal) else Decimal(native_cost)
        budget = BudgetBlock(model=budget_model, standard_native_cost=cost, priced=priced)
    return ProviderLimitRecord(
        provider=provider,
        operation=operation,
        auth_mode=auth_mode,
        supported=supported,
        transport_available=transport_available,
        rate=rate,
        budget=budget,
        native_unit=native_unit,
        native_pool_id=pool_id,
        conversion_profile=_profile(price),
    )


def _rate_block() -> RateBlock:
    """Return an empty synthetic rate block so the import is exercised."""
    return RateBlock(windows=[], published=False)


# K=0.001 scale ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("usd", "expected"),
    [
        ("0.001", "1"),
        ("0.002", "2"),
        ("5", "5000"),
        ("10", "10000"),
        ("100", "100000"),
    ],
)
def test_k_scale_usd_to_crd(usd: str, expected: str) -> None:
    profile = _profile(None)
    assert profile.reference_usd_per_crd == REF
    pool = _pool(usd, UnitKind.USD)
    assert native_to_crd(pool, profile) == Decimal(expected)


def test_brave_you_standard_search_cost_five() -> None:
    record = _record(native_cost="0.005")
    assert request_native_cost(record) == Decimal("0.005")
    assert request_cost_crd(record) == Decimal("5")


def test_exa_standard_search_cost_seven() -> None:
    record = _record(provider="synth-exa", native_cost="0.007")
    assert request_cost_crd(record) == Decimal("7")


def test_parallel_turbo_cost_one() -> None:
    assert request_cost_crd(_record(native_cost="0.001")) == Decimal("1")


def test_parallel_basic_cost_five() -> None:
    assert request_cost_crd(_record(native_cost="0.005")) == Decimal("5")


def test_tavily_paygo_basic_search_cost_eight() -> None:
    record = _record(
        provider="synth-tavily",
        budget_model=BudgetModel.CREDITS,
        native_cost="1",
        native_unit=UnitKind.CREDIT,
        price="0.008",
        pool_id="synth:keyed:credit",
    )
    assert request_native_cost(record) == Decimal("1")
    assert request_cost_crd(record) == Decimal("8")


def test_tavily_basic_url_cost_fractional() -> None:
    record = _record(
        provider="synth-tavily",
        operation=LimitOperation.FETCH,
        budget_model=BudgetModel.CREDITS,
        native_cost="0.2",
        native_unit=UnitKind.CREDIT,
        price="0.008",
        pool_id="synth:keyed:credit",
    )
    assert request_cost_crd(record) == Decimal("1.6")


def test_firecrawl_hobby_standard_fetch_cost() -> None:
    record = _record(
        provider="firecrawl",
        operation=LimitOperation.FETCH,
        budget_model=BudgetModel.CREDITS,
        native_cost="1",
        native_unit=UnitKind.CREDIT,
        price="0.0038",
        pool_id="firecrawl:keyed:credit",
    )
    assert request_cost_crd(record) == Decimal("3.8")


def test_firecrawl_scale_annual_exact_fetch_cost() -> None:
    record = _record(
        provider="firecrawl",
        operation=LimitOperation.FETCH,
        budget_model=BudgetModel.CREDITS,
        native_cost="1",
        native_unit=UnitKind.CREDIT,
        price="0.000599",
        pool_id="firecrawl:keyed:credit",
    )
    assert request_cost_crd(record) == Decimal("0.599")


def test_daily_pool_100_queries_equals_500_crd() -> None:
    pool = _pool("100", UnitKind.REQUEST, pool_id="synth:keyed:daily")
    assert native_to_crd(pool, _profile("0.005")) == Decimal("500")


# Exactness -------------------------------------------------------------------


def test_fractional_debits_sum_exactly() -> None:
    profile = _profile(None)
    first = priced_crd_debit(
        NativeDebit(
            provider="synth",
            operation=LimitOperation.SEARCH,
            auth_mode=AuthMode.KEYED,
            native_unit=UnitKind.USD,
            native_units=Decimal("0.1"),
        ),
        profile,
    )
    second = priced_crd_debit(
        NativeDebit(
            provider="synth",
            operation=LimitOperation.SEARCH,
            auth_mode=AuthMode.KEYED,
            native_unit=UnitKind.USD,
            native_units=Decimal("0.2"),
        ),
        profile,
    )
    assert first == Decimal("100")
    assert second == Decimal("200")
    assert first + second == Decimal("300")
    assert Decimal("0.1") + Decimal("0.2") == Decimal("0.3")


def test_repeated_fractional_debits_stay_exact() -> None:
    total = Decimal("0")
    for _ in range(3):
        total += Decimal("0.599")
    assert total == Decimal("1.797")
    assert isinstance(total, Decimal)


def test_unknown_price_returns_none_never_zero() -> None:
    pool = _pool("10", UnitKind.CREDIT, pool_id="synth:keyed:credit")
    result = native_to_crd(pool, _profile(None))
    assert result is None
    assert result != Decimal("0")


def test_unknown_price_debit_returns_none() -> None:
    debit = NativeDebit(
        provider="synth",
        operation=LimitOperation.SEARCH,
        auth_mode=AuthMode.KEYED,
        native_unit=UnitKind.CREDIT,
        native_units=Decimal("1"),
    )
    assert priced_crd_debit(debit, _profile(None)) is None


def test_free_unit_prices_at_zero() -> None:
    pool = _pool("100", UnitKind.FREE, pool_id="synth:keyed:free")
    assert native_to_crd(pool, _profile(None)) == Decimal("0")


def test_zero_native_debit_is_zero_even_without_price() -> None:
    debit = NativeDebit(
        provider="synth",
        operation=LimitOperation.SEARCH,
        auth_mode=AuthMode.KEYED,
        native_unit=UnitKind.CREDIT,
        native_units=Decimal("0"),
    )
    assert priced_crd_debit(debit, _profile(None)) == Decimal("0")


def test_negative_remaining_clamped_to_zero_in_view() -> None:
    # NativePool rejects negatives; model_construct exercises the defensive clamp.
    # A zero standard cost keeps possible_standard_calls at None so only the
    # remaining clamp is under test.
    record = _record(native_cost="0")
    pool = NativePool.model_construct(
        pool_id="synth:keyed:usd",
        provider="synth",
        auth_mode=AuthMode.KEYED,
        native_unit=UnitKind.USD,
        remaining=Decimal("-5"),
    )
    view = crd_view(record, pool)
    assert view.state is CRDState.FINITE
    assert view.remaining_crd == Decimal("0")


def test_sub_one_call_capacity_floors_to_zero() -> None:
    record = _record(native_cost="1")
    pool = _pool("0.5", UnitKind.USD)
    assert possible_standard_calls(record, pool) == Decimal("0")


def test_exa_ten_usd_gives_1428_whole_searches() -> None:
    record = _record(provider="synth-exa", native_cost="0.007")
    pool = _pool("10", UnitKind.USD)
    assert possible_standard_calls(record, pool) == Decimal("1428")


def test_spendable_is_minimum_of_remaining_and_grant() -> None:
    record = _record(native_cost="0.005")
    pool = _pool("10", UnitKind.USD)
    view = crd_view(record, pool, grant_remaining=Decimal("3"))
    assert view.remaining_crd == Decimal("10000")
    assert view.local_remaining_crd == Decimal("3")
    assert spendable_crd(view) == Decimal("3")


def test_zero_grant_keeps_native_funds_with_local_zero() -> None:
    record = _record(native_cost="0.005")
    pool = _pool("0.005", UnitKind.USD)
    view = crd_view(record, pool)
    combined = effective_crd(view, Decimal("0"))
    assert combined.remaining_crd == Decimal("5")
    assert combined.local_remaining_crd == Decimal("0")
    assert spendable_crd(combined) == Decimal("0")


def test_shared_views_project_together_funds_count_once() -> None:
    pool = _pool("1000", UnitKind.CREDIT, pool_id="shared:keyed:credit")
    profile = _profile("0.0038")
    search = _record(
        provider="shared",
        operation=LimitOperation.SEARCH,
        budget_model=BudgetModel.CREDITS,
        native_cost="1",
        native_unit=UnitKind.CREDIT,
        price="0.0038",
        pool_id="shared:keyed:credit",
    )
    fetch = _record(
        provider="shared",
        operation=LimitOperation.FETCH,
        budget_model=BudgetModel.CREDITS,
        native_cost="1",
        native_unit=UnitKind.CREDIT,
        price="0.0038",
        pool_id="shared:keyed:credit",
    )
    # Exercise the RateBlock import without changing covered behavior.
    assert _rate_block().windows == []
    views = project_shared_crd_views(pool, [search, fetch])
    assert len(views) == 2
    funds = shared_pool_funds(pool, [search, fetch])
    assert funds == Decimal("3800")
    assert views[0].remaining_crd == funds
    assert views[1].remaining_crd == funds
    assert views[0].remaining_crd + views[1].remaining_crd == Decimal("7600")
    assert funds == native_to_crd(pool, profile)
    assert shared_pool_funds(pool, []) is None


# States ----------------------------------------------------------------------


def test_unsupported_takes_precedence_over_null_budget() -> None:
    record = _record(supported=False, budget_model=None, native_cost=None)
    pool = _pool("10", UnitKind.USD)
    assert crd_state(record, pool) is CRDState.UNAVAILABLE


def test_transport_unavailable_is_unavailable() -> None:
    record = _record(transport_available=False)
    pool = _pool("10", UnitKind.USD)
    assert crd_state(record, pool) is CRDState.UNAVAILABLE


def test_eligible_null_budget_is_unmetered() -> None:
    record = _record(budget_model=None, native_cost=None)
    pool = _pool("10", UnitKind.USD)
    assert crd_state(record, pool) is CRDState.UNMETERED
    view = crd_view(record, pool)
    assert view.state is CRDState.UNMETERED
    assert spendable_crd(view) is None


def test_unpriced_budget_is_unknown_never_zero() -> None:
    record = _record(priced=False)
    pool = _pool("10", UnitKind.USD)
    assert crd_state(record, pool) is CRDState.UNKNOWN
    view = crd_view(record, pool)
    assert view.remaining_crd is None
    assert view.remaining_crd != Decimal("0")


def test_absent_balance_is_unknown() -> None:
    record = _record(native_cost="0.005")
    assert crd_state(record, None) is CRDState.UNKNOWN
    assert crd_state(record, _pool(None, UnitKind.USD)) is CRDState.UNKNOWN


def test_finite_only_with_known_priced_balance() -> None:
    record = _record(native_cost="0.005")
    pool = _pool("5", UnitKind.USD)
    assert crd_state(record, pool) is CRDState.FINITE
    view = crd_view(record, pool)
    assert view.remaining_crd == Decimal("5000")


def test_exact_gate_point_five_eight_cannot_cover_point_five_nine_nine() -> None:
    balance = Decimal("0.58")
    cost = Decimal("0.599")
    assert balance < cost
    assert balance != cost
    record = _record(
        provider="firecrawl",
        operation=LimitOperation.FETCH,
        budget_model=BudgetModel.CREDITS,
        native_cost="1",
        native_unit=UnitKind.CREDIT,
        price="0.000599",
        pool_id="firecrawl:keyed:credit",
    )
    assert request_cost_crd(record) == cost
    pool = _pool("1", UnitKind.CREDIT, pool_id="firecrawl:keyed:credit")
    funds = native_to_crd(pool, _profile("0.000599"))
    assert funds == cost
    assert balance < funds


def test_unsupported_view_has_no_request_cost() -> None:
    record = _record(supported=False, native_cost="0.005")
    view = crd_view(record, _pool("5", UnitKind.USD))
    assert view.state is CRDState.UNAVAILABLE
    assert view.request_cost_crd is None
    assert view.remaining_crd is None


# Tavily depth rule (PLAN 4.1): same rule as the adapter ------------------------


def test_tavily_search_depth_rule_basic_and_advanced() -> None:
    from freesearch.models.contracts import SearchRequest

    record = _record(
        provider="tavily",
        budget_model=BudgetModel.CREDITS,
        native_cost="1",
        native_unit=UnitKind.CREDIT,
        price="0.008",
        pool_id="tavily:keyed:credit",
    )
    assert (
        request_native_cost(record, SearchRequest(query="q", limit=2)) == Decimal("1")
    )
    assert (
        request_native_cost(record, SearchRequest(query="q", limit=2, mode="advanced"))
        == Decimal("2")
    )


def test_tavily_extract_depth_rule_basic_and_advanced() -> None:
    from freesearch.models.contracts import FetchRequest
    from freesearch.models.tavily import TavilyExtractParams

    record = _record(
        provider="tavily",
        operation=LimitOperation.FETCH,
        budget_model=BudgetModel.CREDITS,
        native_cost="0.2",
        native_unit=UnitKind.CREDIT,
        price="0.008",
        pool_id="tavily:keyed:credit",
    )
    basic = FetchRequest(
        url="https://example.com/a", tavily=TavilyExtractParams(extract_depth="basic")
    )
    advanced = FetchRequest(
        url="https://example.com/a", tavily=TavilyExtractParams(extract_depth="advanced")
    )
    assert request_native_cost(record, basic) == Decimal("0.2")
    assert request_native_cost(record, advanced) == Decimal("0.4")
    assert request_cost_crd(record, basic) == Decimal("1.6")
    assert request_cost_crd(record, advanced) == Decimal("3.2")
