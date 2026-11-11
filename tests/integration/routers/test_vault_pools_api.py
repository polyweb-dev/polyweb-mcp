"""Vault pool API against real SQLite and materialized runtime bindings."""

import json
import sys
from types import ModuleType
from unittest.mock import AsyncMock
from uuid import UUID

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from sqlalchemy import select, text

from polyweb.configuration.config import get_settings
from polyweb.models.credentials import CredentialOperation
from polyweb.models.projects import BuiltinRole, MembershipStatus, ProjectMemberAdd
from polyweb.persistence.audit import SystemAuditEventRow
from polyweb.persistence.bindings import ProjectBindingRepository
from polyweb.persistence.credentials import CredentialProjectGrantRow
from polyweb.persistence.key_pools import KeyPoolRepository
from polyweb.persistence.projects import ProjectRepository
from polyweb.persistence.storage import SQLiteRepository
from polyweb.persistence.users import UserRow
from polyweb.routers.api import create_app
from polyweb.services.projects import ProjectService
from tests.fixtures.a2_execution import build_execution_world
from tests.fixtures.alpha_fixtures import ALPHA_ADMIN_PASSWORD
from tests.fixtures.auth import (
    account_id_from_pair,
    bare_login,
    raw_auth_headers,
    register_and_login,
    register_system_admin_login,
    temp_email,
    temp_principal,
)
from tests.fixtures.execution import seed_execution_project

BASE = "/api/v1/account/vault"


@pytest.mark.asyncio
async def test_migrated_pool_is_readable_editable_and_preserves_windows(
    repository, vault_env, auth_secret
):
    with TestClient(create_app([], repository=repository)) as client:
        owner = await register_system_admin_login(client, repository, temp_email("migrated-pool"))
        headers = raw_auth_headers(owner["access_token"])
        project = await seed_execution_project(repository, user_id=account_id_from_pair(owner))
        key = client.post(
            f"{BASE}/keys",
            headers=headers,
            json={"provider_type": "exa", "label": "key", "secret": "private"},
        ).json()
        created = client.post(
            f"{BASE}/keys/{key['id']}/pools",
            headers=headers,
            json={"label": "pool", "project_id": str(project.project_id)},
        )
        assert created.status_code == 201
        pool_id = created.json()["id"]
        limits = {
            "search": {"rate_limit": 20, "rate_window_seconds": 60},
            "fetch": {"rate_limit": None, "rate_window_seconds": 3600},
        }
        import json

        async with repository.session() as session:
            await session.execute(
                text("UPDATE key_pools SET operation_limits=:limits WHERE id=:pool"),
                {"limits": json.dumps(limits), "pool": pool_id},
            )
            await session.commit()
        path = f"{BASE}/pools/{pool_id}"
        assert client.get(path, headers=headers).json()["operation_limits"] == limits
        assert (
            client.get(f"{BASE}/keys/{key['id']}/pools", headers=headers).json()[0][
                "operation_limits"
            ]
            == limits
        )
        updated = client.patch(path, headers=headers, json={"label": "renamed"})
        assert updated.status_code == 200, updated.text
        assert updated.json()["operation_limits"] == limits
        async with repository.session() as session:
            rows = (
                await session.execute(
                    text(
                        "SELECT operation_scope,base_rate,rate_window_seconds "
                        "FROM project_pool_allocations WHERE key_pool_id=:pool "
                        "ORDER BY operation_scope"
                    ),
                    {"pool": pool_id},
                )
            ).all()
            assert rows == [("fetch", None, 3600), ("search", 20, 60)]


@pytest_asyncio.fixture
async def repository(tmp_path):
    repo = await SQLiteRepository.open(tmp_path / "pools.db")
    try:
        yield repo
    finally:
        await repo.close()


@pytest.fixture
def vault_env(monkeypatch, tmp_path):
    monkeypatch.setenv("POLYWEB_ENCRYPTION_KEY", "pool-integration-test-key")
    monkeypatch.setenv("POLYWEB_ENCRYPTION_KEY_FILE", str(tmp_path / "vault-key"))
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


