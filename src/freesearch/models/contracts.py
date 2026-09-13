"""Provider-neutral request, response, usage, and error models."""

from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any, Literal, Self

from pydantic import (
    AnyHttpUrl,
    BaseModel,
    ConfigDict,
    Field,
    SecretStr,
    computed_field,
    field_validator,
    model_serializer,
    model_validator,
)


def parse_decimal(value: object, *, allow_negative: bool = False) -> Decimal:
    """Parse a finite, non-negative Decimal without passing through float."""

    if value is None or isinstance(value, (bool, float)):
        raise TypeError("decimal inputs must be finite integers, strings, or Decimals")
    try:
        parsed = value if isinstance(value, Decimal) else Decimal(value)  # type: ignore[arg-type]
    except (ArithmeticError, TypeError, ValueError) as exc:
        raise ValueError("value is not a valid Decimal") from exc
    if not parsed.is_finite():
        raise ValueError("Decimal must be finite")
    if not allow_negative and parsed < 0:
        raise ValueError("Decimal must be non-negative")
    return parsed


class ContractModel(BaseModel):
    """Base model used to keep contract payloads strict and serializable."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class RoutingMode(StrEnum):
    AUTO = "auto"
    PREFER = "prefer"
    REQUIRE = "require"


class RoutingPreference(ContractModel):
    """Caller preferences used later by the routing layer."""

    mode: RoutingMode = RoutingMode.AUTO
    providers: tuple[str, ...] = ()
    allow_fallback: bool = True

    @field_validator("providers")
    @classmethod
    def validate_provider_names(cls, providers: tuple[str, ...]) -> tuple[str, ...]:
        if any(not provider.strip() for provider in providers):
            raise ValueError("provider names must not be blank")
        return providers


class SearchRequest(ContractModel):
    query: str = Field(min_length=1, max_length=2_000)
    limit: int = Field(default=10, ge=1, le=100)
    mode: Literal["turbo", "basic", "advanced"] | None = None
    extra_bundles: int = Field(default=0, ge=0, le=10_000)
    language: str | None = Field(default=None, min_length=2, max_length=16)
    country_code: str | None = Field(default=None, min_length=2, max_length=2)
    domains: tuple[str, ...] = ()
    routing: RoutingPreference = Field(default_factory=RoutingPreference)


class SearchResult(ContractModel):
    title: str
    url: AnyHttpUrl
    snippet: str = ""
    published_at: datetime | None = None
    source: str | None = None
    score: float | None = Field(default=None, ge=0, le=1)
    metadata: dict[str, Any] = Field(default_factory=dict)


class SearchResponse(ContractModel):
    query: str
    results: list[SearchResult]
    provider: str
    total_results: int | None = Field(default=None, ge=0)
    usage: "UsageEvent | None" = None
    quota_snapshot: "QuotaSnapshot | None" = Field(default=None, exclude=True)
    # Internal marker for a successful response whose vendor omitted metering.
    # It is intentionally excluded from wire serialization for compatibility.
    usage_gap: dict[str, Any] | None = Field(default=None, exclude=True)


class FetchRequest(ContractModel):
    url: AnyHttpUrl
    max_chars: int | None = Field(default=None, ge=1, le=2_000_000)
    url_count: int = Field(default=1, ge=1, le=10_000)
    pdf_pages: int = Field(default=0, ge=0, le=10_000)
    json_extract: bool = False
    enhanced: bool = False
    zero_data_retention: bool = False
    routing: RoutingPreference = Field(default_factory=RoutingPreference)


class FetchedDocument(ContractModel):
    url: AnyHttpUrl
    content: str
    title: str | None = None
    content_type: str | None = None
    fetched_at: datetime
    metadata: dict[str, Any] = Field(default_factory=dict)


class FetchResponse(ContractModel):
    provider: str
    document: FetchedDocument
    usage: "UsageEvent | None" = None
    usage_gap: dict[str, Any] | None = Field(default=None, exclude=True)


class UsageOperation(StrEnum):
    SEARCH = "search"
    FETCH = "fetch"
    COST_ESTIMATE = "cost_estimate"


class UsageStatus(StrEnum):
    """Outcome recorded alongside a usage event's measured latency."""

    SUCCESS = "success"
    FAILURE = "failure"


class UnitKind(StrEnum):
    """Dimension used when aggregating raw usage units."""

    REQUEST = "REQUEST"
    CREDIT = "CREDIT"
    USD = "USD"
    FREE = "FREE"


class UsageEvent(ContractModel):
    provider: str
    operation: UsageOperation
    units: Decimal = Field(ge=0)
    unit_kind: UnitKind | None = None
    display_unit: str | None = None
    observed_at: datetime
    request_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    latency_ms: int | None = Field(default=None, ge=0)
    status: UsageStatus = UsageStatus.SUCCESS

    @field_validator("units", mode="before")
    @classmethod
    def validate_units(cls, value: object) -> Decimal:
        return parse_decimal(value)


