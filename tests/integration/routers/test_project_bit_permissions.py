"""HTTP regression coverage for project permission bits."""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from freesearch.models.projects import (
    BuiltinRole,
    MembershipStatus,
    PermissionAction,
    ProjectCreate,
    ProjectMemberAdd,
    ScopeType,
)
from freesearch.persistence.projects import ProjectMembershipRow, ProjectRepository
from freesearch.routers.api import create_app
from freesearch.services.authorization import ScopedAuthorizationService, human_principal
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
            contract_path = (
                Path(__file__).resolve().parents[3]
                / "freesearch-ui/src/domains/projects/model/permissionContract.json"
            )
            contract = json.loads(contract_path.read_text(encoding="utf-8"))
            assert [
                {key: entry[key] for key in ("key", "bit", "action")}
                for entry in catalog.json()["permissions"]
            ] == contract["permissions"]
            assert {
                preset["label"]: preset["permissions"] for preset in catalog.json()["presets"]
            } == contract["presets"]
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


@pytest.mark.asyncio
async def test_archived_member_changes_cannot_expand_access(
    tmp_path: Path, auth_secret: str
) -> None:
    repository = await create_alpha_test_db(tmp_path / "archived-bits.db")
    try:
        owner = await create_temp_user(repository, temp_email("archive-owner"), system_admin=True)
        peer = await create_temp_user(repository, temp_email("archive-admin"))
        first = await create_temp_user(repository, temp_email("archive-dev"))
        second = await create_temp_user(repository, temp_email("archive-dev2"))
        service = ProjectService(repository)
        principal = temp_principal(owner)
        project = await service.create_project(
            principal, ProjectCreate(name="Archive", slug="archive", initial_admin_user_id=owner.id)
        )
        await service.add_member(
            principal,
            project.id,
            ProjectMemberAdd(user_id=peer.id, initial_role=BuiltinRole.PROJECT_ADMIN),
        )
        for user in (first, second):
            await service.add_member(
                principal, project.id, ProjectMemberAdd(user_id=user.id, permissions=3)
            )
        app = create_app([], repository=repository, secret_store=MemoryStore())
        with TestClient(app) as client:
            headers = login(client, owner.email)
            root = f"/api/v1/projects/{project.id}"
            assert client.post(f"{root}/archive", headers=headers).status_code == 200
            before = client.get(f"{root}/members", headers=headers).json()
            audit_before = await audit_rows(repository, scope="project")
            attempts = [
                (f"{root}/members/{first.id}", {"role": "admin"}),
                (f"{root}/members/{first.id}", {"permissions": 7}),
                (
                    f"{root}/members/bulk",
                    {"changes": [{"user_id": str(first.id), "role": "admin"}]},
                ),
                (
                    f"{root}/members/bulk",
                    {
                        "changes": [
                            {"user_id": str(first.id), "permissions": 1},
                            {"user_id": str(second.id), "permissions": 7},
                        ]
                    },
                ),
            ]
            for url, body in attempts:
                response = client.patch(url, headers=headers, json=body)
                assert response.status_code == 409, response.text
                assert "PROJECT_ARCHIVED" in response.text
                assert client.get(f"{root}/members", headers=headers).json() == before
                assert await audit_rows(repository, scope="project") == audit_before
            transfer = client.post(
                f"{root}/provider-owner", headers=headers, json={"user_id": str(peer.id)}
            )
            assert transfer.status_code == 409
            assert "PROJECT_ARCHIVED" in transfer.text
            assert client.get(f"{root}/provider-owner", headers=headers).json()["user_id"] == str(
                owner.id
            )
            assert await audit_rows(repository, scope="project") == audit_before
            assert (
                client.post(
                    f"{root}/provider-owner", headers=headers, json={"user_id": str(owner.id)}
                ).status_code
                == 200
            )
            assert (
                client.patch(
                    f"{root}/members/bulk",
                    headers=headers,
                    json={"changes": [{"user_id": str(first.id), "role": "developer"}]},
                ).status_code
                == 200
            )
            assert (
                client.patch(
                    f"{root}/members/{first.id}", headers=headers, json={"permissions": 1}
                ).status_code
                == 200
            )
            assert (
                client.patch(
                    f"{root}/members/bulk",
                    headers=headers,
                    json={"changes": [{"user_id": str(second.id), "permissions": 1}]},
                ).status_code
                == 200
            )
            assert (
                client.patch(
                    f"{root}/members/{peer.id}", headers=headers, json={"role": "developer"}
                ).status_code
                == 200
            )
            assert (
                client.patch(
                    f"{root}/members/{first.id}", headers=headers, json={"status": "suspended"}
                ).status_code
                == 200
            )
            after_reduction = client.get(f"{root}/members", headers=headers).json()
            audit_after_reduction = await audit_rows(repository, scope="project")
            assert (
                client.patch(
                    f"{root}/members/{first.id}", headers=headers, json={"status": "active"}
                ).status_code
                == 409
            )
            assert client.get(f"{root}/members", headers=headers).json() == after_reduction
            assert await audit_rows(repository, scope="project") == audit_after_reduction
    finally:
        await repository.close()


