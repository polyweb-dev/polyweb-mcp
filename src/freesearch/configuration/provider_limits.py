"""Documented provider limit catalog and approved CRD reference.

The catalog holds one record per provider, operation, and auth mode. Sixteen
keyed records cover the eight providers for search and fetch. Nine documented
keyless operation records cover Keenable (search and fetch), Firecrawl, Tavily,
and Parallel (search and fetch each) and You.com (search only). The catalog
therefore holds 25 records: unsupported combinations have no record at all, and
Tinyfish, Brave, and Exa keyless combinations are hidden.

The catalog also declares each provider's documented free and paid subpools.
Those declarations are entitlement and reset documentation, not vendor
balances: a vendor observation supplies the numbers and the catalog supplies
the tier structure, source, and reset rule.

One CRD is ``CRD_USD_REFERENCE`` of priced native use. The catalog keeps exact
``Decimal`` prices and labels assumed list prices as estimated.
"""

from decimal import Decimal
from typing import Final, Literal

from freesearch.models.contracts import UnitKind
from freesearch.models.provider_limits import (
    CRD_USD_REFERENCE,
    AuthMode,
    BudgetBlock,
    BudgetModel,
    Confidence,
    CRDPriceProfile,
    ExhaustAction,
    FundingMode,
    LimitOperation,
    ProviderLimitRecord,
    RateBlock,
    RateScope,
    RateUnit,
    RateWindow,
    RateWindowName,
    ResetRule,
    TierBalance,
    native_pool_id,
)

__all__ = [
    "CATALOG_RECORD_COUNT",
    "CRD_USD_REFERENCE",
    "PROVIDER_AUTH_KEYLESS",
    "PROVIDER_IDS",
    "documented_keyless_operations",
    "provider_limit_defaults",
    "provider_tier_defaults",
]

PROVIDER_IDS: Final[tuple[str, ...]] = (
    "brave",
    "exa",
    "firecrawl",
    "keenable",
    "parallel",
    "tavily",
    "tinyfish",
    "you",
)

# Keyless rails with no adapter transport in this phase.
PROVIDER_AUTH_KEYLESS: Final[tuple[str, ...]] = ("firecrawl", "keenable", "parallel")

CATALOG_RECORD_COUNT: Final[int] = 25

# Tavily search and extract draw on one documented default bucket. The search
# bucket ID stays the ID stored attempts already use, so prior minute counts
# keep applying to the shared window.
TAVILY_DEFAULT_BUCKET_ID: Final[str] = "tavily:keyed:search:requests"
TAVILY_RPM_DEV: Final[Decimal] = Decimal("100")
TAVILY_RPM_PROD: Final[Decimal] = Decimal("1000")

# Example-only reference prices. They are documented vendor prices, not account
# confirmations, so the conversion profiles that use them stay estimated.
KEENABLE_LIST_USD_PER_REQUEST: Final[Decimal] = Decimal("0.004")
FIRECRAWL_HOBBY_MONTHLY_USD_PER_CREDIT: Final[Decimal] = Decimal("0.0038")
TAVILY_PAYGO_USD_PER_CREDIT: Final[Decimal] = Decimal("0.008")
BRAVE_USD_PER_REQUEST: Final[Decimal] = Decimal("0.005")
EXA_USD_PER_SEARCH: Final[Decimal] = Decimal("0.007")
EXA_USD_PER_PAGE: Final[Decimal] = Decimal("0.001")
PARALLEL_USD_PER_TURBO: Final[Decimal] = Decimal("0.001")
YOUCOM_USD_PER_SEARCH: Final[Decimal] = Decimal("0.005")
YOUCOM_USD_PER_PAGE: Final[Decimal] = Decimal("0.001")


