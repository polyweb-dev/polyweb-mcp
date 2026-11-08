"""Provider limit, credit-unit, tier, and rate-window contracts.

This module owns the provider-neutral limit domain: the native rate and budget
description of one provider/operation/auth rail, the durable native pools that
hold vendor funds, the exact credit-unit (CRD) projections derived from those
pools, and the free/paid tier and hour/day rate progress views the dashboard
consumes.

One CRD is ``CRD_USD_REFERENCE`` of priced native use. Exact ``Decimal``
arithmetic governs admission, debit, audit, and totals; rounding happens only in
presentation helpers downstream. Amount fields use :data:`ExactDecimal`, so a
JSON payload carries the exact value as a string.
"""

from datetime import date, datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Any, Final, Literal
from uuid import UUID

from pydantic import BeforeValidator, ConfigDict, Field, PlainSerializer

from freesearch.models.contracts import (
    ContractModel,
    FetchRequest,
    ProviderError,
    SearchRequest,
    UnitKind,
)
from freesearch.models.credentials import CredentialAuthMode
from freesearch.models.observability import ActorType

# Approved common reference: one CRD is USD 0.001 of priced native use.
CRD_USD_REFERENCE: Final[Decimal] = Decimal("0.001")
CRD_UNIT_NAME: Final[str] = "CRD"
CRD_PRICE_VERSION: Final[str] = "crd-usd-0.001"
LOCAL_FUNDS_DENIAL_CODE: Final[str] = "budget_exhausted"
LOCAL_RATE_DENIAL_CODE: Final[str] = "rate_limited"
UNPRICED_CEILING_CODE: Final[str] = "budget_price_unknown"
MAX_HISTORY_PAGE_SIZE: Final[int] = 100
DEFAULT_HISTORY_PAGE_SIZE: Final[int] = 50
DEFAULT_ATTEMPT_LEASE_SECONDS: Final[int] = 300


def parse_exact_decimal(value: object, *, allow_negative: bool = False) -> Decimal:
    """Parse a finite Decimal without binary-float arithmetic.

    Integers, exact strings, and Decimals pass through unchanged. A JSON float
    is converted through its shortest decimal text, so a caller-supplied ``0.5``
    stays exactly ``0.5``. Booleans and non-finite values are rejected.
    """

    if value is None or isinstance(value, bool):
        raise ValueError("decimal inputs must be exact numbers, not booleans")
    if isinstance(value, float):
        value = repr(value)
    try:
        parsed = value if isinstance(value, Decimal) else Decimal(value)  # type: ignore[arg-type]
    except (ArithmeticError, TypeError, ValueError) as exc:
        raise ValueError("value is not a valid Decimal") from exc
    if not parsed.is_finite():
        raise ValueError("Decimal must be finite")
    if not allow_negative and parsed < 0:
        raise ValueError("Decimal must be non-negative")
    return parsed


def parse_optional_exact_decimal(value: object) -> Decimal | None:
    """Parse an optional exact Decimal, preserving an explicit null."""

    if value is None:
        return None
    return parse_exact_decimal(value)


def _decimal_text(value: Decimal | None) -> str | None:
    """Serialize an optional Decimal as its exact decimal string."""

    if value is None:
        return None
    return format(value, "f")


# Exact amounts stay Decimal in Python and cross the wire as exact strings.
ExactDecimal = Annotated[
    Decimal,
    BeforeValidator(parse_exact_decimal),
    PlainSerializer(_decimal_text, return_type=str, when_used="json"),
]
OptionalExactDecimal = Annotated[
    Decimal | None,
    BeforeValidator(parse_optional_exact_decimal),
    PlainSerializer(_decimal_text, return_type=str | None, when_used="json"),
]


class LimitOperation(StrEnum):
    """The two limit dimensions: search and fetch."""

    SEARCH = "search"
    FETCH = "fetch"

    @property
    def usage_operation(self) -> str:
        """Return the matching :class:`UsageOperation` value."""

        return self.value


class AuthMode(StrEnum):
    """Credential rail a record describes."""

    KEYLESS = "keyless"
    KEYED = "keyed"


class CRDState(StrEnum):
    """Availability state of one credit-unit view."""

    FINITE = "finite"
    UNMETERED = "unmetered"
    UNAVAILABLE = "unavailable"
    UNKNOWN = "unknown"


