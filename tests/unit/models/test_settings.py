"""Typed P03 settings catalog and write-contract validation."""

from __future__ import annotations

from uuid import uuid4

import pytest
from pydantic import ValidationError

from freesearch.models.contracts import FallbackPolicy
from freesearch.models.projects import (
    TRACE_DETAIL_CONSTRAINT_ORDER,
    TRACE_REDACTION_CONSTRAINT_ORDER,
    ExecutionSettings,
    ProjectSettingsDocument,
    RoutingSettings,
    TraceDetailPolicy,
    TraceRedactionPolicy,
    TraceSettings,
)
from freesearch.models.settings import (
    SETTINGS_FIELD_CATALOG,
    SETTINGS_NAMESPACE,
    SETTINGS_SCHEMA_VERSION,
    ProjectSettingsUpdate,
    SettingsCopyMode,
    SettingsCopyRequest,
    SettingsFieldPolicy,
    SystemExecutionDefaults,
    SystemSafetyLimits,
    SystemSettingsDocument,
    SystemSettingsPayload,
    SystemTraceDefaults,
    resolve_trace_policy,
)


def test_catalog_publishes_consistent_defaults_and_resolution_rules() -> None:
    """Every catalog field is unique, classified, and backed by the system document."""

    field_ids = [spec.field_id for spec in SETTINGS_FIELD_CATALOG]
    assert len(field_ids) == len(set(field_ids))
    assert SETTINGS_NAMESPACE == "projects"
    assert SETTINGS_SCHEMA_VERSION == 1

    system = SystemSettingsDocument(revision=0)
    policies = {spec.field_id: spec.policy for spec in SETTINGS_FIELD_CATALOG}
    assert {
        field_id
        for field_id, policy in policies.items()
        if policy is SettingsFieldPolicy.SYSTEM_ONLY
    } == {
        "system.max_timeout_seconds",
        "system.max_fanout_concurrency",
        "system.max_trace_retention_days",
    }
    assert {
        field_id
        for field_id, policy in policies.items()
        if policy is SettingsFieldPolicy.SYSTEM_CONSTRAINED
    } == {
        "execution.default_timeout_seconds",
        "execution.max_fanout_concurrency",
        "trace.detail",
        "trace.payload_redaction",
        "trace.retention_days",
    }
    assert policies["routing.fallback_policy"] is SettingsFieldPolicy.PROJECT_OVERRIDE
    assert policies["routing.preferred_providers"] is SettingsFieldPolicy.PROJECT_OVERRIDE
    assert policies["execution.cache_enabled"] is SettingsFieldPolicy.PROJECT_OVERRIDE
    assert policies["execution.default_timeout_seconds"] is SettingsFieldPolicy.SYSTEM_CONSTRAINED
    assert policies["execution.max_fanout_concurrency"] is SettingsFieldPolicy.SYSTEM_CONSTRAINED
    assert policies["system.max_timeout_seconds"] is SettingsFieldPolicy.SYSTEM_ONLY
    assert policies["system.max_fanout_concurrency"] is SettingsFieldPolicy.SYSTEM_ONLY

    for spec in SETTINGS_FIELD_CATALOG:
        default = getattr(getattr(system, spec.section), spec.attribute)
        assert default == spec.default, spec.field_id
        if spec.safety_limit_attribute is not None:
            assert getattr(system.safety_limits, spec.safety_limit_attribute) is not None


