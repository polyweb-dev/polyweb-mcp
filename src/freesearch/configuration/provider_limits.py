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
PROVIDER_AUTH_KEYLESS: Final[tuple[str, ...]] = ("firecrawl", "keenable", "parallel", "tavily")

CATALOG_RECORD_COUNT: Final[int] = 25

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


def provider_limit_defaults() -> tuple[ProviderLimitRecord, ...]:
    """Return the documented catalog.

    C0 ships the shared core only. The provider builders and their tier
    declarations arrive with slices C1 to C8, so the catalog holds zero records
    and no provider is gated yet.
    """

    return ()


def documented_keyless_operations(provider: str) -> list[LimitOperation]:
    """Return the documented keyless operations of ``provider``, if any."""

    return [
        record.operation
        for record in provider_limit_defaults()
        if record.provider == provider and record.auth_mode is AuthMode.KEYLESS
    ]


def provider_tier_defaults() -> dict[str, list[TierBalance]]:
    """Return declared free and paid subpools keyed by ``provider:auth_mode``.

    C0 ships no tier declarations; the provider slices add them.
    """

    return {}
