"""P03 service: inheritance, provenance, constraints, revisions, context, cache."""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import textwrap
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import update

from freesearch.models.contracts import FallbackPolicy
from freesearch.models.observability import (
    ActorType,
    TraceOperation,
    TraceOutcome,
    TraceSpanKind,
    TraceSpanRecord,
)
from freesearch.models.project_permissions import ProjectPermission
from freesearch.models.projects import (
    BuiltinRole,
    ExecutionSettings,
    MembershipStatus,
    PermissionAction,
    ProjectContext,
    ProjectCreate,
    ProjectMemberAdd,
    ProjectRead,
    RoutingSettings,
    SettingsProvenance,
    SettingsScope,
    TraceDetailPolicy,
    TraceSettings,
)
from freesearch.models.retention import RetentionRunRequest
from freesearch.models.schema_enums import RetentionDataClass
from freesearch.models.settings import (
    COPY_FIELD_NOT_OVERRIDDEN,
    COPY_FIELD_SYSTEM_ONLY,
    ProjectSettingsUpdate,
    SettingsCopyMode,
    SettingsCopyRequest,
    SystemExecutionDefaults,
    SystemRoutingDefaults,
    SystemSafetyLimits,
    SystemSettingsUpdate,
    SystemTraceDefaults,
)
from freesearch.models.users import UserPrincipal
from freesearch.persistence.audit import AuditRepository
from freesearch.persistence.bindings import StoredBinding
from freesearch.persistence.otel_exporter import write_trace_spans
from freesearch.persistence.projects import (
    AccountRow,
    ProjectMembershipRow,
    ProjectRepository,
)
from freesearch.persistence.scoped import ProjectScopedRepository
from freesearch.persistence.storage import SQLiteRepository
from freesearch.persistence.users import UserRow
from freesearch.services.authorization import (
    AuthorizationDenied,
    ScopedAuthorizationService,
    human_principal,
)
from freesearch.services.control_errors import ResourceInvalid, ResourceNotFound
from freesearch.services.observability import get_project_trace, list_project_traces
from freesearch.services.projects import ProjectService
from freesearch.services.retention import (
    RETENTION_CUTOFF_FUTURE,
    RETENTION_CUTOFF_REQUIRED,
    ProjectRetentionService,
)
from freesearch.services.settings import (
    PROJECT_ARCHIVED,
    SETTINGS_REVISION_CONFLICT,
    SettingsConflict,
    SettingsNotFound,
    SettingsRevisionConflict,
    SettingsService,
    SettingsValidationError,
)
from tests.fixtures.alpha_fixtures import bootstrap_fresh_alpha
from tests.fixtures.auth import create_temp_user, temp_email, temp_principal


async def _create_system_admin(repository: SQLiteRepository) -> UserPrincipal:
    row = await create_temp_user(repository, temp_email("p03-system"), system_admin=True)
    return temp_principal(row)


async def _create_second_project(
    repository: SQLiteRepository,
    *,
    system_actor: UserPrincipal,
    project_admin: UserPrincipal,
) -> ProjectRead:
    return await ProjectService(repository).create_project(
        system_actor,
        ProjectCreate(
            name="Second Settings Project",
            slug="second-settings",
            initial_admin_user_id=project_admin.id,
        ),
    )


@pytest.mark.asyncio
async def test_inheritance_provenance_and_safety_constraints(tmp_path: Path) -> None:
    """System defaults, project overrides, and ceilings resolve with provenance."""

    boot = await bootstrap_fresh_alpha(tmp_path / "p03-inheritance.db")
    try:
        service = SettingsService(boot.repository)
        admin = temp_principal(boot.admin_user)
        project_id = boot.default_project.id

        system0 = await service.get_system_settings(admin)
        assert system0.revision == 0
        assert system0.routing.max_attempts == 3
        assert system0.execution.default_timeout_seconds == 30.0

        inherited = await service.get_project_settings(admin, project_id)
        assert (inherited.system_revision, inherited.project_revision) == (0, 0)
        assert inherited.effective_settings["execution.cache_enabled"] is True
        assert (
            inherited.fields["execution.cache_enabled"].provenance
            is SettingsProvenance.SYSTEM_DEFAULT
        )
        assert inherited.fields["system.max_timeout_seconds"].override_allowed is False
        assert inherited.fields["execution.default_timeout_seconds"].system_safety_limit == 300.0

        system1 = await service.update_system_settings(
            admin,
            SystemSettingsUpdate(
                expected_revision=0,
                routing=SystemRoutingDefaults(
                    max_attempts=4,
                ),
                execution=SystemExecutionDefaults(
                    cache_enabled=True,
                    default_timeout_seconds=50.0,
                    max_fanout_concurrency=5,
                    cache_ttl_seconds=90,
                ),
                safety_limits=SystemSafetyLimits(
                    max_timeout_seconds=60.0,
                    max_fanout_concurrency=6,
                ),
            ),
        )
        assert system1.revision == 1
        after_system = await service.get_project_settings(admin, project_id)
        assert after_system.system_revision == 1
        assert after_system.project_revision == 0
        assert after_system.effective_settings["routing.max_attempts"] == 4
        assert after_system.effective_settings["execution.default_timeout_seconds"] == 50.0

        written = await service.update_project_settings(
            admin,
            project_id,
            ProjectSettingsUpdate(
                expected_revision=0,
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
            ),
        )

        assert written.system_revision == 1
        assert written.project_revision == 1
        assert written.effective_settings["routing.fallback_policy"] == "first_only"
        assert written.effective_settings["routing.max_attempts"] == 5
        assert written.effective_settings["execution.cache_enabled"] is False
        assert written.effective_settings["execution.cache_ttl_seconds"] == 0
        assert written.effective_settings["execution.default_timeout_seconds"] == 60.0
        assert written.effective_settings["execution.max_fanout_concurrency"] == 6

        timeout = written.fields["execution.default_timeout_seconds"]
        assert timeout.provenance is SettingsProvenance.SYSTEM_CONSTRAINED
        assert timeout.constraint_applied is True
        assert timeout.system_default == 50.0
        assert timeout.project_override == 120.0
        assert timeout.system_safety_limit == 60.0
        assert timeout.source_scope is SettingsScope.SYSTEM
        assert timeout.override_allowed is True

        fanout = written.fields["execution.max_fanout_concurrency"]
        assert fanout.provenance is SettingsProvenance.SYSTEM_CONSTRAINED
        assert fanout.constraint_applied is True
        assert fanout.project_override == 15
        assert fanout.system_safety_limit == 6
        assert written.fields["execution.cache_enabled"].provenance is (
            SettingsProvenance.PROJECT_OVERRIDE
        )
        assert written.fields["system.max_timeout_seconds"].override_allowed is False
        assert written.overrides["execution.default_timeout_seconds"] == 120.0
        assert written.overrides["execution.max_fanout_concurrency"] == 15
        assert written.overrides["execution.cache_enabled"] is False
        assert written.overrides["execution.cache_ttl_seconds"] == 0

        system2 = await service.update_system_settings(
            admin,
            SystemSettingsUpdate(
                expected_revision=1,
                routing=SystemRoutingDefaults(
                    max_attempts=6,
                ),
                execution=SystemExecutionDefaults(
                    cache_enabled=True,
                    default_timeout_seconds=40.0,
                    max_fanout_concurrency=4,
                    cache_ttl_seconds=120,
                ),
                safety_limits=SystemSafetyLimits(
                    max_timeout_seconds=70.0,
                    max_fanout_concurrency=8,
                ),
            ),
        )
        assert system2.revision == 2

        after_system_change = await service.get_project_settings(admin, project_id)
        assert after_system_change.system_revision == 2
        assert after_system_change.project_revision == 1
        assert after_system_change.effective_settings["routing.max_attempts"] == 5
        assert after_system_change.effective_settings["execution.cache_enabled"] is False
        assert after_system_change.effective_settings["execution.default_timeout_seconds"] == 70.0
        assert after_system_change.effective_settings["execution.max_fanout_concurrency"] == 8
        assert after_system_change.effective_settings["execution.cache_ttl_seconds"] == 0
        assert after_system_change.fields["execution.default_timeout_seconds"].project_override == (
            120.0
        )
        assert after_system_change.fields["execution.default_timeout_seconds"].system_default == (
            40.0
        )
    finally:
        await boot.repository.close()


@pytest.mark.asyncio
async def test_timeout_minimum_boundary_survives_write_and_read_resolution(tmp_path: Path) -> None:
    """A 1.0-second minimum survives system/project writes and ceiling resolution."""

    boot = await bootstrap_fresh_alpha(tmp_path / "p03-timeout-boundary.db")
    try:
        service = SettingsService(boot.repository)
        admin = temp_principal(boot.admin_user)
        project_id = boot.default_project.id

        system = await service.update_system_settings(
            admin,
            SystemSettingsUpdate(
                expected_revision=0,
                execution=SystemExecutionDefaults(
                    default_timeout_seconds=1.0,
                    max_fanout_concurrency=5,
                ),
                safety_limits=SystemSafetyLimits(
                    max_timeout_seconds=1.0,
                    max_fanout_concurrency=6,
                ),
            ),
        )
        assert system.execution.default_timeout_seconds == 1.0
        assert system.safety_limits.max_timeout_seconds == 1.0

        written = await service.update_project_settings(
            admin,
            project_id,
            ProjectSettingsUpdate(
                expected_revision=0,
                execution=ExecutionSettings(default_timeout_seconds=1.0),
            ),
        )
        assert written.project_revision == 1
        assert written.effective_settings["execution.default_timeout_seconds"] == 1.0
        timeout = written.fields["execution.default_timeout_seconds"]
        assert timeout.provenance is SettingsProvenance.PROJECT_OVERRIDE
        assert timeout.constraint_applied is False
        assert timeout.system_safety_limit == 1.0

        read = await service.get_project_settings(admin, project_id)
        assert read.project_revision == 1
        assert read.effective_settings["execution.default_timeout_seconds"] == 1.0
        assert read.fields["execution.default_timeout_seconds"].project_override == 1.0

        clamped = await service.update_project_settings(
            admin,
            project_id,
            ProjectSettingsUpdate(
                expected_revision=1,
                execution=ExecutionSettings(default_timeout_seconds=2.0),
            ),
        )
        assert clamped.effective_settings["execution.default_timeout_seconds"] == 1.0
        clamped_timeout = clamped.fields["execution.default_timeout_seconds"]
        assert clamped_timeout.provenance is SettingsProvenance.SYSTEM_CONSTRAINED
        assert clamped_timeout.constraint_applied is True

        with pytest.raises(ValidationError):
            ProjectSettingsUpdate(
                expected_revision=2,
                execution=ExecutionSettings(default_timeout_seconds=0.999),
            )
        unchanged = await service.get_project_settings(admin, project_id)
        assert unchanged.project_revision == 2
        assert unchanged.fields["execution.default_timeout_seconds"].project_override == 2.0

        with pytest.raises(ValidationError):
            SystemSettingsUpdate(
                expected_revision=1,
                execution=SystemExecutionDefaults(default_timeout_seconds=0.999),
            )
        system_unchanged = await service.get_system_settings(admin)
        assert system_unchanged.revision == 1
        assert system_unchanged.execution.default_timeout_seconds == 1.0
    finally:
        await boot.repository.close()