async def _bindings(repository, project_id):
    async with repository.session() as session:
        return await ProjectBindingRepository(session).list_for_project(project_id=project_id)


async def _assert_bindings(repository, project_id, *exa_credential_ids):
    bindings = await _bindings(repository, project_id)
    # Only explicitly assigned pools confer runtime access, including keyless providers.
    expected = {(credential_id, "exa") for credential_id in exa_credential_ids}
    assert len(bindings) == len(expected)
    assert {(binding.credential_id, binding.route_label) for binding in bindings} == expected
    async with repository.session() as session:
        pools = await KeyPoolRepository(session).list_for_project(project_id)
        assert {(pool.credential_id, pool.provider_type) for pool in pools} == expected
        grants = (
            await session.scalars(
                select(CredentialProjectGrantRow).where(
                    CredentialProjectGrantRow.project_id == str(project_id)
                )
            )
        ).all()
        assert len(grants) == len(exa_credential_ids)
        assert {UUID(grant.credential_id) for grant in grants} == set(exa_credential_ids)
        for grant in grants:
            pool = next(pool for pool in pools if str(pool.credential_id) == grant.credential_id)
            assert grant.owner_scope == "system"
            assert set(json.loads(grant.permitted_operations)) == set(pool.operations)
    for binding in bindings:
        pool = next(pool for pool in pools if pool.credential_id == binding.credential_id)
        assert {operation.value for operation in binding.enabled_operations} == set(pool.operations)
    return bindings


@pytest.mark.asyncio
async def test_pool_lifecycle_authorization_and_materialization(repository, vault_env, auth_secret):
    with TestClient(create_app([], repository=repository)) as client:
        owner = await register_system_admin_login(client, repository, temp_email("pool-owner"))
        other = await register_system_admin_login(client, repository, temp_email("pool-other"))
        # A normal signup owns a Default project, so it may use the vault (404 on
        # foreign keys); only an account with no project at all is denied (403).
        developer = register_and_login(client, temp_email("pool-developer"))
        bare = await bare_login(client, repository, temp_email("pool-bare"))
        headers = raw_auth_headers(owner["access_token"])
        other_headers = raw_auth_headers(other["access_token"])
        dev_headers = raw_auth_headers(developer["access_token"])
        bare_headers = raw_auth_headers(bare["access_token"])
        project = await seed_execution_project(repository, user_id=account_id_from_pair(owner))
        foreign = await seed_execution_project(repository, user_id=account_id_from_pair(other))
        key = client.post(
            f"{BASE}/keys",
            headers=headers,
            json={"provider_type": "exa", "label": "key", "secret": "private"},
        )
        assert key.status_code == 201, key.text
        key_path = f"{BASE}/keys/{key.json()['id']}/pools"
        assert client.get(key_path, headers=bare_headers).status_code == 403
        assert client.get(key_path, headers=dev_headers).status_code == 404
        assert client.get(key_path, headers=other_headers).status_code == 404
        for operations, code in [
            ([], "OPERATIONS_REQUIRED"),
            (["bogus"], "OPERATION_NOT_SUPPORTED"),
        ]:
            invalid = client.post(
                key_path, headers=headers, json={"label": "bad", "operations": operations}
            )
            assert invalid.status_code == 422
            assert invalid.json()["detail"]["code"] == code
        created = client.post(
            key_path,
            headers=headers,
            json={"label": "pool", "budget": {"limit": 12.345678}, "rate": {"limit": None}},
        )
        assert created.status_code == 201, created.text
        pool = created.json()
        assert pool["budget"] == {"limit": 12.345678, "period": "month"}
        assert pool["budget_used_usd"] == 0
        assert set(pool["operations"]) == {"search", "fetch"}
        url = f"{BASE}/pools/{pool['id']}"
        assert client.get(url, headers=other_headers).status_code == 404
        denied = client.post(
            f"{url}/assign", headers=headers, json={"project_id": str(foreign.project_id)}
        )
        assert denied.status_code == 403
        # The owner's provider-owner projects are exactly the signup Default project
        # and the manual one. Available providers are the owner's key providers not yet
        # assigned there: the Default project already holds both keyless pools.
        owned = client.get("/api/v1/projects", headers=headers).json()
        default_id = next(item["id"] for item in owned if item["name"] == "Default")
        projects = client.get(f"{BASE}/projects", headers=headers).json()
        assert projects == sorted(
            [
                {"id": default_id, "name": "Default", "available_providers": ["exa"]},
                {
                    "id": str(project.project_id),
                    "name": "Execution Project",
                    "available_providers": ["exa", "keenable", "tavily"],
                },
            ],
            key=lambda item: item["id"],
        )
        assigned = client.post(
            f"{url}/assign", headers=headers, json={"project_id": str(project.project_id)}
        )
        assert assigned.status_code == 200, assigned.text
        assert assigned.json()["project_id"] == str(project.project_id)
        credential_id = UUID(key.json()["id"])
        bindings = await _assert_bindings(repository, project.project_id, credential_id)
        binding = next(binding for binding in bindings if binding.credential_id == credential_id)
        assert {op.value for op in binding.enabled_operations} == {"search", "fetch"}
        updated = client.patch(url, headers=headers, json={"operations": ["search"]})
        assert updated.status_code == 200, updated.text
        bindings = await _assert_bindings(repository, project.project_id, credential_id)
        binding = next(binding for binding in bindings if binding.credential_id == credential_id)
        assert {op.value for op in binding.enabled_operations} == {"search"}
        unassigned = client.post(f"{url}/unassign", headers=headers)
        assert unassigned.status_code == 200
        assert unassigned.json()["project_id"] is None
        await _assert_bindings(repository, project.project_id)
        assert (
            client.post(
                f"{url}/assign", headers=headers, json={"project_id": str(project.project_id)}
            ).status_code
            == 200
        )
        await _assert_bindings(repository, project.project_id, credential_id)
        assert client.delete(url, headers=headers).status_code == 204
        await _assert_bindings(repository, project.project_id)
        async with repository.session() as session:
            events = (
                await session.scalars(
                    select(SystemAuditEventRow).where(SystemAuditEventRow.target_id == pool["id"])
                )
            ).all()
            assert {event.action for event in events} == {
                "vault.pool_created",
                "vault.pool_assigned",
                "vault.pool_updated",
                "vault.pool_unassigned",
                "vault.pool_deleted",
            }
            assert all("private" not in event.detail for event in events)


