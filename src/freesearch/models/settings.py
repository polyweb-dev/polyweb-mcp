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
from uuid import UUID

from pydantic import ConfigDict, Field, field_validator, model_validator

from freesearch.models.contracts import ContractModel, CostPreset, FallbackPolicy
from freesearch.models.projects import (
    TRACE_DETAIL_CONSTRAINT_ORDER,
    TRACE_REDACTION_CONSTRAINT_ORDER,
    ExecutionSettings,
    ProjectSettingsDocument,
    ProjectTracePolicy,
    RoutingSettings,
    SettingsProvenance,
    SettingsResolution,
    TraceDetailPolicy,
    TraceRedactionPolicy,
    TraceSettings,
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
    constraint_order: tuple[str, ...] | None = None
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
        field_id="trace.sampling_rate",
        section="trace",
        attribute="sampling_rate",
        policy=SettingsFieldPolicy.PROJECT_OVERRIDE,
        kind=SettingsFieldKind.NUMBER,
        default=1.0,
        minimum=0.0,
        maximum=1.0,
        description=(
            "Fraction of this project's new traces persisted. Sampling never "
            "affects mandatory security audit events."
        ),
    ),
    SettingsFieldSpec(
        field_id="trace.detail",
        section="trace",
        attribute="detail",
        policy=SettingsFieldPolicy.SYSTEM_CONSTRAINED,
        kind=SettingsFieldKind.ENUM,
        default=TraceDetailPolicy.METADATA,
        constraint_order=TRACE_DETAIL_CONSTRAINT_ORDER,
        description=(
            "Payload detail for new traces. Metadata-only is the default; the "
            "system value is the most permissive detail allowed, and a project "
            "may choose stricter."
        ),
    ),
    SettingsFieldSpec(
        field_id="trace.payload_redaction",
        section="trace",
        attribute="payload_redaction",
        policy=SettingsFieldPolicy.SYSTEM_CONSTRAINED,
        kind=SettingsFieldKind.ENUM,
        default=TraceRedactionPolicy.STANDARD,
        constraint_order=TRACE_REDACTION_CONSTRAINT_ORDER,
        description=(
            "Payload redaction for new traces. The system value is the loosest "
            "redaction allowed; a project may choose stricter."
        ),
    ),
    SettingsFieldSpec(
        field_id="trace.retention_days",
        section="trace",
        attribute="retention_days",
        policy=SettingsFieldPolicy.SYSTEM_CONSTRAINED,
        kind=SettingsFieldKind.INTEGER,
        default=30,
        minimum=1,
        maximum=365,
        safety_limit_attribute="max_trace_retention_days",
        description="Retention window applied to this project's traces, capped by the system.",
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
    SettingsFieldSpec(
        field_id="system.max_trace_retention_days",
        section="safety_limits",
        attribute="max_trace_retention_days",
        policy=SettingsFieldPolicy.SYSTEM_ONLY,
        kind=SettingsFieldKind.INTEGER,
        default=365,
        minimum=1,
        maximum=365,
        description="System ceiling for a project's trace retention window.",
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


class SystemTraceDefaults(ContractModel):
    """Non-null system trace policy.

    ``detail`` is the most permissive detail the deployment allows and
    ``payload_redaction`` is the loosest redaction it allows. Capture is
    metadata-only until an operator stores ``detail=full`` in the system
    settings document: a deployment opts into request/response payload
    explicitly, and a fresh database never captures payload.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    sampling_rate: float = Field(default=1.0, ge=0.0, le=1.0)
    detail: TraceDetailPolicy = TraceDetailPolicy.METADATA
    payload_redaction: TraceRedactionPolicy = TraceRedactionPolicy.STANDARD
    retention_days: int = Field(default=30, ge=1, le=365)


class SystemSafetyLimits(ContractModel):
    """System-owned ceilings that win after project override resolution."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    max_timeout_seconds: float = Field(default=300.0, ge=1.0, le=300)
    max_fanout_concurrency: int = Field(default=20, ge=1, le=20)
    max_trace_retention_days: int = Field(default=365, ge=1, le=365)


class SystemSettingsPayload(ContractModel):
    """Validated system defaults plus their safety ceilings."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    routing: SystemRoutingDefaults = Field(default_factory=SystemRoutingDefaults)
    execution: SystemExecutionDefaults = Field(default_factory=SystemExecutionDefaults)
    trace: SystemTraceDefaults = Field(default_factory=SystemTraceDefaults)
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
        if self.trace.retention_days > self.safety_limits.max_trace_retention_days:
            raise ValueError(
                "system trace retention_days must not exceed safety_limits.max_trace_retention_days"
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
    trace: TraceSettings | None = None

    @model_validator(mode="after")
    def _requires_a_section(self) -> ProjectSettingsUpdate:
        if not ({"routing", "execution", "trace"} & self.model_fields_set):
            raise ValueError("a project settings update must name routing, execution or trace")
        return self


class SettingsCopyMode(StrEnum):
    """How a settings copy treats values the source project inherits."""

    #: Copy only overrides the source project explicitly set. The default.
    OVERRIDES_ONLY = "overrides_only"
    #: Pin the source project's effective values as explicit target overrides.
    EFFECTIVE_SNAPSHOT = "effective_snapshot"


#: Rejection code: the field is installation-owned and can never be copied.
COPY_FIELD_SYSTEM_ONLY: Final[str] = "SYSTEM_ONLY"
#: Rejection code: overrides-only mode found no source override for the field.
COPY_FIELD_NOT_OVERRIDDEN: Final[str] = "NOT_OVERRIDDEN"
#: Rejection code: the source binding names a credential owned by another project.
COPY_CREDENTIAL_PRIVATE: Final[str] = "PRIVATE_CREDENTIAL"
#: Rejection code: the target project has no grant for the system credential.
COPY_CREDENTIAL_NOT_GRANTED: Final[str] = "CREDENTIAL_NOT_GRANTED"
#: Rejection code: the source binding's credential is no longer active.
COPY_CREDENTIAL_UNAVAILABLE: Final[str] = "CREDENTIAL_UNAVAILABLE"
#: Rejection code: the target already uses the same route label for the credential.
COPY_BINDING_ROUTE_CONFLICT: Final[str] = "BINDING_ROUTE_CONFLICT"
#: Rejection code: a binding reference is not available to the target.
COPY_BINDING_UNAVAILABLE: Final[str] = "BINDING_UNAVAILABLE"


class SettingsCopyRequest(ContractModel):
    """One revision-bound settings copy against an explicit source project.

    The three expected revisions are the dry-run binding: a preview returns
    them, and applying that preview must echo exactly those values. Any system,
    source, or target change in between produces a conflict instead of silently
    copying a stale plan.

    Provider binding references are copied only when named explicitly in
    ``binding_versions`` (binding id -> the version the preview showed); an
    omitted or empty mapping copies no binding. A binding changed since the
    preview, or one that is no longer eligible for the target, is a conflict or
    a rejection rather than a silent copy.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    source_project_id: UUID
    expected_source_revision: int = Field(ge=0)
    expected_target_revision: int = Field(ge=0)
    expected_system_revision: int = Field(ge=0)
    mode: SettingsCopyMode = SettingsCopyMode.OVERRIDES_ONLY
    fields: tuple[str, ...] | None = None
    binding_versions: dict[UUID, int] = Field(default_factory=dict)

    @field_validator("fields")
    @classmethod
    def _unique_fields(cls, value: tuple[str, ...] | None) -> tuple[str, ...] | None:
        if value is not None and not value:
            raise ValueError("copy fields must not be empty")
        if value is not None and len(set(value)) != len(value):
            raise ValueError("copy fields must not repeat")
        return value

    @field_validator("binding_versions")
    @classmethod
    def _positive_binding_versions(cls, value: dict[UUID, int]) -> dict[UUID, int]:
        if any(version < 1 for version in value.values()):
            raise ValueError("binding versions must be positive")
        return value


class SettingsCopyField(ContractModel):
    """One field the copy plan writes, with the source value's provenance."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    field_id: str
    section: str
    attribute: str
    provenance: SettingsProvenance
    value: Any
    changed: bool
    constraint_applied: bool = False


class SettingsCopyRejection(ContractModel):
    """One field or binding reference the copy plan refuses to write.

    ``field_id`` is a catalog field id, or ``binding:<binding uuid>`` for an
    ineligible source provider binding reference.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    field_id: str
    reason: str


class SettingsCopyBinding(ContractModel):
    """One source binding reference, its target eligibility, and its selection."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    binding_id: UUID
    credential_id: UUID
    route_label: str
    version: int = Field(ge=1)
    selected: bool
    eligible: bool
    rejection: str | None = None


class SettingsCopyPlan(ContractModel):
    """A dry-run plan: exactly what apply would write plus the visible snapshot.

    ``overrides`` is the planned field-override patch applied to the target;
    fields outside the plan keep the target's existing overrides.
    ``effective_snapshot`` is the explicit effective view the preview showed,
    keyed by catalog field id, so a client never has to recompute inheritance.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    source_project_id: UUID
    target_project_id: UUID
    mode: SettingsCopyMode
    source_revision: int
    target_revision: int
    system_revision: int
    overrides: dict[str, Any]
    effective_snapshot: dict[str, Any]
    fields: list[SettingsCopyField]
    rejected: list[SettingsCopyRejection]
    bindings: list[SettingsCopyBinding]


class SettingsCopyPreview(SettingsCopyPlan):
    """Preview response: the plan plus the target view it would produce."""

    target: SettingsResolution


class SettingsCopyResult(SettingsCopyPlan):
    """Apply response: the applied plan, the new target view, and its audit row.

    ``target_revision`` is the revision of the target after the write (the
    value the target resolution reports). The plan's ``overrides`` are exactly
    what was written.
    """

    target: SettingsResolution
    bindings_copied: list[UUID] = Field(default_factory=list)
    audit_event_id: UUID


def _constrained_enum(
    system_value: TraceDetailPolicy | TraceRedactionPolicy,
    override: TraceDetailPolicy | TraceRedactionPolicy | None,
    order: tuple[str, ...],
) -> tuple[TraceDetailPolicy | TraceRedactionPolicy, bool]:
    """Return the stricter of the system ceiling and the project override."""

    if override is None:
        return system_value, False
    if order.index(override.value) <= order.index(system_value.value):
        return override, False
    return system_value, True


def resolve_trace_policy(
    *, system: SystemSettingsDocument, project: ProjectSettingsDocument
) -> ProjectTracePolicy:
    """Resolve the trace policy of one project from its validated documents.

    This mirrors the catalog rules for the ``trace`` section so offline paths
    (the span exporter and the retention job) reuse the same defaults, project
    overrides, and system ceilings as the settings API.
    """

    sampling_rate = (
        system.trace.sampling_rate
        if project.trace.sampling_rate is None
        else project.trace.sampling_rate
    )
    detail, _detail_constrained = _constrained_enum(
        system.trace.detail, project.trace.detail, TRACE_DETAIL_CONSTRAINT_ORDER
    )
    redaction, _redaction_constrained = _constrained_enum(
        system.trace.payload_redaction,
        project.trace.payload_redaction,
        TRACE_REDACTION_CONSTRAINT_ORDER,
    )
    retention_days = (
        system.trace.retention_days
        if project.trace.retention_days is None
        else project.trace.retention_days
    )
    return ProjectTracePolicy(
        sampling_rate=sampling_rate,
        detail=TraceDetailPolicy(detail),
        payload_redaction=TraceRedactionPolicy(redaction),
        retention_days=min(retention_days, system.safety_limits.max_trace_retention_days),
    )


__all__ = [
    "COPY_BINDING_ROUTE_CONFLICT",
    "COPY_BINDING_UNAVAILABLE",
    "COPY_CREDENTIAL_NOT_GRANTED",
    "COPY_CREDENTIAL_PRIVATE",
    "COPY_CREDENTIAL_UNAVAILABLE",
    "COPY_FIELD_NOT_OVERRIDDEN",
    "COPY_FIELD_SYSTEM_ONLY",
    "SETTINGS_FIELD_CATALOG",
    "SETTINGS_NAMESPACE",
    "SETTINGS_SCHEMA_VERSION",
    "ProjectSettingsUpdate",
    "SettingsCopyBinding",
    "SettingsCopyField",
    "SettingsCopyMode",
    "SettingsCopyPlan",
    "SettingsCopyPreview",
    "SettingsCopyRejection",
    "SettingsCopyRequest",
    "SettingsCopyResult",
    "SettingsFieldKind",
    "SettingsFieldPolicy",
    "SettingsFieldSpec",
    "SystemExecutionDefaults",
    "SystemRoutingDefaults",
    "SystemSafetyLimits",
    "SystemSettingsDocument",
    "SystemSettingsPayload",
    "SystemSettingsUpdate",
    "SystemTraceDefaults",
    "resolve_trace_policy",
    "settings_field",
]
