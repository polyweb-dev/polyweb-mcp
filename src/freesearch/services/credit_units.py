"""Exact credit-unit (CRD) arithmetic, shared by the limit services.

One CRD is the approved ``CRDPriceProfile.reference_usd_per_crd`` amount of
priced native use. Every function here is pure: no persistence, no vendor I/O,
no routing input. Values stay exact ``Decimal`` values end to end, and an
unknown price stays unknown instead of becoming zero.

The conversion is uniform once the applicable USD price of one native unit is
known::

    price = 1 USD for a USD-denominated pool, else profile.native_usd_per_unit
    CRD   = native_units * price / reference_usd_per_crd
"""

from collections.abc import Sequence
from decimal import Decimal
from typing import Final

from freesearch.models.contracts import FetchRequest, SearchRequest, UnitKind
from freesearch.models.provider_limits import (
    CRDPriceProfile,
    CRDState,
    CRDView,
    NativeDebit,
    NativePool,
    ProviderLimitRecord,
)

ZERO: Final[Decimal] = Decimal("0")
_ONE: Final[Decimal] = Decimal("1")
# A Tavily advanced search bills twice the basic depth factor.
_ADVANCED_DEPTH_FACTOR: Final[Decimal] = Decimal("2")


def _unit_price(native_unit: UnitKind, profile: CRDPriceProfile) -> Decimal | None:
    """Return the USD price of one native unit, or ``None`` when unknown."""

    if native_unit is UnitKind.USD:
        return _ONE
    if native_unit is UnitKind.FREE:
        return ZERO
    return profile.native_usd_per_unit


def _to_crd(
    native: Decimal | None, native_unit: UnitKind, profile: CRDPriceProfile
) -> Decimal | None:
    """Convert an exact native amount to CRDs, preserving unknown prices."""

    price = _unit_price(native_unit, profile)
    if native is None or price is None:
        return None
    return native * price / profile.reference_usd_per_crd


def native_to_crd(pool: NativePool, profile: CRDPriceProfile) -> Decimal | None:
    """Return the exact CRD value of a native pool's remaining funds.

    ``None`` means the priced value is unknown: either the pool holds no known
    balance or the profile has no applicable source price. It never means zero.
    """

    return _to_crd(pool.remaining, pool.native_unit, profile)


def priced_crd_debit(debit: NativeDebit | NativePool, profile: CRDPriceProfile) -> Decimal | None:
    """Return the exact CRD debit of one finished operation.

    A definite failure with no charged native units records zero CRDs. A
    confirmed charge records its priced value even when the vendor returned an
    error, which keeps the Firecrawl returned-document exception exact.
    """

    if isinstance(debit, NativePool):
        return _to_crd(debit.remaining, debit.native_unit, profile)
    if debit.native_units == 0:
        return ZERO
    return _to_crd(debit.native_units, debit.native_unit, profile)


def request_native_cost(
    record: ProviderLimitRecord,
    request: SearchRequest | FetchRequest | None = None,
) -> Decimal | None:
    """Return the exact native cost one request is expected to consume.

    The standard cost comes from the record's budget block. A Tavily advanced
    search doubles that cost. The other provider add-ons arrive with their own
    slices.
    """

    if record.budget is None or record.native_unit is None:
        return None
    cost = record.budget.standard_native_cost
    if request is None:
        return cost
    if record.provider == "tavily" and _is_advanced_search(request):
        cost *= _ADVANCED_DEPTH_FACTOR
    return cost


def _is_advanced_search(request: SearchRequest | FetchRequest) -> bool:
    """Return whether a search request asks for the advanced depth."""

    return isinstance(request, SearchRequest) and request.mode == "advanced"


def request_cost_crd(
    record: ProviderLimitRecord,
    request: SearchRequest | FetchRequest | None = None,
) -> Decimal | None:
    """Return the exact CRD cost of one request under the record's profile."""

    native = request_native_cost(record, request)
    if native is None or record.native_unit is None:
        return None
    return _to_crd(native, record.native_unit, record.conversion_profile)