@pytest.mark.asyncio
async def test_live_permissions_refresh_after_raw_update_in_same_session(
    tmp_path: Path, auth_secret: str
) -> None:
    repository = await create_alpha_test_db(tmp_path / "live-bits.db")
    try:
        owner = await create_temp_user(repository, temp_email("refresh-owner"), system_admin=True)
        developer = await create_temp_user(repository, temp_email("refresh-dev"))
        service = ProjectService(repository)
        principal = temp_principal(owner)
        project = await service.create_project(
            principal, ProjectCreate(name="Refresh", slug="refresh", initial_admin_user_id=owner.id)
        )
        await service.add_member(
            principal, project.id, ProjectMemberAdd(user_id=developer.id, permissions=4)
        )
        authorization = ScopedAuthorizationService(repository)
        dev = human_principal(temp_principal(developer))
        async with repository.session() as session:
            membership = await session.get(
                ProjectMembershipRow, (str(project.id), str(developer.id))
            )
            assert membership is not None and membership.permissions == 4
            context = await authorization.resolve_project_context_in_session(
                session, dev, project.id
            )
            assert context is not None and context.allows(PermissionAction.TRACES_READ)
            assert (
                PermissionAction.TRACES_READ
                in await authorization.effective_permissions_in_session(
                    session, dev, scope_type=ScopeType.PROJECT, scope_id=project.id
                )
            )
            await session.execute(
                text(
                    "UPDATE project_memberships SET permissions=0 "
                    "WHERE project_id=:p AND user_id=:u"
                ),
                {"p": str(project.id), "u": str(developer.id)},
            )
            context = await authorization.resolve_project_context_in_session(
                session, dev, project.id
            )
            assert context is not None and not context.allows(PermissionAction.TRACES_READ)
            assert (
                PermissionAction.TRACES_READ
                not in await authorization.effective_permissions_in_session(
                    session, dev, scope_type=ScopeType.PROJECT, scope_id=project.id
                )
            )
    finally:
        await repository.close()


@pytest.mark.asyncio
async def test_member_list_reports_deactivated_creator(tmp_path: Path, auth_secret: str) -> None:
    repository = await create_alpha_test_db(tmp_path / "inactive-member.db")
    try:
        system = await create_temp_user(
            repository, temp_email("inactive-system"), system_admin=True
        )
        creator = await create_temp_user(
            repository, temp_email("inactive-creator"), system_admin=True
        )
        peer = await create_temp_user(repository, temp_email("active-peer"))
        service = ProjectService(repository)
        project = await service.create_project(
            temp_principal(creator),
            ProjectCreate(name="Inactive", slug="inactive", initial_admin_user_id=creator.id),
        )
        await service.add_member(
            temp_principal(creator),
            project.id,
            ProjectMemberAdd(user_id=peer.id, initial_role=BuiltinRole.PROJECT_ADMIN),
        )
        await service.deactivate_accounts([creator.id], actor=temp_principal(system))
        app = create_app([], repository=repository, secret_store=MemoryStore())
        with TestClient(app) as client:
            members = client.get(
                f"/api/v1/projects/{project.id}/members", headers=login(client, peer.email)
            )
            assert members.status_code == 200
            by_id = {member["user_id"]: member for member in members.json()}
            assert by_id[str(creator.id)]["status"] == "active"
            assert by_id[str(creator.id)]["account_active"] is False
            assert by_id[str(peer.id)]["account_active"] is True
    finally:
        await repository.close()


@pytest.mark.asyncio
async def test_isolated_developer_bits_gate_routes(tmp_path: Path, auth_secret: str) -> None:
    repository = await create_alpha_test_db(tmp_path / "isolated-bits.db")
    try:
        owner = await create_temp_user(repository, temp_email("gates-owner"), system_admin=True)
        developer = await create_temp_user(repository, temp_email("gates-dev"))
        service = ProjectService(repository)
        principal = temp_principal(owner)
        projects = []
        for name in ("source", "target"):
            project = await service.create_project(
                principal, ProjectCreate(name=name, slug=name, initial_admin_user_id=owner.id)
            )
            await service.add_member(
                principal, project.id, ProjectMemberAdd(user_id=developer.id, permissions=0)
            )
            projects.append(project)
        source, target = projects
        app = create_app([], repository=repository, secret_store=MemoryStore())
        with TestClient(app) as client:
            admin = login(client, owner.email)
            dev = login(client, developer.email)
            root = f"/api/v1/projects/{target.id}"
            issued = client.post(f"{root}/api-keys", headers=admin, json={"label": "revoke"})
            assert issued.status_code == 201
            key_url = f"{root}/api-keys/{issued.json()['id']}"
            copy = {
                "source_project_id": str(source.id),
                "expected_source_revision": 0,
                "expected_target_revision": 0,
                "expected_system_revision": 0,
            }
            fetch = {"project_id": str(target.id), "url": "https://example.com"}
            cases = [
                (2, lambda: client.post("/fetch", headers=dev, json=fetch)),
                (8, lambda: client.get(f"{root}/usage", headers=dev)),
                (32, lambda: client.post(f"{root}/settings/copy/preview", headers=dev, json=copy)),
                (128, lambda: client.delete(key_url, headers=dev)),
            ]
            for bit, request in cases:
                assert request().status_code == 403
                updated = client.patch(
                    f"{root}/members/{developer.id}", headers=admin, json={"permissions": bit}
                )
                assert updated.status_code == 200
                response = request()
                if bit == 2:
                    # No provider is configured; execution passes authorization but cannot route.
                    assert response.status_code != 403
                else:
                    assert response.status_code == (204 if bit == 128 else 200), response.text
                assert (
                    client.patch(
                        f"{root}/members/{developer.id}", headers=admin, json={"permissions": 0}
                    ).status_code
                    == 200
                )
    finally:
        await repository.close()