class QuotaSource(StrEnum):
    AUTHORITATIVE = "authoritative"
    OBSERVED = "observed"
    ESTIMATED = "estimated"


class QuotaSnapshot(ContractModel):
    provider: str
    source: QuotaSource
    remaining: Decimal | None = Field(default=None, ge=0)
    limit: Decimal | None = Field(default=None, ge=0)
    unit_kind: UnitKind | None = None
    display_unit: str | None = None
    reset_at: datetime | None = None
    observed_at: datetime
    # Local routing state is not a vendor payload and is never serialized.
    metadata: dict[str, Any] = Field(default_factory=dict, exclude=True)

    @computed_field(return_type=Decimal | None)  # type: ignore[prop-decorator]
    @property
    def remaining_percent(self) -> Decimal | None:
        """Return remaining capacity as a canonical 0-100 percentage.

        The percentage is deliberately derived from the native values rather
        than persisted.  A missing/zero limit (or missing remaining value)
        does not describe a bounded allowance, so it remains unknown.  Some
        vendors report promotional balance above their baseline plan; clamp
        that case to 100 while retaining the original native values.
        """

        if self.remaining is None or self.limit is None or self.limit <= 0:
            return None
        ratio = self.remaining / self.limit * Decimal("100")
        return min(Decimal("100"), max(Decimal("0"), ratio))

    @computed_field(return_type=str | None)  # type: ignore[prop-decorator]
    @property
    def window(self) -> str | None:
        """Expose an optional non-sensitive scope label without raw metadata."""

        value = self.metadata.get("window")
        return value if isinstance(value, str) else None

    @model_serializer(mode="wrap")
    def _serialize_compat(self, handler: Any) -> Any:
        """Keep legacy/unknown snapshots backward compatible on the wire.

        The derived percentage is useful only for a canonical unit-bearing
        snapshot.  Omitting it for legacy rows and unknown limits preserves
        the historical payload shape while known quotas gain one consistent
        field.
        """

        payload = handler(self)
        if self.unit_kind is None:
            payload.pop("remaining_percent", None)
        if self.window is None:
            payload.pop("window", None)
        return payload

    @field_validator("remaining", "limit", mode="before")
    @classmethod
    def validate_quota_number(cls, value: object) -> Decimal | None:
        if value is None:
            return None
        return parse_decimal(value)


def is_soft_quota_zero(provider: str, snapshot: QuotaSnapshot) -> bool:
    """Identify non-authoritative zero signals without weakening hard exhaustion."""

    if (
        provider == "keenable"
        and snapshot.source is QuotaSource.OBSERVED
        and snapshot.metadata.get("mode") == "keyless"
        and snapshot.metadata.get("scope") == "shared_pool_local_observation"
    ):
        # This is only this process's view of a shared IP/pool rate limit. A
        # local count reaching zero cannot prove the vendor pool is exhausted;
        # let the provider's 429 response remain the authoritative pressure.
        return True
    return (
        provider == "parallel"
        and snapshot.source is QuotaSource.ESTIMATED
        and (snapshot.metadata.get("soft_zero") is not False)
    )


class CostEstimate(ContractModel):
    provider: str
    operation: UsageOperation
    units: Decimal = Field(ge=0)
    currency: str = "USD"
    notes: str | None = None

    @field_validator("units", mode="before")
    @classmethod
    def validate_units(cls, value: object) -> Decimal:
        return parse_decimal(value)


class ProviderCapabilities(ContractModel):
    search: bool = True
    fetch: bool = False
    cost_estimate: bool = False
    quota: bool = False


