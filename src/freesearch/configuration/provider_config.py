"""Provider configuration registry: enablement, priorities, and quota estimates.

This module is the provider-neutral runtime configuration surface for the
planned routing and dashboard slices. It holds non-secret configuration only:
provider enablement, deterministic priorities (lower values are preferred),
local free-tier usage estimates, optional reset schedules, and a non-secret
reference to the injected vault key. Provider credentials never appear
here; they are resolved exclusively through the encrypted vault.
"""

import json
from decimal import Decimal
from functools import lru_cache
from typing import Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    field_validator,
    model_validator,
)
from pydantic_settings import BaseSettings, SettingsConfigDict

from freesearch.infrastructure.secrets import ProviderName
from freesearch.models.contracts import QuotaSource, UsageOperation
from freesearch.models.provider_access import (
    ALL_BITS,
    FETCH_BIT,
    GLOBAL_BIT,
    SEARCH_BIT,
    is_operation_enabled,
    support_mask_from_capabilities,
)

# System-owned tool support per canonical provider. The map is independent of
# credentials and health. A changed adapter capability needs one change here.
PROVIDER_SUPPORT_MASKS: dict[ProviderName, int] = {
    ProviderName.BRAVE: support_mask_from_capabilities(search=True, fetch=False),
    ProviderName.EXA: support_mask_from_capabilities(search=True, fetch=True),
    ProviderName.FIRECRAWL: support_mask_from_capabilities(search=True, fetch=True),
    ProviderName.KEENABLE: support_mask_from_capabilities(search=True, fetch=True),
    ProviderName.PARALLEL: support_mask_from_capabilities(search=True, fetch=True),
    ProviderName.TAVILY: support_mask_from_capabilities(search=True, fetch=True),
    ProviderName.TINYFISH: support_mask_from_capabilities(search=True, fetch=True),
    ProviderName.YOU: support_mask_from_capabilities(search=True, fetch=True),
}


class ProviderConfigError(ValueError):
    """Raised when a stored provider record fails strict validation."""


def system_support_mask(provider: ProviderName) -> int:
    """Return the system support mask; an unknown provider supports all tools."""

    return PROVIDER_SUPPORT_MASKS.get(provider, ALL_BITS)


def _legacy_enable_mask(enabled: bool) -> int:
    """Translate one legacy global choice into an enable mask for all bits."""

    return ALL_BITS if enabled else 0


def _check_non_negative(
    estimates: dict[UsageOperation, Decimal],
) -> dict[UsageOperation, Decimal]:
    """Reject negative free-tier estimates shared by both configuration models."""

    if any(units < 0 for units in estimates.values()):
        raise ValueError("free-tier estimates must be non-negative")
    return estimates


def _check_no_floats(estimates: Any) -> Any:
    """Reject float estimate inputs so Decimal conversion is exact.

    JSON numbers arrive as ``float`` (e.g. ``0.5``) and would otherwise be
    silently coerced with precision loss; integers and strings are exact.
    """

    if isinstance(estimates, dict) and any(
        isinstance(units, float) for units in estimates.values()
    ):
        raise ValueError("free-tier estimates must be integers or decimal strings, not floats")
    return estimates


