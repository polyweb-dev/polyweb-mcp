"""Transport-neutral P03 settings resolution rules."""

from __future__ import annotations

from uuid import uuid4

from freesearch.models.contracts import CostPreset, FallbackPolicy
from freesearch.models.projects import (
    ExecutionSettings,
    ProjectSettingsDocument,
    RoutingSettings,
    SettingsProvenance,
    SettingsScope,
)
from freesearch.models.settings import (
    SystemExecutionDefaults,
    SystemRoutingDefaults,
    SystemSafetyLimits,
    SystemSettingsDocument,
)
from freesearch.services.settings import resolve_settings


def test_resolution_records_defaults_overrides_false_zero_and_constraints() -> None:
    """Resolution applies defaults, then overrides, then safety ceilings."""

    project_id = uuid4()
    system = SystemSettingsDocument(
        routing=SystemRoutingDefaults(
            max_attempts=4,
            preferred_providers=("exa", "tavily"),
        ),
        execution=SystemExecutionDefaults(
            cache_enabled=True,
            default_timeout_seconds=50.0,
            max_fanout_concurrency=5,
            cache_ttl_seconds=60,
        ),
        safety_limits=SystemSafetyLimits(
            max_timeout_seconds=60.0,
            max_fanout_concurrency=6,
        ),
        revision=2,
    )
    project = ProjectSettingsDocument(
        routing=RoutingSettings(
            fallback_policy=FallbackPolicy.FIRST_ONLY,
            max_attempts=5,
            preferred_providers=(),
        ),
        execution=ExecutionSettings(
            cache_enabled=False,
            default_timeout_seconds=120.0,
            max_fanout_concurrency=15,
            cache_ttl_seconds=0,
        ),
        revision=3,
    )

    resolution = resolve_settings(
        system=system,
        system_revision=2,
        project=project,
        project_revision=3,
        project_id=project_id,
    )

    assert resolution.system_revision == 2
    assert resolution.project_revision == 3
    assert resolution.project_id == project_id
    assert resolution.provenance_by_field["routing.fallback_policy"] is (
        SettingsProvenance.PROJECT_OVERRIDE
    )
    assert resolution.provenance_by_field["routing.cost_optimization_preset"] is (
        SettingsProvenance.SYSTEM_DEFAULT
    )
    assert resolution.provenance_by_field["execution.cache_enabled"] is (
        SettingsProvenance.PROJECT_OVERRIDE
    )
    assert resolution.provenance_by_field["execution.default_timeout_seconds"] is (
        SettingsProvenance.SYSTEM_CONSTRAINED
    )
    assert resolution.provenance_by_field["execution.max_fanout_concurrency"] is (
        SettingsProvenance.SYSTEM_CONSTRAINED
    )

    assert resolution.effective_settings["routing.fallback_policy"] == (
        FallbackPolicy.FIRST_ONLY.value
    )
    assert resolution.effective_settings["routing.cost_optimization_preset"] == (
        CostPreset.BALANCED.value
    )
    assert resolution.effective_settings["routing.preferred_providers"] == []
    assert resolution.effective_settings["execution.cache_enabled"] is False
    assert resolution.effective_settings["execution.cache_ttl_seconds"] == 0
    assert resolution.effective_settings["execution.default_timeout_seconds"] == 60.0
    assert resolution.effective_settings["execution.max_fanout_concurrency"] == 6

    timeout = resolution.fields["execution.default_timeout_seconds"]
    assert timeout.system_default == 50.0
    assert timeout.project_override == 120.0
    assert timeout.system_safety_limit == 60.0
    assert timeout.constraint_applied is True
    assert timeout.source_scope is SettingsScope.SYSTEM
    assert timeout.override_allowed is True
    assert timeout.is_null is False

    fanout = resolution.fields["execution.max_fanout_concurrency"]
    assert fanout.system_default == 5
    assert fanout.project_override == 15
    assert fanout.system_safety_limit == 6
    assert fanout.constraint_applied is True

    system_only = resolution.fields["system.max_timeout_seconds"]
    assert system_only.effective_value == 60.0
    assert system_only.override_allowed is False
    assert system_only.provenance is SettingsProvenance.SYSTEM_DEFAULT

    assert resolution.overrides == {
        "routing.fallback_policy": FallbackPolicy.FIRST_ONLY.value,
        "routing.max_attempts": 5,
        "routing.preferred_providers": [],
        "execution.cache_enabled": False,
        "execution.default_timeout_seconds": 120.0,
        "execution.max_fanout_concurrency": 15,
        "execution.cache_ttl_seconds": 0,
    }


def test_resolution_without_stored_documents_uses_catalog_defaults() -> None:
    """Revision zero means the documented catalog defaults are effective."""

    resolution = resolve_settings(
        system=SystemSettingsDocument(revision=0),
        system_revision=0,
        project=ProjectSettingsDocument(),
        project_revision=0,
        project_id=uuid4(),
    )

    assert resolution.system_revision == 0
    assert resolution.project_revision == 0
    assert resolution.effective_settings == {
        "routing.fallback_policy": FallbackPolicy.CHAINED.value,
        "routing.cost_optimization_preset": CostPreset.BALANCED.value,
        "routing.max_attempts": 3,
        "routing.preferred_providers": [],
        "execution.cache_enabled": True,
        "execution.default_timeout_seconds": 30.0,
        "execution.max_fanout_concurrency": 5,
        "execution.cache_ttl_seconds": 300,
        "system.max_timeout_seconds": 300.0,
        "system.max_fanout_concurrency": 20,
    }
    assert set(resolution.provenance_by_field.values()) == {SettingsProvenance.SYSTEM_DEFAULT}
    assert all(field.constraint_applied is False for field in resolution.fields.values())
    assert all(
        field.override_allowed is False
        for field in resolution.fields.values()
        if field.field_name.startswith("system.")
    )
    assert resolution.overrides == {}


def test_project_override_resolves_against_catalog_when_no_system_row_exists() -> None:
    """A project override works before any system settings document is written."""

    resolution = resolve_settings(
        system=SystemSettingsDocument(revision=0),
        system_revision=0,
        project=ProjectSettingsDocument(
            execution=ExecutionSettings(cache_enabled=False),
            revision=1,
        ),
        project_revision=1,
        project_id=uuid4(),
    )

    assert resolution.system_revision == 0
    assert resolution.project_revision == 1
    assert resolution.effective_settings["execution.cache_enabled"] is False
    assert resolution.effective_settings["execution.default_timeout_seconds"] == 30.0
    assert resolution.effective_settings["routing.max_attempts"] == 3
    assert resolution.provenance_by_field["execution.cache_enabled"] is (
        SettingsProvenance.PROJECT_OVERRIDE
    )
    assert resolution.provenance_by_field["routing.max_attempts"] is (
        SettingsProvenance.SYSTEM_DEFAULT
    )
    assert resolution.overrides == {"execution.cache_enabled": False}