class HealthStatus(StrEnum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"
    UNKNOWN = "unknown"


class ProviderHealth(ContractModel):
    provider: str
    status: HealthStatus
    checked_at: datetime
    message: str | None = None


class ProviderError(ContractModel):
    provider: str
    code: str
    message: str
    retryable: bool = False
    status_code: int | None = Field(default=None, ge=100, le=599)
    details: dict[str, Any] = Field(default_factory=dict)


class SecretPresence(StrEnum):
    """Resolved credential presence for a provider."""

    CONFIGURED = "configured"
    MISSING = "missing"
    KEYLESS_PUBLIC = "keyless_public"


class BreakerState(StrEnum):
    """Persisted circuit-breaker state shown on the control surface."""

    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitBreakerState(ContractModel):
    """Nested breaker state inside a provider status entry."""

    state: BreakerState = BreakerState.CLOSED
    updated_at: datetime


class CircuitBreakerStatusResponse(ContractModel):
    """Result of a manual circuit-breaker reset."""

    provider: str
    state: BreakerState = BreakerState.CLOSED
    updated_at: datetime


class ProviderStatusResponse(ContractModel):
    """One canonical provider's control-plane status entry."""

    provider_id: str
    enabled: bool
    priority: int
    health: HealthStatus | None = None
    circuit_breaker: CircuitBreakerState
    latency_p95_ms: int | None = Field(default=None, ge=0)
    secret_presence: SecretPresence
    free_tier_estimates: dict[UsageOperation, Decimal] = Field(default_factory=dict)
    reset_schedule: str | None = None


class ProviderTestResponse(ContractModel):
    """Result of a timed provider health probe."""

    provider: str
    ok: bool
    status: HealthStatus
    latency_ms: int = Field(ge=0)
    detail: str | None = None
    checked_at: datetime


class SetSecretRequest(ContractModel):
    """Write-only key payload; the raw value is never echoed or logged."""

    key: SecretStr = Field(min_length=1)


class SecretStatusResponse(ContractModel):
    """Masked secret status: presence plus a stable fingerprint, never the key."""

    provider: str
    presence: SecretPresence
    fingerprint: str | None = None
    updated_at: datetime | None = None
    source: Literal["environment", "dotenv", "keyring", "none"]


class FallbackPolicy(StrEnum):
    """Global routing fallback policy."""

    CHAINED = "chained"
    FIRST_ONLY = "first_only"


class CostPreset(StrEnum):
    """Global cost-optimization preset applied to candidate ordering."""

    BALANCED = "balanced"
    FREE_FIRST = "free_first"


class RoutingConfigResponse(ContractModel):
    """Persisted global routing defaults."""

    fallback_policy: FallbackPolicy = FallbackPolicy.CHAINED
    cost_optimization_preset: CostPreset = CostPreset.BALANCED
    max_attempts: int = Field(default=3, ge=1)


class RoutingConfigUpdate(ContractModel):
    """Partial routing-policy update merged onto the persisted record."""

    fallback_policy: FallbackPolicy | None = None
    cost_optimization_preset: CostPreset | None = None
    max_attempts: int | None = Field(default=None, ge=1)


def manual_quota_remaining(allowance: Decimal, current_usage: Decimal) -> Decimal:
    """Return the remaining allowance, floored at zero with Decimal math."""

    remaining = allowance - current_usage
    return remaining if remaining > 0 else Decimal("0")


def manual_quota_remaining_percent(allowance: Decimal, current_usage: Decimal) -> Decimal | None:
    """Return remaining capacity as 0-100, or None when allowance is unknown."""

    if allowance <= 0:
        return None
    remaining = manual_quota_remaining(allowance, current_usage)
    ratio = remaining / allowance * Decimal("100")
    return min(Decimal("100"), max(Decimal("0"), ratio))


class _ManualQuotaInputBase(ContractModel):
    """Shared billing-anchor input fields and checks.

    Owned jointly by ``ManualQuota`` and ``ManualQuotaUpdate`` (identical
    input shape). ``ManualQuotaResponse`` is intentionally excluded: it
    validates remaining/optional percent and lacks the window validator.
    """

    billing_start: date
    billing_end: date
    allowance: Decimal = Field(ge=0)
    current_usage: Decimal = Field(ge=0)
    note: str | None = Field(default=None, max_length=500)

    @field_validator("allowance", "current_usage", mode="before")
    @classmethod
    def validate_quota_decimal(cls, value: object) -> Decimal:
        try:
            return parse_decimal(value)
        except TypeError as exc:
            raise ValueError(str(exc)) from exc

    @model_validator(mode="after")
    def validate_billing_window(self) -> Self:
        if self.billing_end <= self.billing_start:
            raise ValueError("billing_end must be after billing_start")
        return self


class ManualQuota(_ManualQuotaInputBase):
    """Operator-entered billing anchor; provider-agnostic and routing-neutral.

    The unit is implied by the provider (Brave/Exa/Parallel use USD with
    Brave costing $0.005/request; other providers use REQUEST/CREDIT). This
    model never steers routing; it only feeds the ESTIMATED control response.
    """


class ManualQuotaUpdate(_ManualQuotaInputBase):
    """Full billing-anchor input accepted by PUT; same shape as ManualQuota."""


class ManualQuotaResponse(ContractModel):
    """Stored billing anchor plus derived ESTIMATED capacity for the dashboard."""

    provider: str
    billing_start: date
    billing_end: date
    allowance: Decimal = Field(ge=0)
    current_usage: Decimal = Field(ge=0)
    remaining: Decimal = Field(ge=0)
    remaining_percent: Decimal | None = Field(default=None, ge=0, le=100)
    source: QuotaSource = QuotaSource.ESTIMATED
    updated_at: datetime
    note: str | None = Field(default=None, max_length=500)

    @field_validator("allowance", "current_usage", "remaining", mode="before")
    @classmethod
    def validate_quota_decimal(cls, value: object) -> Decimal:
        try:
            return parse_decimal(value)
        except TypeError as exc:
            raise ValueError(str(exc)) from exc

    @field_validator("remaining_percent", mode="before")
    @classmethod
    def validate_percent(cls, value: object) -> Decimal | None:
        if value is None:
            return None
        try:
            return parse_decimal(value)
        except TypeError as exc:
            raise ValueError(str(exc)) from exc


SearchResponse.model_rebuild()
FetchResponse.model_rebuild()
