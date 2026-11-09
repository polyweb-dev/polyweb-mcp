"""USD transport contracts. The persisted ledger retains its exact credit units."""

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from pydantic import Field, model_validator

from freesearch.models import provider_limits as ledger
from freesearch.models.budget_period import BudgetPeriod
from freesearch.models.contracts import ContractModel, UnitKind
from freesearch.models.credentials import CredentialAuthMode

USD_PRICE_VERSION = "usd-v1"


def project_usd(value: Any) -> Any:
    """Project ledger money into decimal USD without changing stored values."""
    if isinstance(value, ContractModel):
        value = value.model_dump()
    if isinstance(value, list):
        return [project_usd(item) for item in value]
    if not isinstance(value, dict):
        return value
    result: dict[str, Any] = {}
    for raw_key, item in value.items():
        key = str(raw_key)
        if key in ("period_start", "period_end") and "search_granted_crd" in value:
            continue
        if key == "reference_usd_per_crd":
            continue
        if key == "price_version" and item == ledger.CRD_PRICE_VERSION:
            result[key] = USD_PRICE_VERSION
            continue
        if key.endswith("_crd") or key == "crd_debit":
            name = "debit_usd" if key == "crd_debit" else key[:-4] + "_usd"
            if key == "normalized_crd":
                name = "spend_usd"
            result[name] = None if item is None else Decimal(str(item)) * ledger.CRD_USD_REFERENCE
        else:
            name = {"crd_views": "usd_views", "crd_split_note": "balance_split_note"}.get(key, key)
            result[name] = project_usd(item)
    if value.get("source") == "operator_grant" and "remaining_crd" in value:
        result["native_unit"] = "USD"
        for native_name in ("native_remaining", "native_allowance"):
            amount = value.get(native_name)
            result[native_name] = (
                None if amount is None else Decimal(str(amount)) * ledger.CRD_USD_REFERENCE
            )
    return result


class USDContract(ContractModel):
    """Accept an internal contract only at this explicit transport boundary."""

    @model_validator(mode="before")
    @classmethod
    def from_ledger(cls, value: Any) -> Any:
        return project_usd(value)


class USDPriceProfile(USDContract):
    native_usd_per_unit: ledger.OptionalExactDecimal = Field(default=None, ge=0)
    cost_basis: Literal["priced_native_use"] = "priced_native_use"
    price_version: str = USD_PRICE_VERSION
    source: str = "documented"
    estimated: bool = False


class USDTierBalance(USDContract):
    pool_id: str
    tier: Literal["free", "paid", "unknown"]
    native_unit: UnitKind
    native_remaining: ledger.OptionalExactDecimal = None
    native_allowance: ledger.OptionalExactDecimal = None
    remaining_usd: ledger.OptionalExactDecimal = None
    allowance_usd: ledger.OptionalExactDecimal = None
    reset_rule: ledger.ResetRule = ledger.ResetRule.UNKNOWN
    reset_at: datetime | None = None
    funding_mode: ledger.FundingMode = ledger.FundingMode.RECURRING
    source: str = "vendor_api"
    confidence: ledger.Confidence = ledger.Confidence.UNKNOWN
    transport_available: bool = True
    label: str | None = None


class USDNativePool(USDContract):
    pool_id: str
    provider: str
    auth_mode: ledger.AuthMode
    native_unit: UnitKind
    remaining: ledger.OptionalExactDecimal = None
    allowance: ledger.OptionalExactDecimal = None
    actual_spend_usd: ledger.OptionalExactDecimal = None
    source: str = "vendor_api"
    confidence: ledger.Confidence = ledger.Confidence.UNKNOWN
    reset_at: datetime | None = None
    observed_at: datetime | None = None
    version: int = Field(default=1, ge=1)
    credential_generation: int = 0
    next_sync_at: datetime | None = None
    stale: bool = False
    manual_anchor: bool = False
    tiers: list[USDTierBalance] = Field(default_factory=list)
    tier_split_known: bool = True


class USDVaultKeyUsage(USDContract):
    key_id: UUID
    label: str
    owner_email: str
    auth_mode: CredentialAuthMode = CredentialAuthMode.API_KEY
    oauth_connected: bool | None = None
    balance: USDNativePool | None = None


class USDLimitRecord(USDContract):
    provider: str
    operation: ledger.LimitOperation
    auth_mode: ledger.AuthMode
    supported: bool
    transport_available: bool
    rate: ledger.RateBlock | None = None
    budget: ledger.BudgetBlock | None = None
    native_unit: UnitKind | None = None
    native_pool_id: str | None = None
    conversion_profile: USDPriceProfile = Field(default_factory=USDPriceProfile)
    plan_name: str | None = None
    usage_url: str | None = None
    version: int = Field(default=1, ge=1)


