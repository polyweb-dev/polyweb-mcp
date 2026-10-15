"""Documented provider limit catalog and approved CRD reference.

The catalog holds one record per provider, operation, and auth mode. Sixteen
keyed records cover the eight providers for search and fetch. Eight documented
keyless operation records cover Keenable, Firecrawl, Tavily, and Parallel
(search and fetch each). The catalog therefore holds 24 records: unsupported
combinations have no record at all, and Tinyfish, Brave, Exa, and You.com
keyless combinations are hidden.

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

CATALOG_RECORD_COUNT: Final[int] = 24

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


def _tinyfish_records() -> list[ProviderLimitRecord]:
    search_rate = _rate(
        _request_window(
            "tinyfish",
            AuthMode.KEYED,
            "search",
            "30",
            window=RateWindowName.MINUTE,
            scope=RateScope.KEY,
        ),
        _request_window(
            "tinyfish",
            AuthMode.KEYED,
            "search",
            "500",
            window=RateWindowName.HOUR,
            scope=RateScope.KEY,
        ),
    )
    fetch_rate = _rate(
        _request_window(
            "tinyfish",
            AuthMode.KEYED,
            "fetch",
            "150",
            window=RateWindowName.MINUTE,
            scope=RateScope.KEY,
            unit=RateUnit.URLS,
        ),
        _request_window(
            "tinyfish",
            AuthMode.KEYED,
            "fetch",
            "1000",
            window=RateWindowName.DAY,
            scope=RateScope.KEY,
            unit=RateUnit.URLS,
        ),
    )
    free_profile = _profile("0", source="unbilled_free")
    return [
        _record(
            "tinyfish",
            LimitOperation.SEARCH,
            AuthMode.KEYED,
            rate=search_rate,
            budget=None,
            profile=free_profile,
            plan_name="Free within rate limits",
        ),
        _record(
            "tinyfish",
            LimitOperation.FETCH,
            AuthMode.KEYED,
            rate=fetch_rate,
            budget=None,
            profile=free_profile,
            plan_name="Free within rate limits",
        ),
    ]


def _keenable_records() -> list[ProviderLimitRecord]:
    keyed_pool = UnitKind.REQUEST
    shared = "keenable:keyed:requests"
    keyed_rate = _rate(_request_window("keenable", AuthMode.KEYED, "search", "10", bucket=shared))
    keyed_budget = _budget(
        BudgetModel.REQUESTS,
        free_allowance="100000",
        allowance_unit="requests",
        allowance_period="month",
        cost_per_1k="4",
        native_cost="1",
        usd_per_call=str(KEENABLE_LIST_USD_PER_REQUEST),
        usage_api=None,
    )
    keyed_profile = _profile(
        str(KEENABLE_LIST_USD_PER_REQUEST), source="list_price_assumed", estimated=True
    )
    keyless_shared = "keenable:keyless:requests"
    keyless_rate = _rate(
        _request_window(
            "keenable",
            AuthMode.KEYLESS,
            "search",
            "10",
            scope=RateScope.IP,
            source="documented_keyless",
            bucket=keyless_shared,
        ),
        _request_window(
            "keenable",
            AuthMode.KEYLESS,
            "search",
            "1000",
            window=RateWindowName.HOUR,
            scope=RateScope.IP,
            source="documented_keyless",
            bucket=keyless_shared,
        ),
    )
    records: list[ProviderLimitRecord] = []
    for operation in (LimitOperation.SEARCH, LimitOperation.FETCH):
        records.append(
            _record(
                "keenable",
                operation,
                AuthMode.KEYED,
                rate=keyed_rate,
                budget=keyed_budget,
                pool_unit=keyed_pool,
                profile=keyed_profile,
                plan_name="Monthly free requests",
                usage_url="https://app.keenable.ai/console",
            )
        )
        records.append(
            _record(
                "keenable",
                operation,
                AuthMode.KEYLESS,
                rate=keyless_rate,
                budget=None,
                profile=_profile("0", source="unbilled_keyless"),
                plan_name="Keyless public pool",
            )
        )
    return records


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


def _parallel_records() -> list[ProviderLimitRecord]:
    """Build the four documented Parallel records.

    Keyed search and fetch share the documented USD-per-request model on one
    native USD pool with separate POST-only minute rate buckets (600 search +
    600 extract). Search prices the documented Basic/Advanced default
    (``$5/1k``; Turbo/Fast ``$1/1k`` in ``SEARCH_USD_BY_MODE``) and fetch
    prices one URL at ``PARALLEL_USD_PER_TURBO`` (``$1/1k``). Both keyed
    budgets carry the documented ``$5`` monthly free credit with card
    overage billing. Keyless search and fetch run with no published numeric
    limit and no budget.
    """

    search_rate = _rate(
        _request_window(
            "parallel",
            AuthMode.KEYED,
            "search",
            "600",
            window=RateWindowName.MINUTE,
            scope=RateScope.KEY,
        )
    )
    fetch_rate = _rate(
        _request_window(
            "parallel",
            AuthMode.KEYED,
            "fetch",
            "600",
            window=RateWindowName.MINUTE,
            scope=RateScope.KEY,
        )
    )
    search_price = "0.005"
    fetch_price = str(PARALLEL_USD_PER_TURBO)
    search_budget = _budget(
        BudgetModel.USD,
        free_allowance="5",
        allowance_unit="USD",
        allowance_period="month",
        cost_per_1k="5",
        native_cost=search_price,
        usd_per_call=search_price,
        on_exhausted=ExhaustAction.BILL,
    )
    fetch_budget = _budget(
        BudgetModel.USD,
        free_allowance="5",
        allowance_unit="USD",
        allowance_period="month",
        cost_per_1k="1",
        native_cost=fetch_price,
        usd_per_call=fetch_price,
        on_exhausted=ExhaustAction.BILL,
    )
    records = [
        _record(
            "parallel",
            LimitOperation.SEARCH,
            AuthMode.KEYED,
            rate=search_rate,
            budget=search_budget,
            pool_unit=UnitKind.USD,
            profile=_profile(search_price, source="usd_native"),
            plan_name="Pay-per-request USD pricing",
            usage_url="https://platform.parallel.ai",
        ),
        _record(
            "parallel",
            LimitOperation.FETCH,
            AuthMode.KEYED,
            rate=fetch_rate,
            budget=fetch_budget,
            pool_unit=UnitKind.USD,
            profile=_profile(fetch_price, source="usd_native"),
            plan_name="Pay-per-request USD pricing",
            usage_url="https://platform.parallel.ai",
        ),
    ]
    for operation in (LimitOperation.SEARCH, LimitOperation.FETCH):
        records.append(
            _record(
                "parallel",
                operation,
                AuthMode.KEYLESS,
                transport_available=False,
                rate=_unpublished_rate(),
                budget=None,
                profile=_profile(None, source="keyless_unpublished"),
                plan_name="Keyless access mode (rate limit not published)",
            )
        )
    return records


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


def _firecrawl_records() -> list[ProviderLimitRecord]:
    """Build the documented Firecrawl records.

    Keyed search bills 2 credits per 10 results rounded up and fetch bills 1
    base credit per page, backed by the shared 1,000 monthly free credits.
    The keyless rail has no transport available.
    """

    shared_rate = _rate(
        _request_window(
            "firecrawl",
            AuthMode.KEYED,
            "search",
            "10",
            window=RateWindowName.MINUTE,
            scope=RateScope.TEAM,
            bucket="firecrawl:keyed:requests",
            source="documented_plan",
        )
    )
    search_budget = _budget(
        BudgetModel.CREDITS,
        free_allowance="1000",
        allowance_unit="credits",
        allowance_period="month",
        cost_per_1k="3.8",
        native_cost="2",
        usd_per_call="0.0076",
        on_exhausted=ExhaustAction.STOP,
        usage_api="https://api.firecrawl.dev/v2/team/credit-usage",
    )
    fetch_budget = _budget(
        BudgetModel.CREDITS,
        free_allowance="1000",
        allowance_unit="credits",
        allowance_period="month",
        cost_per_1k="3.8",
        native_cost="1",
        usd_per_call="0.0038",
        on_exhausted=ExhaustAction.STOP,
        usage_api="https://api.firecrawl.dev/v2/team/credit-usage",
    )
    keyed_profile = _profile(
        str(FIRECRAWL_HOBBY_MONTHLY_USD_PER_CREDIT),
        source="hobby_monthly_reference",
        estimated=True,
    )
    records: list[ProviderLimitRecord] = [
        _record(
            "firecrawl",
            LimitOperation.SEARCH,
            AuthMode.KEYED,
            rate=shared_rate,
            budget=search_budget,
            pool_unit=UnitKind.CREDIT,
            profile=keyed_profile,
            plan_name="Free plan (1,000 monthly credits)",
            usage_url="https://firecrawl.dev/app/settings",
        ),
        _record(
            "firecrawl",
            LimitOperation.FETCH,
            AuthMode.KEYED,
            rate=shared_rate,
            budget=fetch_budget,
            pool_unit=UnitKind.CREDIT,
            profile=keyed_profile,
            plan_name="Free plan (1,000 monthly credits)",
            usage_url="https://firecrawl.dev/app/settings",
        ),
    ]
    for operation in (LimitOperation.SEARCH, LimitOperation.FETCH):
        records.append(
            _record(
                "firecrawl",
                operation,
                AuthMode.KEYLESS,
                transport_available=False,
                rate=_unpublished_rate(),
                budget=None,
                profile=_profile(None, source="keyless_unpublished"),
                plan_name="Keyless public pool (rate limit not published)",
            )
        )
    return records


def _exa_records() -> list[ProviderLimitRecord]:
    """Build the documented Exa records.

    Keyed search bills $0.007 for the first 10 results at 10 QPS (team scope),
    and fetch bills $0.001 per page at 100 QPS (team scope), both backed by
    the shared $10.00 monthly USD pool.
    """

    search_rate = _rate(
        _request_window(
            "exa",
            AuthMode.KEYED,
            "search",
            "10",
            window=RateWindowName.SECOND,
            scope=RateScope.TEAM,
            source="documented_team",
        )
    )
    fetch_rate = _rate(
        _request_window(
            "exa",
            AuthMode.KEYED,
            "fetch",
            "100",
            window=RateWindowName.SECOND,
            scope=RateScope.TEAM,
            source="documented_team",
        )
    )
    search_budget = _budget(
        BudgetModel.USD,
        free_allowance="10",
        allowance_unit="USD",
        allowance_period="month",
        cost_per_1k="7",
        native_cost=str(EXA_USD_PER_SEARCH),
        usd_per_call=str(EXA_USD_PER_SEARCH),
        on_exhausted=ExhaustAction.HTTP_402,
        usage_api="https://exa.ai/docs/reference/team-management/get-api-key-usage",
    )
    fetch_budget = _budget(
        BudgetModel.USD,
        free_allowance="10",
        allowance_unit="USD",
        allowance_period="month",
        cost_per_1k="1",
        native_cost=str(EXA_USD_PER_PAGE),
        usd_per_call=str(EXA_USD_PER_PAGE),
        on_exhausted=ExhaustAction.HTTP_402,
        usage_api="https://exa.ai/docs/reference/team-management/get-api-key-usage",
    )
    profile = _profile("1", source="usd_native")
    return [
        _record(
            "exa",
            LimitOperation.SEARCH,
            AuthMode.KEYED,
            rate=search_rate,
            budget=search_budget,
            pool_unit=UnitKind.USD,
            profile=profile,
            plan_name="Free $10 monthly grant + bonus",
            usage_url="https://dashboard.exa.ai/",
        ),
        _record(
            "exa",
            LimitOperation.FETCH,
            AuthMode.KEYED,
            rate=fetch_rate,
            budget=fetch_budget,
            pool_unit=UnitKind.USD,
            profile=profile,
            plan_name="Free $10 monthly grant + bonus",
            usage_url="https://dashboard.exa.ai/",
        ),
    ]


def _you_records() -> list[ProviderLimitRecord]:
    """Build the documented You.com records.

    Keyed search bills $0.005 per call and fetch (contents) bills $0.001 per
    live page, both backed by the shared one-time $100 signup USD pool (the
    budget claims no monthly period, and the renewing 100-calls/day free
    search allowance lives on the daily tier, not here). Each endpoint has
    its own 10 req/sec team rate bucket, which stays detail-only.
    """

    search_rate = _rate(
        _request_window(
            "you",
            AuthMode.KEYED,
            "search",
            "10",
            window=RateWindowName.SECOND,
            scope=RateScope.TEAM,
            source="documented_team",
        )
    )
    fetch_rate = _rate(
        _request_window(
            "you",
            AuthMode.KEYED,
            "fetch",
            "10",
            window=RateWindowName.SECOND,
            scope=RateScope.TEAM,
            source="documented_team",
        )
    )
    search_budget = _budget(
        BudgetModel.USD,
        free_allowance="100",
        allowance_unit="USD",
        cost_per_1k="5",
        native_cost=str(YOUCOM_USD_PER_SEARCH),
        usd_per_call=str(YOUCOM_USD_PER_SEARCH),
        on_exhausted=ExhaustAction.HTTP_402,
        usage_api="https://api.you.com/v1/billing/account_balance",
    )
    fetch_budget = _budget(
        BudgetModel.USD,
        free_allowance="100",
        allowance_unit="USD",
        cost_per_1k="1",
        native_cost=str(YOUCOM_USD_PER_PAGE),
        usd_per_call=str(YOUCOM_USD_PER_PAGE),
        on_exhausted=ExhaustAction.HTTP_402,
        usage_api="https://api.you.com/v1/billing/account_balance",
    )
    profile = _profile("1", source="usd_native")
    return [
        _record(
            "you",
            LimitOperation.SEARCH,
            AuthMode.KEYED,
            rate=search_rate,
            budget=search_budget,
            pool_unit=UnitKind.USD,
            profile=profile,
            plan_name="Signup $100 credit + 100 free searches/day",
            usage_url="https://you.com/platform/analytics",
        ),
        _record(
            "you",
            LimitOperation.FETCH,
            AuthMode.KEYED,
            rate=fetch_rate,
            budget=fetch_budget,
            pool_unit=UnitKind.USD,
            profile=profile,
            plan_name="Signup $100 credit + 100 free searches/day",
            usage_url="https://you.com/platform/analytics",
        ),
    ]


def provider_limit_defaults() -> tuple[ProviderLimitRecord, ...]:
    """Return the documented catalog in stable catalog order.

    Slice C1 holds the two keyed Brave records, slice P1 holds the four keyed
    and keyless Parallel records, and slice C6 adds the four keyed and keyless
    Tavily records. The other provider builders arrive with their own slices,
    including the two keyed You.com records.
    """

    records: list[ProviderLimitRecord] = []
    for builder in (
        _tinyfish_records,
        _keenable_records,
        _brave_records,
        _parallel_records,
        _tavily_records,
        _firecrawl_records,
        _exa_records,
        _you_records,
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

    Slice C1 holds the Brave keyed group, slice P1 holds the Parallel keyed
    and keyless groups, and slice C6 adds the Tavily keyed and keyless groups.
    The other provider groups arrive with their own slices, including the
    You.com keyed group with its one-time signup credit and daily search
    allowance. The
    declarations describe documented entitlement, reset rules, and funding
    mode. A vendor observation supplies the numbers; without one, a declared
    allowance still lets the UI show a denominator it can trust.
    """

    request = UnitKind.REQUEST
    credit = UnitKind.CREDIT
    request = UnitKind.REQUEST
    usd = UnitKind.USD
    return {
        "tinyfish:keyed": [
            _tier(
                "tinyfish:keyed:unmetered",
                "free",
                request,
                funding_mode=FundingMode.NO_BUDGET,
                confidence=Confidence.OBSERVED,
                label="Free - unmetered (search/fetch never draw the wallet)",
            ),
        ],
        "keenable:keyed": [
            _tier(
                "keenable:keyed:free",
                "free",
                request,
                allowance="100000",
                reset_rule=ResetRule.VENDOR_PERIOD,
                source="documented_plan",
                label="100000 monthly requests, shared search/fetch",
            ),
            _tier(
                "keenable:keyed:purchased",
                "paid",
                request,
                funding_mode=FundingMode.PREPAID,
                confidence=Confidence.UNKNOWN,
                label="Purchased credits (expiry unknown)",
            ),
        ],
        "keenable:keyless": [
            _tier(
                "keenable:keyless:unmetered",
                "free",
                request,
                funding_mode=FundingMode.NO_BUDGET,
                confidence=Confidence.OBSERVED,
                label="Free - unmetered (rate windows only)",
            ),
        ],
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
        "firecrawl:keyed": [
            _tier(
                "firecrawl:keyed:free",
                "free",
                credit,
                allowance="1000",
                reset_rule=ResetRule.VENDOR_PERIOD,
                source="documented_plan",
                label="Free plan (1,000 monthly credits)",
            ),
            _tier(
                "firecrawl:keyed:paid",
                "paid",
                credit,
                reset_rule=ResetRule.VENDOR_PERIOD,
                confidence=Confidence.UNKNOWN,
                label="Purchased credits",
            ),
        ],
        "firecrawl:keyless": _keyless_documented_tier(
            "firecrawl",
            native_unit=credit,
            transport_available=False,
            label="Documented keyless public pool (rate limit not published)",
        ),
        "parallel:keyed": [
            # No free allowance is claimed: the documented monthly credit
            # varies by eligibility (card on file, one per org), so the
            # tier keeps the USD unit with an unknown reset and no invented
            # denominator. The local seed ledger supplies the numbers.
            _tier(
                "parallel:keyed:free",
                "free",
                usd,
                reset_rule=ResetRule.UNKNOWN,
                source="documented_plan",
                confidence=Confidence.UNKNOWN,
                label="USD balance (pay-per-request, free credit varies)",
            ),
            _tier(
                "parallel:keyed:postpaid",
                "paid",
                usd,
                reset_rule=ResetRule.NEVER,
                funding_mode=FundingMode.POSTPAID,
                confidence=Confidence.UNKNOWN,
                label="PAYGO overage (card billed, no cap documented)",
            ),
        ],
        "parallel:keyless": _keyless_documented_tier(
            "parallel",
            native_unit=usd,
            transport_available=False,
            label="Documented keyless search and extract (rate limit not published)",
        ),
        "exa:keyed": [
            _tier(
                "exa:keyed:free",
                "free",
                usd,
                allowance="10",
                reset_rule=ResetRule.MONTHLY_FIRST,
                funding_mode=FundingMode.RECURRING,
                source="documented_plan",
                confidence=Confidence.ESTIMATED,
                label="USD 10 free monthly grant (resets on the 1st)",
            ),
            _tier(
                "exa:keyed:bonus",
                "free",
                usd,
                allowance="10",
                reset_rule=ResetRule.NEVER,
                funding_mode=FundingMode.PREPAID,
                source="documented_plan",
                confidence=Confidence.ESTIMATED,
                label="USD 10 onboarding bonus (one-time, no expiry)",
            ),
            _tier(
                "exa:keyed:paid",
                "paid",
                usd,
                reset_rule=ResetRule.NEVER,
                funding_mode=FundingMode.PREPAID,
                confidence=Confidence.UNKNOWN,
                label="Purchased prepaid dollar credits",
            ),
        ],
        "you:keyed": [
            # No monthly allowance is claimed: the documented $100 signup
            # credit is one-time, so the free tier keeps a never reset and no
            # period. The renewing 100-calls/day free search allowance is a
            # separate daily-estimate tier, never a second monthly grant.
            _tier(
                "you:keyed:free",
                "free",
                usd,
                allowance="100",
                reset_rule=ResetRule.NEVER,
                funding_mode=FundingMode.PREPAID,
                source="documented_plan",
                confidence=Confidence.ESTIMATED,
                label="USD 100 signup credit (one-time, shared across products)",
            ),
            _tier(
                "you:keyed:daily-search",
                "free",
                request,
                allowance="100",
                reset_rule=ResetRule.DAILY_ESTIMATE,
                funding_mode=FundingMode.RECURRING,
                source="documented_plan",
                confidence=Confidence.ESTIMATED,
                label="100 free search calls/day (renewing, search only)",
            ),
            _tier(
                "you:keyed:paid",
                "paid",
                usd,
                reset_rule=ResetRule.NEVER,
                funding_mode=FundingMode.PREPAID,
                confidence=Confidence.UNKNOWN,
                label="Purchased prepaid dollar credits",
            ),
        ],
    }