def test_project_update_distinguishes_omission_null_false_and_zero() -> None:
    """The request contract preserves omission, explicit null, false, and zero."""

    omitted = ProjectSettingsUpdate(
        expected_revision=0,
        execution=ExecutionSettings(cache_ttl_seconds=0),
    )
    assert "routing" not in omitted.model_fields_set
    assert omitted.execution is not None
    assert omitted.execution.model_fields_set == {"cache_ttl_seconds"}
    assert omitted.execution.cache_ttl_seconds == 0
    assert omitted.execution.cache_enabled is None

    explicit_false = ProjectSettingsUpdate(
        expected_revision=0,
        execution=ExecutionSettings(cache_enabled=False),
    )
    assert explicit_false.execution is not None
    assert explicit_false.execution.model_fields_set == {"cache_enabled"}
    assert explicit_false.execution.cache_enabled is False

    reset_field = ProjectSettingsUpdate(
        expected_revision=0,
        execution=ExecutionSettings(cache_enabled=None),
    )
    assert reset_field.execution is not None
    assert reset_field.execution.model_fields_set == {"cache_enabled"}
    assert reset_field.execution.cache_enabled is None

    reset_section = ProjectSettingsUpdate(expected_revision=0, routing=None)
    assert "routing" in reset_section.model_fields_set
    assert reset_section.routing is None

    empty_list = ProjectSettingsUpdate(
        expected_revision=0,
        routing=RoutingSettings(preferred_providers=()),
    )
    assert empty_list.routing is not None
    assert empty_list.routing.model_fields_set == {"preferred_providers"}
    assert empty_list.routing.preferred_providers == ()


def test_project_update_requires_a_section_and_known_fields() -> None:
    """A project write must name an editable section and cannot smuggle fields."""

    with pytest.raises(ValidationError, match="must name routing, execution or trace"):
        ProjectSettingsUpdate(expected_revision=0)
    with pytest.raises(ValidationError):
        ProjectSettingsUpdate.model_validate({"expected_revision": 0, "project_id": "other"})
    with pytest.raises(ValidationError):
        ProjectSettingsUpdate(expected_revision=0, routing=RoutingSettings(max_attempts=11))
    with pytest.raises(ValidationError):
        ProjectSettingsUpdate(
            expected_revision=0,
            routing=RoutingSettings(preferred_providers=("EXA",)),
        )
    with pytest.raises(ValidationError):
        ProjectSettingsUpdate(
            expected_revision=-1,
            routing=RoutingSettings(fallback_policy=FallbackPolicy.FIRST_ONLY),
        )


def test_system_payload_rejects_defaults_above_their_safety_limits() -> None:
    """A system default that already violates its ceiling is invalid."""

    with pytest.raises(ValidationError, match="default_timeout_seconds"):
        SystemSettingsPayload(
            execution=SystemExecutionDefaults(
                default_timeout_seconds=90.0,
                max_fanout_concurrency=5,
            ),
            safety_limits=SystemSafetyLimits(
                max_timeout_seconds=60.0,
                max_fanout_concurrency=6,
            ),
        )
    with pytest.raises(ValidationError, match="max_fanout_concurrency"):
        SystemSettingsPayload(
            execution=SystemExecutionDefaults(
                default_timeout_seconds=30.0,
                max_fanout_concurrency=7,
            ),
            safety_limits=SystemSafetyLimits(
                max_timeout_seconds=60.0,
                max_fanout_concurrency=6,
            ),
        )


def test_timeout_static_minimum_is_enforced_everywhere() -> None:
    """The catalog's one-second minimum must bound defaults, overrides, and ceilings."""

    with pytest.raises(ValidationError):
        ExecutionSettings(default_timeout_seconds=0.5)
    with pytest.raises(ValidationError):
        SystemExecutionDefaults(default_timeout_seconds=0.5)
    with pytest.raises(ValidationError):
        SystemSafetyLimits(max_timeout_seconds=0.5)


