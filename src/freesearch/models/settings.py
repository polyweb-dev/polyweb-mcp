"""Typed settings catalog and revisioned system/project settings contracts (P03).

The catalog is the single source of truth for:

* each field's documented default,
* its inheritance policy (project override or system constrained),
* its static safety bounds, and
* the system-owned safety ceiling that can win after project resolution.

Project overrides use :class:`freesearch.models.projects.ProjectSettingsDocument`.
``None`` always means "no override exists" at storage level. A write request can
still send an explicit ``null`` to remove a stored override; the service records
that as a reset. Values such as ``False``, ``0``, and the empty list are real
overrides and never collapse into inheritance.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Final

from pydantic import ConfigDict, Field, field_validator, model_validator

from freesearch.models.contracts import ContractModel, CostPreset, FallbackPolicy
from freesearch.models.projects import (
    ExecutionSettings,
    RoutingSettings,
    normalize_preferred_providers,
)

#: Namespace of the typed system/project settings document.
SETTINGS_NAMESPACE: Final[str] = "projects"

#: Version of the typed settings schema stored with every document.
SETTINGS_SCHEMA_VERSION: Final[int] = 1


class SettingsFieldKind(StrEnum):
    """Wire kind of one typed settings field."""

    ENUM = "enum"
    INTEGER = "integer"
    NUMBER = "number"
    BOOLEAN = "boolean"
    STRING_LIST = "string_list"


class SettingsFieldPolicy(StrEnum):
    """Documented inheritance policy for one settings field."""

    #: System-owned value; a project can never override it.
    SYSTEM_ONLY = "system_only"
    #: A project may replace the system default.
    PROJECT_OVERRIDE = "project_override"
    #: A project may supply a value, but the system safety ceiling always wins.
    SYSTEM_CONSTRAINED = "system_constrained"


class SettingsFieldSpec(ContractModel):
    """One typed settings field and its resolution rule."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    field_id: str
    section: str
    attribute: str
    policy: SettingsFieldPolicy
    kind: SettingsFieldKind
    default: Any
    minimum: int | float | None = None
    maximum: int | float | None = None
    max_items: int | None = None
    safety_limit_attribute: str | None = None
    description: str = ""


#: Ordered catalog used by storage validation, resolution, and API responses.
SETTINGS_FIELD_CATALOG: Final[tuple[SettingsFieldSpec, ...]] = (
    SettingsFieldSpec(
        field_id="routing.fallback_policy",
        section="routing",
        attribute="fallback_policy",
        policy=SettingsFieldPolicy.PROJECT_OVERRIDE,
        kind=SettingsFieldKind.ENUM,
        default=FallbackPolicy.CHAINED,
        description="Fallback behaviour after a provider attempt fails.",
    ),
    SettingsFieldSpec(
        field_id="routing.cost_optimization_preset",
        section="routing",
        attribute="cost_optimization_preset",
        policy=SettingsFieldPolicy.PROJECT_OVERRIDE,
        kind=SettingsFieldKind.ENUM,
        default=CostPreset.BALANCED,
        description="Candidate ordering preset for this project.",
    ),
    SettingsFieldSpec(
        field_id="routing.max_attempts",
        section="routing",
        attribute="max_attempts",
        policy=SettingsFieldPolicy.PROJECT_OVERRIDE,
        kind=SettingsFieldKind.INTEGER,
        default=3,
        minimum=1,
        maximum=10,
        description="Bounded provider attempts for one logical request.",
    ),
    SettingsFieldSpec(
        field_id="routing.preferred_providers",
        section="routing",
        attribute="preferred_providers",
        policy=SettingsFieldPolicy.PROJECT_OVERRIDE,
        kind=SettingsFieldKind.STRING_LIST,
        default=(),
        max_items=8,
        description=(
            "Ordered provider preference. A non-empty list replaces the system "
            "preference; an explicit empty list clears it."
        ),
    ),
    SettingsFieldSpec(
        field_id="execution.cache_enabled",
        section="execution",
        attribute="cache_enabled",
        policy=SettingsFieldPolicy.PROJECT_OVERRIDE,
        kind=SettingsFieldKind.BOOLEAN,
        default=True,
        description="Whether this project may reuse cached execution results.",
    ),
    SettingsFieldSpec(
        field_id="execution.default_timeout_seconds",
        section="execution",
        attribute="default_timeout_seconds",
        policy=SettingsFieldPolicy.SYSTEM_CONSTRAINED,
        kind=SettingsFieldKind.NUMBER,
        default=30.0,
        minimum=1.0,
        maximum=300.0,
        safety_limit_attribute="max_timeout_seconds",
        description="Local execution timeout, capped by the system safety ceiling.",
    ),
    SettingsFieldSpec(
        field_id="execution.max_fanout_concurrency",
        section="execution",
        attribute="max_fanout_concurrency",
        policy=SettingsFieldPolicy.SYSTEM_CONSTRAINED,
        kind=SettingsFieldKind.INTEGER,
        default=5,
        minimum=1,
        maximum=20,
        safety_limit_attribute="max_fanout_concurrency",
        description="Fan-out concurrency, capped by the system safety ceiling.",
    ),
    SettingsFieldSpec(
        field_id="execution.cache_ttl_seconds",
        section="execution",
        attribute="cache_ttl_seconds",
        policy=SettingsFieldPolicy.PROJECT_OVERRIDE,
        kind=SettingsFieldKind.INTEGER,
        default=300,
        minimum=0,
        maximum=86400,
        description="Cache lifetime; an explicit zero disables reuse for this project.",
    ),
    SettingsFieldSpec(
        field_id="system.max_timeout_seconds",
        section="safety_limits",
        attribute="max_timeout_seconds",
        policy=SettingsFieldPolicy.SYSTEM_ONLY,
        kind=SettingsFieldKind.NUMBER,
        default=300.0,
        minimum=1.0,
        maximum=300.0,
        description="System ceiling for project execution timeouts; projects cannot override it.",
    ),
    SettingsFieldSpec(
        field_id="system.max_fanout_concurrency",
        section="safety_limits",
        attribute="max_fanout_concurrency",
        policy=SettingsFieldPolicy.SYSTEM_ONLY,
        kind=SettingsFieldKind.INTEGER,
        default=20,
        minimum=1,
        maximum=20,
        description="System ceiling for project fan-out concurrency; projects cannot override it.",
    ),
)