class Confidence(StrEnum):
    """How a value was obtained."""

    AUTHORITATIVE = "authoritative"
    OBSERVED = "observed"
    ESTIMATED = "estimated"
    UNKNOWN = "unknown"


class FundingMode(StrEnum):
    """How a tier or pool is funded."""

    PREPAID = "prepaid"
    RECURRING = "recurring"
    POSTPAID = "postpaid"
    NO_BUDGET = "no_budget"


class ResetRule(StrEnum):
    """Documented reset behavior of one subpool."""

    MONTHLY_FIRST = "monthly_first"
    VENDOR_PERIOD = "vendor_period"
    DAILY_VENDOR = "daily_vendor"
    DAILY_ESTIMATE = "daily_estimate"
    NEVER = "never"
    UNKNOWN = "unknown"


class RateWindowName(StrEnum):
    """Rate window identity."""

    SECOND = "1s"
    MINUTE = "1m"
    HOUR = "1h"
    DAY = "1d"


class RateScope(StrEnum):
    """Scope a vendor counter applies to."""

    ORG = "org"
    TEAM = "team"
    KEY = "key"
    IP = "ip"


class RateUnit(StrEnum):
    """Unit a rate bucket counts."""

    REQUESTS = "requests"
    URLS = "urls"


class BudgetModel(StrEnum):
    """Vendor spend meter for one rail."""

    NONE = "none"
    REQUESTS = "requests"
    CREDITS = "credits"
    USD = "usd"


class ExhaustAction(StrEnum):
    """What the vendor does when an allowance is exhausted."""

    HTTP_402 = "402"
    STOP = "stop"
    BILL = "bill"


class RateWindow(ContractModel):
    """One documented vendor rate window."""

    bucket_id: str
    limit: ExactDecimal
    window: RateWindowName
    scope: RateScope
    unit: RateUnit = RateUnit.REQUESTS
    remaining: OptionalExactDecimal = None
    reset_at: datetime | None = None
    source: str = "documented"
    confidence: Confidence = Confidence.AUTHORITATIVE
    kind: Literal["rate", "free_daily_allowance"] = "rate"

    @property
    def detail_only(self) -> bool:
        """Return whether this window appears only as detail text."""

        return self.window in (RateWindowName.SECOND, RateWindowName.MINUTE)


class RateBlock(ContractModel):
    """Published rate windows for one rail; a shared bucket keeps one ID."""

    windows: list[RateWindow] = Field(default_factory=list)
    published: bool = False


class PoolRateConstraint(ContractModel):
    """One documented upstream-pool rate constraint.

    This is the settled contract for the ``upstream_quota_pools.constraints``
    JSON list: any other kind, algorithm, unit, field, or operation selector is
    invalid instead of being silently skipped. An omitted ``operations``
    selector is one allowance shared by both operations; a present selector
    declares independent per-operation allowances.
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["rate"] = "rate"
    algorithm: Literal["trailing_window"] = "trailing_window"
    window: int | str
    limit: ExactDecimal
    unit: Literal["requests", "urls"] = "requests"
    operations: tuple[Literal["search", "fetch"], ...] | None = Field(default=None, min_length=1)


class BudgetBlock(ContractModel):
    """Native budget description for one rail.

    ``standard_native_cost`` is the native amount one standard (no add-on) call
    consumes. ``usd_per_call`` records the standard USD price when the vendor
    publishes one. Both feed the exact USD projection.
    """

    model: BudgetModel = BudgetModel.NONE
    free_allowance: OptionalExactDecimal = None
    allowance_unit: str = ""
    allowance_period: str | None = None
    cost_per_1k: OptionalExactDecimal = None
    standard_native_cost: ExactDecimal = Decimal("1")
    usd_per_call: OptionalExactDecimal = None
    on_exhausted: ExhaustAction = ExhaustAction.HTTP_402
    usage_api: str | None = None
    priced: bool = True


class CRDPriceProfile(ContractModel):
    """Conversion profile from native units to credit units.

    ``native_usd_per_unit`` is the applicable USD reference for one native unit
    (one credit, one request, or one USD where the native unit is already USD).
    A null price keeps the conversion unknown rather than zero.
    """

    reference_usd_per_crd: ExactDecimal = Field(default=CRD_USD_REFERENCE, gt=0)
    native_usd_per_unit: OptionalExactDecimal = Field(default=None, ge=0)
    cost_basis: Literal["priced_native_use"] = "priced_native_use"
    price_version: str = CRD_PRICE_VERSION
    source: str = "documented"
    estimated: bool = False


class TierBalance(ContractModel):
    """One applicable free or paid subpool of a provider account."""

    pool_id: str
    tier: Literal["free", "paid", "unknown"]
    native_unit: UnitKind
    native_remaining: OptionalExactDecimal = None
    native_allowance: OptionalExactDecimal = None
    remaining_crd: OptionalExactDecimal = None
    allowance_crd: OptionalExactDecimal = None
    reset_rule: ResetRule = ResetRule.UNKNOWN
    reset_at: datetime | None = None
    funding_mode: FundingMode = FundingMode.RECURRING
    source: str = "vendor_api"
    confidence: Confidence = Confidence.UNKNOWN
    transport_available: bool = True
    label: str | None = None


class ProviderLimitRecord(ContractModel):
    """Catalog record: one provider, one operation, one auth mode."""

    provider: str
    operation: LimitOperation
    auth_mode: AuthMode
    supported: bool
    transport_available: bool
    rate: RateBlock | None = None
    budget: BudgetBlock | None = None
    native_unit: UnitKind | None = None
    native_pool_id: str | None = None
    conversion_profile: CRDPriceProfile = Field(default_factory=CRDPriceProfile)
    plan_name: str | None = None
    usage_url: str | None = None
    version: int = Field(default=1, ge=1)

    @property
    def key(self) -> tuple[str, LimitOperation, AuthMode]:
        """Return the record's primary key."""

        return (self.provider, self.operation, self.auth_mode)


