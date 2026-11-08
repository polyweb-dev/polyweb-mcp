"""Focused HTTP regression coverage for project scoping and live revocation."""

from __future__ import annotations

from pathlib import Path
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from freesearch.models.project_permissions import (
    DEVELOPER_BITS,
    PROVIDER_OWNER_BIT,
    STANDARD,
    ProjectPermission,
)
from freesearch.models.projects import (
    BUILTIN_ROLE_DEFINITIONS,
    DEFAULT_INSTALLATION_ACCOUNT_ID,
    BuiltinRole,
    MembershipStatus,
    PermissionAction,
    ProjectCreate,
    ProjectMemberAdd,
    ProjectMemberUpdate,
)
from freesearch.persistence.projects import ProjectRepository
from freesearch.persistence.storage import SQLiteRepository
from freesearch.persistence.users import UserRow
from freesearch.routers.api import create_app
from freesearch.services.projects import LAST_PROJECT_ADMIN, ProjectConflict, ProjectService
from freesearch.services.users import AuthLastSystemAdmin
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
    *,
    admin_is_system: bool = False,
) -> tuple[UserRow, UserRow, UserRow]:
    system = await create_temp_user(repository, temp_email("p02-http-system"), system_admin=True)
    admin = await create_temp_user(
        repository, temp_email("p02-http-admin"), system_admin=admin_is_system
    )
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
        creator_row = await create_temp_user(
            repository, temp_email("p02-http-creator"), system_admin=True
        )
        app = create_app(
            [],
            repository=repository,
            secret_store=_MemorySecretStore(),
        )
        with TestClient(app) as client:
            system_headers = _login(client, system_row.email)
            admin_headers = _login(client, admin_row.email)
            creator_headers = _login(client, creator_row.email)

            created = client.post(
                "/api/v1/projects",
                headers=creator_headers,
                json={
                    "name": "HTTP Scoped",
                    "slug": "http-scoped",
                    "initial_admin_user_id": str(admin_row.id),
                },
            )
            assert created.status_code == 201, created.text
            project_id = created.json()["id"]

            # Only the creating system administrator gains project membership.
            assert client.get("/api/v1/projects", headers=creator_headers).json()[0]["id"] == (
                project_id
            )
            assert client.get("/api/v1/projects", headers=system_headers).json() == []
            # R5: a non-member gets the same 404 as an unknown project.
            assert (
                client.get(
                    f"/api/v1/projects/{project_id}/members",
                    headers=system_headers,
                ).status_code
                == 404
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
            # (A1: the assignment row itself is removed; no role column exists.)
            async with repository.session() as session:
                assert await ProjectRepository(session).delete_system_role(
                    account_id=DEFAULT_INSTALLATION_ACCOUNT_ID,
                    user_id=system_row.id,
                    role_key=BuiltinRole.SYSTEM_ADMIN.value,
                )
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
async def test_service_deactivation_guard_and_live_token_revocation(
    tmp_path: Path,
    auth_secret: str,
) -> None:
    repository = await create_alpha_test_db(tmp_path / "p02-http-deactivate.db")
    try:
        system_row, admin_row, peer_row = await _seed_users(repository, admin_is_system=True)
        system = temp_principal(system_row)
        project = await ProjectService(repository).create_project(
            temp_principal(admin_row),
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
            _login(client, system_row.email)
            admin_headers = _login(client, admin_row.email)
            peer_headers = _login(client, peer_row.email)

            with pytest.raises(ProjectConflict) as refused:
                await ProjectService(repository).deactivate_accounts([admin_row.id], actor=system)
            assert refused.value.code == LAST_PROJECT_ADMIN
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

            deactivated = await ProjectService(repository).deactivate_accounts(
                [admin_row.id], actor=system
            )
            assert deactivated[0].is_active is False

            # Existing access tokens are rejected on the next request after
            # account deactivation; the peer administrator remains live.
            assert client.get("/users/me", headers=admin_headers).status_code == 401
            assert client.get("/users/me", headers=peer_headers).status_code == 200

            with pytest.raises(ProjectConflict) as refused_last:
                await ProjectService(repository).deactivate_accounts([peer_row.id], actor=system)
            assert refused_last.value.code == LAST_PROJECT_ADMIN
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
                [
                    *(
                        action.value
                        for action in BUILTIN_ROLE_DEFINITIONS[BuiltinRole.SYSTEM_ADMIN].permissions
                    ),
                    "vault.manage",
                ]
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

            service = ProjectService(repository)
            project = await service.create_project(
                temp_principal(system_row),
                ProjectCreate(name="Vault Access", initial_admin_user_id=admin_row.id),
            )
            assert client.get("/api/v1/system/access", headers=admin_headers).json() == {
                "rollout_state": "preview",
                "permissions": ["vault.manage"],
            }
            await service.remove_member(temp_principal(system_row), project.id, admin_row.id)
            assert client.get("/api/v1/system/access", headers=admin_headers).json() == {
                "rollout_state": "preview",
                "permissions": [],
            }
            async with repository.session() as session:
                assert await ProjectRepository(session).delete_system_role(
                    account_id=DEFAULT_INSTALLATION_ACCOUNT_ID,
                    user_id=system_row.id,
                    role_key=BuiltinRole.SYSTEM_ADMIN.value,
                )
                await session.commit()
            # The former system admin still has a vault as the project creator.
            assert client.get("/api/v1/system/access", headers=system_headers).json() == {
                "rollout_state": "preview",
                "permissions": ["vault.manage"],
            }
            assert client.get("/api/v1/system/access").status_code == 401
    finally:
        await repository.close()


@pytest.mark.asyncio
async def test_system_projects_lists_every_project_for_system_administrators(
    tmp_path: Path,
    auth_secret: str,
) -> None:
    repository = await create_alpha_test_db(tmp_path / "system-projects.db")
    try:
        system_row, admin_row, _peer_row = await _seed_users(repository)
        creator_row = await create_temp_user(
            repository, temp_email("system-projects-creator"), system_admin=True
        )
        project = await ProjectService(repository).create_project(
            temp_principal(creator_row),
            ProjectCreate(
                name="Handed Off",
                slug="handed-off",
                initial_admin_user_id=admin_row.id,
            ),
        )
        app = create_app([], repository=repository, secret_store=_MemorySecretStore())
        with TestClient(app) as client:
            system_headers = _login(client, system_row.email)
            admin_headers = _login(client, admin_row.email)

            # The system administrator is not a member, so the membership list
            # omits the project while the system list still names it.
            own = client.get("/api/v1/projects", headers=system_headers)
            assert own.status_code == 200, own.text
            assert str(project.id) not in {item["id"] for item in own.json()}
            listed = client.get("/api/v1/system/projects", headers=system_headers)
            assert listed.status_code == 200, listed.text
            assert {"id": str(project.id), "name": "Handed Off"}.items() <= next(
                item for item in listed.json() if item["id"] == str(project.id)
            ).items()

            assert client.get("/api/v1/system/projects", headers=admin_headers).status_code == 403
            assert client.get("/api/v1/system/projects").status_code == 401
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
        outsider_system_row = await create_temp_user(
            repository, temp_email("p06-access-system"), system_admin=True
        )
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
            set(member_permissions)
            | {
                "project.archive",
                "members.manage",
                "roles.assign",
                "settings.write",
                "settings.copy",
                "providers.configure",
                "tokens.manage",
            }
        )

        app = create_app(
            [],
            repository=repository,
            secret_store=_MemorySecretStore(),
        )
        with TestClient(app) as client:
            system_headers = _login(client, outsider_system_row.email)
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

            # A live permission grant is reflected on the very next call.
            await service.update_member(
                admin,
                project_a.id,
                human_row.id,
                ProjectMemberUpdate(
                    permissions=STANDARD | int(ProjectPermission.PROVIDERS_CONFIGURE)
                ),
            )
            access_a = client.get(
                f"/api/v1/projects/{project_a.id}/access",
                headers=human_headers,
            )
            assert access_a.status_code == 200, access_a.text
            assert access_a.json()["roles"] == [BuiltinRole.PROJECT_MEMBER.value]
            assert access_a.json()["permissions"] == sorted(
                [*member_permissions, PermissionAction.PROVIDERS_CONFIGURE.value]
            )

            # Removing the permission is reflected immediately as well.
            await service.update_member(
                admin,
                project_a.id,
                human_row.id,
                ProjectMemberUpdate(permissions=STANDARD),
            )
            access_a = client.get(
                f"/api/v1/projects/{project_a.id}/access",
                headers=human_headers,
            )
            assert access_a.json()["roles"] == [BuiltinRole.PROJECT_MEMBER.value]
            assert access_a.json()["permissions"] == member_permissions

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
            assert {item["user_id"]: item for item in members.json()} == {
                str(admin_row.id): {
                    "project_id": str(project.id),
                    "user_id": str(admin_row.id),
                    "email": admin_row.email,
                    "status": "active",
                    "roles": [BuiltinRole.PROJECT_ADMIN.value],
                    "version": 1,
                    "role": "admin",
                    "permissions": 0,
                    "provider_owner": False,
                },
                str(system_row.id): {
                    "project_id": str(project.id),
                    "user_id": str(system_row.id),
                    "email": system_row.email,
                    "status": "active",
                    "roles": [BuiltinRole.PROJECT_ADMIN.value],
                    "version": 1,
                    "role": "admin",
                    "permissions": DEVELOPER_BITS | PROVIDER_OWNER_BIT,
                    "provider_owner": True,
                },
            }

            # Email identifiers are normalized before resolution.
            added = client.post(
                f"/api/v1/projects/{project.id}/members",
                headers=admin_headers,
                json={"email": peer_row.email.upper(), "initial_role": "project_member"},
            )
            assert added.status_code == 201, added.text
            assert added.json()["user_id"] == str(peer_row.id)
            assert added.json()["email"] == peer_row.email
            assert added.json()["role"] == "developer"
            assert added.json()["permissions"] == STANDARD
            assert added.json()["provider_owner"] is False

            members = client.get(
                f"/api/v1/projects/{project.id}/members",
                headers=admin_headers,
            )
            emails = {item["user_id"]: item["email"] for item in members.json()}
            assert emails == {
                str(admin_row.id): admin_row.email,
                str(system_row.id): system_row.email,
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
            assert {item["user_id"]: item for item in members.json()} == {
                str(admin_row.id): {
                    "project_id": project_id,
                    "user_id": str(admin_row.id),
                    "email": admin_row.email,
                    "status": "active",
                    "roles": [BuiltinRole.PROJECT_ADMIN.value],
                    "version": 1,
                    "role": "admin",
                    "permissions": 0,
                    "provider_owner": False,
                },
                str(system_row.id): {
                    "project_id": project_id,
                    "user_id": str(system_row.id),
                    "email": system_row.email,
                    "status": "active",
                    "roles": [BuiltinRole.PROJECT_ADMIN.value],
                    "version": 1,
                    "role": "admin",
                    "permissions": DEVELOPER_BITS | PROVIDER_OWNER_BIT,
                    "provider_owner": True,
                },
            }

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


# --- R5 (TASK-000041 ruling): non-member and unknown project are the same 404 ---


def _project_scoped_routes(app: object) -> list[tuple[str, str]]:
    from fastapi.routing import APIRoute

    found: list[tuple[str, str]] = []
    for route in app.routes:  # type: ignore[attr-defined]
        if not isinstance(route, APIRoute) or "{project_id}" not in route.path:
            continue
        module = getattr(route.endpoint, "__module__", "")
        if module not in {"freesearch.routers.projects", "freesearch.routers.api_keys"}:
            continue
        for method in sorted(route.methods - {"HEAD", "OPTIONS"}):
            found.append((method, route.path))
    return found


def _route_body(method: str, path: str, user_id: UUID) -> dict[str, object] | None:
    if path.endswith("/provider-owner") and method == "POST":
        return {"user_id": str(user_id)}
    if path.endswith("/api-keys") and method == "POST":
        return {"label": "probe"}
    if path.endswith("/members") and method == "POST":
        return {"user_id": str(user_id)}
    if path.endswith("/members/bulk"):
        return {"changes": [{"user_id": str(user_id), "status": "suspended"}]}
    if path.endswith("/members/{user_id}") and method == "PATCH":
        return {"status": "suspended"}
    if path.endswith("/rotate"):
        return {}
    return None


@pytest.mark.asyncio
async def test_project_scoped_routes_hide_existence_from_non_members(
    tmp_path: Path, auth_secret: str
) -> None:
    repository = await create_alpha_test_db(tmp_path / "r5-visibility.db")
    try:
        system_row, admin_row, peer_row = await _seed_users(repository)
        creator_row = await create_temp_user(
            repository, temp_email("r5-creator"), system_admin=True
        )
        stranger_row = await create_temp_user(repository, temp_email("r5-stranger"))
        member_row = await create_temp_user(repository, temp_email("r5-member"))
        service = ProjectService(repository)
        project = await service.create_project(
            temp_principal(creator_row),
            ProjectCreate(name="R5", slug="r5-visibility", initial_admin_user_id=admin_row.id),
        )
        await service.add_member(
            temp_principal(admin_row), project.id, ProjectMemberAdd(user_id=member_row.id)
        )
        app = create_app([], repository=repository, secret_store=_MemorySecretStore())
        with TestClient(app) as client:
            admin_headers = _login(client, admin_row.email)
            issued = client.post(
                f"/api/v1/projects/{project.id}/api-keys",
                json={"label": "r5"},
                headers=admin_headers,
            )
            assert issued.status_code == 201
            key_id = issued.json()["id"]
            outsiders = {
                "stranger": _login(client, stranger_row.email),
                "system admin": _login(client, system_row.email),
            }
            member_headers = _login(client, member_row.email)

            routes = _project_scoped_routes(app)
            assert len(routes) >= 12, routes
            for method, template in routes:
                concrete = (
                    template.replace("{user_id}", str(member_row.id))
                    .replace("{key_id}", key_id)
                    .replace("{role_key}", BuiltinRole.ROUTING_EDITOR.value)
                )
                body = _route_body(method, template, peer_row.id)
                unknown = client.request(
                    method,
                    concrete.replace("{project_id}", str(uuid4())),
                    headers=admin_headers,
                    json=body,
                )
                assert unknown.status_code == 404, (method, template, unknown.status_code)
                for who, headers in outsiders.items():
                    hidden = client.request(
                        method,
                        concrete.replace("{project_id}", str(project.id)),
                        headers=headers,
                        json=body,
                    )
                    assert hidden.status_code == 404, (who, method, template, hidden.status_code)
                    assert hidden.content == unknown.content, (who, method, template)
                    assert dict(hidden.headers).get("content-type") == dict(unknown.headers).get(
                        "content-type"
                    )

            # A member without the permission is told 403, not 404.
            for method, path, body in (
                ("GET", f"/api/v1/projects/{project.id}/api-keys", None),
                ("POST", f"/api/v1/projects/{project.id}/api-keys", {"label": "x"}),
                ("DELETE", f"/api/v1/projects/{project.id}/api-keys/{key_id}", None),
                ("POST", f"/api/v1/projects/{project.id}/archive", None),
                ("POST", f"/api/v1/projects/{project.id}/members", {"user_id": str(peer_row.id)}),
                (
                    "DELETE",
                    f"/api/v1/projects/{project.id}/members/{admin_row.id}",
                    None,
                ),
            ):
                denied = client.request(method, path, headers=member_headers, json=body)
                assert denied.status_code == 403, (method, path, denied.status_code)
            assert (
                client.get(f"/api/v1/projects/{project.id}/members", headers=member_headers)
            ).status_code == 200

            # Nothing the outsiders attempted changed the project.
            listed = client.get(f"/api/v1/projects/{project.id}/api-keys", headers=admin_headers)
            assert [(item["id"], item["status"]) for item in listed.json()] == [(key_id, "active")]
            members = client.get(f"/api/v1/projects/{project.id}/members", headers=admin_headers)
            assert {item["user_id"] for item in members.json()} == {
                str(admin_row.id),
                str(creator_row.id),
                str(member_row.id),
            }
            owner = client.get(
                f"/api/v1/projects/{project.id}/provider-owner", headers=admin_headers
            )
            assert owner.json()["user_id"] == str(creator_row.id)
    finally:
        await repository.close()


# --- R2: deactivation never removes the last active system administrator ---------


async def _active(repository: SQLiteRepository, user_id: UUID) -> bool:
    async with repository.session() as session:
        row = await session.get(UserRow, user_id)
        assert row is not None
        return bool(row.is_active)


@pytest.mark.asyncio
async def test_service_deactivation_refuses_the_last_active_system_admin(
    tmp_path: Path, auth_secret: str
) -> None:
    repository = await create_alpha_test_db(tmp_path / "r2-rest.db")
    try:
        only = await create_temp_user(repository, temp_email("r2-only"), system_admin=True)
        app = create_app([], repository=repository, secret_store=_MemorySecretStore())
        with TestClient(app) as client:
            only_headers = _login(client, only.email)
            with pytest.raises(AuthLastSystemAdmin):
                await ProjectService(repository).deactivate_accounts(
                    [only.id], actor=temp_principal(only)
                )
            assert await _active(repository, only.id) is True
            # No state change: the same session still works with system authority.
            assert client.get("/api/v1/system/access", headers=only_headers).status_code == 200
            assert client.get("/api/v1/routing/config", headers=only_headers).status_code == 200

            second = await create_temp_user(repository, temp_email("r2-second"), system_admin=True)
            second_headers = _login(client, second.email)
            done = await ProjectService(repository).deactivate_accounts(
                [only.id], actor=temp_principal(second)
            )
            assert done[0].is_active is False
            assert await _active(repository, only.id) is False
            # Now the second is the last one and cannot deactivate itself.
            with pytest.raises(AuthLastSystemAdmin):
                await ProjectService(repository).deactivate_accounts(
                    [second.id], actor=temp_principal(second)
                )
            assert client.get("/users/me", headers=second_headers).status_code == 200
            assert await _active(repository, second.id) is True
    finally:
        await repository.close()