class USDView(USDContract):
    state: Literal["finite", "unmetered", "unavailable", "unknown"]
    operation: ledger.LimitOperation
    remaining_usd: ledger.OptionalExactDecimal = None
    local_remaining_usd: ledger.OptionalExactDecimal = None
    request_cost_usd: ledger.OptionalExactDecimal = None
    shared_pool_id: str | None = None
    possible_standard_calls: ledger.OptionalExactDecimal = None
    price_version: str | None = None
    priced: bool = True


class USDUsageTotal(USDContract):
    provider: str
    operation: ledger.LimitOperation
    spend_usd: ledger.ExactDecimal = Decimal("0")
    attempt_count: int = 0
    volume_count: int = 0


class USDAuditEvent(USDContract):
    event_id: str
    provider: str
    auth_mode: ledger.AuthMode
    operation: ledger.LimitOperation | None = None
    pool_id: str | None = None
    observed_at: datetime
    source: str
    reason: str
    old_native: ledger.OptionalExactDecimal = None
    new_native: ledger.OptionalExactDecimal = None
    old_usd: ledger.OptionalExactDecimal = None
    new_usd: ledger.OptionalExactDecimal = None
    debit_usd: ledger.OptionalExactDecimal = None
    native_debit: ledger.OptionalExactDecimal = None
    actual_usd: ledger.OptionalExactDecimal = None
    confidence: ledger.Confidence = ledger.Confidence.OBSERVED
    local_attempt_id: str | None = None
    detail: dict[str, Any] = Field(default_factory=dict)


class USDHistoryPage(USDContract):
    events: list[USDAuditEvent] = Field(default_factory=list)
    next_cursor: str | None = None


class USDGrantsSummary(USDContract):
    provider: str
    auth_mode: ledger.AuthMode
    period: BudgetPeriod = "month"
    version: int = 1
    search_granted_usd: ledger.ExactDecimal = Decimal("0")
    search_consumed_usd: ledger.ExactDecimal = Decimal("0")
    search_reserved_usd: ledger.ExactDecimal = Decimal("0")
    fetch_granted_usd: ledger.ExactDecimal = Decimal("0")
    fetch_consumed_usd: ledger.ExactDecimal = Decimal("0")
    fetch_reserved_usd: ledger.ExactDecimal = Decimal("0")


class USDLimitDetail(USDContract):
    plan_name: str | None = None
    native_unit: UnitKind | None = None
    native_balance: ledger.OptionalExactDecimal = None
    native_allowance: ledger.OptionalExactDecimal = None
    usd_per_call: ledger.OptionalExactDecimal = None
    actual_spend_usd: ledger.OptionalExactDecimal = None
    reset_at: datetime | None = None
    reset_rule: ledger.ResetRule = ledger.ResetRule.UNKNOWN
    usage_url: str | None = None
    source: str = "vendor_api"
    confidence: ledger.Confidence = ledger.Confidence.UNKNOWN
    last_sync_at: datetime | None = None
    stale: bool = False
    price_version: str = USD_PRICE_VERSION
    balance_split_note: str | None = None
    rate_windows: list[ledger.RateWindow] = Field(default_factory=list)
    retry_after_seconds: int | None = Field(default=None, ge=0)
    tier_split_known: bool = True
    aggregate_pool_id: str | None = None


class USDAuthLimits(USDContract):
    auth_mode: ledger.AuthMode
    transport_available: bool = False
    search: USDLimitRecord | None = None
    fetch: USDLimitRecord | None = None
    free_tiers: list[USDTierBalance] = Field(default_factory=list)
    paid_tiers: list[USDTierBalance] = Field(default_factory=list)
    unknown_tiers: list[USDTierBalance] = Field(default_factory=list)
    tier_split_known: bool = True
    aggregate_pool: USDNativePool | None = None
    usd_views: list[USDView] = Field(default_factory=list)
    rate_progress: list[ledger.RateProgressView] = Field(default_factory=list)
    grants: USDGrantsSummary | None = None
    detail: USDLimitDetail | None = None


class USDProviderLimits(USDContract):
    provider: str
    active_auth_mode: ledger.AuthMode
    auths: list[USDAuthLimits] = Field(default_factory=list)
    documented_keyless_operations: list[ledger.LimitOperation] = Field(default_factory=list)
    version: int = 1
    generated_at: datetime


class USDBudgetPayload(ContractModel):
    """Provider-wide search and fetch ceilings in decimal USD."""

    version: int = Field(default=0, ge=0)
    period: BudgetPeriod = "month"
    search_usd: ledger.ExactDecimal = Decimal("0")
    fetch_usd: ledger.ExactDecimal = Decimal("0")

    def to_ledger(self) -> ledger.CRDGrantPayload:
        """Convert USD to the existing persisted credit unit once on write."""
        return ledger.CRDGrantPayload(
            version=self.version,
            period=self.period,
            search_crd=self.search_usd / ledger.CRD_USD_REFERENCE,
            fetch_crd=self.fetch_usd / ledger.CRD_USD_REFERENCE,
        )