class NativePool(ContractModel):
    """Durable native funds shared by one or more operation views."""

    pool_id: str
    provider: str
    auth_mode: AuthMode
    native_unit: UnitKind
    remaining: OptionalExactDecimal = None
    allowance: OptionalExactDecimal = None
    actual_spend_usd: OptionalExactDecimal = None
    source: str = "vendor_api"
    confidence: Confidence = Confidence.UNKNOWN
    reset_at: datetime | None = None
    observed_at: datetime | None = None
    version: int = Field(default=1, ge=1)
    credential_generation: int = 0
    next_sync_at: datetime | None = None
    stale: bool = False
    manual_anchor: bool = False
    tiers: list["TierBalance"] = Field(default_factory=list)
    tier_split_known: bool = True


class NativeDebit(ContractModel):
    """Actual native use of one finished operation.

    ``native_units`` is the native amount the vendor charged for this attempt.
    A definite failure with no charge records zero. The Firecrawl
    returned-document exception reports its charged credits here even for a 403
    or 404 status.
    """

    provider: str
    operation: LimitOperation
    auth_mode: AuthMode
    native_unit: UnitKind
    pool_id: str | None = None
    native_units: ExactDecimal = Decimal("0")
    successful_urls: int = 0
    actual_usd: OptionalExactDecimal = None
    charged_document: bool = False
    failed: bool = False
    price_version: str = CRD_PRICE_VERSION


class RateObservation(ContractModel):
    """One durable vendor or local observation of a rate bucket."""

    bucket_id: str
    provider: str
    auth_mode: AuthMode
    window: RateWindowName
    unit: RateUnit
    limit: OptionalExactDecimal = None
    remaining: OptionalExactDecimal = None
    reset_at: datetime | None = None
    observed_at: datetime
    operation: LimitOperation | None = None
    source: str = "vendor_header"
    confidence: Confidence = Confidence.OBSERVED
    stale: bool = False


class RateProgressView(ContractModel):
    """Hourly or daily rate capacity shown outside collapsed detail."""

    bucket_id: str
    operation: LimitOperation
    window: Literal["1h", "1d"]
    unit: RateUnit
    remaining: OptionalExactDecimal = None
    limit: OptionalExactDecimal = None
    reset_at: datetime | None = None
    source: str = "vendor_header"
    confidence: Confidence = Confidence.OBSERVED
    kind: Literal["rate", "free_daily_allowance"] = "rate"
    stale: bool = False
    enforceable: bool = True


class RateReservation(ContractModel):
    """Reserved units of one rate bucket during one attempt."""

    bucket_id: str
    window: RateWindowName
    units: ExactDecimal = Decimal("1")


class RateDenial(ContractModel):
    """One rate window that lacks capacity for a request."""

    bucket_id: str
    window: RateWindowName
    limit: OptionalExactDecimal = None
    remaining: OptionalExactDecimal = None
    reset_at: datetime | None = None
    reason: str = "capacity"