def _request_window(
    provider: str,
    auth_mode: AuthMode,
    operation: str,
    limit: str,
    *,
    window: RateWindowName = RateWindowName.SECOND,
    scope: RateScope = RateScope.ORG,
    unit: RateUnit = RateUnit.REQUESTS,
    source: str = "documented",
    bucket: str | None = None,
) -> RateWindow:
    """Build one documented rate window with a stable shared bucket ID."""

    return RateWindow(
        bucket_id=bucket or f"{provider}:{auth_mode.value}:{operation}:{unit.value}",
        limit=Decimal(limit),
        window=window,
        scope=scope,
        unit=unit,
        source=source,
    )


def _rate(*windows: RateWindow, published: bool = True) -> RateBlock:
    """Build a published rate block from documented windows."""

    return RateBlock(windows=list(windows), published=published)


def _unpublished_rate() -> RateBlock:
    """Return a rate block for a rail with no published numeric limit."""

    return RateBlock(windows=[], published=False)


def _budget(
    model: BudgetModel,
    *,
    free_allowance: str | None = None,
    allowance_unit: str = "",
    allowance_period: str | None = None,
    cost_per_1k: str | None = None,
    native_cost: str = "1",
    usd_per_call: str | None = None,
    on_exhausted: ExhaustAction = ExhaustAction.HTTP_402,
    usage_api: str | None = None,
    priced: bool = True,
) -> BudgetBlock:
    """Build a native budget block from documented vendor values."""

    return BudgetBlock(
        model=model,
        free_allowance=Decimal(free_allowance) if free_allowance is not None else None,
        allowance_unit=allowance_unit,
        allowance_period=allowance_period,
        cost_per_1k=Decimal(cost_per_1k) if cost_per_1k is not None else None,
        standard_native_cost=Decimal(native_cost),
        usd_per_call=Decimal(usd_per_call) if usd_per_call is not None else None,
        on_exhausted=on_exhausted,
        usage_api=usage_api,
        priced=priced,
    )


def _profile(
    usd_per_unit: str | None,
    *,
    source: str = "documented",
    estimated: bool = False,
) -> CRDPriceProfile:
    """Build a conversion profile at the approved CRD reference."""

    return CRDPriceProfile(
        reference_usd_per_crd=CRD_USD_REFERENCE,
        native_usd_per_unit=Decimal(usd_per_unit) if usd_per_unit is not None else None,
        source=source,
        estimated=estimated,
    )


def _record(
    provider: str,
    operation: LimitOperation,
    auth_mode: AuthMode,
    *,
    supported: bool = True,
    transport_available: bool = True,
    rate: RateBlock | None = None,
    budget: BudgetBlock | None = None,
    pool_unit: UnitKind | None = None,
    profile: CRDPriceProfile | None = None,
    plan_name: str | None = None,
    usage_url: str | None = None,
    version: int = 1,
) -> ProviderLimitRecord:
    """Build one catalog record, defaulting the shared pool ID from its unit."""

    return ProviderLimitRecord(
        provider=provider,
        operation=operation,
        auth_mode=auth_mode,
        supported=supported,
        transport_available=transport_available,
        rate=rate,
        budget=budget,
        native_unit=pool_unit,
        native_pool_id=(
            native_pool_id(provider, auth_mode, pool_unit) if pool_unit is not None else None
        ),
        conversion_profile=profile or _profile(None),
        plan_name=plan_name,
        usage_url=usage_url,
        version=version,
    )


def _tier(
    pool_id: str,
    tier: Literal["free", "paid", "unknown"],
    native_unit: UnitKind,
    *,
    allowance: str | None = None,
    remaining: str | None = None,
    reset_rule: ResetRule = ResetRule.UNKNOWN,
    funding_mode: FundingMode = FundingMode.RECURRING,
    source: str = "documented_plan",
    confidence: Confidence = Confidence.ESTIMATED,
    transport_available: bool = True,
    label: str | None = None,
) -> TierBalance:
    """Build one declared free or paid subpool."""

    return TierBalance(
        pool_id=pool_id,
        tier=tier,
        native_unit=native_unit,
        native_remaining=Decimal(remaining) if remaining is not None else None,
        native_allowance=Decimal(allowance) if allowance is not None else None,
        reset_rule=reset_rule,
        funding_mode=funding_mode,
        source=source,
        confidence=confidence,
        transport_available=transport_available,
        label=label,
    )


