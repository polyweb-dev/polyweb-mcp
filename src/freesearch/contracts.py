"""Provider-neutral request, response, usage, and error models."""

import re
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any, Literal

from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field, SecretStr, field_validator


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


class FetchRequest(ContractModel):
    url: AnyHttpUrl
    max_chars: int | None = Field(default=None, ge=1, le=2_000_000)
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


class UsageOperation(StrEnum):
    SEARCH = "search"
    FETCH = "fetch"
    COST_ESTIMATE = "cost_estimate"


class UsageStatus(StrEnum):
    """Outcome recorded alongside a usage event's measured latency."""

    SUCCESS = "success"
    FAILURE = "failure"


class UsageEvent(ContractModel):
    provider: str
    operation: UsageOperation
    units: Decimal = Field(ge=0)
    observed_at: datetime
    request_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    latency_ms: int | None = Field(default=None, ge=0)
    status: UsageStatus = UsageStatus.SUCCESS


class QuotaSource(StrEnum):
    AUTHORITATIVE = "authoritative"
    OBSERVED = "observed"
    ESTIMATED = "estimated"


class QuotaSnapshot(ContractModel):
    provider: str
    source: QuotaSource
    remaining: Decimal | None = Field(default=None, ge=0)
    limit: Decimal | None = Field(default=None, ge=0)
    reset_at: datetime | None = None
    observed_at: datetime


class CostEstimate(ContractModel):
    provider: str
    operation: UsageOperation
    units: Decimal = Field(ge=0)
    currency: str = "USD"
    notes: str | None = None


class ProviderCapabilities(ContractModel):
    search: bool = True
    fetch: bool = False
    cost_estimate: bool = False
    health: bool = False
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


class CacheMetadata(ContractModel):
    """Metadata for a cached operation; cached payloads are never persisted here."""

    cache_key: str = Field(min_length=1)
    provider: str
    operation: UsageOperation
    created_at: datetime
    expires_at: datetime
    accessed_at: datetime
    hit_count: int = Field(default=0, ge=0)
    size_bytes: int | None = Field(default=None, ge=0)

    @field_validator("cache_key")
    @classmethod
    def validate_cache_key(cls, cache_key: str) -> str:
        if re.fullmatch(r"[0-9a-f]{64}", cache_key) is None:
            raise ValueError("cache_key must be a lowercase SHA-256 digest")
        return cache_key


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


SearchResponse.model_rebuild()
FetchResponse.model_rebuild()