class RateAdmission(ContractModel):
    """Result of rate admission for one attempt."""

    admitted: bool
    provider: str
    auth_mode: AuthMode
    attempt_id: str
    operation: LimitOperation | None = None
    reservations: list[RateReservation] = Field(default_factory=list)
    denials: list[RateDenial] = Field(default_factory=list)
    retry_after_seconds: int | None = None
    source: str = "local"
    # The verified actor of the admitted attempt, copied from the trusted
    # call context; durable rate rows refuse an attempt without one.
    actor_type: ActorType | None = None
    actor_id: UUID | None = None


class ProviderObservationScope(ContractModel):
    """Resolved credential identity carried through polling and reconciliation."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    credential_id: UUID
    upstream_pool_id: UUID | None = None
    credential_generation: int = 0

    def native_pool_id(self, base: str) -> str:
        """Use the same funds identity as a scoped execution admission."""
        scope = (
            f"pool:{self.upstream_pool_id}"
            if self.upstream_pool_id is not None
            else f"cred:{self.credential_id}"
        )
        return f"{base}#{scope}"


class NativeUsageSnapshot(ContractModel):
    """One vendor (or manual) observation of a provider's native funds."""

    pool_id: str
    provider: str
    auth_mode: AuthMode
    native_unit: UnitKind
    observed_at: datetime
    source: str = "vendor_api"
    confidence: Confidence = Confidence.OBSERVED
    remaining: OptionalExactDecimal = None
    allowance: OptionalExactDecimal = None
    actual_spend_usd: OptionalExactDecimal = None
    reset_at: datetime | None = None
    credential_generation: int = 0
    credential_id: UUID | None = None
    upstream_pool_id: UUID | None = None
    plan_name: str | None = None
    usage_url: str | None = None
    tiers: list[TierBalance] = Field(default_factory=list)
    tier_split_known: bool = False
    rate_observations: list[RateObservation] = Field(default_factory=list)
    stale: bool = False
    error_code: str | None = None


class UsageSyncRequest(ContractModel):
    """Request passed to an adapter's usage-snapshot seam."""

    provider: str
    auth_mode: AuthMode
    operations: tuple[LimitOperation, ...] = (LimitOperation.SEARCH, LimitOperation.FETCH)
    observed_at: datetime
    credential_generation: int = 0


class SyncClaim(ContractModel):
    """Cross-process lease claim for one scheduled sync."""

    provider: str
    owner: str
    now: datetime
    pool_id: str | None = None
    lease_seconds: int = 60
    credential_generation: int = 0


class SyncResult(ContractModel):
    """Outcome of one provider sync attempt."""

    provider: str
    status: Literal["synced", "skipped", "failed"]
    observed_at: datetime
    next_sync_at: datetime | None = None
    error_code: str | None = None
    stale: bool = False
    changed: bool = False
    reason: str | None = None


class CRDView(ContractModel):
    """Exact credit-unit capacity of one operation view."""

    state: CRDState
    operation: LimitOperation
    remaining_crd: OptionalExactDecimal = None
    local_remaining_crd: OptionalExactDecimal = None
    request_cost_crd: OptionalExactDecimal = None
    shared_pool_id: str | None = None
    possible_standard_calls: OptionalExactDecimal = None
    price_version: str | None = None
    priced: bool = True

    @property
    def spendable_crd(self) -> Decimal | None:
        """Return the exact spendable capacity, or ``None`` when unmetered."""

        if self.state is CRDState.UNMETERED:
            return None
        candidates = [
            value for value in (self.remaining_crd, self.local_remaining_crd) if value is not None
        ]
        if not candidates:
            return None
        return min(candidates)


class CRDUsageTotal(ContractModel):
    """Credit-unit use aggregated for one provider and operation."""

    provider: str
    operation: LimitOperation
    normalized_crd: ExactDecimal = Decimal("0")
    attempt_count: int = 0
    volume_count: int = 0


class LimitCallContext(ContractModel):
    """Execution context admitted before a vendor call."""

    provider: str
    operation: LimitOperation
    auth_mode: AuthMode
    attempt_id: str
    successful_urls: int = 1
    request: SearchRequest | FetchRequest | None = None
    requested_at: datetime
    credential_generation: int = 0
    # Trusted consumer attribution resolved from a verified project context;
    # never caller input, and never a substitute for the live scope decision.
    project_id: UUID | None = None
    credential_id: UUID | None = None
    binding_id: UUID | None = None
    upstream_pool_id: UUID | None = None
    request_id: str | None = None
    actor_type: ActorType | None = None
    actor_id: UUID | None = None