def _keyless_documented_tier(
    provider: str,
    *,
    native_unit: UnitKind,
    label: str,
    allowance: str | None = None,
    reset_rule: ResetRule = ResetRule.UNKNOWN,
    transport_available: bool = False,
) -> list[TierBalance]:
    """Build the free subpool of one documented keyless rail."""

    return [
        _tier(
            f"{provider}:keyless:documented",
            "free",
            native_unit,
            allowance=allowance,
            reset_rule=reset_rule,
            funding_mode=FundingMode.NO_BUDGET,
            source="documented_keyless",
            confidence=Confidence.UNKNOWN,
            transport_available=transport_available,
            label=label,
        )
    ]


def _brave_records() -> list[ProviderLimitRecord]:
    search_rate = _rate(
        _request_window("brave", AuthMode.KEYED, "search", "50", scope=RateScope.ORG)
    )
    budget = _budget(
        BudgetModel.USD,
        free_allowance="5",
        allowance_unit="USD",
        allowance_period="month",
        cost_per_1k="5",
        native_cost=str(BRAVE_USD_PER_REQUEST),
        usd_per_call=str(BRAVE_USD_PER_REQUEST),
        on_exhausted=ExhaustAction.BILL,
    )
    return [
        _record(
            "brave",
            LimitOperation.SEARCH,
            AuthMode.KEYED,
            rate=search_rate,
            budget=budget,
            pool_unit=UnitKind.USD,
            profile=_profile(str(BRAVE_USD_PER_REQUEST), source="usd_native"),
            plan_name="Monthly search credit",
            usage_url="https://api-dashboard.search.brave.com/",
        ),
        # Brave has no generic fetch; the placeholder record keeps the card's
        # required "n/a" main-number state.
        _record(
            "brave",
            LimitOperation.FETCH,
            AuthMode.KEYED,
            supported=False,
            transport_available=False,
            rate=None,
            budget=None,
        ),
    ]


def _tavily_records() -> list[ProviderLimitRecord]:
    """Build the four Tavily catalog records (catalog version 2 contract).

    Search and extract share one documented default minute bucket whose limit
    the explicit key-environment configuration selects (development 100,
    production 1000). Both keyed operations draw on one native Credits pool.
    Keyless search and extract run on the active transport without a numeric
    rate window or a budget record.
    """

    keyed_rate = _rate(
        _request_window(
            "tavily",
            AuthMode.KEYED,
            "search",
            str(TAVILY_RPM_DEV),
            window=RateWindowName.MINUTE,
            scope=RateScope.KEY,
            source="documented_development_key",
            bucket=TAVILY_DEFAULT_BUCKET_ID,
        )
    )
    credit_price = str(TAVILY_PAYGO_USD_PER_CREDIT)
    search_budget = _budget(
        BudgetModel.CREDITS,
        free_allowance="1000",
        allowance_unit="Credits",
        allowance_period="month",
        cost_per_1k="8",
        native_cost="1",
        usd_per_call=credit_price,
        on_exhausted=ExhaustAction.STOP,
        usage_api="https://api.tavily.com/usage",
    )
    fetch_budget = _budget(
        BudgetModel.CREDITS,
        free_allowance="1000",
        allowance_unit="Credits",
        allowance_period="month",
        cost_per_1k="8",
        native_cost="0.2",
        usd_per_call="0.0016",
        on_exhausted=ExhaustAction.STOP,
        usage_api="https://api.tavily.com/usage",
    )
    keyed_profile = _profile(credit_price, source="paygo_reference", estimated=True)
    records = [
        _record(
            "tavily",
            LimitOperation.SEARCH,
            AuthMode.KEYED,
            rate=keyed_rate,
            budget=search_budget,
            pool_unit=UnitKind.CREDIT,
            profile=keyed_profile,
            plan_name="Free plan",
            usage_url="https://app.tavily.com/home",
            version=2,
        ),
        _record(
            "tavily",
            LimitOperation.FETCH,
            AuthMode.KEYED,
            rate=keyed_rate,
            budget=fetch_budget,
            pool_unit=UnitKind.CREDIT,
            profile=keyed_profile,
            plan_name="Free plan",
            usage_url="https://app.tavily.com/home",
            version=2,
        ),
    ]
    for operation in (LimitOperation.SEARCH, LimitOperation.FETCH):
        records.append(
            _record(
                "tavily",
                operation,
                AuthMode.KEYLESS,
                transport_available=True,
                rate=_unpublished_rate(),
                budget=None,
                profile=_profile(None, source="keyless_unpublished"),
                plan_name="Keyless access mode (rate limit not published)",
                version=2,
            )
        )
    return records