class ProviderConfig(BaseModel):
    """Runtime configuration record for a single provider.

    All values are non-secret. Free-tier figures are local estimates only and
    are exposed through :attr:`quota_source`, which always reports
    ``QuotaSource.ESTIMATED`` rather than a vendor-confirmed value.

    ``enable_mask`` stores the administrator choice. ``support_mask`` stores the
    system tool support. The ``enabled`` property decodes effective global
    access from both masks.
    """

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        frozen=True,
        hide_input_in_errors=True,
    )

    enable_mask: StrictInt = Field(default=ALL_BITS, ge=0, le=ALL_BITS)
    support_mask: StrictInt = Field(default=ALL_BITS, ge=0, le=ALL_BITS)
    priority: StrictInt = Field(default=100, gt=0)
    free_tier_estimates: dict[UsageOperation, Decimal] = Field(
        default_factory=lambda: {operation: Decimal("0") for operation in UsageOperation}
    )
    reset_schedule: str | None = Field(default=None, min_length=1)
    parallel_free_seed_usd: Decimal | None = Field(default=None, ge=0)
    exa_monthly_budget_usd: Decimal | None = Field(default=None, ge=0)
    exa_manual_starting_credits_usd: Decimal | None = Field(default=None, ge=0)
    # Explicit, non-secret Tavily key and overage choices. The usage payload
    # does not identify the key environment, so the operator declares it here
    # instead of the code inferring it from a secret prefix.
    tavily_key_environment: Literal["dev", "prod"] = "dev"
    tavily_paygo_enabled: StrictBool = False

    @model_validator(mode="before")
    @classmethod
    def _decode_legacy_access(cls, data: Any) -> Any:
        """Translate a legacy global Boolean into an enable mask.

        A record that holds both the legacy value and a mask is ambiguous and
        is not accepted. Direct configuration and stored records share this
        decode, so an old global choice keeps its original meaning.
        """

        if not isinstance(data, dict) or "enabled" not in data:
            return data
        if "enable_mask" in data or "support_mask" in data:
            raise ValueError("do not combine enabled with an access mask")
        legacy = data["enabled"]
        if not isinstance(legacy, bool):
            raise ValueError("enabled must be a Boolean")
        translated = dict(data)
        translated.pop("enabled")
        translated["enable_mask"] = _legacy_enable_mask(legacy)
        return translated

    @property
    def enabled(self) -> bool:
        """Effective global access decoded from both masks."""

        return bool(self.enable_mask & self.support_mask & GLOBAL_BIT)

    def allows(self, operation: UsageOperation) -> bool:
        """Return effective access for ``operation`` from both masks."""

        return is_operation_enabled(self.enable_mask, self.support_mask, operation.value)

    @field_validator("free_tier_estimates", mode="before")
    @classmethod
    def _estimates_no_floats(cls, estimates: Any) -> Any:
        return _check_no_floats(estimates)

    @field_validator("free_tier_estimates")
    @classmethod
    def _estimates_must_be_non_negative(
        cls, estimates: dict[UsageOperation, Decimal]
    ) -> dict[UsageOperation, Decimal]:
        return _check_non_negative(estimates)

    @field_validator("parallel_free_seed_usd", mode="before")
    @classmethod
    def _seed_must_be_exact(cls, value: Any) -> Any:
        if value is None:
            return None
        if isinstance(value, (bool, float)):
            raise ValueError("Parallel seed must be an exact Decimal input")
        parsed = Decimal(value)
        if not parsed.is_finite() or parsed < 0:
            raise ValueError("Parallel seed must be finite and non-negative")
        return parsed

    @field_validator("exa_monthly_budget_usd", "exa_manual_starting_credits_usd", mode="before")
    @classmethod
    def _exa_budget_must_be_exact(cls, value: Any) -> Any:
        if value is None:
            return None
        if isinstance(value, (bool, float)):
            raise ValueError("Exa quota amount must be an exact Decimal input")
        parsed = Decimal(value)
        if not parsed.is_finite() or parsed < 0:
            raise ValueError("Exa quota amount must be finite and non-negative")
        return parsed

    @property
    def quota_source(self) -> QuotaSource:
        """Provenance for these figures: local estimates, never authoritative."""

        return QuotaSource.ESTIMATED