@pytest.mark.asyncio
async def test_omission_reset_replacement_and_empty_values(tmp_path: Path) -> None:
    """Omitted, null, false, zero, empty-list, replacement, and section reset differ."""

    boot = await bootstrap_fresh_alpha(tmp_path / "p03-resets.db")
    try:
        service = SettingsService(boot.repository)
        admin = temp_principal(boot.admin_user)
        project_id = boot.default_project.id

        await service.update_system_settings(
            admin,
            SystemSettingsUpdate(
                expected_revision=0,
                routing=SystemRoutingDefaults(
                    max_attempts=3,
                ),
                execution=SystemExecutionDefaults(
                    cache_enabled=True,
                    default_timeout_seconds=30.0,
                    max_fanout_concurrency=5,
                    cache_ttl_seconds=60,
                ),
                safety_limits=SystemSafetyLimits(
                    max_timeout_seconds=60.0,
                    max_fanout_concurrency=6,
                ),
            ),
        )

        initial = await service.update_project_settings(
            admin,
            project_id,
            ProjectSettingsUpdate(
                expected_revision=0,
                routing=RoutingSettings(
                    fallback_policy=FallbackPolicy.FIRST_ONLY,
                    max_attempts=5,
                ),
                execution=ExecutionSettings(
                    cache_enabled=False,
                    default_timeout_seconds=45.0,
                    max_fanout_concurrency=5,
                    cache_ttl_seconds=0,
                ),
            ),
        )
        assert initial.project_revision == 1

        retained = await service.update_project_settings(
            admin,
            project_id,
            ProjectSettingsUpdate(
                expected_revision=1,
                execution=ExecutionSettings(cache_ttl_seconds=30),
            ),
        )
        assert retained.project_revision == 2
        assert retained.effective_settings["routing.fallback_policy"] == "first_only"
        assert retained.effective_settings["routing.max_attempts"] == 5
        assert retained.effective_settings["execution.cache_enabled"] is False
        assert retained.effective_settings["execution.default_timeout_seconds"] == 45.0
        assert retained.effective_settings["execution.max_fanout_concurrency"] == 5
        assert retained.effective_settings["execution.cache_ttl_seconds"] == 30

        changed = await service.update_project_settings(
            admin,
            project_id,
            ProjectSettingsUpdate(
                expected_revision=2,
                routing=RoutingSettings(max_attempts=7),
            ),
        )
        assert changed.project_revision == 3
        assert changed.fields["routing.max_attempts"].provenance is (
            SettingsProvenance.PROJECT_OVERRIDE
        )
        assert changed.effective_settings["routing.max_attempts"] == 7

        replaced = await service.update_project_settings(
            admin,
            project_id,
            ProjectSettingsUpdate(
                expected_revision=3,
                routing=RoutingSettings(max_attempts=8),
            ),
        )
        assert replaced.project_revision == 4
        assert replaced.effective_settings["routing.max_attempts"] == 8

        field_reset = await service.update_project_settings(
            admin,
            project_id,
            ProjectSettingsUpdate(
                expected_revision=4,
                execution=ExecutionSettings(
                    cache_enabled=None,
                    cache_ttl_seconds=None,
                ),
            ),
        )
        assert field_reset.project_revision == 5
        assert field_reset.effective_settings["execution.cache_enabled"] is True
        assert field_reset.effective_settings["execution.cache_ttl_seconds"] == 60
        assert (
            field_reset.fields["execution.cache_enabled"].provenance
            is SettingsProvenance.SYSTEM_DEFAULT
        )
        assert field_reset.effective_settings["execution.default_timeout_seconds"] == 45.0
        assert field_reset.effective_settings["execution.max_fanout_concurrency"] == 5
        assert field_reset.effective_settings["routing.max_attempts"] == 8

        routing_reset = await service.update_project_settings(
            admin,
            project_id,
            ProjectSettingsUpdate(expected_revision=5, routing=None),
        )
        assert routing_reset.project_revision == 6
        assert routing_reset.effective_settings["routing.fallback_policy"] == "chained"
        assert routing_reset.effective_settings["routing.max_attempts"] == 3
        assert routing_reset.effective_settings["execution.default_timeout_seconds"] == 45.0
        assert routing_reset.fields["routing.max_attempts"].provenance is (
            SettingsProvenance.SYSTEM_DEFAULT
        )

        execution_reset = await service.update_project_settings(
            admin,
            project_id,
            ProjectSettingsUpdate(expected_revision=6, execution=None),
        )
        assert execution_reset.project_revision == 7
        assert execution_reset.effective_settings["execution.cache_enabled"] is True
        assert execution_reset.effective_settings["execution.default_timeout_seconds"] == 30.0
        assert execution_reset.effective_settings["execution.max_fanout_concurrency"] == 5
        assert execution_reset.effective_settings["execution.cache_ttl_seconds"] == 60
        assert execution_reset.overrides == {}
    finally:
        await boot.repository.close()


@pytest.mark.asyncio
async def test_stale_revisions_and_invalid_overrides_are_atomic(tmp_path: Path) -> None:
    """Conflicts and validation failures leave the stored document unchanged."""

    boot = await bootstrap_fresh_alpha(tmp_path / "p03-revisions.db")
    try:
        service = SettingsService(boot.repository)
        admin = temp_principal(boot.admin_user)
        project_id = boot.default_project.id

        await service.update_system_settings(
            admin,
            SystemSettingsUpdate(
                expected_revision=0,
                routing=SystemRoutingDefaults(max_attempts=4),
                execution=SystemExecutionDefaults(
                    default_timeout_seconds=30.0,
                    max_fanout_concurrency=5,
                ),
                safety_limits=SystemSafetyLimits(
                    max_timeout_seconds=60.0,
                    max_fanout_concurrency=6,
                ),
            ),
        )
        await service.update_project_settings(
            admin,
            project_id,
            ProjectSettingsUpdate(
                expected_revision=0,
                routing=RoutingSettings(max_attempts=5),
                execution=ExecutionSettings(cache_enabled=False),
            ),
        )

        with pytest.raises(SettingsRevisionConflict) as stale:
            await service.update_project_settings(
                admin,
                project_id,
                ProjectSettingsUpdate(
                    expected_revision=0,
                    routing=RoutingSettings(max_attempts=9),
                ),
            )
        assert stale.value.code == SETTINGS_REVISION_CONFLICT
        unchanged = await service.get_project_settings(admin, project_id)
        assert unchanged.project_revision == 1
        assert unchanged.effective_settings["routing.max_attempts"] == 5
        assert unchanged.effective_settings["execution.cache_enabled"] is False

        with pytest.raises(ValidationError):
            RoutingSettings.model_validate({"preferred_providers": ["ghost"]})
        after_invalid = await service.get_project_settings(admin, project_id)
        assert after_invalid.project_revision == 1
        assert after_invalid.effective_settings["routing.max_attempts"] == 5

        with pytest.raises(ValidationError):
            ProjectSettingsUpdate(
                expected_revision=1,
                routing=RoutingSettings(max_attempts=0),
            )

        with pytest.raises(SettingsRevisionConflict):
            await service.update_system_settings(
                admin,
                SystemSettingsUpdate(
                    expected_revision=0,
                    routing=SystemRoutingDefaults(max_attempts=9),
                ),
            )
        system_after = await service.get_system_settings(admin)
        assert system_after.revision == 1
        assert system_after.routing.max_attempts == 4

        with pytest.raises(ValidationError):
            SystemRoutingDefaults.model_validate({"preferred_providers": ["ghost"]})
        system_after_invalid = await service.get_system_settings(admin)
        assert system_after_invalid.revision == 1
        assert system_after_invalid.routing.max_attempts == 4

        with pytest.raises(SettingsRevisionConflict):
            await service.update_project_settings(
                admin,
                project_id,
                ProjectSettingsUpdate(
                    expected_revision=0,
                    execution=ExecutionSettings(cache_enabled=True),
                ),
            )
        assert (await service.get_project_settings(admin, project_id)).project_revision == 1

        # The archived project remains readable but refuses writes.
        await ProjectService(boot.repository).archive_project(admin, project_id)
        archived = await service.get_project_settings(admin, project_id)
        assert archived.project_revision == 1
        with pytest.raises(SettingsConflict) as archived_error:
            await service.update_project_settings(
                admin,
                project_id,
                ProjectSettingsUpdate(
                    expected_revision=1,
                    execution=ExecutionSettings(cache_enabled=True),
                ),
            )
        assert archived_error.value.code == PROJECT_ARCHIVED
    finally:
        await boot.repository.close()