def test_timeout_minimum_boundary_is_exact_and_matches_catalog() -> None:
    """Exactly 1.0 is valid; 0.999 is rejected by every timeout contract."""

    minima = {
        spec.field_id: spec.minimum
        for spec in SETTINGS_FIELD_CATALOG
        if spec.field_id in {"execution.default_timeout_seconds", "system.max_timeout_seconds"}
    }
    assert minima == {
        "execution.default_timeout_seconds": 1.0,
        "system.max_timeout_seconds": 1.0,
    }

    assert ExecutionSettings(default_timeout_seconds=1.0).default_timeout_seconds == 1.0
    with pytest.raises(ValidationError):
        ExecutionSettings(default_timeout_seconds=0.999)

    assert SystemExecutionDefaults(default_timeout_seconds=1.0).default_timeout_seconds == 1.0
    with pytest.raises(ValidationError):
        SystemExecutionDefaults(default_timeout_seconds=0.999)

    assert SystemSafetyLimits(max_timeout_seconds=1.0).max_timeout_seconds == 1.0
    with pytest.raises(ValidationError):
        SystemSafetyLimits(max_timeout_seconds=0.999)

    project_update = ProjectSettingsUpdate(
        expected_revision=0,
        execution=ExecutionSettings(default_timeout_seconds=1.0),
    )
    assert project_update.execution is not None
    assert project_update.execution.default_timeout_seconds == 1.0
    with pytest.raises(ValidationError):
        ProjectSettingsUpdate(
            expected_revision=0,
            execution=ExecutionSettings(default_timeout_seconds=0.999),
        )

    system_payload = SystemSettingsPayload(
        execution=SystemExecutionDefaults(default_timeout_seconds=1.0),
        safety_limits=SystemSafetyLimits(max_timeout_seconds=1.0),
    )
    assert system_payload.execution.default_timeout_seconds == 1.0
    assert system_payload.safety_limits.max_timeout_seconds == 1.0


def test_trace_catalog_marks_inheritance_and_system_ceiling_policies() -> None:
    """Trace fields expose their override policy, bounds, and ceiling rules."""

    by_id = {spec.field_id: spec for spec in SETTINGS_FIELD_CATALOG}
    assert by_id["trace.sampling_rate"].policy is SettingsFieldPolicy.PROJECT_OVERRIDE
    assert by_id["trace.detail"].policy is SettingsFieldPolicy.SYSTEM_CONSTRAINED
    assert by_id["trace.payload_redaction"].policy is SettingsFieldPolicy.SYSTEM_CONSTRAINED
    assert by_id["trace.retention_days"].policy is SettingsFieldPolicy.SYSTEM_CONSTRAINED
    assert by_id["trace.retention_days"].safety_limit_attribute == "max_trace_retention_days"
    assert by_id["trace.sampling_rate"].minimum == 0.0
    assert by_id["trace.sampling_rate"].maximum == 1.0
    assert by_id["trace.retention_days"].minimum == 1
    assert by_id["trace.retention_days"].maximum == 365
    assert by_id["trace.detail"].constraint_order == TRACE_DETAIL_CONSTRAINT_ORDER
    assert by_id["trace.payload_redaction"].constraint_order == TRACE_REDACTION_CONSTRAINT_ORDER

    system = SystemSettingsDocument(revision=0)
    assert by_id["trace.sampling_rate"].default == system.trace.sampling_rate
    assert by_id["trace.detail"].default == system.trace.detail
    assert by_id["trace.payload_redaction"].default == system.trace.payload_redaction
    assert by_id["trace.retention_days"].default == system.trace.retention_days
    assert by_id["system.max_trace_retention_days"].policy is SettingsFieldPolicy.SYSTEM_ONLY