@pytest.mark.asyncio
async def test_copy_and_budget_usage(repository, vault_env, auth_secret, monkeypatch):
    module = ModuleType("polyweb.services.pool_budget")
    counter = AsyncMock(side_effect=[0, 0, 1234567, 0])
    module.pool_budget_used_micros = counter
    monkeypatch.setitem(sys.modules, "polyweb.services.pool_budget", module)
    with TestClient(create_app([], repository=repository)) as client:
        owner = await register_system_admin_login(client, repository, temp_email("copy-owner"))
        headers = raw_auth_headers(owner["access_token"])
        owner_id = account_id_from_pair(owner)
        first = await seed_execution_project(repository, user_id=owner_id)
        second = await seed_execution_project(repository, user_id=owner_id)
        key = client.post(
            f"{BASE}/keys",
            headers=headers,
            json={"provider_type": "exa", "label": "key", "secret": "private"},
        ).json()
        created = client.post(
            f"{BASE}/keys/{key['id']}/pools",
            headers=headers,
            json={"label": "first", "project_id": str(first.project_id), "budget": {"limit": 5}},
        )
        assert created.status_code == 201, created.text
        url = f"{BASE}/pools/{created.json()['id']}"
        copied = client.post(
            f"{url}/copy",
            headers=headers,
            json={"project_id": str(second.project_id), "label": "second"},
        )
        assert copied.status_code == 200, copied.text
        assert copied.json()["project_id"] == str(second.project_id)
        assert client.get(url, headers=headers).json()["budget_used_usd"] == 1.234567
        assert (
            client.get(f"{BASE}/pools/{copied.json()['id']}", headers=headers).json()[
                "budget_used_usd"
            ]
            == 0
        )
        assert [call.args[1] for call in counter.await_args_list] == [
            UUID(created.json()["id"]),
            UUID(copied.json()["id"]),
            UUID(created.json()["id"]),
            UUID(copied.json()["id"]),
        ]