@pytest.mark.asyncio
async def test_concurrent_project_writers_from_separate_repositories_one_wins(
    tmp_path: Path,
) -> None:
    """Two independent SQLite connections cannot both apply the same revision."""

    boot = await bootstrap_fresh_alpha(tmp_path / "p03-race.db")
    second_repository = await SQLiteRepository.open(boot.repository.database_path)
    third_repository = await SQLiteRepository.open(boot.repository.database_path)
    try:
        admin = temp_principal(boot.admin_user)
        project_id = boot.default_project.id
        first = SettingsService(boot.repository)
        second = SettingsService(second_repository)

        results = await asyncio.gather(
            first.update_project_settings(
                admin,
                project_id,
                ProjectSettingsUpdate(
                    expected_revision=0,
                    execution=ExecutionSettings(cache_enabled=False),
                ),
            ),
            second.update_project_settings(
                admin,
                project_id,
                ProjectSettingsUpdate(
                    expected_revision=0,
                    execution=ExecutionSettings(cache_enabled=True),
                ),
            ),
            return_exceptions=True,
        )

        successes = [result for result in results if not isinstance(result, BaseException)]
        failures = [result for result in results if isinstance(result, BaseException)]
        assert len(successes) == 1
        assert len(failures) == 1
        assert isinstance(failures[0], SettingsRevisionConflict)
        assert failures[0].code == SETTINGS_REVISION_CONFLICT

        final = await SettingsService(third_repository).get_project_settings(admin, project_id)
        assert final.project_revision == 1
        assert (
            final.effective_settings["execution.cache_enabled"]
            == (successes[0].effective_settings["execution.cache_enabled"])
        )
    finally:
        await boot.repository.close()
        await second_repository.close()
        await third_repository.close()


@pytest.mark.asyncio
async def test_context_resolution_and_facade_reject_invalid_or_foreign_state(
    tmp_path: Path,
) -> None:
    """Immutable contexts are live, account-bound, and never a cross-project bypass."""

    boot = await bootstrap_fresh_alpha(tmp_path / "p03-context.db")
    try:
        repository = boot.repository
        service = SettingsService(repository)
        authorization = ScopedAuthorizationService(repository)
        admin = temp_principal(boot.admin_user)
        project_id = boot.default_project.id

        context = await authorization.resolve_project_context(human_principal(admin), project_id)
        assert context is not None
        with pytest.raises(ValidationError):
            context.project_id = uuid4()  # type: ignore[misc]

        system_admin = await _create_system_admin(repository)
        project_b_admin_row = await create_temp_user(repository, temp_email("p03-b-admin"))
        project_b_admin = temp_principal(project_b_admin_row)
        project_b = await _create_second_project(
            repository,
            system_actor=system_admin,
            project_admin=project_b_admin,
        )

        assert await authorization.resolve_project_context(human_principal(admin), uuid4()) is None
        assert (
            await authorization.resolve_project_context(human_principal(system_admin), project_id)
            is None
        )
        assert (
            await authorization.resolve_project_context(human_principal(admin), project_b.id)
            is None
        )
        assert (
            await authorization.resolve_project_context(
                human_principal(project_b_admin), project_b.id
            )
            is not None
        )

        with pytest.raises(SettingsNotFound):
            await service.get_project_settings(system_admin, project_id)
        with pytest.raises(SettingsNotFound):
            await service.get_project_settings(admin, project_b.id)

        token_manager_row = await create_temp_user(repository, temp_email("p03-token-manager"))
        token_manager = temp_principal(token_manager_row)
        await ProjectService(repository).add_member(
            admin,
            project_id,
            ProjectMemberAdd(
                user_id=token_manager.id,
                initial_role=BuiltinRole.PROJECT_MEMBER.value,
                permissions=int(ProjectPermission.TOKENS),
            ),
        )
        token_manager_context = await authorization.resolve_project_context(
            human_principal(token_manager), project_id
        )
        assert token_manager_context is not None
        assert PermissionAction.SETTINGS_READ in token_manager_context.effective_permissions
        assert PermissionAction.PROJECT_READ in token_manager_context.effective_permissions
        assert PermissionAction.TOKENS_MANAGE in token_manager_context.effective_permissions
        assert (await service.get_project_settings(token_manager, project_id)).project_revision == 0
        with pytest.raises(AuthorizationDenied):
            await service.update_project_settings(
                token_manager,
                project_id,
                ProjectSettingsUpdate(
                    expected_revision=0,
                    execution=ExecutionSettings(cache_enabled=False),
                ),
            )

        member_row = await create_temp_user(repository, temp_email("p03-member"))
        member = temp_principal(member_row)
        await ProjectService(repository).add_member(
            admin,
            project_id,
            ProjectMemberAdd(user_id=member.id),
        )
        member_context = await authorization.resolve_project_context(
            human_principal(member), project_id
        )
        assert member_context is not None
        assert member_context.allows(PermissionAction.SETTINGS_READ)
        assert not member_context.allows(PermissionAction.SETTINGS_WRITE)
        assert (await service.get_project_settings(member, project_id)).project_revision == 0
        with pytest.raises(AuthorizationDenied):
            await service.update_project_settings(
                member,
                project_id,
                ProjectSettingsUpdate(
                    expected_revision=0,
                    execution=ExecutionSettings(cache_enabled=False),
                ),
            )

        async with repository.session() as session:
            await session.execute(
                update(ProjectMembershipRow)
                .where(
                    ProjectMembershipRow.project_id == str(project_id),
                    ProjectMembershipRow.user_id == str(member.id),
                )
                .values(status=MembershipStatus.SUSPENDED.value)
            )
            await session.commit()
        assert (
            await authorization.resolve_project_context(human_principal(member), project_id) is None
        )
        with pytest.raises(SettingsNotFound):
            await service.get_project_settings(member, project_id)

        async with repository.session() as session:
            await session.execute(
                update(UserRow).where(UserRow.id == str(token_manager.id)).values(is_active=False)
            )
            await session.commit()
        assert (
            await authorization.resolve_project_context(human_principal(token_manager), project_id)
            is None
        )

        foreign_account_id = uuid4()
        async with repository.session() as session:
            session.add(AccountRow(id=str(foreign_account_id), status="active"))
            await session.flush()
            foreign_project, _, _ = await ProjectRepository(session).create_project_with_admin(
                account_id=foreign_account_id,
                created_by=admin.id,
                project_create=ProjectCreate(
                    name="Foreign Account Project",
                    slug="foreign-account",
                    initial_admin_user_id=admin.id,
                ),
            )
            await session.commit()
        assert (
            await authorization.resolve_project_context(human_principal(admin), foreign_project.id)
            is None
        )

        foreign_context = ProjectContext(
            account_id=uuid4(),
            project_id=project_id,
            principal=human_principal(admin),
            effective_permissions=context.effective_permissions,
        )
        async with repository.session() as session:
            with pytest.raises(ValueError, match="does not match the installation account"):
                ProjectScopedRepository(
                    session,
                    context=foreign_context,
                    account_id=boot.account_id,
                )
            facade = ProjectScopedRepository(session, context=context)
            assert facade.context is context
            assert (await facade.require_project()).id == project_id

        async with repository.session() as session:
            await session.execute(
                update(AccountRow)
                .where(AccountRow.id == str(boot.account_id))
                .values(status="suspended")
            )
            await session.commit()
        assert (
            await authorization.resolve_project_context(human_principal(admin), project_id) is None
        )
    finally:
        await boot.repository.close()


_CHILD_SETTINGS_WRITER = textwrap.dedent(
    """
    from __future__ import annotations

    import asyncio
    import sys
    from pathlib import Path
    from uuid import UUID

    from freesearch.models.projects import ExecutionSettings
    from freesearch.models.settings import (
        ProjectSettingsUpdate,
        SystemExecutionDefaults,
        SystemRoutingDefaults,
        SystemSafetyLimits,
        SystemSettingsUpdate,
    )
    from freesearch.models.users import UserPrincipal
    from freesearch.persistence.storage import SQLiteRepository
    from freesearch.services.settings import SettingsService


    async def main() -> None:
        db, user_id, action, project_id = sys.argv[1:5]
        repository = await SQLiteRepository.open(Path(db))
        try:
            service = SettingsService(repository)
            actor = UserPrincipal(
                id=UUID(user_id),
                email="child-writer@example.com",
                session_id=UUID("00000000-0000-4000-8000-000000000099"),
                is_active=True,
                is_verified=True,
            )
            if action == "system":
                await service.update_system_settings(
                    actor,
                    SystemSettingsUpdate(
                        expected_revision=0,
                        routing=SystemRoutingDefaults(max_attempts=7),
                        execution=SystemExecutionDefaults(
                            default_timeout_seconds=45.0,
                            max_fanout_concurrency=4,
                        ),
                        safety_limits=SystemSafetyLimits(
                            max_timeout_seconds=120.0,
                            max_fanout_concurrency=10,
                        ),
                    ),
                )
            elif action == "project":
                await service.update_project_settings(
                    actor,
                    UUID(project_id),
                    ProjectSettingsUpdate(
                        expected_revision=0,
                        execution=ExecutionSettings(
                            cache_enabled=False,
                            cache_ttl_seconds=0,
                        ),
                    ),
                )
            else:
                raise SystemExit(f"unknown action {action!r}")
        finally:
            await repository.close()


    asyncio.run(main())
    """
).strip()


