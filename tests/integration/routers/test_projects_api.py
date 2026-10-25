"""Focused HTTP regression coverage for project scoping and live revocation."""

from __future__ import annotations

from pathlib import Path
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from freesearch.models.projects import (
    BUILTIN_ROLE_DEFINITIONS,
    BuiltinRole,
    MembershipStatus,
    PermissionAction,
    ProjectCreate,
    ProjectMemberAdd,
    ProjectMemberUpdate,
)
from freesearch.models.users import UserRole
from freesearch.persistence.projects import ProjectRepository
from freesearch.persistence.storage import SQLiteRepository
from freesearch.persistence.users import UserDatabase, UserRow
from freesearch.routers.api import create_app
from freesearch.services.projects import LAST_PROJECT_ADMIN, ProjectService
from tests.fixtures.alpha_fixtures import create_alpha_test_db
from tests.fixtures.auth import (
    TEMP_PASSWORD,
    create_temp_user,
    temp_email,
    temp_principal,
)


class _MemorySecretStore:
    """Small async secret store so this router test never touches a key file."""

    def __init__(self) -> None:
        self._values: dict[str, str] = {}

    async def get(self, name: str) -> str | None:
        return self._values.get(name)

    async def set(self, name: str, value: str) -> None:
        self._values[name] = value

    async def delete(self, name: str) -> None:
        self._values.pop(name, None)