@pytest.mark.asyncio
async def test_transfer_unassigns_pools_and_removes_runtime(repository, vault_env, auth_secret):
    with TestClient(create_app([], repository=repository)) as client:
        owner = await register_system_admin_login(client, repository, temp_email("transfer-owner"))
        peer = register_and_login(client, temp_email("transfer-peer"))
        headers = raw_auth_headers(owner["access_token"])
        owner_id = account_id_from_pair(owner)
        peer_id = account_id_from_pair(peer)
        project = await seed_execution_project(repository, user_id=owner_id)
        async with repository.session() as session:
            user = await session.get(UserRow, owner_id)
            assert user is not None
            actor = temp_principal(user)
        await ProjectService(repository).add_member(
            actor,
            project.project_id,
            ProjectMemberAdd(user_id=peer_id, initial_role=BuiltinRole.PROJECT_ADMIN),
        )
        key = client.post(
            f"{BASE}/keys",
            headers=headers,
            json={"provider_type": "exa", "label": "key", "secret": "private"},
        ).json()
        created = client.post(
            f"{BASE}/keys/{key['id']}/pools",
            headers=headers,
            json={"label": "transfer", "project_id": str(project.project_id)},
        )
        assert created.status_code == 201, created.text
        pool_id = UUID(created.json()["id"])
        await _assert_bindings(repository, project.project_id, UUID(key["id"]))
        transfer = client.post(
            f"/api/v1/projects/{project.project_id}/provider-owner",
            headers=headers,
            json={"user_id": str(peer_id)},
        )
        assert transfer.status_code == 200, transfer.text
        assert transfer.json()["unassigned_pools"] == [
            {"pool_id": str(pool_id), "label": "transfer"}
        ]
        await _assert_bindings(repository, project.project_id)
        async with repository.session() as session:
            pool = await KeyPoolRepository(session).get(pool_id)
            assert pool is not None and pool.project_id is None
        peer_headers = raw_auth_headers(peer["access_token"])
        peer_key = client.post(
            f"{BASE}/keys",
            headers=peer_headers,
            json={"provider_type": "exa", "label": "peer", "secret": "peer-secret"},
        )
        assert peer_key.status_code == 201, peer_key.text
        peer_pool = client.post(
            f"{BASE}/keys/{peer_key.json()['id']}/pools",
            headers=peer_headers,
            json={"label": "peer pool", "project_id": str(project.project_id)},
        )
        assert peer_pool.status_code == 201, peer_pool.text
        await _assert_bindings(repository, project.project_id, UUID(peer_key.json()["id"]))
        async with repository.session() as session:
            await ProjectRepository(session).update_membership_status(
                project_id=project.project_id, user_id=peer_id, status=MembershipStatus.SUSPENDED
            )
            await session.commit()
        claim = client.post(
            f"/api/v1/projects/{project.project_id}/provider-owner",
            headers=headers,
            json={"user_id": str(owner_id)},
        )
        assert claim.status_code == 200, claim.text
        assert claim.json()["unassigned_pools"] == [
            {"pool_id": peer_pool.json()["id"], "label": "peer pool"}
        ]
        await _assert_bindings(repository, project.project_id)


