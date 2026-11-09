"""Audit isolation and unavailable vault-key behavior for project routing."""

from collections.abc import AsyncIterator
from hashlib import sha256
from uuid import uuid4

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from sqlalchemy import select

from freesearch.configuration.config import get_settings
from freesearch.persistence.audit import ProjectAuditEventRow, SystemAuditEventRow
from freesearch.persistence.credentials import ProviderCredentialRow
from freesearch.persistence.key_pools import KeyPoolRow
from freesearch.persistence.storage import RuntimeSettingRow, SQLiteRepository
from freesearch.routers.api import create_app
from tests.fixtures.auth import (
    account_id_from_pair,
    raw_auth_headers,
    register_system_admin_login,
    temp_email,
)
from tests.fixtures.execution import seed_execution_project

BASE = "/api/v1/account/vault"


@pytest_asyncio.fixture
async def repository(tmp_path, monkeypatch) -> AsyncIterator[SQLiteRepository]:
    monkeypatch.setenv("FREESEARCH_ENCRYPTION_KEY", "routing-audit-test-key")
    monkeypatch.setenv("FREESEARCH_ENCRYPTION_KEY_FILE", str(tmp_path / "key"))
    get_settings.cache_clear()
    repo = await SQLiteRepository.open(tmp_path / "routing-audit.db")
    try:
        yield repo
    finally:
        await repo.close()
        get_settings.cache_clear()


async def audit_snapshot(repository: SQLiteRepository):
    async with repository.session() as session:
        system = set(
            (
                await session.execute(select(SystemAuditEventRow.id, SystemAuditEventRow.action))
            ).all()
        )
        projects = set(
            (
                await session.execute(
                    select(
                        ProjectAuditEventRow.id,
                        ProjectAuditEventRow.project_id,
                        ProjectAuditEventRow.action,
                    )
                )
            ).all()
        )
    return system, projects


async def durable_snapshot(repository: SQLiteRepository):
    async with repository.session() as session:
        credentials = set(
            (
                await session.execute(
                    select(
                        ProviderCredentialRow.id,
                        ProviderCredentialRow.label,
                        ProviderCredentialRow.status,
                        ProviderCredentialRow.generation,
                        ProviderCredentialRow.version,
                    )
                )
            ).all()
        )
        pools = set((await session.execute(select(KeyPoolRow.id, KeyPoolRow.project_id))).all())
        secrets = {
            key: sha256(value.encode()).hexdigest()
            for key, value in (
                await session.execute(
                    select(RuntimeSettingRow.key, RuntimeSettingRow.value_json).where(
                        RuntimeSettingRow.key.like("secret.enc:%")
                    )
                )
            ).all()
        }
    return credentials, pools, secrets, await audit_snapshot(repository)


@pytest.mark.asyncio
async def test_vault_and_order_audit_scopes_and_failed_writes(repository, auth_secret):
    with TestClient(create_app([], repository=repository)) as client:
        owner = await register_system_admin_login(client, repository, temp_email("audit-owner"))
        other = await register_system_admin_login(client, repository, temp_email("audit-other"))
        headers = raw_auth_headers(owner["access_token"])
        other_headers = raw_auth_headers(other["access_token"])
        project = await seed_execution_project(repository, user_id=account_id_from_pair(owner))
        await seed_execution_project(repository, user_id=account_id_from_pair(other))
        system_before, projects_before = await audit_snapshot(repository)

        created = client.post(
            f"{BASE}/keys",
            headers=headers,
            json={"provider_type": "exa", "label": "audit-key", "secret": "fake-key"},
        )
        assert created.status_code == 201, created.text
        system_after_key, projects_after_key = await audit_snapshot(repository)
        assert [action for _, action in system_after_key - system_before] == ["vault.key_created"]
        assert projects_after_key == projects_before

        order = f"/api/v1/projects/{project.project_id}/routing/order/search"
        changed = client.put(order, headers=headers, json={"strategy": "free_first"})
        assert changed.status_code == 200, changed.text
        system_after_order, projects_after_order = await audit_snapshot(repository)
        assert system_after_order == system_after_key
        added = projects_after_order - projects_after_key
        assert [(project_id, action) for _, project_id, action in added] == [
            (str(project.project_id), "routing.order_changed")
        ]

        key_id = created.json()["id"]
        assert (
            client.patch(
                f"{BASE}/keys/{key_id}", headers=other_headers, json={"label": "denied"}
            ).status_code
            == 404
        )
        invalid = client.put(
            order, headers=headers, json={"strategy": "custom", "order": ["not-a-provider"]}
        )
        assert invalid.status_code in (409, 422)
        assert await audit_snapshot(repository) == (system_after_order, projects_after_order)


@pytest.mark.asyncio
async def test_unavailable_foreign_keys_have_identical_denials_and_no_writes(
    repository, auth_secret
):
    with TestClient(create_app([], repository=repository)) as client:
        owner = await register_system_admin_login(client, repository, temp_email("keys-owner"))
        other = await register_system_admin_login(client, repository, temp_email("keys-other"))
        headers = raw_auth_headers(owner["access_token"])
        other_headers = raw_auth_headers(other["access_token"])
        project = await seed_execution_project(repository, user_id=account_id_from_pair(owner))

        def create_key(label: str, provider: str = "exa", auth_mode: str = "api_key") -> str:
            body = {"provider_type": provider, "label": label, "auth_mode": auth_mode}
            if auth_mode == "api_key":
                body["secret"] = "fake-key"
            response = client.post(f"{BASE}/keys", headers=headers, json=body)
            assert response.status_code == 201, response.text
            return response.json()["id"]

        foreign = create_key("foreign")
        deleted = create_key("deleted")
        assert client.delete(f"{BASE}/keys/{deleted}", headers=headers).status_code == 200
        unassigned = create_key("unassigned")
        pool = client.post(
            f"{BASE}/keys/{unassigned}/pools",
            headers=headers,
            json={"label": "unassigned pool", "project_id": str(project.project_id)},
        )
        assert pool.status_code == 201, pool.text
        assert (
            client.post(f"{BASE}/pools/{pool.json()['id']}/unassign", headers=headers).status_code
            == 200
        )
        disconnected = create_key("disconnected", "parallel", "oauth")
        assert (
            client.delete(f"{BASE}/keys/{disconnected}/oauth", headers=headers).status_code == 204
        )
        owner_list = client.get(f"{BASE}/keys", headers=headers)
        assert owner_list.status_code == 200
        assert disconnected in {key["id"] for key in owner_list.json()}

        before = await durable_snapshot(repository)
        ids = [foreign, str(uuid4()), deleted, unassigned, disconnected]
        for method, suffix, body in [
            ("GET", "/pools", None),
            ("PATCH", "", {"label": "denied"}),
            ("POST", "/rotate", {"expected_generation": 1, "secret": "fake-new-key"}),
            ("DELETE", "", None),
        ]:
            responses = [
                client.request(
                    method, f"{BASE}/keys/{key_id}{suffix}", headers=other_headers, json=body
                )
                for key_id in ids
            ]
            assert all(response.status_code == 404 for response in responses)
            assert all(response.content == responses[0].content for response in responses)
        assert await durable_snapshot(repository) == before