@pytest.mark.asyncio
async def test_cross_process_revisions_invalidate_cached_project_resolutions(
    tmp_path: Path,
) -> None:
    """A separate OS process invalidates both system and project cache identities."""

    boot = await bootstrap_fresh_alpha(tmp_path / "p03-cross-process.db")
    try:
        repository = boot.repository
        service = SettingsService(repository)
        admin = temp_principal(boot.admin_user)
        second_admin_row = await create_temp_user(repository, temp_email("p03-cross-b"))
        second_admin = temp_principal(second_admin_row)
        project_b = await _create_second_project(
            repository,
            system_actor=admin,
            project_admin=second_admin,
        )
        project_a = boot.default_project.id

        cached_a = await service.get_project_settings(admin, project_a)
        cached_b = await service.get_project_settings(second_admin, project_b.id)
        assert (cached_a.system_revision, cached_a.project_revision) == (0, 0)
        assert (cached_b.system_revision, cached_b.project_revision) == (0, 0)

        child = tmp_path / "p03_child_writer.py"
        child.write_text(_CHILD_SETTINGS_WRITER, encoding="utf-8")
        repository_root = Path(__file__).resolve().parents[3]
        environment = os.environ.copy()
        environment["PYTHONPATH"] = os.pathsep.join(
            [str(repository_root), environment.get("PYTHONPATH", "")]
        ).rstrip(os.pathsep)

        system_write = subprocess.run(
            [
                sys.executable,
                str(child),
                str(boot.repository.database_path),
                str(boot.admin_user.id),
                "system",
                str(project_a),
            ],
            capture_output=True,
            text=True,
            env=environment,
            timeout=60,
            check=False,
        )
        assert system_write.returncode == 0, system_write.stderr

        after_system_a = await service.get_project_settings(admin, project_a)
        after_system_b = await service.get_project_settings(second_admin, project_b.id)
        assert after_system_a.system_revision == 1
        assert after_system_b.system_revision == 1
        assert after_system_a.project_revision == 0
        assert after_system_b.project_revision == 0
        assert after_system_a.effective_settings["routing.max_attempts"] == 7
        assert after_system_b.effective_settings["routing.max_attempts"] == 7

        project_write = subprocess.run(
            [
                sys.executable,
                str(child),
                str(boot.repository.database_path),
                str(boot.admin_user.id),
                "project",
                str(project_a),
            ],
            capture_output=True,
            text=True,
            env=environment,
            timeout=60,
            check=False,
        )
        assert project_write.returncode == 0, project_write.stderr

        after_project_a = await service.get_project_settings(admin, project_a)
        after_project_b = await service.get_project_settings(second_admin, project_b.id)
        assert after_project_a.system_revision == 1
        assert after_project_a.project_revision == 1
        assert after_project_a.effective_settings["execution.cache_enabled"] is False
        assert after_project_a.effective_settings["execution.cache_ttl_seconds"] == 0
        assert after_project_b.system_revision == 1
        assert after_project_b.project_revision == 0
        assert after_project_b.effective_settings["execution.cache_enabled"] is True
    finally:
        await boot.repository.close()


async def _copy_pair(
    repository: SQLiteRepository,
    source_id: UUID,
    admin: UserPrincipal,
    slug: str,
) -> tuple[ProjectRead, UserPrincipal]:
    """Create target B with its own admin who can also read source A.

    The returned copier holds source ``settings.read`` as a plain member of A
    plus target ``settings.copy``/``settings.write`` as project admin of B.
    """

    target_admin = temp_principal(await create_temp_user(repository, temp_email("p05-copy-admin")))
    target = await ProjectService(repository).create_project(
        admin,
        ProjectCreate(
            name="Second Settings Copy Project",
            slug=slug,
            initial_admin_user_id=target_admin.id,
        ),
    )
    await ProjectService(repository).add_member(
        admin,
        source_id,
        ProjectMemberAdd(user_id=target_admin.id),
    )
    return target, target_admin


@pytest.mark.asyncio
async def test_copy_overrides_only_skips_inherited_values(tmp_path: Path) -> None:
    """Overrides-only copy moves explicit source overrides and nothing else."""

    boot = await bootstrap_fresh_alpha(tmp_path / "p05-copy-overrides.db")
    try:
        service = SettingsService(boot.repository)
        admin = temp_principal(boot.admin_user)
        source_id = boot.default_project.id
        target, copier = await _copy_pair(boot.repository, source_id, admin, "second-copy-settings")

        await service.update_project_settings(
            admin,
            source_id,
            ProjectSettingsUpdate(
                expected_revision=0,
                routing=RoutingSettings(
                    fallback_policy=FallbackPolicy.FIRST_ONLY,
                    max_attempts=5,
                ),
                execution=ExecutionSettings(cache_enabled=False),
            ),
        )

        preview = await service.preview_copy(
            copier,
            target.id,
            SettingsCopyRequest(
                source_project_id=source_id,
                expected_source_revision=1,
                expected_target_revision=0,
                expected_system_revision=0,
            ),
        )
        assert preview.source_revision == 1
        assert preview.target_revision == 0
        assert preview.system_revision == 0
        copied = {field.field_id for field in preview.fields}
        assert copied == {
            "routing.fallback_policy",
            "routing.max_attempts",
            "execution.cache_enabled",
        }
        assert preview.rejected == []
        assert preview.bindings == []
        assert preview.target.system_revision == 0
        assert preview.target.project_revision == 0
        assert preview.target.effective_settings["routing.max_attempts"] == 5
        assert preview.target.effective_settings["execution.cache_enabled"] is False
        assert "routing.cost_optimization_preset" not in preview.target.effective_settings
        # Preview must not write: the live target still inherits the defaults.
        untouched = await service.get_project_settings(copier, target.id)
        assert untouched.project_revision == 0
        assert untouched.effective_settings["routing.max_attempts"] == 3
        assert untouched.effective_settings["execution.cache_enabled"] is True
        assert untouched.overrides == {}

        source_revision, target_revision, system_revision = (
            preview.source_revision,
            preview.target_revision,
            preview.system_revision,
        )
        result = await service.apply_copy(
            copier,
            target.id,
            SettingsCopyRequest(
                source_project_id=source_id,
                expected_source_revision=source_revision,
                expected_target_revision=target_revision,
                expected_system_revision=system_revision,
            ),
        )
        assert result.target_revision == 1
        assert result.bindings_copied == []
        assert result.target.effective_settings["routing.max_attempts"] == 5
        assert result.target.effective_settings["execution.cache_enabled"] is False
        assert result.overrides["routing.max_attempts"] == 5
        assert "routing.cost_optimization_preset" not in result.overrides

        async with boot.repository.session() as session:
            events = await AuditRepository(session).list_project_events(project_id=target.id)
        assert events
        assert events[0].action == "settings.copy"
        assert events[0].scope_id == target.id
        assert result.audit_event_id == events[0].id

        reread = await service.get_project_settings(copier, target.id)
        assert reread.project_revision == 1
        assert reread.effective_settings["routing.max_attempts"] == 5

        # Re-applying the same state is a no-op: no new revision, same overrides.
        same = await service.apply_copy(
            copier,
            target.id,
            SettingsCopyRequest(
                source_project_id=source_id,
                expected_source_revision=1,
                expected_target_revision=1,
                expected_system_revision=0,
            ),
        )
        assert same.target_revision == 1
        assert (await service.get_project_settings(copier, target.id)).project_revision == 1
    finally:
        await boot.repository.close()


@pytest.mark.asyncio
async def test_copy_effective_snapshot_pins_inherited_values_as_overrides(
    tmp_path: Path,
) -> None:
    """Effective-snapshot copy pins the source's resolved view onto the target."""

    boot = await bootstrap_fresh_alpha(tmp_path / "p05-copy-snapshot.db")
    try:
        service = SettingsService(boot.repository)
        admin = temp_principal(boot.admin_user)
        source_id = boot.default_project.id
        target, copier = await _copy_pair(boot.repository, source_id, admin, "second-copy-snapshot")

        await service.update_system_settings(
            admin,
            SystemSettingsUpdate(
                expected_revision=0,
                routing=SystemRoutingDefaults(max_attempts=6),
                execution=SystemExecutionDefaults(
                    default_timeout_seconds=40.0,
                    max_fanout_concurrency=4,
                    cache_enabled=True,
                    cache_ttl_seconds=120,
                ),
                safety_limits=SystemSafetyLimits(
                    max_timeout_seconds=70.0,
                    max_fanout_concurrency=8,
                ),
            ),
        )
        await service.update_project_settings(
            admin,
            source_id,
            ProjectSettingsUpdate(
                expected_revision=0,
                routing=RoutingSettings(max_attempts=5),
            ),
        )

        preview = await service.preview_copy(
            copier,
            target.id,
            SettingsCopyRequest(
                source_project_id=source_id,
                expected_source_revision=1,
                expected_target_revision=0,
                expected_system_revision=1,
                mode=SettingsCopyMode.EFFECTIVE_SNAPSHOT,
            ),
        )
        snapshot = {field.field_id: field.value for field in preview.fields}
        # Inherited system values are pinned as explicit overrides here.
        assert snapshot["routing.max_attempts"] == 5
        assert snapshot["execution.cache_enabled"] is True
        assert snapshot["execution.default_timeout_seconds"] == 40.0
        assert preview.effective_snapshot["routing.max_attempts"] == 5
        assert preview.target.project_revision == 0
        assert preview.target.effective_settings["routing.max_attempts"] == 5

        source_revision, target_revision, system_revision = (
            preview.source_revision,
            preview.target_revision,
            preview.system_revision,
        )
        result = await service.apply_copy(
            copier,
            target.id,
            SettingsCopyRequest(
                source_project_id=source_id,
                expected_source_revision=source_revision,
                expected_target_revision=target_revision,
                expected_system_revision=system_revision,
                mode=SettingsCopyMode.EFFECTIVE_SNAPSHOT,
            ),
        )
        assert result.target_revision == 1
        assert result.overrides["execution.cache_enabled"] is True
        reread = await service.get_project_settings(copier, target.id)
        assert reread.overrides["execution.cache_enabled"] is True
    finally:
        await boot.repository.close()


@pytest.mark.asyncio
async def test_copy_reports_system_only_and_unset_overrides_as_rejections(
    tmp_path: Path,
) -> None:
    """Explicit field lists reject authority-owned and uninherited fields."""

    boot = await bootstrap_fresh_alpha(tmp_path / "p05-copy-reject.db")
    try:
        service = SettingsService(boot.repository)
        admin = temp_principal(boot.admin_user)
        source_id = boot.default_project.id
        target, copier = await _copy_pair(boot.repository, source_id, admin, "second-copy-reject")
        await service.update_project_settings(
            admin,
            source_id,
            ProjectSettingsUpdate(
                expected_revision=0,
                routing=RoutingSettings(max_attempts=5),
            ),
        )

        preview = await service.preview_copy(
            copier,
            target.id,
            SettingsCopyRequest(
                source_project_id=source_id,
                expected_source_revision=1,
                expected_target_revision=0,
                expected_system_revision=0,
                fields=(
                    "routing.max_attempts",
                    "routing.fallback_policy",
                    "system.max_timeout_seconds",
                ),
            ),
        )
        assert [field.field_id for field in preview.fields] == ["routing.max_attempts"]
        rejected = {item.field_id: item.reason for item in preview.rejected}
        assert rejected == {
            "routing.fallback_policy": COPY_FIELD_NOT_OVERRIDDEN,
            "system.max_timeout_seconds": COPY_FIELD_SYSTEM_ONLY,
        }

        with pytest.raises(SettingsValidationError, match="unknown settings field"):
            await service.preview_copy(
                copier,
                target.id,
                SettingsCopyRequest(
                    source_project_id=source_id,
                    expected_source_revision=1,
                    expected_target_revision=0,
                    expected_system_revision=0,
                    fields=("routing.nope",),
                ),
            )
    finally:
        await boot.repository.close()