@pytest.mark.asyncio
async def test_api_writes_change_execution_lookup(tmp_path, monkeypatch, auth_secret):
    world = await build_execution_world(tmp_path, monkeypatch, limits=False)
    try:
        async with world.repository.session() as session:
            owner = await session.get(UserRow, world.project.actor_id)
            assert owner is not None
            email = owner.email
        world.adapters_by_secret["pool-secret"] = world.adapters["a1"]
        app = create_app([], repository=world.repository, secret_store=world.store)
        with TestClient(app) as client:
            login = client.post(
                "/auth/jwt/login", data={"username": email, "password": ALPHA_ADMIN_PASSWORD}
            )
            assert login.status_code == 200, login.text
            headers = raw_auth_headers(login.json()["access_token"])
            key = client.post(
                f"{BASE}/keys",
                headers=headers,
                json={"provider_type": "exa", "label": "runtime", "secret": "pool-secret"},
            )
            assert key.status_code == 201, key.text
            created = client.post(
                f"{BASE}/keys/{key.json()['id']}/pools",
                headers=headers,
                json={"label": "runtime"},
            )
            assert created.status_code == 201, created.text
            url = f"{BASE}/pools/{created.json()['id']}"
            assigned = client.post(
                f"{url}/assign", headers=headers, json={"project_id": str(world.project.project_id)}
            )
            assert assigned.status_code == 200, assigned.text
            credential_id = UUID(key.json()["id"])
            bindings = await _assert_bindings(
                world.repository, world.project.project_id, credential_id
            )
            binding = next(
                binding for binding in bindings if binding.credential_id == credential_id
            )
            for op in (CredentialOperation.SEARCH, CredentialOperation.FETCH):
                assert await world.service._resolve_binding(
                    world.context, binding, op, providers=None
                )
            assert (
                client.patch(url, headers=headers, json={"operations": ["search"]}).status_code
                == 200
            )
            bindings = await _assert_bindings(
                world.repository, world.project.project_id, credential_id
            )
            binding = next(
                binding for binding in bindings if binding.credential_id == credential_id
            )
            assert await world.service._resolve_binding(
                world.context, binding, CredentialOperation.SEARCH, providers=None
            )
            assert (
                await world.service._resolve_binding(
                    world.context, binding, CredentialOperation.FETCH, providers=None
                )
                is None
            )
            assert client.post(f"{url}/unassign", headers=headers).status_code == 200
            await _assert_bindings(world.repository, world.project.project_id)
    finally:
        await world.aclose()


@pytest.mark.asyncio
async def test_deactivation_unassigns_owned_pools(repository, vault_env, auth_secret):
    with TestClient(create_app([], repository=repository)) as client:
        # The owner is a bare system administrator: this test is about the seeded
        # project's owned pools, not about a signup Default project's sole administrator.
        owner = await bare_login(
            client, repository, temp_email("deactivate-owner"), system_admin=True
        )
        peer = register_and_login(client, temp_email("deactivate-peer"))
        owner_id = account_id_from_pair(owner)
        peer_id = account_id_from_pair(peer)
        headers = raw_auth_headers(owner["access_token"])
        project = await seed_execution_project(repository, user_id=owner_id)
        async with repository.session() as session:
            user = await session.get(UserRow, owner_id)
            assert user is not None
            actor = temp_principal(user)
        service = ProjectService(repository)
        await service.add_member(
            actor,
            project.project_id,
            ProjectMemberAdd(user_id=peer_id, initial_role=BuiltinRole.PROJECT_ADMIN),
        )
        key = client.post(
            f"{BASE}/keys",
            headers=headers,
            json={"provider_type": "exa", "label": "key", "secret": "private"},
        ).json()
        created = client.post(
            f"{BASE}/keys/{key['id']}/pools",
            headers=headers,
            json={"label": "owned", "project_id": str(project.project_id)},
        )
        assert created.status_code == 201, created.text
        await _assert_bindings(repository, project.project_id, UUID(key["id"]))
        # The installation must retain an active system administrator.
        await register_system_admin_login(client, repository, temp_email("replacement-admin"))
        await service.deactivate_accounts([owner_id], trusted=True)
        await _assert_bindings(repository, project.project_id)
        async with repository.session() as session:
            pool = await KeyPoolRepository(session).get(UUID(created.json()["id"]))
            assert pool is not None and pool.project_id is None
        claim = client.post(
            f"/api/v1/projects/{project.project_id}/provider-owner",
            headers=raw_auth_headers(peer["access_token"]),
            json={"user_id": str(peer_id)},
        )
        assert claim.status_code == 200, claim.text
        assert claim.json()["user_id"] == str(peer_id)
