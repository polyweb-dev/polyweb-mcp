"""P03 service: inheritance, provenance, constraints, revisions, context, cache."""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import textwrap
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import update

from freesearch.models.contracts import FallbackPolicy
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
)
from freesearch.models.settings import (
    ProjectSettingsUpdate,
    SystemExecutionDefaults,
    SystemRoutingDefaults,
    SystemSafetyLimits,
    SystemSettingsUpdate,
)
from freesearch.models.users import UserPrincipal
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
from freesearch.services.projects import ProjectService
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
                    preferred_providers=("exa", "tavily"),
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
                    preferred_providers=("brave", "exa"),
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
        assert written.effective_settings["routing.preferred_providers"] == ["brave", "exa"]
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
        assert written.fields["routing.preferred_providers"].project_override == ["brave", "exa"]
        assert written.fields["system.max_timeout_seconds"].override_allowed is False
        assert written.overrides["execution.default_timeout_seconds"] == 120.0
        assert written.overrides["execution.max_fanout_concurrency"] == 15
        assert written.overrides["execution.cache_enabled"] is False
        assert written.overrides["execution.cache_ttl_seconds"] == 0
        assert written.overrides["routing.preferred_providers"] == ["brave", "exa"]

        system2 = await service.update_system_settings(
            admin,
            SystemSettingsUpdate(
                expected_revision=1,
                routing=SystemRoutingDefaults(
                    max_attempts=6,
                    preferred_providers=("tavily",),
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
        assert after_system_change.effective_settings["routing.preferred_providers"] == [
            "brave",
            "exa",
        ]
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
                    preferred_providers=("exa",),
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
                    preferred_providers=("brave", "exa"),
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
        assert retained.effective_settings["routing.preferred_providers"] == ["brave", "exa"]
        assert retained.effective_settings["execution.cache_enabled"] is False
        assert retained.effective_settings["execution.default_timeout_seconds"] == 45.0
        assert retained.effective_settings["execution.max_fanout_concurrency"] == 5
        assert retained.effective_settings["execution.cache_ttl_seconds"] == 30

        empty_list = await service.update_project_settings(
            admin,
            project_id,
            ProjectSettingsUpdate(
                expected_revision=2,
                routing=RoutingSettings(preferred_providers=()),
            ),
        )
        assert empty_list.project_revision == 3
        assert empty_list.effective_settings["routing.preferred_providers"] == []
        assert empty_list.fields["routing.preferred_providers"].provenance is (
            SettingsProvenance.PROJECT_OVERRIDE
        )
        assert empty_list.effective_settings["routing.max_attempts"] == 5

        replaced = await service.update_project_settings(
            admin,
            project_id,
            ProjectSettingsUpdate(
                expected_revision=3,
                routing=RoutingSettings(preferred_providers=("tavily",)),
            ),
        )
        assert replaced.project_revision == 4
        assert replaced.effective_settings["routing.preferred_providers"] == ["tavily"]

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
        assert field_reset.effective_settings["routing.preferred_providers"] == ["tavily"]

        routing_reset = await service.update_project_settings(
            admin,
            project_id,
            ProjectSettingsUpdate(expected_revision=5, routing=None),
        )
        assert routing_reset.project_revision == 6
        assert routing_reset.effective_settings["routing.fallback_policy"] == "chained"
        assert routing_reset.effective_settings["routing.max_attempts"] == 3
        assert routing_reset.effective_settings["routing.preferred_providers"] == ["exa"]
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
                routing=RoutingSettings(max_attempts=5, preferred_providers=("exa",)),
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
        assert unchanged.effective_settings["routing.preferred_providers"] == ["exa"]
        assert unchanged.effective_settings["execution.cache_enabled"] is False

        with pytest.raises(SettingsValidationError, match="unknown provider"):
            await service.update_project_settings(
                admin,
                project_id,
                ProjectSettingsUpdate(
                    expected_revision=1,
                    routing=RoutingSettings(preferred_providers=("ghost",)),
                ),
            )
        after_invalid = await service.get_project_settings(admin, project_id)
        assert after_invalid.project_revision == 1
        assert after_invalid.effective_settings["routing.preferred_providers"] == ["exa"]

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

        with pytest.raises(SettingsValidationError, match="unknown provider"):
            await service.update_system_settings(
                admin,
                SystemSettingsUpdate(
                    expected_revision=1,
                    routing=SystemRoutingDefaults(preferred_providers=("ghost",)),
                ),
            )
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
            system_actor=admin,
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
                initial_role=BuiltinRole.TOKEN_MANAGER.value,
            ),
        )
        token_manager_context = await authorization.resolve_project_context(
            human_principal(token_manager), project_id
        )
        assert token_manager_context is not None
        assert PermissionAction.SETTINGS_READ not in token_manager_context.effective_permissions
        assert PermissionAction.PROJECT_READ in token_manager_context.effective_permissions
        with pytest.raises(AuthorizationDenied):
            await service.get_project_settings(token_manager, project_id)
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