class LimitAdmission(ContractModel):
    """Durable reservation that finalizes or releases exactly once."""

    attempt_id: str
    provider: str
    operation: LimitOperation
    auth_mode: AuthMode
    pool_id: str | None = None
    reserved_crd: ExactDecimal = Decimal("0")
    reserved_native: OptionalExactDecimal = None
    state: Literal["reserved", "finalized", "released"] = "reserved"
    created_at: datetime
    expires_at: datetime
    rate_reservations: list[RateReservation] = Field(default_factory=list)
    local_only: bool = False
    project_id: UUID | None = None
    credential_id: UUID | None = None
    binding_id: UUID | None = None
    upstream_pool_id: UUID | None = None
    request_id: str | None = None
    actor_type: ActorType | None = None
    actor_id: UUID | None = None

    @property
    def finalized(self) -> bool:
        """Return whether this admission already finished."""

        return self.state != "reserved"


class LimitDebit(ContractModel):
    """Actual native and credit-unit use of one finished attempt."""

    attempt_id: str
    provider: str
    operation: LimitOperation
    auth_mode: AuthMode
    pool_id: str | None = None
    outcome: Literal["success", "failure"] = "success"
    native_units: OptionalExactDecimal = None
    successful_urls: int = 0
    actual_usd: OptionalExactDecimal = None
    charged_document: bool = False
    crd_debit: OptionalExactDecimal = None
    price_version: str = CRD_PRICE_VERSION
    native_unit: UnitKind | None = None
    reason: str = "local_success"
    audit_source: str = "local"


class LimitAuditEvent(ContractModel):
    """One immutable balance-change or denial record."""

    event_id: str
    provider: str
    auth_mode: AuthMode
    operation: LimitOperation | None = None
    pool_id: str | None = None
    observed_at: datetime
    source: str
    reason: str
    old_native: OptionalExactDecimal = None
    new_native: OptionalExactDecimal = None
    old_crd: OptionalExactDecimal = None
    new_crd: OptionalExactDecimal = None
    crd_debit: OptionalExactDecimal = None
    native_debit: OptionalExactDecimal = None
    actual_usd: OptionalExactDecimal = None
    confidence: Confidence = Confidence.OBSERVED
    local_attempt_id: str | None = None
    detail: dict[str, Any] = Field(default_factory=dict)


class LimitHistoryQuery(ContractModel):
    """Paged audit read for one provider."""

    provider: str
    auth_mode: AuthMode | None = None
    limit: int = Field(default=DEFAULT_HISTORY_PAGE_SIZE, ge=1, le=MAX_HISTORY_PAGE_SIZE)
    cursor: str | None = None


class LimitHistoryPage(ContractModel):
    """One page of audit events plus the opaque next cursor."""

    events: list[LimitAuditEvent] = Field(default_factory=list)
    next_cursor: str | None = None


class LimitRecordUpdate(ContractModel):
    """Partial catalog update.

    An omitted field keeps its stored value; an explicit null clears the field.
    Callers inspect :meth:`touched` to tell the two cases apart.
    """

    provider: str
    operation: LimitOperation
    auth_mode: AuthMode
    version: int = Field(ge=1)
    rate: RateBlock | None = None
    budget: BudgetBlock | None = None
    conversion_profile: CRDPriceProfile | None = None
    plan_name: str | None = None
    usage_url: str | None = None
    supported: bool | None = None
    transport_available: bool | None = None

    def touched(self, field: str) -> bool:
        """Return whether ``field`` appeared in the incoming payload."""

        return field in self.model_fields_set


class CRDGrantPayload(ContractModel):
    """Operator grant of search and fetch credit units for one period."""

    version: int = Field(default=0, ge=0)
    period_start: date
    period_end: date
    search_crd: ExactDecimal = Decimal("0")
    fetch_crd: ExactDecimal = Decimal("0")

    @property
    def grants(self) -> dict[LimitOperation, Decimal]:
        """Return the per-operation grant amounts."""

        return {
            LimitOperation.SEARCH: self.search_crd,
            LimitOperation.FETCH: self.fetch_crd,
        }


