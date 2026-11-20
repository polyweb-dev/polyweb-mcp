"""Unit tests for USD pricing of recorded usage events."""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest

from polyweb.models.contracts import (
    CostSource,
    FetchRequest,
    SearchRequest,
    UnitKind,
    UsageCost,
    UsageEvent,
    UsageOperation,
    UsageStatus,
)
from polyweb.models.provider_limits import AuthMode
from polyweb.services.usage_cost import catalog_usage_event, usage_cost

_AT = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)


def _event(
    provider: str,
    units: str,
    kind: UnitKind | None,
    *,
    operation: UsageOperation = UsageOperation.SEARCH,
    metadata: dict[str, Any] | None = None,
    status: UsageStatus = UsageStatus.SUCCESS,
) -> UsageEvent:
    return UsageEvent(
        provider=provider,
        operation=operation,
        units=Decimal(units),
        unit_kind=kind,
        observed_at=_AT,
        metadata=metadata or {},
        status=status,
    )


def _estimated(usd: str) -> UsageCost:
    return UsageCost(usd=Decimal(usd), source=CostSource.ESTIMATED)


def test_vendor_reported_usd_is_reported() -> None:
    assert usage_cost(_event("exa", "0.0042", UnitKind.USD)) == UsageCost(
        usd=Decimal("0.0042"), source=CostSource.REPORTED
    )


def test_estimated_usd_gap_event_stays_estimated() -> None:
    metadata = {"estimated": True, "metering_gap": True}
    event = _event("you", "0.005", UnitKind.USD, metadata=metadata)

    assert usage_cost(event) == _estimated("0.005")


def test_exa_pricing_fallback_usd_event_is_estimated() -> None:
    metadata = {
        "provenance": "exa_pricing_fallback",
        "source": "estimated",
        "pricing_date": "2026-01-01",
    }
    event = _event("exa", "0.007", UnitKind.USD, metadata=metadata)

    assert usage_cost(event) == _estimated("0.007")


def test_free_unit_costs_zero() -> None:
    assert usage_cost(_event("anything", "3", UnitKind.FREE)) == _estimated("0")


@pytest.mark.parametrize(
    ("provider", "metadata"),
    [
        ("keenable", {"mode": "keyless", "cost_usd": Decimal("0")}),
        ("tinyfish", {"cost_usd": Decimal("0")}),
    ],
)
def test_adapter_metadata_cost_wins_over_the_catalog(
    provider: str, metadata: dict[str, Any]
) -> None:
    event = _event(provider, "1", UnitKind.REQUEST, metadata=metadata)

    assert usage_cost(event, auth_mode=AuthMode.KEYLESS) == _estimated("0")
    assert usage_cost(event) == _estimated("0")


@pytest.mark.parametrize("raw", ["-1", "NaN", "Infinity", "not-a-number", True, [1]])
def test_invalid_metadata_cost_falls_back_to_the_catalog(raw: object) -> None:
    event = _event("brave", "1", UnitKind.REQUEST, metadata={"cost_usd": raw})

    assert usage_cost(event) == _estimated("0.005")


def test_brave_request_uses_the_per_call_price() -> None:
    assert usage_cost(_event("brave", "1", UnitKind.REQUEST)) == _estimated("0.005")
    assert usage_cost(_event("brave", "3", UnitKind.REQUEST)) == _estimated("0.015")


@pytest.mark.parametrize(
    ("provider", "operation", "units", "expected"),
    [
        ("tavily", UsageOperation.SEARCH, "2", "0.016"),
        ("tavily", UsageOperation.FETCH, "1", "0.008"),
        ("firecrawl", UsageOperation.SEARCH, "2", "0.0076"),
        ("firecrawl", UsageOperation.FETCH, "1", "0.0038"),
    ],
)
def test_credit_events_use_the_catalog_credit_price(
    provider: str, operation: UsageOperation, units: str, expected: str
) -> None:
    event = _event(provider, units, UnitKind.CREDIT, operation=operation)

    assert usage_cost(event) == _estimated(expected)


def test_keenable_keyed_credits_price_on_the_request_record() -> None:
    assert usage_cost(_event("keenable", "2", UnitKind.CREDIT)) == _estimated("0.008")


def test_parallel_search_prices_mode_and_bundles() -> None:
    advanced = _event(
        "parallel",
        "1",
        UnitKind.REQUEST,
        metadata={"skus": [{"sku": "search", "count": 1}], "mode": "advanced", "extra_bundles": 0},
    )
    turbo = _event(
        "parallel",
        "1",
        UnitKind.REQUEST,
        metadata={"skus": [{"sku": "search", "count": 1}], "mode": "turbo", "extra_bundles": 2},
    )

    assert usage_cost(advanced) == _estimated("0.005")
    assert usage_cost(turbo) == _estimated("0.003")


def test_parallel_fetch_prices_each_url() -> None:
    event = _event(
        "parallel",
        "3",
        UnitKind.REQUEST,
        operation=UsageOperation.FETCH,
        metadata={"skus": [{"sku": "extract", "count": 3}], "url_count": 3},
    )

    assert usage_cost(event) == _estimated("0.003")


def test_parallel_unknown_legacy_mode_is_unknown_not_zero() -> None:
    event = _event(
        "parallel",
        "1",
        UnitKind.REQUEST,
        metadata={"skus": [{"sku": "search", "count": 1}], "mode": "ultra-mega"},
    )

    assert usage_cost(event) is None