_SETTINGS_FIELDS_BY_ID: Final[dict[str, SettingsFieldSpec]] = {
    spec.field_id: spec for spec in SETTINGS_FIELD_CATALOG
}


def settings_field(field_id: str) -> SettingsFieldSpec:
    """Return one catalog field or raise a caller-facing validation error."""

    spec = _SETTINGS_FIELDS_BY_ID.get(field_id)
    if spec is None:
        raise ValueError(f"unknown settings field {field_id!r}")
    return spec


class SystemRoutingDefaults(ContractModel):
    """Non-null system routing defaults."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    fallback_policy: FallbackPolicy = FallbackPolicy.CHAINED
    cost_optimization_preset: CostPreset = CostPreset.BALANCED
    max_attempts: int = Field(default=3, ge=1, le=10)
    #: System-wide preference order. Projects inherit it unless they override.
    preferred_providers: tuple[str, ...] = ()

    @field_validator("preferred_providers")
    @classmethod
    def _ordered_provider_preferences(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return normalize_preferred_providers(value)


class SystemExecutionDefaults(ContractModel):
    """Non-null system execution defaults."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    cache_enabled: bool = True
    default_timeout_seconds: float = Field(default=30.0, ge=1.0, le=300)
    max_fanout_concurrency: int = Field(default=5, ge=1, le=20)
    cache_ttl_seconds: int = Field(default=300, ge=0, le=86400)


class SystemSafetyLimits(ContractModel):
    """System-owned ceilings that win after project override resolution."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    max_timeout_seconds: float = Field(default=300.0, ge=1.0, le=300)
    max_fanout_concurrency: int = Field(default=20, ge=1, le=20)


class SystemSettingsPayload(ContractModel):
    """Validated system defaults plus their safety ceilings."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    routing: SystemRoutingDefaults = Field(default_factory=SystemRoutingDefaults)
    execution: SystemExecutionDefaults = Field(default_factory=SystemExecutionDefaults)
    safety_limits: SystemSafetyLimits = Field(default_factory=SystemSafetyLimits)

    @model_validator(mode="after")
    def _defaults_fit_safety_limits(self) -> SystemSettingsPayload:
        if self.execution.default_timeout_seconds > self.safety_limits.max_timeout_seconds:
            raise ValueError(
                "system default_timeout_seconds must not exceed safety_limits.max_timeout_seconds"
            )
        if self.execution.max_fanout_concurrency > self.safety_limits.max_fanout_concurrency:
            raise ValueError(
                "system max_fanout_concurrency must not exceed safety_limits.max_fanout_concurrency"
            )
        return self


class SystemSettingsDocument(SystemSettingsPayload):
    """Effective system settings document with its durable revision.

    Revision ``0`` means no system document has been written yet and the
    documented catalog defaults are in force.
    """

    revision: int = Field(default=1, ge=0)


class SystemSettingsUpdate(SystemSettingsPayload):
    """Replacement system settings write with an expected revision."""

    expected_revision: int = Field(ge=0)


class ProjectSettingsUpdate(ContractModel):
    """Bounded project settings write against one expected revision.

    Sections omitted from the request keep their current overrides. An explicit
    ``null`` section resets every override in that section. Within a present
    section, omitted fields keep their current override, an explicit ``null``
    removes one override, and any other value replaces it. Lists replace
    wholesale.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    expected_revision: int = Field(ge=0)
    routing: RoutingSettings | None = None
    execution: ExecutionSettings | None = None

    @model_validator(mode="after")
    def _requires_a_section(self) -> ProjectSettingsUpdate:
        if not ({"routing", "execution"} & self.model_fields_set):
            raise ValueError("a project settings update must name routing or execution")
        return self


__all__ = [
    "SETTINGS_FIELD_CATALOG",
    "SETTINGS_NAMESPACE",
    "SETTINGS_SCHEMA_VERSION",
    "ProjectSettingsUpdate",
    "SettingsFieldKind",
    "SettingsFieldPolicy",
    "SettingsFieldSpec",
    "SystemExecutionDefaults",
    "SystemRoutingDefaults",
    "SystemSafetyLimits",
    "SystemSettingsDocument",
    "SystemSettingsPayload",
    "SystemSettingsUpdate",
    "settings_field",
]