# The rename contract keeps both names available to the API and repository.
CRDGrantUpdate = CRDGrantPayload


class CRDGrantsSummary(ContractModel):
    """Stored grant state for one provider/auth mode and period."""

    provider: str
    auth_mode: AuthMode
    period_start: date
    period_end: date
    version: int = 1
    search_granted_crd: ExactDecimal = Decimal("0")
    search_consumed_crd: ExactDecimal = Decimal("0")
    search_reserved_crd: ExactDecimal = Decimal("0")
    fetch_granted_crd: ExactDecimal = Decimal("0")
    fetch_consumed_crd: ExactDecimal = Decimal("0")
    fetch_reserved_crd: ExactDecimal = Decimal("0")

    def remaining(self, operation: LimitOperation) -> Decimal | None:
        """Return the exact unspent, unreserved grant, or ``None`` when absent."""

        granted, consumed, reserved = self._amounts(operation)
        if granted == 0 and consumed == 0 and reserved == 0:
            return None
        remaining = granted - consumed - reserved
        return remaining if remaining > 0 else Decimal("0")

    def _amounts(self, operation: LimitOperation) -> tuple[Decimal, Decimal, Decimal]:
        if operation is LimitOperation.SEARCH:
            return (self.search_granted_crd, self.search_consumed_crd, self.search_reserved_crd)
        return (self.fetch_granted_crd, self.fetch_consumed_crd, self.fetch_reserved_crd)


class ProviderLimitDetail(ContractModel):
    """Detail-only native, USD, plan, and rate information for one rail."""

    plan_name: str | None = None
    native_unit: UnitKind | None = None
    native_balance: OptionalExactDecimal = None
    native_allowance: OptionalExactDecimal = None
    usd_per_call: OptionalExactDecimal = None
    actual_spend_usd: OptionalExactDecimal = None
    reset_at: datetime | None = None
    reset_rule: ResetRule = ResetRule.UNKNOWN
    usage_url: str | None = None
    source: str = "vendor_api"
    confidence: Confidence = Confidence.UNKNOWN
    last_sync_at: datetime | None = None
    stale: bool = False
    price_version: str = CRD_PRICE_VERSION
    crd_split_note: str | None = None
    rate_windows: list[RateWindow] = Field(default_factory=list)
    # Remaining seconds of a vendor 429 cooldown exposed as rate state.
    retry_after_seconds: int | None = Field(default=None, ge=0)
    tier_split_known: bool = True
    aggregate_pool_id: str | None = None


class ProviderAuthLimits(ContractModel):
    """Limit state of one provider under one auth mode."""

    auth_mode: AuthMode
    transport_available: bool = False
    search: ProviderLimitRecord | None = None
    fetch: ProviderLimitRecord | None = None
    free_tiers: list[TierBalance] = Field(default_factory=list)
    paid_tiers: list[TierBalance] = Field(default_factory=list)
    unknown_tiers: list[TierBalance] = Field(default_factory=list)
    tier_split_known: bool = True
    aggregate_pool: NativePool | None = None
    crd_views: list[CRDView] = Field(default_factory=list)
    rate_progress: list[RateProgressView] = Field(default_factory=list)
    grants: CRDGrantsSummary | None = None
    detail: ProviderLimitDetail | None = None


class ProviderLimitsResponse(ContractModel):
    """Dashboard payload for one provider: both auth modes and their views."""

    provider: str
    active_auth_mode: AuthMode
    auths: list[ProviderAuthLimits] = Field(default_factory=list)
    documented_keyless_operations: list[LimitOperation] = Field(default_factory=list)
    version: int = 1
    generated_at: datetime

    def auth(self, auth_mode: AuthMode) -> ProviderAuthLimits | None:
        """Return the entry for ``auth_mode`` when present."""

        return next((entry for entry in self.auths if entry.auth_mode is auth_mode), None)


class VaultKeyUsage(ContractModel):
    """Sanitized quota observation for one vault key."""

    key_id: UUID
    label: str
    owner_email: str
    auth_mode: CredentialAuthMode = CredentialAuthMode.API_KEY
    oauth_connected: bool | None = None
    balance: NativePool | None = None


class LimitStoreUnavailable(RuntimeError):
    """Raised when a limit write or capacity check cannot reach durable storage."""

    def __init__(self, provider: str) -> None:
        super().__init__(f"{provider}: the limit store is unavailable for a metered write")
        self.provider = provider