@pytest.mark.asyncio
async def test_copy_revision_triple_rejects_stale_source_target_and_system(
    tmp_path: Path,
) -> None:
    """Any stale revision in the source/target/system triple aborts the copy."""

    boot = await bootstrap_fresh_alpha(tmp_path / "p05-copy-stale.db")
    try:
        service = SettingsService(boot.repository)
        admin = temp_principal(boot.admin_user)
        source_id = boot.default_project.id
        target, copier = await _copy_pair(boot.repository, source_id, admin, "second-copy-stale")
        await service.update_project_settings(
            admin,
            source_id,
            ProjectSettingsUpdate(
                expected_revision=0,
                routing=RoutingSettings(max_attempts=5),
            ),
        )
        good = SettingsCopyRequest(
            source_project_id=source_id,
            expected_source_revision=1,
            expected_target_revision=0,
            expected_system_revision=0,
        )

        with pytest.raises(SettingsRevisionConflict):
            await service.preview_copy(
                copier,
                target.id,
                good.model_copy(update={"expected_source_revision": 0}),
            )
        with pytest.raises(SettingsRevisionConflict):
            await service.preview_copy(
                copier,
                target.id,
                good.model_copy(update={"expected_target_revision": 7}),
            )
        await service.update_system_settings(
            admin,
            SystemSettingsUpdate(
                expected_revision=0,
                routing=SystemRoutingDefaults(max_attempts=4),
                execution=SystemExecutionDefaults(
                    default_timeout_seconds=30.0,
                    max_fanout_concurrency=5,
                ),
                safety_limits=SystemSafetyLimits(
                    max_timeout_seconds=60.0,
                    max_fanout_concurrency=6,
                ),
            ),
        )
        with pytest.raises(SettingsRevisionConflict):
            await service.preview_copy(copier, target.id, good)
        with pytest.raises(SettingsRevisionConflict):
            await service.apply_copy(copier, target.id, good)

        # Target moves too: the first apply wins, the replayed plan loses.
        moved = await service.apply_copy(
            copier,
            target.id,
            SettingsCopyRequest(
                source_project_id=source_id,
                expected_source_revision=1,
                expected_target_revision=0,
                expected_system_revision=1,
            ),
        )
        assert moved.target_revision == 1
        with pytest.raises(SettingsRevisionConflict):
            await service.apply_copy(
                copier,
                target.id,
                SettingsCopyRequest(
                    source_project_id=source_id,
                    expected_source_revision=1,
                    expected_target_revision=0,
                    expected_system_revision=1,
                ),
            )
        reread = await service.get_project_settings(copier, target.id)
        assert reread.project_revision == 1
    finally:
        await boot.repository.close()


@pytest.mark.asyncio
async def test_copy_enforces_source_read_target_copy_and_write_split(tmp_path: Path) -> None:
    """Source reads, target copy, and target writes are independent gates."""

    boot = await bootstrap_fresh_alpha(tmp_path / "p05-copy-rbac.db")
    try:
        repository = boot.repository
        service = SettingsService(repository)
        admin = temp_principal(boot.admin_user)
        source_id = boot.default_project.id

        source_outsider_row = await create_temp_user(repository, temp_email("p05-copy-outsider"))
        source_outsider = temp_principal(source_outsider_row)

        target_admin_row = await create_temp_user(repository, temp_email("p05-copy-tadmin"))
        target_admin = temp_principal(target_admin_row)
        target = await ProjectService(repository).create_project(
            admin,
            ProjectCreate(
                name="Second Settings RBAC Project",
                slug="second-copy-rbac",
                initial_admin_user_id=target_admin.id,
            ),
        )

        request = SettingsCopyRequest(
            source_project_id=source_id,
            expected_source_revision=0,
            expected_target_revision=0,
            expected_system_revision=0,
        )
        # No membership anywhere: target resolution itself is not found.
        with pytest.raises(SettingsNotFound):
            await service.preview_copy(source_outsider, target.id, request)
        with pytest.raises(SettingsNotFound):
            await service.apply_copy(source_outsider, target.id, request)

        # Source member (read-only) cannot preview into the target: the target
        # context is missing first, then SETTINGS_COPY is required as a member.
        await ProjectService(repository).add_member(
            admin,
            source_id,
            ProjectMemberAdd(user_id=source_outsider.id),
        )
        readable = await service.get_project_settings(source_outsider, source_id)
        assert readable.project_revision == 0
        with pytest.raises(SettingsNotFound):
            await service.preview_copy(source_outsider, target.id, request)
        await ProjectService(repository).add_member(
            target_admin,
            target.id,
            ProjectMemberAdd(user_id=source_outsider.id),
        )
        with pytest.raises(AuthorizationDenied):
            await service.preview_copy(source_outsider, target.id, request)
        # Read on the source and copy on the target are now satisfied, but plain
        # members cannot write the target.
        with pytest.raises(AuthorizationDenied):
            await service.apply_copy(source_outsider, target.id, request)

        # A target-only admin lacks source read: target resolution succeeds but
        # the source context is not found, so no silent authority copy happens.
        with pytest.raises(SettingsNotFound):
            await service.preview_copy(target_admin, target.id, request)
        with pytest.raises(SettingsNotFound):
            await service.apply_copy(target_admin, target.id, request)

        # Self-copy is rejected before any revision check.
        with pytest.raises(SettingsValidationError, match="cannot copy settings onto itself"):
            await service.preview_copy(
                admin,
                source_id,
                SettingsCopyRequest(
                    source_project_id=source_id,
                    expected_source_revision=0,
                    expected_target_revision=0,
                    expected_system_revision=0,
                ),
            )
    finally:
        await boot.repository.close()


@pytest.mark.asyncio
async def test_copy_refuses_archived_targets_and_preserves_without_secret_copy(
    tmp_path: Path,
) -> None:
    """Archived targets refuse the copy; a clean copy carries no secret detail."""

    boot = await bootstrap_fresh_alpha(tmp_path / "p05-copy-archived.db")
    try:
        service = SettingsService(boot.repository)
        admin = temp_principal(boot.admin_user)
        source_id = boot.default_project.id
        target, copier = await _copy_pair(boot.repository, source_id, admin, "second-copy-archived")
        await ProjectService(boot.repository).archive_project(copier, target.id)
        request = SettingsCopyRequest(
            source_project_id=source_id,
            expected_source_revision=0,
            expected_target_revision=0,
            expected_system_revision=0,
        )
        with pytest.raises(SettingsConflict) as archived_preview:
            await service.preview_copy(copier, target.id, request)
        assert archived_preview.value.code == PROJECT_ARCHIVED
        with pytest.raises(SettingsConflict) as archived_apply:
            await service.apply_copy(copier, target.id, request)
        assert archived_apply.value.code == PROJECT_ARCHIVED

        async with boot.repository.session() as session:
            events = await AuditRepository(session).list_project_events(project_id=target.id)
        assert all(event.action != "settings.copy" for event in events)
    finally:
        await boot.repository.close()


@pytest.mark.asyncio
async def test_trace_inheritance_and_system_ceilings(tmp_path: Path) -> None:
    """Trace overrides inherit and ceilings bind."""

    boot = await bootstrap_fresh_alpha(tmp_path / "p05-trace-inherit.db")
    try:
        service = SettingsService(boot.repository)
        admin = temp_principal(boot.admin_user)
        project_id = boot.default_project.id

        inherited = await service.get_project_settings(admin, project_id)
        assert inherited.effective_settings["trace.detail"] == "full"
        assert inherited.effective_settings["trace.retention_days"] is None
        assert "trace.sampling_rate" not in inherited.fields
        assert "trace.payload_redaction" not in inherited.fields
        assert inherited.overrides == {}

        written = await service.update_project_settings(
            admin,
            project_id,
            ProjectSettingsUpdate(
                expected_revision=0,
                trace=TraceSettings(
                    detail=TraceDetailPolicy.METADATA,
                    retention_days=120,
                ),
            ),
        )
        assert written.project_revision == 1
        assert written.effective_settings["trace.detail"] == "metadata"
        assert written.effective_settings["trace.retention_days"] == 120
        assert written.overrides["trace.retention_days"] == 120
        assert written.fields["trace.retention_days"].provenance is (
            SettingsProvenance.PROJECT_OVERRIDE
        )

        tightened = await service.update_system_settings(
            admin,
            SystemSettingsUpdate(
                expected_revision=0,
                routing=SystemRoutingDefaults(max_attempts=3),
                execution=SystemExecutionDefaults(
                    cache_enabled=True,
                    default_timeout_seconds=30.0,
                    max_fanout_concurrency=5,
                    cache_ttl_seconds=300,
                ),
                trace=SystemTraceDefaults(
                    detail=TraceDetailPolicy.METADATA,
                ),
                safety_limits=SystemSafetyLimits(max_trace_retention_days=14),
            ),
        )
        assert tightened.revision == 1
        reread = await service.get_project_settings(admin, project_id)
        assert reread.system_revision == 1
        assert reread.project_revision == 1
        assert reread.effective_settings["trace.detail"] == "metadata"
        # The project asked for a longer window than the ceiling allows.
        assert reread.effective_settings["trace.retention_days"] == 14

        relaxed = await service.update_project_settings(
            admin,
            project_id,
            ProjectSettingsUpdate(
                expected_revision=1,
                trace=TraceSettings(
                    detail=TraceDetailPolicy.FULL,
                    retention_days=60,
                ),
            ),
        )
        assert relaxed.project_revision == 2
        assert relaxed.effective_settings["trace.detail"] == "metadata"
        assert relaxed.fields["trace.detail"].provenance is (SettingsProvenance.SYSTEM_CONSTRAINED)
        assert relaxed.effective_settings["trace.retention_days"] == 14

        reset = await service.update_project_settings(
            admin,
            project_id,
            ProjectSettingsUpdate(expected_revision=2, trace=None),
        )
        assert reset.project_revision == 3
        assert reset.effective_settings["trace.detail"] == "metadata"
        assert reset.effective_settings["trace.retention_days"] is None
        assert reset.overrides == {}
    finally:
        await boot.repository.close()


