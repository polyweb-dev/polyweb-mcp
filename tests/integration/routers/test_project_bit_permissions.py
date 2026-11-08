"""HTTP regression coverage for project permission bits."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from freesearch.models.projects import (
    BuiltinRole,
    MembershipStatus,
    ProjectCreate,
    ProjectMemberAdd,
)
from freesearch.persistence.projects import ProjectRepository
from freesearch.routers.api import create_app
from freesearch.services.projects import ProjectService
from tests.fixtures.alpha_fixtures import create_alpha_test_db
from tests.fixtures.api_keys import audit_rows
from tests.fixtures.auth import TEMP_PASSWORD, create_temp_user, temp_email, temp_principal


class MemoryStore:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    async def get(self, name: str) -> str | None:
        return self.values.get(name)

    async def set(self, name: str, value: str) -> None:
        self.values[name] = value

    async def delete(self, name: str) -> None:
        self.values.pop(name, None)


def login(client: TestClient, email: str) -> dict[str, str]:
    response = client.post("/auth/jwt/login", data={"username": email, "password": TEMP_PASSWORD})
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


@pytest.mark.asyncio
async def test_member_permissions_and_endpoint_gates(tmp_path: Path, auth_secret: str) -> None:
    repository = await create_alpha_test_db(tmp_path / "bits.db")
    try:
        owner = await create_temp_user(repository, temp_email("bits-owner"), system_admin=True)
        developer = await create_temp_user(repository, temp_email("bits-dev"))
        service = ProjectService(repository)
        principal = temp_principal(owner)
        project = await service.create_project(
            principal,
            ProjectCreate(name="Bits", slug="bits", initial_admin_user_id=owner.id),
        )
        await service.add_member(
            principal, project.id, ProjectMemberAdd(user_id=developer.id, permissions=0)
        )
        app = create_app([], repository=repository, secret_store=MemoryStore())
        with TestClient(app) as client:
            admin = login(client, owner.email)
            dev = login(client, developer.email)
            root = f"/api/v1/projects/{project.id}"
            assert client.get(f"{root}/traces", headers=dev).status_code == 403
            settings = {"expected_revision": 0, "execution": {"cache_enabled": False}}
            assert client.put(f"{root}/settings", headers=dev, json=settings).status_code == 403
            order = {"strategy": "lowest_cost"}
            assert (
                client.put(f"{root}/routing/order/search", headers=dev, json=order).status_code
                == 403
            )
            assert (
                client.post(
                    "/search", headers=dev, json={"project_id": str(project.id), "query": "test"}
                ).status_code
                == 403
            )
            assert client.get(f"{root}/traces", headers=admin).status_code == 200
            assert client.put(f"{root}/settings", headers=admin, json=settings).status_code == 200
            assert (
                client.put(f"{root}/routing/order/search", headers=admin, json=order).status_code
                == 200
            )
            patch = client.patch(
                f"{root}/members/{developer.id}", headers=admin, json={"permissions": 69}
            )
            assert patch.status_code == 200
            assert patch.json()["permissions"] == 69
            assert patch.json()["role"] == "developer"
            assert client.get(f"{root}/traces", headers=dev).status_code == 200
            catalog = client.get("/api/v1/permissions/project-catalog", headers=dev)
            assert catalog.status_code == 200
            assert len(catalog.json()["permissions"]) == 9
            assert len(catalog.json()["presets"]) == 3
            assert (
                client.patch(
                    f"{root}/members/{developer.id}", headers=admin, json={"role": "admin"}
                ).json()["role"]
                == "admin"
            )
            demoted = client.patch(
                f"{root}/members/{developer.id}", headers=admin, json={"role": "developer"}
            )
            assert demoted.json()["permissions"] == 69
        actions = [row["action"] for row in await audit_rows(repository, scope="project")]
        assert actions.count("member.permissions_changed") == 1
        assert actions.count("member.role_changed") == 2
    finally:
        await repository.close()


@pytest.mark.asyncio
async def test_owner_transfer_and_guards(tmp_path: Path, auth_secret: str) -> None:
    repository = await create_alpha_test_db(tmp_path / "owner.db")
    try:
        owner = await create_temp_user(repository, temp_email("owner"), system_admin=True)
        peer = await create_temp_user(repository, temp_email("peer"))
        developer = await create_temp_user(repository, temp_email("developer"))
        service = ProjectService(repository)
        principal = temp_principal(owner)
        project = await service.create_project(
            principal, ProjectCreate(name="Owner", slug="owner", initial_admin_user_id=owner.id)
        )
        await service.add_member(
            principal,
            project.id,
            ProjectMemberAdd(user_id=peer.id, initial_role=BuiltinRole.PROJECT_ADMIN),
        )
        await service.add_member(principal, project.id, ProjectMemberAdd(user_id=developer.id))
        app = create_app([], repository=repository, secret_store=MemoryStore())
        with TestClient(app) as client:
            headers = login(client, owner.email)
            peer_headers = login(client, peer.email)
            url = f"/api/v1/projects/{project.id}/provider-owner"
            assert client.get(url, headers=headers).json()["user_id"] == str(owner.id)
            assert (
                client.post(url, headers=peer_headers, json={"user_id": str(peer.id)}).status_code
                == 403
            )
            assert (
                client.patch(
                    f"/api/v1/projects/{project.id}/members/{owner.id}",
                    headers=headers,
                    json={"role": "developer"},
                ).status_code
                == 409
            )
            result = client.post(url, headers=headers, json={"user_id": str(peer.id)})
            assert result.status_code == 200, result.text
            assert result.json() == {
                "user_id": str(peer.id),
                "email": peer.email,
                "unassigned_pools": [],
            }
            assert (
                "vault.manage"
                in client.get("/api/v1/system/access", headers=peer_headers).json()["permissions"]
            )
            developer_headers = login(client, developer.email)
            assert (
                "vault.manage"
                not in client.get("/api/v1/system/access", headers=developer_headers).json()[
                    "permissions"
                ]
            )
            async with repository.session() as session:
                await ProjectRepository(session).update_membership_status(
                    project_id=project.id, user_id=peer.id, status=MembershipStatus.SUSPENDED
                )
                await session.commit()
            assert client.get(url, headers=headers).json() is None
            assert (
                client.post(
                    url, headers=developer_headers, json={"user_id": str(developer.id)}
                ).status_code
                == 403
            )
            claim = client.post(url, headers=headers, json={"user_id": str(owner.id)})
            assert claim.status_code == 200, claim.text
            assert claim.json()["user_id"] == str(owner.id)
        actions = [row["action"] for row in await audit_rows(repository, scope="project")]
        assert actions.count("project.provider_owner_transferred") == 2
    finally:
        await repository.close()