def _login(client: TestClient, email: str) -> dict[str, str]:
    response = client.post(
        "/auth/jwt/login",
        data={"username": email, "password": TEMP_PASSWORD},
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


async def _count_admins(repository: SQLiteRepository, project_id: UUID) -> int:
    async with repository.session() as session:
        return await ProjectRepository(session).count_active_project_admins(project_id=project_id)


async def _seed_users(
    repository: SQLiteRepository,
) -> tuple[UserRow, UserRow, UserRow]:
    system = await create_temp_user(repository, temp_email("p02-http-system"), role=UserRole.ADMIN)
    admin = await create_temp_user(repository, temp_email("p02-http-admin"))
    peer = await create_temp_user(repository, temp_email("p02-http-peer"))
    return system, admin, peer


@pytest.mark.asyncio
async def test_system_admin_has_no_membership_and_live_revocation_is_effective(
    tmp_path: Path,
    auth_secret: str,
) -> None:
    repository = await create_alpha_test_db(tmp_path / "p02-http-scope.db")
    try:
        system_row, admin_row, _peer_row = await _seed_users(repository)
        app = create_app(
            [],
            repository=repository,
            secret_store=_MemorySecretStore(),
        )
        with TestClient(app) as client:
            system_headers = _login(client, system_row.email)
            admin_headers = _login(client, admin_row.email)

            created = client.post(
                "/api/v1/projects",
                headers=system_headers,
                json={
                    "name": "HTTP Scoped",
                    "slug": "http-scoped",
                    "initial_admin_user_id": str(admin_row.id),
                },
            )
            assert created.status_code == 201, created.text
            project_id = created.json()["id"]

            # Creating a project does not create a membership for the system
            # administrator, and project content remains inaccessible.
            assert client.get("/api/v1/projects", headers=system_headers).json() == []
            assert (
                client.get(
                    f"/api/v1/projects/{project_id}/members",
                    headers=system_headers,
                ).status_code
                == 403
            )

            # The project administrator has project scope, not system scope.
            assert (
                client.get("/api/v1/projects", headers=admin_headers).json()[0]["id"] == project_id
            )
            assert (
                client.get(
                    f"/api/v1/projects/{project_id}/members",
                    headers=admin_headers,
                ).status_code
                == 200
            )
            assert client.get("/api/v1/routing/config", headers=admin_headers).status_code == 403
            assert (
                client.post(
                    "/api/v1/projects",
                    headers=admin_headers,
                    json={
                        "name": "Admin Create",
                        "slug": "admin-create",
                        "initial_admin_user_id": str(admin_row.id),
                    },
                ).status_code
                == 403
            )

            assert client.get("/api/v1/routing/config", headers=system_headers).status_code == 200

            # The same access JWT stays authenticated, but the removed system
            # assignment immediately closes both system-scoped surfaces.
            async with repository.session() as session:
                database = UserDatabase(session, UserRow)
                assert await database.set_role(system_row.id, UserRole.AGENT) is True
                await session.commit()

            assert client.get("/users/me", headers=system_headers).status_code == 200
            assert (
                client.post(
                    "/api/v1/projects",
                    headers=system_headers,
                    json={
                        "name": "Revoked Create",
                        "slug": "revoked-create",
                        "initial_admin_user_id": str(admin_row.id),
                    },
                ).status_code
                == 403
            )
            assert client.get("/api/v1/routing/config", headers=system_headers).status_code == 403
    finally:
        await repository.close()


@pytest.mark.asyncio
async def test_http_deactivation_guard_and_live_token_revocation(
    tmp_path: Path,
    auth_secret: str,
) -> None:
    repository = await create_alpha_test_db(tmp_path / "p02-http-deactivate.db")
    try:
        system_row, admin_row, peer_row = await _seed_users(repository)
        system = temp_principal(system_row)
        project = await ProjectService(repository).create_project(
            system,
            ProjectCreate(
                name="HTTP Deactivate",
                slug="http-deactivate",
                initial_admin_user_id=admin_row.id,
            ),
        )
        app = create_app(
            [],
            repository=repository,
            secret_store=_MemorySecretStore(),
        )
        with TestClient(app) as client:
            system_headers = _login(client, system_row.email)
            admin_headers = _login(client, admin_row.email)
            peer_headers = _login(client, peer_row.email)

            refused = client.post(
                f"/api/v1/users/{admin_row.id}/deactivate",
                headers=system_headers,
            )
            assert refused.status_code == 409, refused.text
            assert refused.json()["detail"]["code"] == LAST_PROJECT_ADMIN
            assert client.get("/users/me", headers=admin_headers).status_code == 200

            added = client.post(
                f"/api/v1/projects/{project.id}/members",
                headers=admin_headers,
                json={
                    "user_id": str(peer_row.id),
                    "initial_role": BuiltinRole.PROJECT_ADMIN.value,
                },
            )
            assert added.status_code == 201, added.text

            deactivated = client.post(
                f"/api/v1/users/{admin_row.id}/deactivate",
                headers=system_headers,
            )
            assert deactivated.status_code == 200, deactivated.text
            assert deactivated.json()["is_active"] is False

            # Existing access tokens are rejected on the next request after
            # account deactivation; the peer administrator remains live.
            assert client.get("/users/me", headers=admin_headers).status_code == 401
            assert client.get("/users/me", headers=peer_headers).status_code == 200

            refused_last = client.post(
                f"/api/v1/users/{peer_row.id}/deactivate",
                headers=system_headers,
            )
            assert refused_last.status_code == 409, refused_last.text
            assert refused_last.json()["detail"]["code"] == LAST_PROJECT_ADMIN
            assert client.get("/users/me", headers=peer_headers).status_code == 200
            assert await _count_admins(repository, project.id) == 1
    finally:
        await repository.close()


@pytest.mark.asyncio
async def test_system_access_reflects_live_system_permissions(
    tmp_path: Path,
    auth_secret: str,
) -> None:
    repository = await create_alpha_test_db(tmp_path / "p06-system-access.db")
    try:
        system_row, admin_row, _peer_row = await _seed_users(repository)
        app = create_app(
            [],
            repository=repository,
            secret_store=_MemorySecretStore(),
        )
        with TestClient(app) as client:
            system_headers = _login(client, system_row.email)
            admin_headers = _login(client, admin_row.email)

            expected = sorted(
                action.value
                for action in BUILTIN_ROLE_DEFINITIONS[BuiltinRole.SYSTEM_ADMIN].permissions
            )
            system_access = client.get("/api/v1/system/access", headers=system_headers)
            assert system_access.status_code == 200, system_access.text
            assert system_access.json() == {
                "rollout_state": "preview",
                "permissions": expected,
            }

            # An ordinary authenticated human has no system-scope permissions.
            ordinary_access = client.get("/api/v1/system/access", headers=admin_headers)
            assert ordinary_access.status_code == 200, ordinary_access.text
            assert ordinary_access.json() == {
                "rollout_state": "preview",
                "permissions": [],
            }

            assert client.get("/api/v1/system/access").status_code == 401
    finally:
        await repository.close()


@pytest.mark.asyncio
async def test_project_access_reflects_live_membership_roles_and_revocation(
    tmp_path: Path,
    auth_secret: str,
) -> None:
    repository = await create_alpha_test_db(tmp_path / "p06-project-access.db")
    try:
        system_row, admin_row, peer_row = await _seed_users(repository)
        human_row = await create_temp_user(repository, temp_email("p06-access-human"))
        service = ProjectService(repository)
        system = temp_principal(system_row)
        admin = temp_principal(admin_row)
        human = temp_principal(human_row)

        # One human is a plain member of project A and the administrator of B.
        project_a = await service.create_project(
            system,
            ProjectCreate(name="Access A", slug="access-a", initial_admin_user_id=admin_row.id),
        )
        project_b = await service.create_project(
            system,
            ProjectCreate(name="Access B", slug="access-b", initial_admin_user_id=human_row.id),
        )
        await service.add_member(admin, project_a.id, ProjectMemberAdd(user_id=human_row.id))

        member_permissions = sorted(
            action.value
            for action in BUILTIN_ROLE_DEFINITIONS[BuiltinRole.PROJECT_MEMBER].permissions
        )
        admin_permissions = sorted(
            action.value
            for action in BUILTIN_ROLE_DEFINITIONS[BuiltinRole.PROJECT_ADMIN].permissions
        )

        app = create_app(
            [],
            repository=repository,
            secret_store=_MemorySecretStore(),
        )
        with TestClient(app) as client:
            system_headers = _login(client, system_row.email)
            peer_headers = _login(client, peer_row.email)
            human_headers = _login(client, human_row.email)

            access_a = client.get(
                f"/api/v1/projects/{project_a.id}/access",
                headers=human_headers,
            )
            assert access_a.status_code == 200, access_a.text
            assert access_a.json()["project_id"] == str(project_a.id)
            assert access_a.json()["permissions"] == member_permissions
            assert access_a.json()["roles"] == [BuiltinRole.PROJECT_MEMBER.value]
            assert access_a.json()["policy_revision"] >= 1

            access_b = client.get(
                f"/api/v1/projects/{project_b.id}/access",
                headers=human_headers,
            )
            assert access_b.status_code == 200, access_b.text
            assert access_b.json()["permissions"] == admin_permissions
            assert access_b.json()["roles"] == [BuiltinRole.PROJECT_ADMIN.value]

            # Unknown, non-member, and system-admin lookups are indistinguishable.
            unknown = client.get(
                f"/api/v1/projects/{uuid4()}/access",
                headers=human_headers,
            )
            assert unknown.status_code == 404
            non_member = client.get(
                f"/api/v1/projects/{project_a.id}/access",
                headers=peer_headers,
            )
            assert non_member.status_code == 404
            system_access = client.get(
                f"/api/v1/projects/{project_a.id}/access",
                headers=system_headers,
            )
            assert system_access.status_code == 404
            assert client.get(f"/api/v1/projects/{project_a.id}/access").status_code == 401

            # A live role assignment is reflected on the very next call.
            await service.assign_role(
                admin,
                project_a.id,
                human_row.id,
                BuiltinRole.ROUTING_EDITOR.value,
            )
            access_a = client.get(
                f"/api/v1/projects/{project_a.id}/access",
                headers=human_headers,
            )
            assert access_a.status_code == 200, access_a.text
            assert access_a.json()["roles"] == [
                BuiltinRole.PROJECT_MEMBER.value,
                BuiltinRole.ROUTING_EDITOR.value,
            ]
            assert PermissionAction.ROUTING_WRITE.value in access_a.json()["permissions"]

            # Removing the role is reflected immediately as well.
            await service.remove_role(
                admin,
                project_a.id,
                human_row.id,
                BuiltinRole.ROUTING_EDITOR.value,
            )
            access_a = client.get(
                f"/api/v1/projects/{project_a.id}/access",
                headers=human_headers,
            )
            assert access_a.json()["roles"] == [BuiltinRole.PROJECT_MEMBER.value]
            assert PermissionAction.ROUTING_WRITE.value not in access_a.json()["permissions"]

            # A suspended membership resolves exactly like an unknown project.
            await service.update_member(
                admin,
                project_a.id,
                human_row.id,
                ProjectMemberUpdate(status=MembershipStatus.SUSPENDED),
            )
            suspended = client.get(
                f"/api/v1/projects/{project_a.id}/access",
                headers=human_headers,
            )
            assert suspended.status_code == 404

            # An archived project with an active membership still reports access.
            await service.archive_project(human, project_b.id)
            access_b = client.get(
                f"/api/v1/projects/{project_b.id}/access",
                headers=human_headers,
            )
            assert access_b.status_code == 200, access_b.text
            assert access_b.json()["roles"] == [BuiltinRole.PROJECT_ADMIN.value]
    finally:
        await repository.close()


@pytest.mark.asyncio
async def test_member_responses_include_email_and_add_member_by_email(
    tmp_path: Path,
    auth_secret: str,
) -> None:
    repository = await create_alpha_test_db(tmp_path / "p06-member-email.db")
    try:
        system_row, admin_row, peer_row = await _seed_users(repository)
        inactive_row = await create_temp_user(repository, temp_email("p06-inactive"))
        service = ProjectService(repository)
        system = temp_principal(system_row)
        project = await service.create_project(
            system,
            ProjectCreate(name="Email", slug="email", initial_admin_user_id=admin_row.id),
        )
        await service.deactivate_accounts([inactive_row.id], actor=system)

        app = create_app(
            [],
            repository=repository,
            secret_store=_MemorySecretStore(),
        )
        with TestClient(app) as client:
            admin_headers = _login(client, admin_row.email)

            members = client.get(
                f"/api/v1/projects/{project.id}/members",
                headers=admin_headers,
            )
            assert members.status_code == 200, members.text
            assert members.json() == [
                {
                    "project_id": str(project.id),
                    "user_id": str(admin_row.id),
                    "email": admin_row.email,
                    "status": "active",
                    "roles": [BuiltinRole.PROJECT_ADMIN.value],
                    "version": 1,
                }
            ]

            # Email identifiers are normalized before resolution.
            added = client.post(
                f"/api/v1/projects/{project.id}/members",
                headers=admin_headers,
                json={"email": peer_row.email.upper(), "initial_role": "project_member"},
            )
            assert added.status_code == 201, added.text
            assert added.json()["user_id"] == str(peer_row.id)
            assert added.json()["email"] == peer_row.email

            members = client.get(
                f"/api/v1/projects/{project.id}/members",
                headers=admin_headers,
            )
            emails = {item["user_id"]: item["email"] for item in members.json()}
            assert emails == {
                str(admin_row.id): admin_row.email,
                str(peer_row.id): peer_row.email,
            }

            # Unknown and inactive identifiers fail exactly like an unknown id:
            # HTTP 400 with an empty body in every case.
            unknown_email = client.post(
                f"/api/v1/projects/{project.id}/members",
                headers=admin_headers,
                json={"email": temp_email("p06-ghost")},
            )
            assert unknown_email.status_code == 400
            assert unknown_email.content == b""
            unknown_id = client.post(
                f"/api/v1/projects/{project.id}/members",
                headers=admin_headers,
                json={"user_id": str(uuid4())},
            )
            assert unknown_id.status_code == 400
            assert unknown_id.content == b""
            inactive_email = client.post(
                f"/api/v1/projects/{project.id}/members",
                headers=admin_headers,
                json={"email": inactive_row.email},
            )
            assert inactive_email.status_code == 400
            assert inactive_email.content == b""

            # Both and neither identifiers are schema errors.
            assert (
                client.post(
                    f"/api/v1/projects/{project.id}/members",
                    headers=admin_headers,
                    json={"user_id": str(uuid4()), "email": peer_row.email},
                ).status_code
                == 422
            )
            assert (
                client.post(
                    f"/api/v1/projects/{project.id}/members",
                    headers=admin_headers,
                    json={},
                ).status_code
                == 422
            )

            # A caller without members.manage is denied before any email lookup.
            peer_headers = _login(client, peer_row.email)
            denied = client.post(
                f"/api/v1/projects/{project.id}/members",
                headers=peer_headers,
                json={"email": temp_email("p06-ghost")},
            )
            assert denied.status_code == 403
    finally:
        await repository.close()


@pytest.mark.asyncio
async def test_create_project_with_initial_admin_email(
    tmp_path: Path,
    auth_secret: str,
) -> None:
    repository = await create_alpha_test_db(tmp_path / "p06-create-email.db")
    try:
        system_row, admin_row, peer_row = await _seed_users(repository)
        service = ProjectService(repository)
        system = temp_principal(system_row)
        await service.deactivate_accounts([peer_row.id], actor=system)

        app = create_app(
            [],
            repository=repository,
            secret_store=_MemorySecretStore(),
        )
        with TestClient(app) as client:
            system_headers = _login(client, system_row.email)
            admin_headers = _login(client, admin_row.email)

            created = client.post(
                "/api/v1/projects",
                headers=system_headers,
                json={
                    "name": "Email Admin",
                    "slug": "email-admin",
                    "initial_admin_email": admin_row.email.upper(),
                },
            )
            assert created.status_code == 201, created.text
            project_id = created.json()["id"]

            # The named user is the active project_admin of the new project.
            access = client.get(
                f"/api/v1/projects/{project_id}/access",
                headers=admin_headers,
            )
            assert access.status_code == 200, access.text
            assert access.json()["roles"] == [BuiltinRole.PROJECT_ADMIN.value]
            members = client.get(
                f"/api/v1/projects/{project_id}/members",
                headers=admin_headers,
            )
            assert members.status_code == 200, members.text
            assert members.json() == [
                {
                    "project_id": project_id,
                    "user_id": str(admin_row.id),
                    "email": admin_row.email,
                    "status": "active",
                    "roles": [BuiltinRole.PROJECT_ADMIN.value],
                    "version": 1,
                }
            ]

            # Unknown and inactive identifiers fail like an unknown user id.
            unknown_email = client.post(
                "/api/v1/projects",
                headers=system_headers,
                json={"name": "Ghost", "initial_admin_email": temp_email("p06-ghost")},
            )
            assert unknown_email.status_code == 400
            assert unknown_email.content == b""
            unknown_id = client.post(
                "/api/v1/projects",
                headers=system_headers,
                json={"name": "Ghost Id", "initial_admin_user_id": str(uuid4())},
            )
            assert unknown_id.status_code == 400
            assert unknown_id.content == b""
            inactive_email = client.post(
                "/api/v1/projects",
                headers=system_headers,
                json={"name": "Inactive", "initial_admin_email": peer_row.email},
            )
            assert inactive_email.status_code == 400
            assert inactive_email.content == b""

            # Both and neither identifiers are schema errors.
            assert (
                client.post(
                    "/api/v1/projects",
                    headers=system_headers,
                    json={
                        "name": "Both",
                        "initial_admin_user_id": str(admin_row.id),
                        "initial_admin_email": admin_row.email,
                    },
                ).status_code
                == 422
            )
            assert (
                client.post(
                    "/api/v1/projects",
                    headers=system_headers,
                    json={"name": "Neither"},
                ).status_code
                == 422
            )

            # A caller without system project.create is denied before lookup.
            denied = client.post(
                "/api/v1/projects",
                headers=admin_headers,
                json={"name": "Denied", "initial_admin_email": temp_email("p06-ghost")},
            )
            assert denied.status_code == 403
    finally:
        await repository.close()
