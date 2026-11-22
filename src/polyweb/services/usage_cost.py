"""Price recorded usage events in USD from vendor reports or the provider catalog.

The pricing is pure: it reads one usage event and the static provider limit
catalog and never touches storage or the network. A vendor-reported USD charge
is kept as reported; every other price is an estimate. An event whose price is
unknown returns ``None`` so unknown cost never becomes zero.
"""

from datetime import datetime
from decimal import Decimal
from functools import lru_cache

from polyweb.adapters.parallel import request_cost_usd as parallel_request_cost_usd
from polyweb.adapters.parallel import usage_event_cost_usd as parallel_usage_cost_usd
from polyweb.configuration.provider_limits import provider_limit_defaults
from polyweb.models.contracts import (
    CostSource,
    FetchRequest,
    QuotaSource,
    SearchRequest,
    UnitKind,
    UsageCost,
    UsageEvent,
    UsageOperation,
    UsageStatus,
)
from polyweb.models.provider_limits import AuthMode, LimitOperation, ProviderLimitRecord
from polyweb.services.credit_units import request_native_cost

__all__ = ["catalog_usage_event", "usage_cost"]

_DISPLAY_UNITS = {
    UnitKind.REQUEST: "requests",
    UnitKind.CREDIT: "credits",
    UnitKind.USD: "USD",
    UnitKind.FREE: "free",
}


def usage_cost(event: UsageEvent, *, auth_mode: AuthMode = AuthMode.KEYED) -> UsageCost | None:
    """Return the USD cost of ``event`` on the ``auth_mode`` rail, or ``None`` when unknown."""

    if event.status is UsageStatus.FAILURE and event.units == 0:
        return None
    if event.unit_kind is UnitKind.USD:
        return UsageCost(
            usd=event.units,
            source=CostSource.ESTIMATED if _is_estimated(event.metadata) else CostSource.REPORTED,
        )
    if event.unit_kind is UnitKind.FREE:
        return UsageCost(usd=Decimal("0"), source=CostSource.ESTIMATED)
    explicit = _metadata_cost(event.metadata.get("cost_usd"))
    if explicit is not None:
        return UsageCost(usd=explicit, source=CostSource.ESTIMATED)
    if _is_parallel_sku_event(event):
        parallel = parallel_usage_cost_usd(event)
        if parallel is None:
            return None
        return UsageCost(usd=parallel, source=CostSource.ESTIMATED)
    price = _catalog_unit_price(event, auth_mode)
    if price is None:
        return None
    return UsageCost(usd=event.units * price, source=CostSource.ESTIMATED)


def catalog_usage_event(
    provider: str,
    operation: UsageOperation,
    auth_mode: AuthMode,
    request: SearchRequest | FetchRequest | None,
    observed_at: datetime,
) -> UsageEvent | None:
    """Estimate one unmetered call's usage from the catalog, or ``None`` when unknown.

    The event carries the native cost the catalog expects ``request`` to
    consume on the ``auth_mode`` rail. Parallel prices ``request`` by its search
    mode, extra bundles and URL count, in dollars like its catalog record. A
    provider without a supported record, a record without a native unit, or an
    unknown native cost yields ``None``.
    """

    try:
        limit_operation = LimitOperation(operation.value)
    except ValueError:
        return None
    record = _catalog_record(provider, limit_operation, auth_mode)
    if record is None or record.native_unit is None:
        return None
    if provider == "parallel" and record.native_unit is UnitKind.USD and request is not None:
        units: Decimal | None = parallel_request_cost_usd(request)
    else:
        units = request_native_cost(record, request)
    if units is None:
        return None
    return UsageEvent(
        provider=provider,
        operation=operation,
        units=units,
        unit_kind=record.native_unit,
        display_unit=_DISPLAY_UNITS[record.native_unit],
        observed_at=observed_at,
        metadata={"estimated": True, "metering_gap": True, "catalog_fallback": True},
    )


def _is_estimated(metadata: dict[str, object]) -> bool:
    """Return whether a USD event's metadata marks its dollar amount as a local estimate.

    Gap and catalog events set ``estimated``; the Exa pricing fallback sets
    ``source`` to ``QuotaSource.ESTIMATED``. Migration ``0009_usage_event_cost``
    mirrors this rule when it backfills stored rows.
    """

    return (
        metadata.get("estimated") is True or metadata.get("source") == QuotaSource.ESTIMATED.value
    )


def _is_parallel_sku_event(event: UsageEvent) -> bool:
    """Return whether ``event`` is a Parallel SKU request event priced by its own table."""

    return (
        event.provider == "parallel"
        and event.unit_kind is UnitKind.REQUEST
        and isinstance(event.metadata.get("skus"), list)
    )


def _metadata_cost(value: object) -> Decimal | None:
    """Parse an adapter-supplied ``cost_usd`` metadata value when it is a valid amount."""

    if value is None or isinstance(value, bool):
        return None
    if not isinstance(value, (Decimal, int, float, str)):
        return None
    try:
        parsed = value if isinstance(value, Decimal) else Decimal(str(value))
    except ArithmeticError:
        return None
    if not parsed.is_finite() or parsed < 0:
        return None
    return parsed


def _catalog_unit_price(event: UsageEvent, auth_mode: AuthMode) -> Decimal | None:
    """Return the catalog USD price of one unit of ``event``, or ``None`` when unknown."""

    try:
        operation = LimitOperation(event.operation.value)
    except ValueError:
        return None
    record = _catalog_record(event.provider, operation, auth_mode)
    if record is None:
        return None
    price = record.conversion_profile.native_usd_per_unit
    if price is None:
        return None
    if price == 0:
        return Decimal("0")
    kind = event.unit_kind
    if kind is None:
        return None
    if kind is record.native_unit and kind in (UnitKind.REQUEST, UnitKind.CREDIT):
        return price
    if kind is UnitKind.REQUEST and record.native_unit is UnitKind.USD:
        return record.budget.standard_native_cost if record.budget is not None else None
    if (
        record.provider == "keenable"
        and record.auth_mode is AuthMode.KEYED
        and record.native_unit is UnitKind.REQUEST
        and kind is UnitKind.CREDIT
    ):
        return price
    return None


@lru_cache(maxsize=64)
def _catalog_record(
    provider: str, operation: LimitOperation, auth_mode: AuthMode
) -> ProviderLimitRecord | None:
    """Return the supported catalog record for one provider rail, if any."""

    for record in provider_limit_defaults():
        if record.key == (provider, operation, auth_mode) and record.supported:
            return record
    return None