class ProviderConfigUpdate(BaseModel):
    """Partial override merged onto a provider's default record.

    ``enable_mask`` is a complete replacement of the administrator choice.
    ``enabled``, ``search_enabled``, and ``fetch_enabled`` each change one
    enable bit. ``support_mask`` is system-owned and absent here.
    """

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        hide_input_in_errors=True,
    )

    enabled: StrictBool | None = None
    enable_mask: StrictInt | None = Field(default=None, ge=0, le=ALL_BITS)
    search_enabled: StrictBool | None = None
    fetch_enabled: StrictBool | None = None
    priority: StrictInt | None = Field(default=None, gt=0)
    free_tier_estimates: dict[UsageOperation, Decimal] | None = None
    reset_schedule: str | None = Field(default=None, min_length=1)
    parallel_free_seed_usd: Decimal | None = Field(default=None, ge=0)
    exa_monthly_budget_usd: Decimal | None = Field(default=None, ge=0)
    exa_manual_starting_credits_usd: Decimal | None = Field(default=None, ge=0)
    tavily_key_environment: Literal["dev", "prod"] | None = None
    tavily_paygo_enabled: StrictBool | None = None

    @model_validator(mode="before")
    @classmethod
    def _check_access_choice(cls, data: Any) -> Any:
        """Reject a null access field and a mixed mask and Boolean choice."""

        if not isinstance(data, dict):
            return data
        access_fields = ("enabled", "enable_mask", "search_enabled", "fetch_enabled")
        for name in access_fields:
            if name in data and data[name] is None:
                raise ValueError(f"{name} must not be null")
        if "enable_mask" in data and any(
            name in data for name in ("enabled", "search_enabled", "fetch_enabled")
        ):
            raise ValueError("do not combine enable_mask with an access Boolean")
        return data

    @field_validator("free_tier_estimates", mode="before")
    @classmethod
    def _estimates_no_floats(cls, estimates: Any) -> Any:
        return _check_no_floats(estimates)

    @field_validator("free_tier_estimates")
    @classmethod
    def _estimates_must_be_non_negative(
        cls, estimates: dict[UsageOperation, Decimal] | None
    ) -> dict[UsageOperation, Decimal] | None:
        if estimates is None:
            return None
        return _check_non_negative(estimates)

    @field_validator("parallel_free_seed_usd", mode="before")
    @classmethod
    def _seed_must_be_exact(cls, value: Any) -> Any:
        if value is None:
            return None
        if isinstance(value, (bool, float)):
            raise ValueError("Parallel seed must be an exact Decimal input")
        parsed = Decimal(value)
        if not parsed.is_finite() or parsed < 0:
            raise ValueError("Parallel seed must be finite and non-negative")
        return parsed

    @field_validator("exa_monthly_budget_usd", "exa_manual_starting_credits_usd", mode="before")
    @classmethod
    def _exa_budget_must_be_exact(cls, value: Any) -> Any:
        if value is None:
            return None
        if isinstance(value, (bool, float)):
            raise ValueError("Exa quota amount must be an exact Decimal input")
        parsed = Decimal(value)
        if not parsed.is_finite() or parsed < 0:
            raise ValueError("Exa quota amount must be finite and non-negative")
        return parsed

    def apply_to(self, base: ProviderConfig) -> ProviderConfig:
        """Return ``base`` with each set field of this override applied.

        Free-tier estimate maps are merged operation-by-operation onto the
        base estimates so a partial override never drops the operations it
        omits. Each access field changes only its own enable bit.
        """

        merged = base.model_dump()
        overrides = self.model_dump(exclude_none=True)
        if "parallel_free_seed_usd" in self.model_fields_set:
            overrides["parallel_free_seed_usd"] = self.parallel_free_seed_usd
        if "exa_monthly_budget_usd" in self.model_fields_set:
            overrides["exa_monthly_budget_usd"] = self.exa_monthly_budget_usd
        if "exa_manual_starting_credits_usd" in self.model_fields_set:
            overrides["exa_manual_starting_credits_usd"] = self.exa_manual_starting_credits_usd
        estimates = overrides.pop("free_tier_estimates", None)
        if estimates:
            merged["free_tier_estimates"].update(estimates)
        for name in ("enable_mask", "enabled", "search_enabled", "fetch_enabled"):
            overrides.pop(name, None)
        merged["enable_mask"] = _merged_enable_mask(base.enable_mask, self)
        merged.update(overrides)
        return ProviderConfig.model_validate(merged)


