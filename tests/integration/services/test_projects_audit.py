"""Scoped audit events for project, membership, role and account changes (A1 AC8).

Real SQLite through the real ``ProjectService``. Each successful mutation
writes its event in the same transaction; a mutation refused by the
last-admin invariant writes nothing. Project changes land in project scope,
account and system-role changes in system scope, and no event carries a
password, hash, token or key.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from freesearch.models.project_permissions import STANDARD, ProjectPermission
from freesearch.models.projects import (
    BuiltinRole,
    MembershipStatus,
    ProjectCreate,
    ProjectMemberAdd,
    ProjectMemberChange,
    ProjectMembersBulkUpdate,
    ProjectMemberUpdate,
)
from freesearch.services.projects import LAST_PROJECT_ADMIN, ProjectConflict, ProjectService
from tests.fixtures.alpha_fixtures import create_alpha_test_db
from tests.fixtures.api_keys import audit_rows, database_dump
from tests.fixtures.auth import TEMP_PASSWORD, create_temp_user, temp_email, temp_principal


@pytest.mark.asyncio
async def test_membership_and_role_lifecycle_write_project_scoped_events(tmp_path: Path) -> None:
    repository = await create_alpha_test_db(tmp_path / "audit-lifecycle.db")
    try:
        system = temp_principal(
            await create_temp_user(repository, temp_email("audit-sys"), system_admin=True)
        )
        admin = temp_principal(await create_temp_user(repository, temp_email("audit-admin")))
        member = temp_principal(await create_temp_user(repository, temp_email("audit-member")))
        service = ProjectService(repository)

        project = await service.create_project(
            system, ProjectCreate(name="Audit", slug="audit", initial_admin_user_id=admin.id)
        )
        await service.add_member(admin, project.id, ProjectMemberAdd(user_id=member.id))
        permissions = int(ProjectPermission.SEARCH)
        await service.update_member(
            admin, project.id, member.id, ProjectMemberUpdate(permissions=permissions)
        )
        await service.update_member(
            admin, project.id, member.id, ProjectMemberUpdate(permissions=permissions)
        )
        await service.assign_role(admin, project.id, member.id, BuiltinRole.PROJECT_ADMIN.value)
        # Re-assigning a held role is not a change and writes no second event.
        await service.assign_role(admin, project.id, member.id, BuiltinRole.PROJECT_ADMIN.value)
        await service.remove_role(admin, project.id, member.id, BuiltinRole.PROJECT_ADMIN.value)
        await service.update_member(admin, project.id, member.id, ProjectMemberUpdate(role="admin"))
        await service.update_member(
            admin, project.id, member.id, ProjectMemberUpdate(role="developer")
        )
        await service.update_member(
            admin,
            project.id,
            member.id,
            ProjectMemberUpdate(status=MembershipStatus.SUSPENDED),
        )
        await service.bulk_update_members(
            admin,
            project.id,
            ProjectMembersBulkUpdate(
                changes=[ProjectMemberChange(user_id=member.id, status=MembershipStatus.ACTIVE)]
            ),
        )
        await service.bulk_update_members(
            admin,
            project.id,
            ProjectMembersBulkUpdate(
                changes=[
                    ProjectMemberChange(
                        user_id=member.id,
                        permissions=int(ProjectPermission.TOKENS),
                    )
                ]
            ),
        )
        await service.remove_member(admin, project.id, member.id)
        await service.archive_project(admin, project.id)

        events = await audit_rows(repository, scope="project")
        actions = [row["action"] for row in sorted(events, key=lambda r: r["occurred_at"])]
        assert actions.count("project.created") == 1
        assert actions.count("member.added") == 1
        assert actions.count("role.assigned") == 1
        assert actions.count("role.removed") == 1
        assert actions.count("member.role_changed") == 2
        assert actions.count("member.permissions_changed") == 2
        assert actions.count("member.status_changed") == 2
        assert actions.count("member.removed") == 1
        assert actions.count("project.archived") == 1
        for row in events:
            assert row["project_id"] == str(project.id)
            assert row["actor_type"] == "human"
            assert row["outcome"] == "success"
        created = next(row for row in events if row["action"] == "project.created")
        assert created["actor_id"] == str(system.id)
        others = [row for row in events if row["action"] != "project.created"]
        assert {row["actor_id"] for row in others} == {str(admin.id)}
        member_events = [row for row in events if row["action"].startswith(("member.", "role."))]
        assert {row["target_id"] for row in member_events} == {str(member.id)}
        permission_details = [
            json.loads(row["detail"])
            for row in events
            if row["action"] == "member.permissions_changed"
        ]
        assert {
            (detail["previous_permissions"], detail["permissions"]) for detail in permission_details
        } == {(STANDARD, permissions), (permissions, int(ProjectPermission.TOKENS))}
        # Project changes never leak into system scope.
        system_actions = {row["action"] for row in await audit_rows(repository, scope="system")}
        assert not system_actions & {"member.added", "role.assigned", "project.created"}
        dump = database_dump(repository)
        assert TEMP_PASSWORD not in dump
    finally:
        await repository.close()


@pytest.mark.asyncio
async def test_provider_owner_transfer_and_claim_are_project_scoped(tmp_path: Path) -> None:
    repository = await create_alpha_test_db(tmp_path / "audit-owner.db")
    try:
        system = temp_principal(
            await create_temp_user(repository, temp_email("audit-sys"), system_admin=True)
        )
        peer = temp_principal(await create_temp_user(repository, temp_email("audit-peer")))
        service = ProjectService(repository)
        project = await service.create_project(
            system, ProjectCreate(name="Owner", slug="owner", initial_admin_user_id=system.id)
        )
        await service.add_member(
            system,
            project.id,
            ProjectMemberAdd(user_id=peer.id, initial_role=BuiltinRole.PROJECT_ADMIN),
        )
        await service.transfer_provider_owner(system, project.id, peer.id)
        await service.transfer_provider_owner(peer, project.id, peer.id)
        await service.deactivate_accounts([peer.id], actor=system)
        await service.transfer_provider_owner(system, project.id, system.id)

        events = await audit_rows(repository, scope="project")
        transfers = [row for row in events if row["action"] == "project.provider_owner_transferred"]
        assert len(transfers) == 2
        assert {row["project_id"] for row in transfers} == {str(project.id)}
        assert {row["actor_id"] for row in transfers} == {str(system.id)}
        assert {row["target_id"] for row in transfers} == {str(peer.id), str(system.id)}
        assert {row["outcome"] for row in transfers} == {"success"}
        assert {
            (row["target_id"], json.loads(row["detail"])["previous_owner"]) for row in transfers
        } == {(str(peer.id), str(system.id)), (str(system.id), None)}
        assert all(json.loads(row["detail"])["unassigned_pools"] == [] for row in transfers)
        system_events = await audit_rows(repository, scope="system")
        assert [
            row["target_id"] for row in system_events if row["action"] == "account.deactivated"
        ] == [str(peer.id)]
        assert not any(
            row["action"] == "project.provider_owner_transferred" for row in system_events
        )
        assert all(TEMP_PASSWORD not in row["detail"] for row in events + system_events)
    finally:
        await repository.close()


@pytest.mark.asyncio
async def test_refused_mutations_write_no_audit_event(tmp_path: Path) -> None:
    repository = await create_alpha_test_db(tmp_path / "audit-refused.db")
    try:
        system = temp_principal(
            await create_temp_user(repository, temp_email("audit-sys"), system_admin=True)
        )
        admin = temp_principal(await create_temp_user(repository, temp_email("audit-only")))
        service = ProjectService(repository)
        project = await service.create_project(
            system, ProjectCreate(name="Solo", slug="solo", initial_admin_user_id=admin.id)
        )
        await service.transfer_provider_owner(system, project.id, admin.id)
        await service.remove_member(system, project.id, system.id)
        before_project = await audit_rows(repository, scope="project")
        before_system = await audit_rows(repository, scope="system")

        with pytest.raises(ProjectConflict) as refused:
            await service.remove_member(admin, project.id, admin.id)
        assert refused.value.code == "PROVIDER_OWNER_REQUIRED"
        with pytest.raises(ProjectConflict) as refused:
            await service.remove_role(admin, project.id, admin.id, BuiltinRole.PROJECT_ADMIN.value)
        assert refused.value.code == "PROVIDER_OWNER_REQUIRED"
        with pytest.raises(ProjectConflict) as refused:
            await service.update_member(
                admin, project.id, admin.id, ProjectMemberUpdate(status=MembershipStatus.SUSPENDED)
            )
        assert refused.value.code == "PROVIDER_OWNER_REQUIRED"
        with pytest.raises(ProjectConflict) as refused:
            await service.deactivate_accounts([admin.id], actor=system)
        assert refused.value.code == LAST_PROJECT_ADMIN

        assert await audit_rows(repository, scope="project") == before_project
        assert await audit_rows(repository, scope="system") == before_system
    finally:
        await repository.close()


@pytest.mark.asyncio
async def test_account_deactivation_writes_one_system_event_per_changed_account(
    tmp_path: Path,
) -> None:
    repository = await create_alpha_test_db(tmp_path / "audit-deactivate.db")
    try:
        system = temp_principal(
            await create_temp_user(repository, temp_email("audit-sys"), system_admin=True)
        )
        target = temp_principal(await create_temp_user(repository, temp_email("audit-target")))
        service = ProjectService(repository)
        await service.deactivate_accounts([target.id], actor=system)
        await service.deactivate_accounts([target.id], actor=system)

        events = await audit_rows(repository, scope="system", action="account.deactivated")
        assert len(events) == 1
        assert events[0]["category"] == "audit"
        assert events[0]["actor_type"] == "human"
        assert events[0]["actor_id"] == str(system.id)
        assert events[0]["target_id"] == str(target.id)
        assert await audit_rows(repository, scope="project") == []
    finally:
        await repository.close()