@pytest.mark.parametrize("provider", ["tavily", "firecrawl", "parallel"])
def test_keyless_rails_without_a_price_are_unknown(provider: str) -> None:
    event = _event(provider, "1", UnitKind.CREDIT)

    assert usage_cost(event, auth_mode=AuthMode.KEYLESS) is None


def test_unknown_provider_is_unknown() -> None:
    assert usage_cost(_event("mystery", "1", UnitKind.REQUEST)) is None


def test_unit_kind_the_catalog_does_not_price_is_unknown() -> None:
    assert usage_cost(_event("tavily", "1", UnitKind.REQUEST)) is None
    assert usage_cost(_event("brave", "1", None)) is None


def test_zero_unit_failure_is_unknown() -> None:
    event = _event("brave", "0", UnitKind.REQUEST, status=UsageStatus.FAILURE)

    assert usage_cost(event) is None


def test_cost_estimate_operation_is_unknown() -> None:
    event = _event("brave", "1", UnitKind.REQUEST, operation=UsageOperation.COST_ESTIMATE)

    assert usage_cost(event) is None


@pytest.mark.parametrize(("limit", "credits", "usd"), [(10, "2", "0.0076"), (15, "4", "0.0152")])
def test_catalog_event_prices_firecrawl_search_bundles(limit: int, credits: str, usd: str) -> None:
    request = SearchRequest(query="q", limit=limit)

    event = catalog_usage_event("firecrawl", UsageOperation.SEARCH, AuthMode.KEYED, request, _AT)

    assert event == UsageEvent(
        provider="firecrawl",
        operation=UsageOperation.SEARCH,
        units=Decimal(credits),
        unit_kind=UnitKind.CREDIT,
        display_unit="credits",
        observed_at=_AT,
        metadata={"estimated": True, "metering_gap": True, "catalog_fallback": True},
    )
    assert usage_cost(event) == _estimated(usd)


def test_catalog_event_for_a_usd_rail_is_estimated() -> None:
    event = catalog_usage_event("exa", UsageOperation.SEARCH, AuthMode.KEYED, None, _AT)

    assert event is not None
    assert (event.units, event.unit_kind, event.display_unit) == (
        Decimal("0.007"),
        UnitKind.USD,
        "USD",
    )
    assert usage_cost(event) == _estimated("0.007")


@pytest.mark.parametrize(
    ("parallel_options", "mode", "extra_bundles", "expected"),
    [
        ({"mode": "turbo"}, None, 0, "0.001"),
        ({"mode": "turbo"}, None, 2, "0.003"),
        (None, "turbo", 0, "0.001"),
        ({"mode": "turbo"}, "advanced", 0, "0.001"),
        (None, None, 0, "0.005"),
        (None, "advanced", 0, "0.005"),
    ],
)
def test_catalog_event_prices_parallel_search_by_mode_and_bundles(
    parallel_options: dict[str, Any] | None,
    mode: str | None,
    extra_bundles: int,
    expected: str,
) -> None:
    provider_options = None if parallel_options is None else {"parallel": parallel_options}
    request = SearchRequest.model_validate(
        {
            "query": "q",
            "mode": mode,
            "extra_bundles": extra_bundles,
            "provider_options": provider_options,
        }
    )

    event = catalog_usage_event("parallel", UsageOperation.SEARCH, AuthMode.KEYED, request, _AT)

    assert event is not None
    assert (event.units, event.unit_kind, event.display_unit) == (
        Decimal(expected),
        UnitKind.USD,
        "USD",
    )
    assert event.metadata["estimated"] is True
    assert usage_cost(event) == _estimated(expected)


def test_catalog_event_prices_parallel_extract_per_url() -> None:
    request = FetchRequest(url="https://example.com/", url_count=3)

    event = catalog_usage_event("parallel", UsageOperation.FETCH, AuthMode.KEYED, request, _AT)

    assert event is not None
    assert (event.units, event.unit_kind) == (Decimal("0.003"), UnitKind.USD)
    assert usage_cost(event) == _estimated("0.003")


def test_catalog_event_for_parallel_without_a_request_uses_the_standard_cost() -> None:
    event = catalog_usage_event("parallel", UsageOperation.SEARCH, AuthMode.KEYED, None, _AT)

    assert event is not None
    assert (event.units, event.unit_kind) == (Decimal("0.005"), UnitKind.USD)


def test_catalog_event_for_an_unknown_provider_is_none() -> None:
    request = SearchRequest(query="q", limit=10)

    assert (
        catalog_usage_event("mystery", UsageOperation.SEARCH, AuthMode.KEYED, request, _AT) is None
    )


@pytest.mark.parametrize("provider", ["tavily", "firecrawl", "parallel", "keenable"])
def test_catalog_event_for_an_unpriced_keyless_rail_is_none(provider: str) -> None:
    request = SearchRequest(query="q", limit=10)

    assert (
        catalog_usage_event(provider, UsageOperation.SEARCH, AuthMode.KEYLESS, request, _AT) is None
    )


def test_catalog_event_without_a_native_unit_is_none() -> None:
    assert catalog_usage_event("tinyfish", UsageOperation.SEARCH, AuthMode.KEYED, None, _AT) is None


def test_catalog_event_for_a_cost_estimate_operation_is_none() -> None:
    assert (
        catalog_usage_event("firecrawl", UsageOperation.COST_ESTIMATE, AuthMode.KEYED, None, _AT)
        is None
    )
