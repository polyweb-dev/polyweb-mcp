"""Provider configuration registry: enablement, priorities, and quota estimates.

This module is the provider-neutral runtime configuration surface for the
planned routing and dashboard slices. It holds non-secret configuration only:
provider enablement, deterministic priorities (lower values are preferred),
local free-tier usage estimates, optional reset schedules, and a non-secret
reference to the shared credential resolver. Provider credentials never appear
here; they are resolved exclusively through :mod:`freesearch.secrets`.
"""

import json
from decimal import Decimal
from functools import lru_cache
from typing import Any

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    field_validator,
)
from pydantic_settings import BaseSettings, SettingsConfigDict

from freesearch.configuration.config import get_settings
from freesearch.infrastructure.secrets import (
    KeyringSecretStore,
    ProviderName,
    ProviderSecretResolver,
)
from freesearch.models.contracts import QuotaSource, UsageOperation


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
    """

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        frozen=True,
        hide_input_in_errors=True,
    )

    enabled: StrictBool = True
    priority: StrictInt = Field(default=100, gt=0)
    free_tier_estimates: dict[UsageOperation, Decimal] = Field(
        default_factory=lambda: {operation: Decimal("0") for operation in UsageOperation}
    )
    reset_schedule: str | None = Field(default=None, min_length=1)
    parallel_free_seed_usd: Decimal | None = Field(default=None, ge=0)

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

    @property
    def quota_source(self) -> QuotaSource:
        """Provenance for these figures: local estimates, never authoritative."""

        return QuotaSource.ESTIMATED


class ProviderConfigUpdate(BaseModel):
    """Partial override merged onto a provider's default record."""

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        hide_input_in_errors=True,
    )

    enabled: StrictBool | None = None
    priority: StrictInt | None = Field(default=None, gt=0)
    free_tier_estimates: dict[UsageOperation, Decimal] | None = None
    reset_schedule: str | None = Field(default=None, min_length=1)
    parallel_free_seed_usd: Decimal | None = Field(default=None, ge=0)

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

    def apply_to(self, base: ProviderConfig) -> ProviderConfig:
        """Return ``base`` with each set field of this override applied.

        Free-tier estimate maps are merged operation-by-operation onto the
        base estimates so a partial override never drops the operations it
        omits.
        """

        merged = base.model_dump()
        overrides = self.model_dump(exclude_none=True)
        if "parallel_free_seed_usd" in self.model_fields_set:
            overrides["parallel_free_seed_usd"] = self.parallel_free_seed_usd
        estimates = overrides.pop("free_tier_estimates", None)
        if estimates:
            merged["free_tier_estimates"].update(estimates)
        merged.update(overrides)
        return ProviderConfig.model_validate(merged)


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
        """Decode the JSON string from the environment before validation."""

        return json.loads(value) if isinstance(value, str) else value


@lru_cache(maxsize=1)
def _provider_registry() -> dict[ProviderName, ProviderConfig]:
    """Build the merged process-wide registry once.

    Records are frozen, so the cached mapping is safe to share with the
    isolated copies returned by :func:`get_provider_configs`.
    """

    registry: dict[ProviderName, ProviderConfig] = {name: ProviderConfig() for name in ProviderName}
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


@lru_cache(maxsize=1)
def get_provider_secret_resolver() -> ProviderSecretResolver:
    """Return the process-wide credential resolver for the configured service.

    Credentials are never settings fields or configuration record data; lookup
    flows only through :class:`freesearch.secrets.ProviderSecretResolver`, bound
    to ``Settings.secret_service_name``.
    """

    return ProviderSecretResolver(store=KeyringSecretStore(get_settings().secret_service_name))
