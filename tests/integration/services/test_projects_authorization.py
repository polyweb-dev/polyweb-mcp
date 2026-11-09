"""Project lifecycle, scoped authorization, and last-administrator invariants.

The concurrency cases use two independent SQLiteRepository connections on the
same temporary file. No test opens the developer's live database or any real
provider credential.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from uuid import UUID

import pytest
from sqlalchemy import select

from polyweb.models.project_permissions import ProjectPermission
from polyweb.models.projects import (
    DEFAULT_INSTALLATION_ACCOUNT_ID,
    BuiltinRole,
    MembershipStatus,
    PermissionAction,
    ProjectCreate,
    ProjectMemberAdd,
    ProjectMemberChange,
    ProjectMembersBulkUpdate,
    ProjectMemberUpdate,
    ProjectRead,
    ProjectStatus,
    ScopeType,
)
from polyweb.models.users import UserPrincipal
from polyweb.persistence.projects import (
    ProjectMembershipRow,
    ProjectRepository,
    bootstrap_fresh_installation,
)
from polyweb.persistence.storage import SQLiteRepository
from polyweb.persistence.users import UserRow
from polyweb.services.authorization import (
    AuthorizationDenied,
    ScopedAuthorizationService,
    human_principal,
)
from polyweb.services.projects import (
    LAST_PROJECT_ADMIN,
    PROJECT_ARCHIVED,
    ProjectConflict,
    ProjectNotFound,
    ProjectService,
    ProjectValidationError,
)
from tests.fixtures.alpha_fixtures import create_alpha_test_db
from tests.fixtures.auth import (
    TEMP_PASSWORD,
    create_temp_user,
    http_jwt_service,
    temp_email,
    temp_principal,
)

#: Outcome of a concurrent writer whose actor assignment the other writer
#: revoked first. It is not accepted as a generic error: each test below names
#: exactly which operation may return it and in which interleaving.
_AUTHORIZATION_DENIED_OUTCOME = "AUTHORIZATION_DENIED"
#: R5: an actor whose own membership or account the other writer removed first
#: is no longer a member, so it gets the project's not-found outcome.
_NOT_FOUND_OUTCOME = "NOT_FOUND"


async def _seed_installation_admin(
    repository: SQLiteRepository,
) -> UserPrincipal:
    user = await create_temp_user(repository, temp_email("p02-sys"))
    async with repository.session() as session:
        await bootstrap_fresh_installation(session, user.id)
        await session.commit()
    return temp_principal(user)


async def _create_ownerless_project(
    repository: SQLiteRepository, system: UserPrincipal, project_create: ProjectCreate
) -> ProjectRead:
    """Deactivate the creator to exercise last-admin guards without an owner guard."""

    creator = temp_principal(
        await create_temp_user(repository, temp_email("p02-creator"), system_admin=True)
    )
    service = ProjectService(repository)
    project = await service.create_project(creator, project_create)
    await service.deactivate_accounts([creator.id], actor=system)
    async with repository.session() as session:
        assert await ProjectRepository(session).get_provider_owner(project.id) is None
    return project


async def _count_admins(repository: SQLiteRepository, project_id: UUID) -> int:
    async with repository.session() as session:
        return await ProjectRepository(session).count_active_project_admins(project_id=project_id)


async def _members(repository: SQLiteRepository, project_id: UUID) -> list[ProjectMembershipRow]:
    async with repository.session() as session:
        return list(
            (
                await session.execute(
                    select(ProjectMembershipRow).where(
                        ProjectMembershipRow.project_id == str(project_id)
                    )
                )
            )
            .scalars()
            .all()
        )


@pytest.mark.asyncio
async def test_project_lifecycle_scope_and_system_admin_non_membership(
    tmp_path: Path,
) -> None:
    repository = await create_alpha_test_db(tmp_path / "p02-lifecycle.db")
    try:
        system = await _seed_installation_admin(repository)
        nonmember_system = temp_principal(
            await create_temp_user(repository, temp_email("p02-other-sys"), system_admin=True)
        )
        admin_row = await create_temp_user(repository, temp_email("p02-admin"))
        member_row = await create_temp_user(repository, temp_email("p02-member"))
        admin = temp_principal(admin_row)
        member = temp_principal(member_row)
        service = ProjectService(repository)

        project = await service.create_project(
            system,
            ProjectCreate(name="Alpha", slug="alpha", initial_admin_user_id=admin.id),
        )

        # The creator is an admin and provider owner, but system authority alone
        # does not make another system administrator a project member.
        assert [item.id for item in await service.list_projects(system)] == [project.id]
        assert (await service.provider_owner(system, project.id)).user_id == system.id
        assert await service.list_projects(nonmember_system) == []
        assert [item.id for item in await service.list_projects(admin)] == [project.id]
        authorization = ScopedAuthorizationService(repository)
        project_permissions = await authorization.effective_permissions(
            human_principal(admin),
            scope_type=ScopeType.PROJECT,
            scope_id=project.id,
        )
        assert PermissionAction.PROJECT_ARCHIVE in project_permissions
        system_project_permissions = await authorization.effective_permissions(
            human_principal(nonmember_system),
            scope_type=ScopeType.PROJECT,
            scope_id=project.id,
        )
        assert system_project_permissions == frozenset()
        # R5: a non-member gets the inaccessible-project not-found, not 403.
        with pytest.raises(ProjectNotFound):
            await service.list_members(nonmember_system, project.id)

        # A project administrator can add a developer and grant individual permissions.
        await service.add_member(
            admin,
            project.id,
            ProjectMemberAdd(user_id=member.id),
        )
        members = await service.list_members(admin, project.id)
        assert {item.user_id for item in members} == {system.id, admin.id, member.id}
        await service.update_member(
            admin,
            project.id,
            member.id,
            ProjectMemberUpdate(permissions=int(ProjectPermission.PROVIDERS_CONFIGURE)),
        )
        member_roles = await service.list_members(admin, project.id)
        member_record = next(item for item in member_roles if item.user_id == member.id)
        assert member_record.permissions == int(ProjectPermission.PROVIDERS_CONFIGURE)
        with pytest.raises(ProjectValidationError):
            await service.assign_role(
                admin,
                project.id,
                member.id,
                BuiltinRole.SYSTEM_ADMIN.value,
            )

        # A plain member has read/execute access, not archive or role authority.
        with pytest.raises(AuthorizationDenied):
            await service.archive_project(member, project.id)
        with pytest.raises(AuthorizationDenied):
            await service.assign_role(
                member,
                project.id,
                member.id,
                BuiltinRole.PROJECT_ADMIN.value,
            )

        # A project administrator cannot create another project (system scope).
        with pytest.raises(AuthorizationDenied):
            await service.create_project(
                admin,
                ProjectCreate(
                    name="Not Allowed",
                    slug="not-allowed",
                    initial_admin_user_id=admin.id,
                ),
            )

        await service.transfer_provider_owner(system, project.id, admin.id)
        await service.remove_member(system, project.id, system.id)
        archived = await service.archive_project(admin, project.id)
        assert archived.status is ProjectStatus.ARCHIVED
        with pytest.raises(ProjectConflict) as archived_write:
            await service.add_member(
                admin,
                project.id,
                ProjectMemberAdd(user_id=member.id),
            )
        assert archived_write.value.code == PROJECT_ARCHIVED
        with pytest.raises(ProjectConflict) as owner_guard:
            await service.remove_member(admin, project.id, admin.id)
        assert owner_guard.value.code == "PROVIDER_OWNER_REQUIRED"
        assert await _count_admins(repository, project.id) == 1
    finally:
        await repository.close()


@pytest.mark.asyncio
async def test_same_human_has_different_roles_without_account_conversion(
    tmp_path: Path,
) -> None:
    repository = await create_alpha_test_db(tmp_path / "p02-two-projects.db")
    try:
        system = await _seed_installation_admin(repository)
        human_row = await create_temp_user(repository, temp_email("p02-human"))
        other_row = await create_temp_user(repository, temp_email("p02-other"))
        human = temp_principal(human_row)
        other = temp_principal(other_row)
        service = ProjectService(repository)

        project_a = await service.create_project(
            system,
            ProjectCreate(
                name="Project A",
                slug="project-a",
                initial_admin_user_id=human.id,
            ),
        )
        project_b = await service.create_project(
            system,
            ProjectCreate(
                name="Project B",
                slug="project-b",
                initial_admin_user_id=other.id,
            ),
        )
        await service.add_member(
            other,
            project_b.id,
            ProjectMemberAdd(user_id=human.id),
        )

        async with repository.session() as session:
            rows = (
                (
                    await session.execute(
                        select(UserRow).where(UserRow.email == human_row.email)  # type: ignore[arg-type]
                    )
                )
                .scalars()
                .all()
            )
            assert len(rows) == 1
            stored = rows[0]
            assert stored.auth_provider == human_row.auth_provider
            assert stored.auth_provider_id == human_row.auth_provider_id
            assert stored.hashed_password == human_row.hashed_password
            assert (
                await ProjectRepository(session).get_system_role_assignments(
                    account_id=DEFAULT_INSTALLATION_ACCOUNT_ID,
                    user_id=human.id,
                )
                == []
            )

        authorization = ScopedAuthorizationService(repository)
        permissions_a = await authorization.effective_permissions(
            human_principal(human), scope_type=ScopeType.PROJECT, scope_id=project_a.id
        )
        permissions_b = await authorization.effective_permissions(
            human_principal(human), scope_type=ScopeType.PROJECT, scope_id=project_b.id
        )
        assert PermissionAction.PROJECT_ARCHIVE in permissions_a
        assert PermissionAction.PROJECT_ARCHIVE not in permissions_b
        assert PermissionAction.MEMBERS_MANAGE in permissions_a
        assert PermissionAction.MEMBERS_MANAGE not in permissions_b

        listed = await service.list_projects(human)
        assert {item.id for item in listed} == {project_a.id, project_b.id}
        with pytest.raises(AuthorizationDenied):
            await service.archive_project(human, project_b.id)
    finally:
        await repository.close()


@pytest.mark.asyncio
async def test_legacy_admin_and_superuser_claims_do_not_grant_live_scope(
    tmp_path: Path,
) -> None:
    """Legacy account flags are display compatibility, not live authority."""

    repository = await create_alpha_test_db(tmp_path / "p02-legacy-claims.db")
    try:
        system = await _seed_installation_admin(repository)
        human_row = await create_temp_user(repository, temp_email("p02-legacy"))
        forged = temp_principal(human_row).model_copy(
            update={
                "role": "admin",
                "is_superuser": True,
                "is_active": True,
            }
        )
        service = ProjectService(repository)

        with pytest.raises(AuthorizationDenied):
            await service.create_project(
                forged,
                ProjectCreate(
                    name="Forged",
                    slug="forged",
                    initial_admin_user_id=forged.id,
                ),
            )
        with pytest.raises(AuthorizationDenied):
            await service.deactivate_accounts([forged.id], actor=forged)

        project = await service.create_project(
            system,
            ProjectCreate(
                name="Explicit",
                slug="explicit",
                initial_admin_user_id=system.id,
            ),
        )
        assert await service.list_projects(forged) == []
        assert (
            await ScopedAuthorizationService(repository).effective_permissions(
                human_principal(forged), scope_type=ScopeType.PROJECT, scope_id=project.id
            )
            == frozenset()
        )
        with pytest.raises(ProjectNotFound):
            await service.list_members(forged, project.id)
        await service.add_member(
            system,
            project.id,
            ProjectMemberAdd(user_id=forged.id, initial_role=BuiltinRole.PROJECT_ADMIN.value),
        )
        # The same forged claims are irrelevant in project scope: the explicit
        # project_admin membership is the only reason the read succeeds.
        assert {item.user_id for item in await service.list_members(forged, project.id)} == {
            forged.id,
            system.id,
        }
        with pytest.raises(AuthorizationDenied):
            await service.create_project(
                forged,
                ProjectCreate(
                    name="Still Forged",
                    slug="still-forged",
                    initial_admin_user_id=forged.id,
                ),
            )
    finally:
        await repository.close()


@pytest.mark.asyncio
async def test_last_admin_guards_self_removal_demotion_bulk_and_rollback(
    tmp_path: Path,
) -> None:
    repository = await create_alpha_test_db(tmp_path / "p02-last-admin.db")
    try:
        system = await _seed_installation_admin(repository)
        admin_row = await create_temp_user(repository, temp_email("p02-admin"))
        peer_row = await create_temp_user(repository, temp_email("p02-peer"))
        bystander_row = await create_temp_user(repository, temp_email("p02-bystander"))
        admin = temp_principal(admin_row)
        peer = temp_principal(peer_row)
        bystander = temp_principal(bystander_row)
        service = ProjectService(repository)
        project = await _create_ownerless_project(
            repository,
            system,
            ProjectCreate(name="Guarded", slug="guarded", initial_admin_user_id=admin.id),
        )
        await service.add_member(
            admin,
            project.id,
            ProjectMemberAdd(user_id=bystander.id),
        )

        with pytest.raises(ProjectConflict) as removal:
            await service.remove_member(admin, project.id, admin.id)
        assert removal.value.code == LAST_PROJECT_ADMIN
        with pytest.raises(ProjectConflict) as suspension:
            await service.update_member(
                admin,
                project.id,
                admin.id,
                ProjectMemberUpdate(status=MembershipStatus.SUSPENDED),
            )
        assert suspension.value.code == LAST_PROJECT_ADMIN
        with pytest.raises(ProjectConflict) as demotion:
            await service.remove_role(
                admin,
                project.id,
                admin.id,
                BuiltinRole.PROJECT_ADMIN.value,
            )
        assert demotion.value.code == LAST_PROJECT_ADMIN
        with pytest.raises(ProjectConflict) as bulk:
            await service.bulk_update_members(
                admin,
                project.id,
                ProjectMembersBulkUpdate(
                    changes=[
                        ProjectMemberChange(
                            user_id=bystander.id,
                            status=MembershipStatus.SUSPENDED,
                        ),
                        ProjectMemberChange(
                            user_id=admin.id,
                            role="developer",
                        ),
                    ]
                ),
            )
        assert bulk.value.code == LAST_PROJECT_ADMIN

        # The failed bulk change left its bystander status untouched.
        members = await _members(repository, project.id)
        bystander_status = next(
            item.status for item in members if item.user_id == str(bystander.id)
        )
        assert bystander_status == MembershipStatus.ACTIVE.value
        assert await _count_admins(repository, project.id) == 1

        await service.add_member(
            admin,
            project.id,
            ProjectMemberAdd(
                user_id=peer.id,
                initial_role=BuiltinRole.PROJECT_ADMIN.value,
            ),
        )
        await service.remove_member(admin, project.id, admin.id)
        assert await _count_admins(repository, project.id) == 1
        with pytest.raises(ProjectConflict) as last_peer:
            await service.remove_member(peer, project.id, peer.id)
        assert last_peer.value.code == LAST_PROJECT_ADMIN
    finally:
        await repository.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["remove", "suspend", "demote", "remove_role", "bulk"])
async def test_provider_owner_cannot_lose_membership_or_admin_before_transfer(
    tmp_path: Path, change: str
) -> None:
    repository = await create_alpha_test_db(tmp_path / "owner-guard.db")
    try:
        owner = await _seed_installation_admin(repository)
        peer = temp_principal(await create_temp_user(repository, temp_email("p02-owner-peer")))
        bystander = temp_principal(
            await create_temp_user(repository, temp_email("p02-owner-bystander"))
        )
        service = ProjectService(repository)
        project = await service.create_project(
            owner,
            ProjectCreate(name="Owner guard", slug="owner-guard", initial_admin_user_id=peer.id),
        )
        await service.add_member(peer, project.id, ProjectMemberAdd(user_id=bystander.id))

        async def mutate() -> None:
            if change == "remove":
                await service.remove_member(peer, project.id, owner.id)
            elif change == "suspend":
                await service.update_member(
                    peer,
                    project.id,
                    owner.id,
                    ProjectMemberUpdate(status=MembershipStatus.SUSPENDED),
                )
            elif change == "demote":
                await service.update_member(
                    peer, project.id, owner.id, ProjectMemberUpdate(role="developer")
                )
            elif change == "remove_role":
                await service.remove_role(
                    peer, project.id, owner.id, BuiltinRole.PROJECT_ADMIN.value
                )
            else:
                await service.bulk_update_members(
                    peer,
                    project.id,
                    ProjectMembersBulkUpdate(
                        changes=[
                            ProjectMemberChange(
                                user_id=bystander.id, status=MembershipStatus.SUSPENDED
                            ),
                            ProjectMemberChange(user_id=owner.id, role="developer"),
                        ]
                    ),
                )

        with pytest.raises(ProjectConflict) as refused:
            await mutate()
        assert refused.value.code == "PROVIDER_OWNER_REQUIRED"
        assert await _count_admins(repository, project.id) == 2
        assert (await service.provider_owner(peer, project.id)).user_id == owner.id
        members = await _members(repository, project.id)
        assert {item.user_id: item.status for item in members} == {
            str(owner.id): MembershipStatus.ACTIVE.value,
            str(peer.id): MembershipStatus.ACTIVE.value,
            str(bystander.id): MembershipStatus.ACTIVE.value,
        }

        await service.transfer_provider_owner(owner, project.id, peer.id)
        await mutate()
        assert (await service.provider_owner(peer, project.id)).user_id == peer.id
        assert await _count_admins(repository, project.id) == 1
    finally:
        await repository.close()


@pytest.mark.asyncio
async def test_account_deactivation_guard_bulk_and_live_revocation(
    tmp_path: Path,
    auth_secret: str,
) -> None:
    repository = await create_alpha_test_db(tmp_path / "p02-deactivate.db")
    try:
        system = await _seed_installation_admin(repository)
        service = ProjectService(repository)
        admin_row = await create_temp_user(repository, temp_email("p02-admin"))
        peer_row = await create_temp_user(repository, temp_email("p02-peer"))
        admin = temp_principal(admin_row)
        peer = temp_principal(peer_row)
        project = await _create_ownerless_project(
            repository,
            system,
            ProjectCreate(
                name="Deactivation",
                slug="deactivation",
                initial_admin_user_id=admin.id,
            ),
        )

        with pytest.raises(ProjectConflict) as last_admin:
            await service.deactivate_accounts([admin.id], actor=system)
        assert last_admin.value.code == LAST_PROJECT_ADMIN
        async with repository.session() as session:
            stored = await session.get(UserRow, admin.id)
            assert stored is not None and stored.is_active is True

        with pytest.raises(AuthorizationDenied):
            await service.deactivate_accounts([admin.id], actor=admin)

        # A live token stops authorizing as soon as the account is deactivated.
        auth = http_jwt_service(repository)
        from fastapi.security import OAuth2PasswordRequestForm

        tokens = await auth.login(
            OAuth2PasswordRequestForm(
                username=admin_row.email,
                password=TEMP_PASSWORD,
            ),
            peer_address="p02-deactivate-probe",
        )
        assert tokens is not None

        await service.add_member(
            admin,
            project.id,
            ProjectMemberAdd(
                user_id=peer.id,
                initial_role=BuiltinRole.PROJECT_ADMIN.value,
            ),
        )
        deactivated = await service.deactivate_accounts([admin.id], actor=system)
        assert deactivated[0].is_active is False
        assert await auth.verify_token(tokens.access_token.get_secret_value()) is None
        assert await _count_admins(repository, project.id) == 1

        # An inactive account cannot be re-added; a third active human is the
        # valid peer for the remaining bulk-deactivation scenario.
        with pytest.raises(ProjectValidationError):
            await service.add_member(
                peer,
                project.id,
                ProjectMemberAdd(
                    user_id=admin.id,
                    initial_role=BuiltinRole.PROJECT_ADMIN.value,
                ),
            )
        replacement_row = await create_temp_user(repository, temp_email("p02-replacement"))
        replacement = temp_principal(replacement_row)
        await service.add_member(
            peer,
            project.id,
            ProjectMemberAdd(
                user_id=replacement.id,
                initial_role=BuiltinRole.PROJECT_ADMIN.value,
            ),
        )
        assert await _count_admins(repository, project.id) == 2

        # Bulk deactivation of both remaining admins, plus the already-inactive
        # former admin, is atomic and rejected.
        with pytest.raises(ProjectConflict) as bulk:
            await service.deactivate_accounts([admin.id, peer.id, replacement.id], actor=system)
        assert bulk.value.code == LAST_PROJECT_ADMIN
        async with repository.session() as session:
            rows = {
                user.id: user.is_active
                for user in (
                    await session.execute(
                        select(UserRow).where(
                            UserRow.id.in_(  # type: ignore[attr-defined]
                                [admin.id, peer.id, replacement.id]
                            )
                        )
                    )
                )
                .scalars()
                .all()
            }
        assert rows == {admin.id: False, peer.id: True, replacement.id: True}
        assert await _count_admins(repository, project.id) == 2
    finally:
        await repository.close()


async def _prepare_race(
    tmp_path: Path, name: str
) -> tuple[SQLiteRepository, SQLiteRepository, ProjectService, UserPrincipal, UserPrincipal, UUID]:
    first = await create_alpha_test_db(tmp_path / name)
    second = await SQLiteRepository.open(first.database_path)
    assert first is not second
    assert first.database_path == second.database_path
    async with first.session() as first_session, second.session() as second_session:
        assert first_session.bind is not second_session.bind
    system = await _seed_installation_admin(first)
    admin_row = await create_temp_user(first, temp_email("p02-race-a"))
    peer_row = await create_temp_user(first, temp_email("p02-race-b"))
    admin = temp_principal(admin_row)
    peer = temp_principal(peer_row)
    project = await _create_ownerless_project(
        first,
        system,
        ProjectCreate(name=name, slug=name.replace(" ", "-"), initial_admin_user_id=admin.id),
    )
    await ProjectService(first).add_member(
        admin,
        project.id,
        ProjectMemberAdd(
            user_id=peer.id,
            initial_role=BuiltinRole.PROJECT_ADMIN.value,
        ),
    )
    return first, second, ProjectService(first), admin, peer, project.id


@pytest.mark.asyncio
async def test_concurrent_self_removals_cannot_remove_both_admins(
    tmp_path: Path,
) -> None:
    first, second, _setup, admin, peer, project_id = await _prepare_race(tmp_path, "race-removal")
    try:
        assert first is not second
        barrier = asyncio.Barrier(2)

        async def remove_self(service: ProjectService, actor: UserPrincipal) -> str | None:
            await barrier.wait()
            try:
                await service.remove_member(actor, project_id, actor.id)
            except ProjectConflict as error:
                return error.code
            return None

        results = await asyncio.gather(
            remove_self(ProjectService(first), admin),
            remove_self(ProjectService(second), peer),
        )
        # Both actors remove only themselves, so the loser's own membership
        # remains valid and it must hit the administrator guard, not an auth
        # failure. Exactly one removal succeeds.
        assert results.count(None) == 1, results
        assert results.count(LAST_PROJECT_ADMIN) == 1, results
        assert await _count_admins(first, project_id) == 1
    finally:
        await second.close()
        await first.close()


@pytest.mark.asyncio
async def test_concurrent_demotion_and_account_deactivation_preserve_admin(
    tmp_path: Path,
) -> None:
    first, second, _setup, admin, peer, project_id = await _prepare_race(
        tmp_path, "race-deactivate"
    )
    try:
        system_row = await create_temp_user(first, temp_email("p02-race-sys"))
        async with first.session() as session:
            await bootstrap_fresh_installation(session, system_row.id)
            await session.commit()
        system = temp_principal(system_row)

        barrier = asyncio.Barrier(2)

        async def demote(
            service: ProjectService, actor: UserPrincipal, target: UserPrincipal
        ) -> str | None:
            await barrier.wait()
            try:
                await service.remove_role(
                    actor,
                    project_id,
                    target.id,
                    BuiltinRole.PROJECT_ADMIN.value,
                )
            except ProjectConflict as error:
                return error.code
            except AuthorizationDenied:
                return _AUTHORIZATION_DENIED_OUTCOME
            except ProjectNotFound:
                return _NOT_FOUND_OUTCOME
            return None

        async def deactivate(service: ProjectService) -> str | None:
            await barrier.wait()
            try:
                await service.deactivate_accounts([peer.id], actor=system)
            except ProjectConflict as error:
                return error.code
            return None

        results = await asyncio.gather(
            demote(ProjectService(first), peer, admin),
            deactivate(ProjectService(second)),
        )
        # If deactivation commits first, peer is inactive and demotion is
        # denied at the live auth check. If demotion commits first, deactivation
        # must roll back because admin is no longer an administrator. No third
        # outcome or partial change is accepted.
        demote_result, deactivate_result = results
        if deactivate_result is None:
            assert demote_result in (_AUTHORIZATION_DENIED_OUTCOME, _NOT_FOUND_OUTCOME)
        else:
            assert deactivate_result == LAST_PROJECT_ADMIN
            assert demote_result is None
        assert await _count_admins(first, project_id) == 1
        async with first.session() as session:
            peer_user = await session.get(UserRow, peer.id)
            admin_user = await session.get(UserRow, admin.id)
        assert peer_user is not None and admin_user is not None
        # A failed deactivation rolls back the whole account change.
        assert peer_user.is_active is (deactivate_result is not None)
        assert admin_user.is_active is True
    finally:
        await second.close()
        await first.close()


@pytest.mark.asyncio
async def test_concurrent_bulk_demotion_and_removal_preserve_admin(
    tmp_path: Path,
) -> None:
    first, second, _setup, admin, peer, project_id = await _prepare_race(tmp_path, "race-bulk")
    try:
        barrier = asyncio.Barrier(2)

        async def bulk_demote(service: ProjectService) -> str | None:
            await barrier.wait()
            try:
                await service.bulk_update_members(
                    peer,
                    project_id,
                    ProjectMembersBulkUpdate(
                        changes=[
                            ProjectMemberChange(
                                user_id=admin.id,
                                role="developer",
                            )
                        ]
                    ),
                )
            except ProjectConflict as error:
                return error.code
            except AuthorizationDenied:
                return _AUTHORIZATION_DENIED_OUTCOME
            except ProjectNotFound:
                return _NOT_FOUND_OUTCOME
            return None

        async def remove_peer(service: ProjectService) -> str | None:
            await barrier.wait()
            try:
                await service.remove_member(peer, project_id, peer.id)
            except ProjectConflict as error:
                return error.code
            return None

        results = await asyncio.gather(
            bulk_demote(ProjectService(first)),
            remove_peer(ProjectService(second)),
        )
        # If peer self-removal commits first, the bulk demotion's actor is gone
        # and it must be denied. If bulk demotion commits first, peer is the
        # only administrator and self-removal must roll back with LAST_PROJECT_ADMIN.
        bulk_result, remove_result = results
        if remove_result is None:
            assert bulk_result in (_AUTHORIZATION_DENIED_OUTCOME, _NOT_FOUND_OUTCOME)
        else:
            assert remove_result == LAST_PROJECT_ADMIN
            assert bulk_result is None
        assert await _count_admins(first, project_id) == 1
    finally:
        await second.close()
        await first.close()


# --- A1 (TASK-000041) AC3: more last-active-admin races -------------------------


async def _independent_admin_count(repository: SQLiteRepository, project_id: UUID) -> int:
    """Count active admins with raw SQL, independent of the repository helper."""

    from sqlalchemy import text

    async with repository.session() as session:
        value = await session.scalar(
            text(
                "SELECT count(*) FROM project_role_assignments r "
                "JOIN project_memberships m ON m.project_id = r.project_id "
                "AND m.user_id = r.user_id "
                'JOIN "user" u ON u.id = r.user_id '
                "WHERE r.project_id = :pid AND r.role_key = 'project_admin' "
                "AND m.status = 'active' AND u.is_active = 1"
            ).bindparams(pid=str(project_id))
        )
    return int(value or 0)


async def _archive(repository: SQLiteRepository, project_id: UUID) -> None:
    async with repository.session() as session:
        await ProjectRepository(session).set_project_status(
            project_id=project_id, status=ProjectStatus.ARCHIVED
        )
        await session.commit()


@pytest.mark.asyncio
@pytest.mark.parametrize("archived", [False, True])
async def test_three_way_removal_demotion_and_deactivation_keep_one_admin(
    tmp_path: Path, archived: bool
) -> None:
    """Removal, demotion and deactivation race on three connections; one admin survives."""

    first, second, _setup, admin, peer, project_id = await _prepare_race(
        tmp_path, f"race-three-{archived}"
    )
    third = await SQLiteRepository.open(first.database_path)
    try:
        system = await _seed_installation_admin(first)
        if archived:
            await _archive(first, project_id)
        barrier = asyncio.Barrier(3)

        async def guarded(operation: object) -> str | None:
            await barrier.wait()
            try:
                await operation  # type: ignore[misc]
            except ProjectConflict as error:
                return error.code
            except AuthorizationDenied:
                return _AUTHORIZATION_DENIED_OUTCOME
            except ProjectNotFound:
                return _NOT_FOUND_OUTCOME
            return None

        results = await asyncio.gather(
            guarded(ProjectService(first).remove_member(admin, project_id, peer.id)),
            guarded(
                ProjectService(second).remove_role(
                    peer, project_id, admin.id, BuiltinRole.PROJECT_ADMIN.value
                )
            ),
            guarded(ProjectService(third).deactivate_accounts([admin.id], actor=system)),
        )
        assert all(
            item in (None, LAST_PROJECT_ADMIN, _AUTHORIZATION_DENIED_OUTCOME, _NOT_FOUND_OUTCOME)
            for item in results
        ), results
        assert results.count(None) >= 1, results
        assert await _independent_admin_count(first, project_id) >= 1
        assert await _count_admins(first, project_id) >= 1
    finally:
        await third.close()
        await second.close()
        await first.close()


@pytest.mark.asyncio
async def test_archived_project_keeps_its_last_admin_under_concurrent_self_removal(
    tmp_path: Path,
) -> None:
    first, second, _setup, admin, peer, project_id = await _prepare_race(
        tmp_path, "race-archived-removal"
    )
    try:
        await _archive(first, project_id)
        barrier = asyncio.Barrier(2)

        async def remove_self(service: ProjectService, actor: UserPrincipal) -> str | None:
            await barrier.wait()
            try:
                await service.remove_member(actor, project_id, actor.id)
            except ProjectConflict as error:
                return error.code
            return None

        results = await asyncio.gather(
            remove_self(ProjectService(first), admin),
            remove_self(ProjectService(second), peer),
        )
        assert sorted(results, key=str) == sorted([None, LAST_PROJECT_ADMIN], key=str), results
        assert await _independent_admin_count(first, project_id) == 1
    finally:
        await second.close()
        await first.close()


@pytest.mark.asyncio
async def test_cli_deactivation_races_service_self_removal_and_keeps_one_admin(
    tmp_path: Path, auth_secret: str
) -> None:
    """The operator CLI uses its own connection; it cannot bypass the invariant."""

    from polyweb.cli.users import _run

    first, second, _setup, admin, peer, project_id = await _prepare_race(
        tmp_path, "race-cli-deactivate"
    )
    try:
        await _archive(first, project_id)
        barrier = asyncio.Barrier(2)

        async def cli_deactivate() -> int:
            await barrier.wait()
            return await _run(
                [
                    "deactivate",
                    "--user-id",
                    str(admin.id),
                    "--database",
                    str(first.database_path),
                ]
            )

        async def remove_peer() -> str | None:
            await barrier.wait()
            try:
                await ProjectService(second).remove_member(peer, project_id, peer.id)
            except ProjectConflict as error:
                return error.code
            return None

        cli_status, removal = await asyncio.gather(cli_deactivate(), remove_peer())
        # Exactly one side wins; the loser is refused by the invariant.
        assert (cli_status == 0) != (removal is None), (cli_status, removal)
        if cli_status != 0:
            assert removal is None
        else:
            assert removal == LAST_PROJECT_ADMIN
        assert await _independent_admin_count(first, project_id) == 1
    finally:
        await second.close()
        await first.close()


@pytest.mark.asyncio
async def test_deactivation_checks_every_affected_project_atomically(tmp_path: Path) -> None:
    """One account that is the sole admin of one project and co-admin of another."""

    repository = await create_alpha_test_db(tmp_path / "multi-project-deactivate.db")
    try:
        system = await _seed_installation_admin(repository)
        shared_row = await create_temp_user(repository, temp_email("multi-shared"))
        peer_row = await create_temp_user(repository, temp_email("multi-peer"))
        shared = temp_principal(shared_row)
        peer = temp_principal(peer_row)
        service = ProjectService(repository)
        co_admin = await _create_ownerless_project(
            repository,
            system,
            ProjectCreate(name="Co", slug="co-admin", initial_admin_user_id=shared.id),
        )
        await service.add_member(
            shared,
            co_admin.id,
            ProjectMemberAdd(user_id=peer.id, initial_role=BuiltinRole.PROJECT_ADMIN.value),
        )
        sole = await _create_ownerless_project(
            repository,
            system,
            ProjectCreate(name="Sole", slug="sole-admin", initial_admin_user_id=shared.id),
        )
        await _archive(repository, sole.id)

        with pytest.raises(ProjectConflict) as refused:
            await service.deactivate_accounts([shared.id], actor=system)
        assert refused.value.code == LAST_PROJECT_ADMIN
        async with repository.session() as session:
            stored = await session.get(UserRow, shared.id)
            assert stored is not None and stored.is_active is True
        assert await _independent_admin_count(repository, co_admin.id) == 2
        assert await _independent_admin_count(repository, sole.id) == 1
    finally:
        await repository.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("trusted", [True, False])
async def test_concurrent_deactivation_of_the_last_two_system_admins_keeps_one(
    tmp_path: Path, trusted: bool
) -> None:
    """R2: two connections each deactivate a different one of the last two system admins."""

    from polyweb.services.users import AuthLastSystemAdmin

    first = await create_alpha_test_db(tmp_path / f"r2-race-{trusted}.db")
    second = await SQLiteRepository.open(first.database_path)
    try:
        one = temp_principal(
            await create_temp_user(first, temp_email("r2-race-one"), system_admin=True)
        )
        two = temp_principal(
            await create_temp_user(first, temp_email("r2-race-two"), system_admin=True)
        )
        barrier = asyncio.Barrier(2)

        async def deactivate(
            repo: SQLiteRepository, target: UserPrincipal, actor: UserPrincipal
        ) -> str | None:
            await barrier.wait()
            try:
                if trusted:
                    await ProjectService(repo).deactivate_accounts([target.id], trusted=True)
                else:
                    await ProjectService(repo).deactivate_accounts([target.id], actor=actor)
            except AuthLastSystemAdmin as error:
                return error.code
            except AuthorizationDenied:
                return _AUTHORIZATION_DENIED_OUTCOME
            return None

        # Each admin deactivates the other (REST shape) or the operator does both (CLI shape).
        results = await asyncio.gather(deactivate(first, one, two), deactivate(second, two, one))
        assert results.count(None) == 1, results
        loser = next(item for item in results if item is not None)
        assert loser in ("LAST_SYSTEM_ADMIN", _AUTHORIZATION_DENIED_OUTCOME), results
        async with first.session() as session:
            remaining = await ProjectRepository(session).count_active_system_admins(
                account_id=DEFAULT_INSTALLATION_ACCOUNT_ID
            )
        assert remaining == 1
    finally:
        await second.close()
        await first.close()