@pytest.mark.asyncio
async def test_trace_retention_uses_effective_policy_and_isolates_project(
    tmp_path: Path,
) -> None:
    """Trace retention derives its cutoff from the policy and stays in project."""

    boot = await bootstrap_fresh_alpha(tmp_path / "p05-trace-retention.db")
    try:
        settings = SettingsService(boot.repository)
        admin = temp_principal(boot.admin_user)
        project_id = boot.default_project.id
        second_admin = temp_principal(
            await create_temp_user(boot.repository, temp_email("p05-trace-ret-b"))
        )
        other = await ProjectService(boot.repository).create_project(
            admin,
            ProjectCreate(
                name="Other Retention Project",
                slug="other-retention",
                initial_admin_user_id=second_admin.id,
            ),
        )

        retention = ProjectRetentionService(boot.repository)
        now = datetime.now(UTC)
        old_root = TraceSpanRecord(
            project_id=project_id,
            actor_type=ActorType.HUMAN,
            actor_id=admin.id,
            span_id="root-old",
            trace_id="a" * 32,
            name="POST /search",
            kind=TraceSpanKind.SERVER,
            started_at=now - timedelta(days=30),
            ended_at=now - timedelta(days=30),
            duration_ms=5,
            operation=TraceOperation.SEARCH,
            outcome=TraceOutcome.SUCCESS,
            user_id=str(admin.id),
        )
        new_root = old_root.model_copy(
            update={
                "span_id": "root-new",
                "trace_id": "b" * 32,
                "started_at": now - timedelta(days=1),
                "ended_at": now - timedelta(days=1),
            }
        )
        foreign_root = old_root.model_copy(
            update={
                "project_id": other.id,
                "span_id": "root-foreign",
                "trace_id": "c" * 32,
            }
        )
        write_trace_spans(boot.repository.database_path, [old_root, new_root, foreign_root])

        keep_all = await retention.run(
            admin, project_id, RetentionRunRequest(data_class=RetentionDataClass.TRACES)
        )
        assert keep_all.deleted_rows == 0
        assert await get_project_trace(boot.repository, admin, project_id, "a" * 32) is not None
        explicit_cutoff = await retention.run(
            admin,
            project_id,
            RetentionRunRequest(data_class=RetentionDataClass.TRACES, cutoff=now),
        )
        assert explicit_cutoff.deleted_rows == 0
        assert await get_project_trace(boot.repository, admin, project_id, "a" * 32) is not None
        await settings.update_project_settings(
            admin,
            project_id,
            ProjectSettingsUpdate(expected_revision=0, trace=TraceSettings(retention_days=7)),
        )
        run = await retention.run(
            admin,
            project_id,
            RetentionRunRequest(data_class=RetentionDataClass.TRACES),
        )
        assert run.project_id == project_id
        assert run.data_class is RetentionDataClass.TRACES
        assert run.deleted_rows >= 1
        assert (now - run.cutoff).days in {6, 7}
        kept = await get_project_trace(boot.repository, admin, project_id, "b" * 32)
        assert kept is not None
        assert await get_project_trace(boot.repository, admin, project_id, "a" * 32) is None
        foreign = await get_project_trace(boot.repository, second_admin, other.id, "c" * 32)
        assert foreign is not None

        with pytest.raises(ResourceInvalid) as missing_cutoff:
            await retention.run(
                admin,
                project_id,
                RetentionRunRequest(data_class=RetentionDataClass.USAGE),
            )
        assert missing_cutoff.value.code == RETENTION_CUTOFF_REQUIRED
        with pytest.raises(ResourceInvalid) as future_cutoff:
            await retention.run(
                admin,
                project_id,
                RetentionRunRequest(
                    data_class=RetentionDataClass.USAGE,
                    cutoff=now + timedelta(days=1),
                ),
            )
        assert future_cutoff.value.code == RETENTION_CUTOFF_FUTURE
    finally:
        await boot.repository.close()


@pytest.mark.asyncio
async def test_activity_reads_are_isolated_between_projects(tmp_path: Path) -> None:
    """Activity lists stay inside the authorized project and need read rights."""

    boot = await bootstrap_fresh_alpha(tmp_path / "p05-trace-isolation.db")
    try:
        admin = temp_principal(boot.admin_user)
        project_id = boot.default_project.id
        second_admin = temp_principal(
            await create_temp_user(boot.repository, temp_email("p05-trace-iso-b"))
        )
        other = await ProjectService(boot.repository).create_project(
            admin,
            ProjectCreate(
                name="Other Isolation Project",
                slug="other-isolation",
                initial_admin_user_id=second_admin.id,
            ),
        )
        now = datetime.now(UTC)
        write_trace_spans(
            boot.repository.database_path,
            [
                TraceSpanRecord(
                    project_id=project_id,
                    actor_type=ActorType.HUMAN,
                    actor_id=admin.id,
                    span_id="root-a",
                    trace_id="d" * 32,
                    name="POST /search",
                    kind=TraceSpanKind.SERVER,
                    started_at=now,
                    ended_at=now,
                    duration_ms=5,
                    operation=TraceOperation.SEARCH,
                    outcome=TraceOutcome.SUCCESS,
                    user_id=str(admin.id),
                ),
                TraceSpanRecord(
                    project_id=other.id,
                    actor_type=ActorType.HUMAN,
                    actor_id=second_admin.id,
                    span_id="root-b",
                    trace_id="e" * 32,
                    name="POST /search",
                    kind=TraceSpanKind.SERVER,
                    started_at=now,
                    ended_at=now,
                    duration_ms=5,
                    operation=TraceOperation.SEARCH,
                    outcome=TraceOutcome.SUCCESS,
                    user_id=str(second_admin.id),
                ),
            ],
        )

        own = await list_project_traces(boot.repository, admin, project_id)
        assert [item.trace_id for item in own.items] == ["d" * 32]
        foreign_project = await list_project_traces(boot.repository, second_admin, other.id)
        assert [item.trace_id for item in foreign_project.items] == ["e" * 32]
        assert await get_project_trace(boot.repository, admin, project_id, "e" * 32) is None
        assert await get_project_trace(boot.repository, second_admin, other.id, "d" * 32) is None
        assert await get_project_trace(boot.repository, admin, project_id, "not-a-trace") is None

        outsider_row = await create_temp_user(
            repository=boot.repository, email=temp_email("p05-iso-out")
        )
        outsider = temp_principal(outsider_row)
        with pytest.raises(ResourceNotFound):
            await list_project_traces(boot.repository, outsider, project_id)

        await ProjectService(boot.repository).add_member(
            admin,
            project_id,
            ProjectMemberAdd(user_id=outsider.id),
        )
        member_view = await list_project_traces(boot.repository, outsider, project_id)
        assert [item.trace_id for item in member_view.items] == ["d" * 32]
        with pytest.raises(ResourceNotFound):
            await list_project_traces(boot.repository, outsider, other.id)

        token_manager_row = await create_temp_user(
            repository=boot.repository, email=temp_email("p05-iso-token")
        )
        token_manager = temp_principal(token_manager_row)
        await ProjectService(boot.repository).add_member(
            admin,
            project_id,
            ProjectMemberAdd(
                user_id=token_manager.id,
                initial_role=BuiltinRole.PROJECT_MEMBER.value,
                permissions=int(ProjectPermission.TOKENS),
            ),
        )
        with pytest.raises(AuthorizationDenied):
            await list_project_traces(boot.repository, token_manager, project_id)
    finally:
        await boot.repository.close()


@pytest.mark.asyncio
async def test_settings_edits_and_copy_are_mandatory_audits(
    tmp_path: Path,
) -> None:
    boot = await bootstrap_fresh_alpha(tmp_path / "mandatory-audit.db")
    try:
        admin = temp_principal(boot.admin_user)
        settings = SettingsService(boot.repository)
        source = boot.default_project.id
        target, copier = await _copy_pair(boot.repository, source, admin, "audit-copy")
        await settings.update_project_settings(
            admin,
            source,
            ProjectSettingsUpdate(expected_revision=0, trace=TraceSettings(detail="metadata")),
        )
        await settings.update_project_settings(
            copier,
            target.id,
            ProjectSettingsUpdate(expected_revision=0, trace=TraceSettings(detail="metadata")),
        )
        result = await settings.apply_copy(
            copier,
            target.id,
            SettingsCopyRequest(
                source_project_id=source,
                expected_source_revision=1,
                expected_target_revision=1,
                expected_system_revision=0,
            ),
        )
        async with boot.repository.session() as session:
            source_events = await AuditRepository(session).list_project_events(project_id=source)
            target_events = await AuditRepository(session).list_project_events(project_id=target.id)
        assert [event.action for event in source_events].count("settings.edit") == 1
        assert [event.action for event in target_events].count("settings.edit") == 1
        assert [event.action for event in target_events].count("settings.copy") == 1
        assert result.audit_event_id in {event.id for event in target_events}
    finally:
        await boot.repository.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["edit", "copy"])