def _merged_enable_mask(base_mask: int, update: ProviderConfigUpdate) -> int:
    """Return the enable mask after the explicit access fields of ``update``."""

    fields = update.model_fields_set
    if "enable_mask" in fields and update.enable_mask is not None:
        return update.enable_mask
    mask = base_mask
    if "enabled" in fields:
        mask = mask | GLOBAL_BIT if update.enabled else mask & ~GLOBAL_BIT
    if "search_enabled" in fields:
        mask = mask | SEARCH_BIT if update.search_enabled else mask & ~SEARCH_BIT
    if "fetch_enabled" in fields:
        mask = mask | FETCH_BIT if update.fetch_enabled else mask & ~FETCH_BIT
    return mask


class ProviderConfigSettings(BaseSettings):
    """FREESEARCH_-prefixed settings holding the JSON registry override.

    Mirrors :class:`freesearch.config.Settings` conventions: ``FREESEARCH_``
    prefix, ``.env`` support, UTF-8 encoding, and unrelated environment input is
    ignored. Only the single documented JSON registry setting is read here.
    """

    model_config = SettingsConfigDict(
        env_prefix="FREESEARCH_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        enable_decoding=False,
        hide_input_in_errors=True,
    )

    provider_config_overrides: dict[ProviderName, ProviderConfigUpdate] = Field(
        default_factory=dict,
        description=(
            "Optional JSON registry override keyed by canonical provider names, "
            'e.g. {"exa": {"priority": 10, "reset_schedule": "monthly"}}.'
        ),
    )

    @field_validator("provider_config_overrides", mode="before")
    @classmethod
    def _decode_json_registry(cls, value: Any) -> Any:
        """Decode the JSON string from the environment before validation.

        A legacy global Boolean becomes an enable mask here, before the entry
        enters the partial-update model.
        """

        if not isinstance(value, str):
            return value
        decoded = json.loads(value)
        if not isinstance(decoded, dict):
            return decoded
        return {name: _translate_legacy_entry(entry) for name, entry in decoded.items()}


def _translate_legacy_entry(entry: Any) -> Any:
    """Translate one legacy registry entry into the mask schema."""

    if not isinstance(entry, dict) or "enabled" not in entry:
        return entry
    if "enable_mask" in entry or "support_mask" in entry:
        raise ValueError("do not combine enabled with an access mask")
    legacy = entry["enabled"]
    if not isinstance(legacy, bool):
        raise ValueError("enabled must be a Boolean")
    translated = dict(entry)
    translated.pop("enabled")
    translated["enable_mask"] = _legacy_enable_mask(legacy)
    return translated


@lru_cache(maxsize=1)
def _provider_registry() -> dict[ProviderName, ProviderConfig]:
    """Build the merged process-wide registry once.

    Records are frozen, so the cached mapping is safe to share with the
    isolated copies returned by :func:`get_provider_configs`.
    """

    registry: dict[ProviderName, ProviderConfig] = {
        name: ProviderConfig(support_mask=system_support_mask(name)) for name in ProviderName
    }
    for name, update in ProviderConfigSettings().provider_config_overrides.items():
        registry[name] = update.apply_to(registry[name])
    return registry


def get_provider_configs() -> dict[ProviderName, ProviderConfig]:
    """Return an isolated mapping of the process-wide provider configuration.

    Every :class:`ProviderName` is present by default; JSON overrides from the
    ``FREESEARCH_PROVIDER_CONFIG_OVERRIDES`` setting are merged on top. Records
    are deep copies of the cached canonical registry, so callers cannot corrupt
    later reads through either the mapping or nested fields. Call
    ``get_provider_configs.cache_clear()`` to reset the cached registry between
    tests.
    """

    return {name: record.model_copy(deep=True) for name, record in _provider_registry().items()}


# Public alias so tests and callers can reset the cached registry.
get_provider_configs.cache_clear = _provider_registry.cache_clear  # type: ignore[attr-defined]
