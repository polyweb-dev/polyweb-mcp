"""Focused HTTP regression coverage for project scoping and live revocation."""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from freesearch.models.projects import BuiltinRole, ProjectCreate
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
