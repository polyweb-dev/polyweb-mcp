"""Project routing cost and ordering rules."""

from decimal import Decimal

import pytest

from freesearch.configuration.provider_limits import PROVIDER_IDS
from freesearch.models.project_routing import RoutingOperation, RoutingStrategy
from freesearch.services.routing_order import (
    call_cost_usd,
    catalog_call_costs,
    merge_order,
    order_for,
)


@pytest.mark.parametrize(
    ("provider", "search", "fetch"),
    [
        ("keenable", "0", "0"),
        ("tinyfish", "0", "0"),
        ("brave", "0.005", None),
        ("parallel", "0.005", "0.001"),
        ("you", "0.005", "0.001"),
        ("exa", "0.007", "0.001"),
        ("firecrawl", "0.0076", "0.0038"),
        ("tavily", "0.008", "0.0016"),
    ],
)
def test_catalog_prices(provider: str, search: str, fetch: str | None) -> None:
    assert call_cost_usd(provider, RoutingOperation.SEARCH) == Decimal(search)
    assert call_cost_usd(provider, RoutingOperation.FETCH) == (
        Decimal(fetch) if fetch is not None else None
    )


@pytest.mark.parametrize("provider", ["keenable", "tavily"])
def test_keyless_catalog_matches_project_routing(provider: str) -> None:
    costs = catalog_call_costs(provider, keyless=True)
    assert {operation.value: price for operation, price in costs.items()} == {
        "search": Decimal(0),
        "fetch": Decimal(0),
    }
    for operation in RoutingOperation:
        assert call_cost_usd(provider, operation, keyless=True) == costs[operation.value]


def test_paid_only_provider_has_no_keyless_price() -> None:
    assert catalog_call_costs("brave", keyless=True) == {}


@pytest.mark.parametrize(
    ("operation", "strategy", "expected"),
    [
        ("search", "free_first", "keenable tinyfish brave exa firecrawl parallel tavily you"),
        ("search", "lowest_cost", "keenable tinyfish brave parallel you exa firecrawl tavily"),
        ("fetch", "free_first", "keenable tinyfish exa firecrawl parallel tavily you"),
        ("fetch", "lowest_cost", "keenable tinyfish exa parallel you tavily firecrawl"),
    ],
)
def test_presets(operation: str, strategy: str, expected: str) -> None:
    op = RoutingOperation(operation)
    costs = {provider: call_cost_usd(provider, op) for provider in PROVIDER_IDS}
    members = [provider for provider in PROVIDER_IDS if costs[provider] is not None]
    assert order_for(RoutingStrategy(strategy), members, None, costs) == expected.split()


def test_custom_appends_new_members_by_cost_and_unknown_last() -> None:
    costs = {"a": Decimal("1"), "b": Decimal("0"), "c": None}
    assert order_for(RoutingStrategy.CUSTOM, costs, ["a", "hidden"], costs) == ["a", "b", "c"]


def test_merge_keeps_hidden_slots_and_drops_removed_catalog_ids() -> None:
    assert merge_order(
        ["a", "hidden", "b", "deleted"],
        ["b", "a", "new"],
        {"a", "b", "new"},
        {"a", "hidden", "b", "new"},
    ) == ["b", "hidden", "a", "new"]