def test_trace_update_distinguishes_zero_strict_values_from_omission_and_reset() -> None:
    """Explicit zero/strict trace values are real overrides, not inheritance."""

    explicit = ProjectSettingsUpdate(
        expected_revision=0,
        trace=TraceSettings(
            sampling_rate=0.0,
            detail=TraceDetailPolicy.METADATA,
            payload_redaction=TraceRedactionPolicy.STRICT,
            retention_days=7,
        ),
    )
    assert explicit.trace is not None
    assert explicit.trace.sampling_rate == 0.0
    assert explicit.trace.model_fields_set == {
        "sampling_rate",
        "detail",
        "payload_redaction",
        "retention_days",
    }

    reset_section = ProjectSettingsUpdate(trace=None, expected_revision=0)
    assert "trace" in reset_section.model_fields_set
    assert reset_section.trace is None

    reset_field = ProjectSettingsUpdate(
        expected_revision=0,
        trace=TraceSettings(sampling_rate=None),
    )
    assert reset_field.trace is not None
    assert reset_field.trace.model_fields_set == {"sampling_rate"}
    assert reset_field.trace.sampling_rate is None

    with pytest.raises(ValidationError):
        ProjectSettingsUpdate(
            expected_revision=0,
            trace=TraceSettings(sampling_rate=-0.1),
        )
    with pytest.raises(ValidationError):
        ProjectSettingsUpdate(
            expected_revision=0,
            trace=TraceSettings(retention_days=366),
        )
    with pytest.raises(ValidationError):
        SystemSettingsPayload(trace=SystemTraceDefaults(retention_days=400))
    with pytest.raises(ValidationError, match="system trace retention_days"):
        SystemSettingsPayload(
            trace=SystemTraceDefaults(retention_days=60),
            safety_limits=SystemSafetyLimits(max_trace_retention_days=30),
        )


def test_resolve_trace_policy_applies_project_values_with_system_ceilings() -> None:
    """Stricter project trace values win; looser ones fall back to the system."""

    system = SystemSettingsDocument(revision=0)
    inherited = resolve_trace_policy(system=system, project=ProjectSettingsDocument())
    assert inherited.sampling_rate == system.trace.sampling_rate
    assert inherited.detail is TraceDetailPolicy.METADATA
    assert inherited.payload_redaction is TraceRedactionPolicy.STANDARD
    assert inherited.retention_days == system.trace.retention_days
    assert inherited.captures_payload is False

    stricter = resolve_trace_policy(
        system=system,
        project=ProjectSettingsDocument(
            trace=TraceSettings(
                sampling_rate=0.0,
                detail=TraceDetailPolicy.METADATA,
                payload_redaction=TraceRedactionPolicy.STRICT,
                retention_days=7,
            )
        ),
    )
    assert stricter.sampling_rate == 0.0
    assert stricter.detail is TraceDetailPolicy.METADATA
    assert stricter.payload_redaction is TraceRedactionPolicy.STRICT
    assert stricter.retention_days == 7
    assert stricter.captures_payload is False

    stricter_system = SystemSettingsDocument(
        revision=0,
        trace=SystemTraceDefaults(
            detail=TraceDetailPolicy.METADATA,
            payload_redaction=TraceRedactionPolicy.STRICT,
            retention_days=14,
        ),
        safety_limits=SystemSafetyLimits(max_trace_retention_days=14),
    )
    capped = resolve_trace_policy(
        system=stricter_system,
        project=ProjectSettingsDocument(
            trace=TraceSettings(
                sampling_rate=0.5,
                detail=TraceDetailPolicy.FULL,
                payload_redaction=TraceRedactionPolicy.STANDARD,
                retention_days=60,
            )
        ),
    )
    assert capped.sampling_rate == 0.5
    assert capped.detail is TraceDetailPolicy.METADATA
    assert capped.payload_redaction is TraceRedactionPolicy.STRICT
    assert capped.retention_days == 14


def test_copy_request_rejects_repeated_fields() -> None:
    """A copy field list must not repeat the same field id."""

    source = uuid4()
    with pytest.raises(ValidationError, match="must not repeat"):
        SettingsCopyRequest(
            source_project_id=source,
            expected_source_revision=0,
            expected_target_revision=0,
            expected_system_revision=0,
            mode=SettingsCopyMode.OVERRIDES_ONLY,
            fields=("routing.max_attempts", "routing.max_attempts"),
        )
    request = SettingsCopyRequest(
        source_project_id=source,
        expected_source_revision=1,
        expected_target_revision=2,
        expected_system_revision=3,
    )
    assert request.mode is SettingsCopyMode.OVERRIDES_ONLY
    assert request.fields is None