def provider_limit_defaults() -> tuple[ProviderLimitRecord, ...]:
    """Return the documented catalog in stable catalog order.

    Slice C1 holds the two keyed Brave records, and slice C6 adds the four keyed
    and keyless Tavily records. The other provider builders arrive with their
    own slices.
    """

    records: list[ProviderLimitRecord] = []
    for builder in (
        _brave_records,
        _tavily_records,
    ):
        records.extend(builder())
    return tuple(records)


def documented_keyless_operations(provider: str) -> list[LimitOperation]:
    """Return the documented keyless operations of ``provider``, if any."""

    return [
        record.operation
        for record in provider_limit_defaults()
        if record.provider == provider and record.auth_mode is AuthMode.KEYLESS
    ]


def provider_tier_defaults() -> dict[str, list[TierBalance]]:
    """Return declared free and paid subpools keyed by ``provider:auth_mode``.

    Slice C1 holds the Brave keyed group and slice C6 adds the Tavily keyed and
    keyless groups. The other provider groups arrive with their own slices. The
    declarations describe documented entitlement, reset rules, and funding
    mode. A vendor observation supplies the numbers; without one, a declared
    allowance still lets the UI show a denominator it can trust.
    """

    request = UnitKind.REQUEST
    credit = UnitKind.CREDIT
    usd = UnitKind.USD
    return {
        "brave:keyed": [
            _tier(
                "brave:keyed:free",
                "free",
                usd,
                allowance="5",
                # Brave reports its own reset instant in the monthly pair
                # element, and its free credit window is a rolling 30-day
                # period, so the header drives the reset and no calendar day
                # is claimed.
                reset_rule=ResetRule.VENDOR_PERIOD,
                source="vendor_headers",
                confidence=Confidence.OBSERVED,
                label="USD 5 monthly search credit (no rollover)",
            ),
            _tier(
                "brave:keyed:postpaid",
                "paid",
                usd,
                reset_rule=ResetRule.NEVER,
                funding_mode=FundingMode.POSTPAID,
                confidence=Confidence.UNKNOWN,
                label="Prepaid funds or confirmed metered card",
            ),
        ],
        "tavily:keyed": [
            _tier(
                "tavily:keyed:free",
                "free",
                credit,
                allowance="1000",
                reset_rule=ResetRule.MONTHLY_FIRST,
                source="documented_plan",
                label="Free plan credits (resets on the first)",
            ),
            _tier(
                "tavily:keyed:plan",
                "paid",
                credit,
                reset_rule=ResetRule.MONTHLY_FIRST,
                confidence=Confidence.UNKNOWN,
                label="Paid plan allowance (plan dependent)",
            ),
            _tier(
                "tavily:keyed:paygo",
                "paid",
                credit,
                reset_rule=ResetRule.NEVER,
                funding_mode=FundingMode.POSTPAID,
                confidence=Confidence.UNKNOWN,
                label="PAYGO access or an explicit spend cap (not stored credits)",
            ),
        ],
        "tavily:keyless": _keyless_documented_tier(
            "tavily",
            native_unit=request,
            transport_available=True,
            label="Documented keyless search and extract (rate limit not published)",
        ),
    }