def possible_standard_calls(record: ProviderLimitRecord, pool: NativePool | None) -> Decimal | None:
    """Return whole standard calls the pool can cover, or ``None`` when unknown."""

    if pool is None or pool.remaining is None or record.budget is None:
        return None
    standard = record.budget.standard_native_cost
    if standard <= 0:
        return None
    return (pool.remaining / standard).to_integral_value(rounding="ROUND_FLOOR")


def crd_state(record: ProviderLimitRecord, pool: NativePool | None) -> CRDState:
    """Return the availability state of one record under the plan's order.

    ``unavailable`` takes precedence over the null-budget rule, an eligible null
    budget is ``unmetered``, and an absent or unpriced balance is ``unknown``.
    """

    if not record.supported or not record.transport_available:
        return CRDState.UNAVAILABLE
    if record.budget is None:
        return CRDState.UNMETERED
    if not record.budget.priced:
        return CRDState.UNKNOWN
    if pool is None or pool.remaining is None:
        return CRDState.UNKNOWN
    return CRDState.FINITE


def crd_view(
    record: ProviderLimitRecord,
    pool: NativePool | None = None,
    *,
    grant_remaining: Decimal | None = None,
    request: SearchRequest | FetchRequest | None = None,
) -> CRDView:
    """Build the exact credit-unit view of one catalog record.

    The view reports the projectable remaining funds, the request cost, the
    shared pool identity, and the whole-call volume detail. A local grant
    ceiling stays separate in ``local_remaining_crd``.
    """

    state = crd_state(record, pool)
    remaining = native_to_crd(pool, record.conversion_profile) if pool is not None else None
    if remaining is not None and remaining < 0:
        remaining = ZERO
    view = CRDView(
        state=state,
        operation=record.operation,
        remaining_crd=remaining if state is CRDState.FINITE else None,
        local_remaining_crd=grant_remaining,
        request_cost_crd=request_cost_crd(record, request) if record.supported else None,
        shared_pool_id=pool.pool_id if pool is not None else None,
        possible_standard_calls=possible_standard_calls(record, pool),
        price_version=record.conversion_profile.price_version,
        priced=record.budget.priced if record.budget is not None else False,
    )
    return effective_crd(view, grant_remaining)


def project_shared_crd_views(
    pool: NativePool, records: Sequence[ProviderLimitRecord]
) -> list[CRDView]:
    """Project one native pool into the CRD views of its operation records.

    Both shared operation views come from the same native balance, so they
    deplete together and contribute their funds once. Records that do not
    reference ``pool`` are ignored.
    """

    return [
        crd_view(record, pool)
        for record in records
        if record.native_pool_id is not None and record.native_pool_id == pool.pool_id
    ]


def effective_crd(view: CRDView, grant_remaining: Decimal | None) -> CRDView:
    """Combine a CRD view with an optional local grant ceiling.

    The result keeps the exact projectable funds and the separate local
    ceiling. Neither value is rounded, and a zero local grant never rewrites
    known native funds.
    """

    if grant_remaining is None:
        return view
    ceiling = grant_remaining if grant_remaining > 0 else ZERO
    return view.model_copy(update={"local_remaining_crd": ceiling})


def spendable_crd(view: CRDView) -> Decimal | None:
    """Return the exact spendable CRD capacity, or ``None`` when unmetered.

    ``None`` means an unmetered rail has no finite funds gate. A finite rail
    with no known balance is not spendable and yields ``None`` as well, so the
    caller must consult :attr:`CRDView.state` before allowing unpriced use.
    """

    if view.state is CRDState.UNMETERED:
        return None
    return view.spendable_crd


def shared_pool_funds(pool: NativePool, records: Sequence[ProviderLimitRecord]) -> Decimal | None:
    """Return a shared pool's CRD funds exactly once.

    Operation views that project the same pool never add together, so a total
    sums this value once per pool ID instead of summing each view.
    """

    profile = next(
        (record.conversion_profile for record in records if record.native_pool_id == pool.pool_id),
        None,
    )
    if profile is None:
        return None
    return native_to_crd(pool, profile)