async def test_audit_failure_rolls_back_settings_revision_and_cached_resolution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, operation: str
) -> None:
    from unittest.mock import AsyncMock

    from freesearch.persistence.bindings import ProjectBindingRepository

    boot = await bootstrap_fresh_alpha(tmp_path / "audit-rollback.db")
    try:
        admin = temp_principal(boot.admin_user)
        source = boot.default_project.id
        settings = SettingsService(boot.repository)
        target, copier = await _copy_pair(boot.repository, source, admin, "rollback-copy")
        await settings.update_project_settings(
            admin,
            source,
            ProjectSettingsUpdate(
                expected_revision=0, execution=ExecutionSettings(cache_enabled=False)
            ),
        )
        binding = await _copy_binding(boot.repository, source, target.id, admin.id)
        before = await settings.get_project_settings(copier, target.id)
        async with boot.repository.session() as session:
            audit_before = await AuditRepository(session).list_project_events(project_id=target.id)
            bindings_before = await ProjectBindingRepository(session).list_for_project(
                project_id=target.id
            )
        with monkeypatch.context() as patch:
            patch.setattr(
                "freesearch.services.settings.record_project_event",
                AsyncMock(side_effect=RuntimeError("injected audit failure")),
            )
            with pytest.raises(RuntimeError, match="injected audit failure"):
                if operation == "copy":
                    await settings.apply_copy(
                        copier,
                        target.id,
                        SettingsCopyRequest(
                            source_project_id=source,
                            expected_source_revision=1,
                            expected_target_revision=0,
                            expected_system_revision=0,
                            binding_versions={binding.id: binding.version},
                        ),
                    )
                else:
                    await settings.update_project_settings(
                        copier,
                        target.id,
                        ProjectSettingsUpdate(
                            expected_revision=0, execution=ExecutionSettings(cache_enabled=False)
                        ),
                    )
        after = await SettingsService(boot.repository).get_project_settings(copier, target.id)
        assert after == before
        async with boot.repository.session() as session:
            audit_after = await AuditRepository(session).list_project_events(project_id=target.id)
            assert (
                await ProjectBindingRepository(session).list_for_project(project_id=target.id)
                == bindings_before
            )
        assert audit_after == audit_before
        # The same expected revision remains usable after rollback.
        written = await settings.update_project_settings(
            copier,
            target.id,
            ProjectSettingsUpdate(
                expected_revision=0, execution=ExecutionSettings(cache_enabled=False)
            ),
        )
        assert written.project_revision == 1
        assert written.effective_settings["execution.cache_enabled"] is False
    finally:
        await boot.repository.close()


async def _copy_binding(
    repository: SQLiteRepository,
    source: UUID,
    target: UUID,
    actor_id: UUID,
    *,
    private: bool = False,
    target_grant: bool = True,
) -> StoredBinding:
    """Seed only nonsecret credential metadata and a source binding."""
    from freesearch.models.credentials import CredentialOperation
    from freesearch.models.projects import DEFAULT_INSTALLATION_ACCOUNT_ID, CredentialOwnerScope
    from freesearch.persistence.bindings import ProjectBindingRepository
    from freesearch.persistence.credentials import CredentialRepository

    scope = CredentialOwnerScope.PROJECT if private else CredentialOwnerScope.SYSTEM
    async with repository.session() as session:
        credentials = CredentialRepository(session)
        credential = await credentials.insert_credential(
            account_id=DEFAULT_INSTALLATION_ACCOUNT_ID,
            provider_type="tavily",
            owner_scope=scope,
            owner_project_id=source if private else None,
            label="copy-source",
            auth_mode="api_key",
            created_by=actor_id,
        )
        if not private:
            for project in [source] + ([target] if target_grant else []):
                await credentials.upsert_grant(
                    credential_id=credential.id,
                    project_id=project,
                    permitted_operations=frozenset({CredentialOperation.SEARCH}),
                    granted_by=actor_id,
                )
        binding = await ProjectBindingRepository(session).create(
            project_id=source,
            credential_id=credential.id,
            credential_scope=scope,
            route_label="source-route",
            priority=17,
            created_by=actor_id,
        )
        await session.commit()
    return binding


@pytest.mark.asyncio
async def test_copy_only_explicitly_selected_binding_versions_and_never_authority(
    tmp_path: Path,
) -> None:
    import sqlite3

    from freesearch.models.contracts import UsageEvent, UsageOperation
    from freesearch.models.observability import ExecutionAttribution
    from freesearch.persistence.bindings import ProjectBindingRepository
    from tests.fixtures.api_keys import issue_project_key

    boot = await bootstrap_fresh_alpha(tmp_path / "copy-bindings.db")
    try:
        admin = temp_principal(boot.admin_user)
        source = boot.default_project.id
        target, copier = await _copy_pair(boot.repository, source, admin, "bindings-target")
        binding = await _copy_binding(boot.repository, source, target.id, admin.id)
        await issue_project_key(boot.repository, owner=admin, project_id=source)
        await boot.repository.set_runtime_setting("secret.fake-test-slot", "fake-only-never-copy")
        await boot.repository.record_usage(
            UsageEvent(
                provider="tavily",
                operation=UsageOperation.SEARCH,
                units=3,
                observed_at=datetime.now(UTC),
            ),
            attribution=ExecutionAttribution(
                project_id=source, actor_type=ActorType.HUMAN, actor_id=admin.id
            ),
        )
        now = datetime.now(UTC)
        write_trace_spans(
            boot.repository.database_path,
            [
                TraceSpanRecord(
                    project_id=source,
                    actor_type=ActorType.HUMAN,
                    actor_id=admin.id,
                    span_id="source-history",
                    trace_id="f" * 32,
                    name="POST /search",
                    kind=TraceSpanKind.SERVER,
                    started_at=now,
                    ended_at=now,
                    duration_ms=0,
                    operation=TraceOperation.SEARCH,
                    user_id=str(admin.id),
                )
            ],
        )
        settings = SettingsService(boot.repository)
        request = SettingsCopyRequest(
            source_project_id=source,
            expected_source_revision=0,
            expected_target_revision=0,
            expected_system_revision=0,
            fields=("routing.max_attempts",),
        )
        preview = await settings.preview_copy(copier, target.id, request)
        assert len(preview.bindings) == 1
        assert preview.bindings[0].version == binding.version
        assert preview.bindings[0].selected is False
        assert preview.bindings[0].eligible is True
        implicit = await settings.apply_copy(copier, target.id, request)
        assert implicit.bindings_copied == []
        assert implicit.target_revision == 0
        selected = request.model_copy(update={"binding_versions": {binding.id: binding.version}})
        selected_preview = await settings.preview_copy(copier, target.id, selected)
        assert selected_preview.bindings[0].selected is True

        def authority_snapshot():
            with sqlite3.connect(boot.repository.database_path) as connection:
                tables = [
                    row[0]
                    for row in connection.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'"
                    )
                ]
                excluded = {
                    "project_provider_bindings",
                    "project_audit_events",
                    "sqlite_sequence",
                    "project_settings",
                }
                return {
                    table: connection.execute(f'SELECT * FROM "{table}" ORDER BY 1').fetchall()
                    for table in tables
                    if table not in excluded
                }

        before = authority_snapshot()
        async with boot.repository.session() as session:
            bindings_before = await ProjectBindingRepository(session).list_for_project(
                project_id=target.id
            )
        result = await settings.apply_copy(copier, target.id, selected)
        assert len(result.bindings_copied) == 1
        assert "fake-only-never-copy" not in result.model_dump_json()
        assert authority_snapshot() == before
        async with boot.repository.session() as session:
            copied = await ProjectBindingRepository(session).list_for_project(project_id=target.id)
        copied = [item for item in copied if item.id not in {row.id for row in bindings_before}]
        assert len(copied) == 1
        assert copied[0].credential_id == binding.credential_id
        assert copied[0].route_label == binding.route_label
        assert copied[0].priority == binding.priority
        assert copied[0].enabled_operations == frozenset()
        assert result.target_revision == 0
        assert result.target.overrides == {}
    finally:
        await boot.repository.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("reason", ["revoked", "unavailable", "private", "not_granted"])
async def test_copy_rechecks_binding_grant_status_and_private_ownership_at_apply(
    tmp_path: Path, reason: str
) -> None:
    from freesearch.models.settings import (
        COPY_CREDENTIAL_NOT_GRANTED,
        COPY_CREDENTIAL_PRIVATE,
        COPY_CREDENTIAL_UNAVAILABLE,
    )
    from freesearch.persistence.bindings import ProjectBindingRepository
    from freesearch.persistence.credentials import CredentialRepository, ProviderCredentialRow

    boot = await bootstrap_fresh_alpha(tmp_path / "copy-recheck.db")
    try:
        admin = temp_principal(boot.admin_user)
        source = boot.default_project.id
        target, copier = await _copy_pair(boot.repository, source, admin, "recheck-target")
        binding = await _copy_binding(
            boot.repository,
            source,
            target.id,
            admin.id,
            private=reason == "private",
            target_grant=reason != "not_granted",
        )
        settings = SettingsService(boot.repository)
        request = SettingsCopyRequest(
            source_project_id=source,
            expected_source_revision=0,
            expected_target_revision=0,
            expected_system_revision=0,
            fields=("routing.max_attempts",),
            binding_versions={binding.id: binding.version},
        )
        preview = await settings.preview_copy(copier, target.id, request)
        async with boot.repository.session() as session:
            bindings_before = await ProjectBindingRepository(session).list_for_project(
                project_id=target.id
            )
        if reason in {"revoked", "unavailable"}:
            assert preview.bindings[0].eligible is True
            async with boot.repository.session() as session:
                if reason == "revoked":
                    await CredentialRepository(session).delete_grant(
                        credential_id=binding.credential_id, project_id=target.id
                    )
                else:
                    await session.execute(
                        update(ProviderCredentialRow)
                        .where(ProviderCredentialRow.id == str(binding.credential_id))
                        .values(status="deleted")
                    )
                await session.commit()
        denied = await settings.apply_copy(copier, target.id, request)
        assert denied.bindings_copied == []
        assert denied.target_revision == 0
        assert denied.rejected
        fresh = await settings.preview_copy(copier, target.id, request)
        expected = (
            COPY_CREDENTIAL_PRIVATE
            if reason == "private"
            else COPY_CREDENTIAL_UNAVAILABLE
            if reason == "unavailable"
            else COPY_CREDENTIAL_NOT_GRANTED
        )
        assert fresh.bindings[0].rejection == expected
        assert fresh.bindings[0].eligible is False
        async with boot.repository.session() as session:
            assert (
                await ProjectBindingRepository(session).list_for_project(project_id=target.id)
                == bindings_before
            )
            events = await AuditRepository(session).list_project_events(project_id=target.id)
        assert len([event for event in events if event.action == "settings.copy"]) == 1
        assert (await settings.get_project_settings(copier, target.id)).project_revision == 0
    finally:
        await boot.repository.close()


