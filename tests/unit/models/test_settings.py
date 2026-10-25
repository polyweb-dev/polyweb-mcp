"""Typed P03 settings catalog and write-contract validation."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from freesearch.models.contracts import FallbackPolicy
from freesearch.models.projects import ExecutionSettings, RoutingSettings
from freesearch.models.settings import (
    SETTINGS_FIELD_CATALOG,
    SETTINGS_NAMESPACE,
    SETTINGS_SCHEMA_VERSION,
    ProjectSettingsUpdate,
    SettingsFieldPolicy,
    SystemExecutionDefaults,
    SystemSafetyLimits,
    SystemSettingsDocument,
    SystemSettingsPayload,
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
    } == {"system.max_timeout_seconds", "system.max_fanout_concurrency"}
    assert {
        field_id
        for field_id, policy in policies.items()
        if policy is SettingsFieldPolicy.SYSTEM_CONSTRAINED
    } == {
        "execution.default_timeout_seconds",
        "execution.max_fanout_concurrency",
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

    with pytest.raises(ValidationError, match="must name routing or execution"):
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
