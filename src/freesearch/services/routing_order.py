"""Pure cost and ordering rules for project provider routing."""

from collections.abc import Collection, Mapping, Sequence
from decimal import Decimal
from functools import lru_cache

from freesearch.configuration.provider_limits import provider_limit_defaults
from freesearch.models.contracts import UsageOperation
from freesearch.models.project_routing import RoutingOperation, RoutingStrategy
from freesearch.services.credit_units import request_cost_crd
from freesearch.services.pool_materializer import KEYLESS_PROVIDERS


@lru_cache(maxsize=1)
def _catalog_prices() -> dict[tuple[str, str], Decimal]:
    prices: dict[tuple[str, str], Decimal] = {}
    for record in provider_limit_defaults():
        if not record.supported or not record.transport_available:
            continue
        if record.conversion_profile.native_usd_per_unit == 0:
            price = Decimal(0)
        else:
            cost = request_cost_crd(record)
            if cost is None:
                continue
            price = cost * record.conversion_profile.reference_usd_per_crd
        key = (record.provider, record.operation.value)
        prices[key] = min(prices.get(key, price), price)
    return prices


def call_cost_usd(
    provider: str, operation: RoutingOperation, *, keyless: bool = False
) -> Decimal | None:
    """Return the cheapest documented standard call, ignoring unpriced modes."""

    if keyless:
        return Decimal(0) if provider in KEYLESS_PROVIDERS else None
    return _catalog_prices().get((provider, operation.value))


def catalog_call_costs(provider: str, *, keyless: bool = False) -> dict[UsageOperation, Decimal]:
    """Catalog prices by access mode, shared by project and system reads."""

    return {
        UsageOperation(operation.value): cost
        for operation in RoutingOperation
        if (cost := call_cost_usd(provider, operation, keyless=keyless)) is not None
    }


def order_for(
    strategy: RoutingStrategy,
    members: Collection[str],
    custom_order: Sequence[str] | None,
    costs: Mapping[str, Decimal | None],
) -> list[str]:
    """Calculate the visible order from current members and current prices."""

    def lowest_key(provider: str) -> tuple[bool, Decimal, str]:
        cost = costs.get(provider)
        return (cost is None, cost if cost is not None else Decimal(0), provider)

    if strategy == RoutingStrategy.FREE_FIRST:
        return sorted(members, key=lambda provider: (costs.get(provider) != 0, provider))
    if strategy == RoutingStrategy.LOWEST_COST or custom_order is None:
        return sorted(members, key=lowest_key)
    member_set = set(members)
    listed = list(dict.fromkeys(provider for provider in custom_order if provider in member_set))
    listed_set = set(listed)
    remaining = (provider for provider in members if provider not in listed_set)
    return listed + sorted(remaining, key=lowest_key)


def merge_order(
    stored: Sequence[str],
    visible_new: Sequence[str],
    members: Collection[str],
    catalog: Collection[str] | None = None,
) -> list[str]:
    """Replace visible slots without moving retained, temporarily hidden slots."""

    members_set = set(members)
    valid = None if catalog is None else set(catalog)
    replacements = iter(visible_new)
    result: list[str] = []
    for provider in dict.fromkeys(stored):
        if valid is not None and provider not in valid:
            continue
        if provider in members_set:
            replacement = next(replacements, None)
            if replacement is not None:
                result.append(replacement)
        else:
            result.append(provider)
    result.extend(replacements)
    return result
