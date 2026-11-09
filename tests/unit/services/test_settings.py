"""Transport-neutral P03 settings resolution rules."""

from __future__ import annotations

from uuid import uuid4

from polyweb.models.contracts import FallbackPolicy
from polyweb.models.projects import (
    ExecutionSettings,
    ProjectSettingsDocument,
    RoutingSettings,
    SettingsProvenance,
    SettingsScope,
)
from polyweb.models.settings import (
    SystemExecutionDefaults,
    SystemRoutingDefaults,
    SystemSafetyLimits,
    SystemSettingsDocument,
    resolve_trace_policy,
)
from polyweb.persistence.settings import StoredSettings
from polyweb.services.settings import _project_document, _system_document, resolve_settings


def test_legacy_routing_fields_are_stripped_for_versions_one_and_two() -> None:
    for version in (1, 2):
        stored = StoredSettings(
            namespace="projects",
            schema_version=version,
            document={
                "routing": {
                    "preferred_providers": ["exa"],
                    "cost_optimization_preset": "free_first",
                    "fallback_policy": "first_only",
                    "max_attempts": 5,
                }
            },
            revision=1,
        )
        for document in (_project_document(stored), _system_document(stored)[0]):
            assert document.routing.fallback_policy == FallbackPolicy.FIRST_ONLY
            assert document.routing.max_attempts == 5
            assert "preferred_providers" not in document.routing.model_dump()
            assert "cost_optimization_preset" not in document.routing.model_dump()


def test_resolution_records_defaults_overrides_false_zero_and_constraints() -> None:
    """Resolution applies defaults, then overrides, then safety ceilings."""

    project_id = uuid4()
    system = SystemSettingsDocument(
        routing=SystemRoutingDefaults(
            max_attempts=4,
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
        "routing.max_attempts": 3,
        "execution.cache_enabled": True,
        "execution.default_timeout_seconds": 30.0,
        "execution.max_fanout_concurrency": 5,
        "execution.cache_ttl_seconds": 300,
        "trace.detail": "full",
        "trace.retention_days": None,
        "system.max_timeout_seconds": 300.0,
        "system.max_fanout_concurrency": 20,
        "system.max_trace_retention_days": 365,
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


def test_version_one_trace_documents_upgrade_without_old_controls() -> None:
    system_stored = StoredSettings(
        namespace="projects",
        schema_version=1,
        revision=4,
        document={
            "trace": {
                "detail": "full",
                "sampling_rate": 0,
                "payload_redaction": "strict",
                "retention_days": 30,
            }
        },
    )
    project_stored = StoredSettings(
        namespace="projects",
        schema_version=1,
        revision=3,
        document={"trace": {"sampling_rate": 0, "payload_redaction": "strict"}},
    )
    system, _ = _system_document(system_stored)
    project = _project_document(project_stored)
    result = resolve_settings(
        system=system,
        system_revision=4,
        project=project,
        project_revision=3,
        project_id=uuid4(),
    )
    assert result.effective_settings["trace.detail"] == "full"
    assert result.effective_settings["trace.retention_days"] is None
    assert "trace.sampling_rate" not in result.fields
    assert "trace.payload_redaction" not in result.fields
    assert system_stored.document["trace"]["sampling_rate"] == 0
    default_system, _ = _system_document(
        StoredSettings(
            namespace="projects",
            schema_version=1,
            revision=1,
            document={"trace": {"sampling_rate": 0, "payload_redaction": "strict"}},
        )
    )
    assert default_system.trace.detail.value == "full"

    explicit = _project_document(
        StoredSettings(
            namespace="projects",
            schema_version=1,
            revision=3,
            document={"trace": {"retention_days": 45, "payload_redaction": "strict"}},
        )
    )
    assert explicit.trace.retention_days == 45


def test_legacy_system_metadata_default_upgrades_but_project_override_survives() -> None:
    legacy = SystemSettingsDocument().model_dump(mode="json", exclude={"revision"})
    legacy["trace"] = {
        "detail": "metadata",
        "sampling_rate": 1.0,
        "payload_redaction": "standard",
        "retention_days": 30,
    }
    system, revision = _system_document(
        StoredSettings(namespace="projects", schema_version=1, revision=4, document=legacy)
    )
    inherited = _project_document(None)
    explicit = _project_document(
        StoredSettings(
            namespace="projects",
            schema_version=1,
            revision=2,
            document={"trace": {"detail": "metadata"}},
        )
    )
    for project, expected in ((inherited, "full"), (explicit, "metadata")):
        resolution = resolve_settings(
            system=system,
            system_revision=revision,
            project=project,
            project_revision=project.revision,
            project_id=uuid4(),
        )
        assert resolution.effective_settings["trace.detail"] == expected
        assert resolve_trace_policy(system=system, project=project).detail == expected

    current, _ = _system_document(
        StoredSettings(
            namespace="projects",
            schema_version=3,
            revision=5,
            document={"trace": {"detail": "metadata"}},
        )
    )
    assert resolve_trace_policy(system=current, project=inherited).detail == "metadata"