@pytest.mark.asyncio
async def test_copy_binding_edit_or_unknown_selection_conflicts_with_preview(
    tmp_path: Path,
) -> None:
    from freesearch.models.credentials import CredentialOperation
    from freesearch.persistence.bindings import ProjectBindingRepository

    boot = await bootstrap_fresh_alpha(tmp_path / "copy-binding-revision.db")
    try:
        admin = temp_principal(boot.admin_user)
        source = boot.default_project.id
        target, copier = await _copy_pair(boot.repository, source, admin, "version-target")
        binding = await _copy_binding(boot.repository, source, target.id, admin.id)
        async with boot.repository.session() as session:
            bindings_before = await ProjectBindingRepository(session).list_for_project(
                project_id=target.id
            )
        settings = SettingsService(boot.repository)
        request = SettingsCopyRequest(
            source_project_id=source,
            expected_source_revision=0,
            expected_target_revision=0,
            expected_system_revision=0,
            binding_versions={binding.id: binding.version},
        )
        assert (await settings.preview_copy(copier, target.id, request)).bindings[0].eligible
        async with boot.repository.session() as session:
            changed = await ProjectBindingRepository(session).update(
                project_id=source,
                binding_id=binding.id,
                enabled_operations=frozenset({CredentialOperation.SEARCH}),
                route_label="changed-route",
                priority=5,
            )
            assert changed.version == binding.version + 1
            await session.commit()
        for stale in [request, request.model_copy(update={"binding_versions": {uuid4(): 1}})]:
            with pytest.raises(SettingsRevisionConflict):
                await settings.preview_copy(copier, target.id, stale)
            with pytest.raises(SettingsRevisionConflict):
                await settings.apply_copy(copier, target.id, stale)
        async with boot.repository.session() as session:
            assert (
                await ProjectBindingRepository(session).list_for_project(project_id=target.id)
                == bindings_before
            )
    finally:
        await boot.repository.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "reader_mode",
    ["trace_policy", "execution_scope_human", "execution_scope_api_key"],
)
async def test_consistent_read_snapshot_prevents_phantom_full_policy_interleaving(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, reader_mode: str
) -> None:
    """Interleaved writer changes must not leak phantom FULL trace policy to a concurrent reader.

    Initial state: SYSTEM=metadata, PROJECT=full -> effective: metadata.
    Writer: updates PROJECT->metadata, then SYSTEM->full.
    Both durable states allow metadata only. With a deferred SQLite read snapshot
    established before authorization and settings reads, the reader never sees
    old PROJECT (full) + new SYSTEM (full).
    """
    from freesearch.models.projects import (
        PermissionAction,
        ProjectApiKeyPrincipal,
        TraceDetailPolicy,
    )
    from freesearch.models.settings import (
        ProjectSettingsUpdate,
        SystemSettingsUpdate,
        SystemTraceDefaults,
        TraceSettings,
    )
    from freesearch.persistence.scoped import ScopedProjectSettings
    from freesearch.services.authorization import human_principal
    from freesearch.services.execution_scope import resolve_execution_boundary
    from freesearch.services.settings import project_trace_policy
    from tests.fixtures.api_keys import issue_project_key

    boot = await bootstrap_fresh_alpha(tmp_path / f"snap-{reader_mode}.db")
    try:
        admin = temp_principal(boot.admin_user)
        human_admin = human_principal(admin)
        project_id = boot.default_project.id
        settings = SettingsService(boot.repository)

        # Initial durable state: SYSTEM=metadata, PROJECT=full
        await settings.update_system_settings(
            admin,
            SystemSettingsUpdate(
                expected_revision=0,
                trace=SystemTraceDefaults(detail=TraceDetailPolicy.METADATA),
            ),
        )
        await settings.update_project_settings(
            admin,
            project_id,
            ProjectSettingsUpdate(
                expected_revision=0,
                trace=TraceSettings(detail=TraceDetailPolicy.FULL),
            ),
        )

        api_key_principal: ProjectApiKeyPrincipal | None = None
        if reader_mode == "execution_scope_api_key":
            key = await issue_project_key(boot.repository, owner=admin, project_id=project_id)
            api_key_principal = ProjectApiKeyPrincipal(
                project_id=project_id,
                api_key_id=key.api_key_id,
                scopes=frozenset({"search.execute"}),
            )

        project_read_done = asyncio.Event()
        writer_done = asyncio.Event()
        interleaved = False

        real_scoped_read = ScopedProjectSettings.read

        async def intercepted_read(self_scoped: ScopedProjectSettings):
            stored = await real_scoped_read(self_scoped)
            nonlocal interleaved
            if self_scoped._project_id == project_id and not interleaved:
                interleaved = True
                project_read_done.set()
                await writer_done.wait()
            return stored

        monkeypatch.setattr(ScopedProjectSettings, "read", intercepted_read)

        async def reader_task():
            if reader_mode == "trace_policy":
                context = await ScopedAuthorizationService(boot.repository).resolve_project_context(
                    human_admin, project_id
                )
                assert context is not None
                return await project_trace_policy(boot.repository, context)
            elif reader_mode == "execution_scope_human":
                boundary = await resolve_execution_boundary(
                    boot.repository,
                    human_admin,
                    project_id=project_id,
                    action=PermissionAction.SEARCH_EXECUTE,
                )
                return boundary.trace_policy
            else:
                boundary = await resolve_execution_boundary(
                    boot.repository,
                    api_key_principal,
                    project_id=project_id,
                    action=PermissionAction.SEARCH_EXECUTE,
                )
                return boundary.trace_policy

        async def writer_task():
            await project_read_done.wait()
            # Independent writer commits: PROJECT -> metadata (rev 2), then SYSTEM -> full (rev 2)
            await settings.update_project_settings(
                admin,
                project_id,
                ProjectSettingsUpdate(
                    expected_revision=1,
                    trace=TraceSettings(detail=TraceDetailPolicy.METADATA),
                ),
            )
            await settings.update_system_settings(
                admin,
                SystemSettingsUpdate(
                    expected_revision=1,
                    trace=SystemTraceDefaults(detail=TraceDetailPolicy.FULL),
                ),
            )
            writer_done.set()

        policy, _ = await asyncio.gather(reader_task(), writer_task())
        assert policy is not None
        assert policy.detail == TraceDetailPolicy.METADATA
        assert policy.captures_payload is False
    finally:
        await boot.repository.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("operation_type", ["edit", "copy"])
async def test_commit_failure_after_computation_does_not_publish_stale_cache_for_edit_and_copy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, operation_type: str
) -> None:
    """Commit failure after computation must roll back DB and not leave stale uncommitted cache.

    Injects commit failure after edit/copy computation so DB transaction rolls back.
    Then an independent writer writes a valid revision 1 with cache_enabled=True.
    The original service must return cache_enabled=True, not stale False from failed write.
    """
    from sqlalchemy.exc import OperationalError
    from sqlalchemy.ext.asyncio import AsyncSession

    from freesearch.models.settings import (
        ExecutionSettings,
        ProjectSettingsUpdate,
        SettingsCopyRequest,
    )
    from freesearch.services.settings import SETTINGS_NAMESPACE, SettingsStorageUnavailable

    boot = await bootstrap_fresh_alpha(tmp_path / f"commit-cache-{operation_type}.db")
    try:
        admin = temp_principal(boot.admin_user)
        source_id = boot.default_project.id
        settings = SettingsService(boot.repository)

        if operation_type == "copy":
            # Set source project to cache_enabled=False
            await settings.update_project_settings(
                admin,
                source_id,
                ProjectSettingsUpdate(
                    expected_revision=0,
                    execution=ExecutionSettings(cache_enabled=False),
                ),
            )
            target, copier = await _copy_pair(boot.repository, source_id, admin, "copy-target")
            target_id = target.id
            actor = copier
            copy_request = SettingsCopyRequest(
                source_project_id=source_id,
                expected_source_revision=1,
                expected_target_revision=0,
                expected_system_revision=0,
                fields=("execution.cache_enabled",),
            )
        else:
            target_id = source_id
            actor = admin
            edit_request = ProjectSettingsUpdate(
                expected_revision=0,
                execution=ExecutionSettings(cache_enabled=False),
            )

        # Force COMMIT failure AFTER computation
        injected = False
        real_commit = AsyncSession.commit

        async def failing_commit(self_session: AsyncSession) -> None:
            nonlocal injected
            if not injected:
                injected = True
                raise OperationalError("COMMIT", {}, Exception("injected commit failure"))
            await real_commit(self_session)

        monkeypatch.setattr(AsyncSession, "commit", failing_commit)

        with pytest.raises(SettingsStorageUnavailable):
            if operation_type == "copy":
                await settings.apply_copy(actor, target_id, copy_request)
            else:
                await settings.update_project_settings(actor, target_id, edit_request)

        assert injected is True

        # Restore healthy commit
        monkeypatch.setattr(AsyncSession, "commit", real_commit)

        # Verify DB rollback: target project settings is still revision 0 (or absent)
        from freesearch.models.settings import SETTINGS_SCHEMA_VERSION
        from freesearch.persistence.settings import ProjectSettingsRepository

        async with boot.repository.session() as session:
            stored = await ProjectSettingsRepository(session).get(
                project_id=target_id, namespace=SETTINGS_NAMESPACE
            )
            assert stored is None or stored.revision == 0

        # Independent RAW DB writer writes valid revision 1 with cache_enabled=True,
        # bypassing SettingsService to avoid triggering cache invalidation.
        async with boot.repository.session() as session:
            repo = ProjectSettingsRepository(session)
            applied = await repo.compare_and_set(
                project_id=target_id,
                namespace=SETTINGS_NAMESPACE,
                schema_version=SETTINGS_SCHEMA_VERSION,
                overrides={"execution": {"cache_enabled": True}},
                expected_revision=0,
            )
            assert applied is True
            await session.commit()

        # Original service queries settings; must return cache_enabled=True
        resolved = await settings.get_project_settings(actor, target_id)
        assert resolved.project_revision == 1
        assert resolved.effective_settings["execution.cache_enabled"] is True
    finally:
        await boot.repository.close()