class LimitRecordNotFound(LookupError):
    """Raised when a provider, operation, and auth mode has no catalog record."""

    def __init__(self, provider: str, operation: str, auth_mode: str) -> None:
        super().__init__(f"no limit record for {provider}/{auth_mode}/{operation}")
        self.provider = provider
        self.operation = operation
        self.auth_mode = auth_mode


class LimitVersionConflict(RuntimeError):
    """Raised when a write carries a version older than the stored record."""

    def __init__(self, provider: str, expected: int, stored: int) -> None:
        super().__init__(
            f"{provider}: version precondition failed (sent {expected}, stored {stored})"
        )
        self.provider = provider
        self.expected = expected
        self.stored = stored


class LimitDeniedError(Exception):
    """Local admission denial carrying a safe, structured provider error.

    The denial happens before any vendor I/O. ``refusal`` distinguishes an
    exhausted funds gate (``local 402``) from an exhausted rate window
    (``local 429``); when both apply, funds take status precedence.
    """

    def __init__(
        self,
        error: ProviderError,
        *,
        refusal: Literal["funds", "rate"],
        reasons: list[str] | None = None,
        retry_after_seconds: int | None = None,
    ) -> None:
        super().__init__(f"{error.provider}: {error.code}: {error.message}")
        self.error = error
        self.refusal = refusal
        self.reasons = list(reasons or [])
        self.retry_after_seconds = retry_after_seconds

    @property
    def status_code(self) -> int:
        """Return the REST status: 429 for rate denial, else 402."""

        if self.refusal == "rate":
            return 429
        return 402


def local_funds_denial(
    provider: str,
    *,
    operation: LimitOperation | None = None,
    reasons: list[str] | None = None,
    detail: dict[str, Any] | None = None,
) -> LimitDeniedError:
    """Build the non-retryable local funds denial (soft 402)."""

    return LimitDeniedError(
        ProviderError(
            provider=provider,
            code=LOCAL_FUNDS_DENIAL_CODE,
            message="local budget is exhausted; vendor call skipped",
            retryable=False,
            status_code=402,
            details={
                "origin": "local",
                "refusal": "funds",
                "operation": operation.value if operation is not None else None,
                "reasons": list(reasons or []),
                **(detail or {}),
            },
        ),
        refusal="funds",
        reasons=reasons,
    )


def local_rate_denial(
    provider: str,
    *,
    operation: LimitOperation | None = None,
    reasons: list[str] | None = None,
    retry_after_seconds: int | None = None,
    detail: dict[str, Any] | None = None,
) -> LimitDeniedError:
    """Build the non-retryable local rate denial (429 with ``Retry-After``)."""

    return LimitDeniedError(
        ProviderError(
            provider=provider,
            code=LOCAL_RATE_DENIAL_CODE,
            message="local rate window has no capacity; vendor call skipped",
            retryable=False,
            status_code=429,
            details={
                "origin": "local",
                "refusal": "rate",
                "operation": operation.value if operation is not None else None,
                "reasons": list(reasons or []),
                "retry_after_seconds": retry_after_seconds,
                **(detail or {}),
            },
        ),
        refusal="rate",
        reasons=reasons,
        retry_after_seconds=retry_after_seconds,
    )


def unpriced_ceiling_error(provider: str, operation: LimitOperation) -> LimitDeniedError:
    """Build the safe configuration error for an unpriced finite CRD ceiling."""

    return LimitDeniedError(
        ProviderError(
            provider=provider,
            code=UNPRICED_CEILING_CODE,
            message="request has no known price and the budget is finite",
            retryable=False,
            status_code=422,
            details={
                "origin": "local",
                "refusal": "funds",
                "operation": operation.value,
                "reasons": ["price_unknown"],
            },
        ),
        refusal="funds",
        reasons=["price_unknown"],
    )


def native_pool_id(provider: str, auth_mode: AuthMode, native_unit: UnitKind) -> str:
    """Return the stable pool ID for one native fund source.

    Different auth modes get different pool IDs, and a shared vendor balance
    keeps one ID so both operation views project the same funds exactly once.
    """

    return f"{provider}:{auth_mode.value}:{native_unit.value.lower()}"


def effective_attempt_deadline(created_at: datetime) -> datetime:
    """Return the instant an unfinished reservation stops being usable."""

    return created_at + timedelta(seconds=DEFAULT_ATTEMPT_LEASE_SECONDS)
