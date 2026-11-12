"""Vault key transport against a fresh SQLite database."""

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from uuid import UUID

import httpx
import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from sqlalchemy import select

from polyweb.configuration.config import get_settings
from polyweb.persistence.audit import SystemAuditEventRow
from polyweb.persistence.credentials import ProviderCredentialRow
from polyweb.persistence.key_pools import KeyPoolRepository, KeyPoolValues
from polyweb.persistence.oauth_grants import CredentialOAuthGrantRow, oauth_secret_slot
from polyweb.persistence.storage import RuntimeSettingRow, SQLiteRepository
from polyweb.routers import vault_keys
from polyweb.routers.api import create_app
from polyweb.services.credentials import credential_secret_slot
from tests.fixtures.auth import (
    account_id_from_pair,
    bare_login,
    raw_auth_headers,
    register_and_login,
    register_system_admin_login,
    temp_email,
)
from tests.fixtures.execution import seed_execution_project
from tests.integration.services.oauth.oauth_stubs import StubOAuthServer, stub_client

BASE = "/api/v1/account/vault/keys"
_DEFAULT_KEYLESS = {"keenable", "tavily"}


def _listed_key(client: TestClient, headers: dict[str, str], key_id: str) -> dict:
    """Return the one listed key with this exact id."""

    matches = [item for item in client.get(BASE, headers=headers).json() if item["id"] == key_id]
    assert len(matches) == 1
    return matches[0]


def _default_keys(client: TestClient, headers: dict[str, str]) -> dict[str, dict]:
    """Return the owner's signup-created keyless keys by id (exactly the two defaults)."""

    listed = client.get(BASE, headers=headers)
    assert listed.status_code == 200, listed.text
    keys = {item["id"]: item for item in listed.json()}
    assert len(keys) == len(listed.json()) == len(_DEFAULT_KEYLESS)
    assert {item["provider_type"] for item in keys.values()} == _DEFAULT_KEYLESS
    assert all(item["auth_mode"] == "keyless" for item in keys.values())
    assert all(item["pool_count"] == 1 for item in keys.values())
    return keys


@pytest_asyncio.fixture
async def repository(tmp_path):
    repo = await SQLiteRepository.open(tmp_path / "vault-api.db")
    try:
        yield repo
    finally:
        await repo.close()


@pytest.fixture
def vault_env(monkeypatch, tmp_path):
    monkeypatch.setenv("POLYWEB_ENCRYPTION_KEY", "vault-integration-test-key")
    monkeypatch.setenv("POLYWEB_ENCRYPTION_KEY_FILE", str(tmp_path / "vault-key"))
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_key_capacity_round_trip_and_clear(repository, vault_env, auth_secret):
    with TestClient(create_app([], repository=repository)) as client:
        owner = await register_system_admin_login(client, repository, temp_email("capacity"))
        other = await register_system_admin_login(client, repository, temp_email("capacity-other"))
        headers = raw_auth_headers(owner["access_token"])
        capacity = {"limit": 13, "window_seconds": 37}
        created = client.post(
            BASE,
            headers=headers,
            json={
                "provider_type": "tavily",
                "label": "capacity",
                "secret": "key",
                "capacity": capacity,
            },
        )
        assert created.status_code == 201, created.text
        key_id = created.json()["id"]
        assert created.json()["capacity"] == capacity
        assert _listed_key(client, headers, key_id)["capacity"] == capacity
        async with repository.session() as session:
            row = await session.get(ProviderCredentialRow, key_id)
            assert row is not None
            row.capacity_budget_micros = 123
            row.capacity_budget_window = "week"
            await session.commit()
        denied = client.patch(
            f"{BASE}/{key_id}",
            headers=raw_auth_headers(other["access_token"]),
            json={"capacity": {"limit": 0, "window_seconds": 7}},
        )
        assert denied.status_code == 404
        zero = {"limit": 0, "window_seconds": 7}
        updated = client.patch(f"{BASE}/{key_id}", headers=headers, json={"capacity": zero})
        assert updated.status_code == 200, updated.text
        assert updated.json()["capacity"] == zero
        renamed = client.patch(f"{BASE}/{key_id}", headers=headers, json={"label": "new"})
        assert renamed.json()["capacity"] == zero
        unknown = {"limit": None, "window_seconds": 19}
        response = client.patch(f"{BASE}/{key_id}", headers=headers, json={"capacity": unknown})
        assert response.json()["capacity"] == unknown
        cleared = client.patch(f"{BASE}/{key_id}", headers=headers, json={"capacity": None})
        assert cleared.status_code == 200, cleared.text
        assert cleared.json()["capacity"] is None
        assert _listed_key(client, headers, key_id)["capacity"] is None
        async with repository.session() as session:
            row = await session.get(ProviderCredentialRow, key_id)
            assert row is not None
            assert (row.capacity_budget_micros, row.capacity_budget_window) == (123, "week")


@pytest.mark.asyncio
async def test_vault_key_lifecycle_and_ownership(repository, vault_env, auth_secret):
    with TestClient(create_app([], repository=repository)) as client:
        owner = await register_system_admin_login(client, repository, temp_email("owner"))
        other = await register_system_admin_login(client, repository, temp_email("other"))
        # A bare account owns no project, so vault use is denied (403). A normal
        # signup owns a Default project and may use the vault, but only its own keys.
        developer = await bare_login(client, repository, temp_email("developer"))
        signup_admin = register_and_login(client, temp_email("signup-admin"))
        headers = raw_auth_headers(owner["access_token"])
        other_headers = raw_auth_headers(other["access_token"])
        denied_headers = raw_auth_headers(developer["access_token"])
        signup_headers = raw_auth_headers(signup_admin["access_token"])
        assert client.get(BASE, headers=denied_headers).status_code == 403
        signup_defaults = _default_keys(client, signup_headers)
        defaults = _default_keys(client, headers)
        assert set(defaults).isdisjoint(signup_defaults)
        assert set(defaults).isdisjoint(_default_keys(client, other_headers))
        created = client.post(
            BASE,
            headers=headers,
            json={"provider_type": "tavily", "label": "primary", "secret": "first-secret"},
        )
        assert created.status_code == 201, created.text
        key = created.json()
        key_id = UUID(key["id"])
        assert "first-secret" not in created.text
        listed = client.get(BASE, headers=headers)
        assert listed.status_code == 200
        # Exactly the two owned default keys plus the key created here, by identity.
        assert {item["id"]: item for item in listed.json()} == {**defaults, key["id"]: key}
        assert len(listed.json()) == len(defaults) + 1
        assert "first-secret" not in listed.text
        # A foreign vault user (including one who owns only keyless defaults) sees 404.
        for foreign in (other_headers, signup_headers):
            assert client.patch(f"{BASE}/{key_id}", headers=foreign, json={}).status_code == 404
            assert client.delete(f"{BASE}/{key_id}", headers=foreign).status_code == 404
        assert _default_keys(client, signup_headers) == signup_defaults
        project = await seed_execution_project(repository, user_id=account_id_from_pair(owner))
        async with repository.session() as session:
            pool = await KeyPoolRepository(session).create(
                credential_id=key_id,
                project_id=project.project_id,
                provider_type="tavily",
                created_by=account_id_from_pair(owner),
                values=KeyPoolValues(label="pool", operations=frozenset({"search"})),
            )
            await session.commit()
        rotated = client.post(
            f"{BASE}/{key_id}/rotate",
            headers=headers,
            json={"expected_generation": 1, "secret": "second-secret"},
        )
        assert rotated.status_code == 200, rotated.text
        assert rotated.json()["generation"] == 2
        assert rotated.json()["pool_count"] == 1
        assert rotated.json()["rotated_at"] is not None
        assert "second-secret" not in rotated.text
        assert await client.app.state.secret_store.get(credential_secret_slot(key_id, 1)) is None
        assert (
            await client.app.state.secret_store.get(credential_secret_slot(key_id, 2))
            == "second-secret"
        )
        async with repository.session() as session:
            from polyweb.persistence.bindings import ProjectBindingRepository
            from polyweb.persistence.pools import PoolAllocationRepository

            bindings = await ProjectBindingRepository(session).list_for_project(
                project_id=project.project_id
            )
            assert any(binding.credential_id == key_id for binding in bindings)
            allocations = await PoolAllocationRepository(session).list_for_project(
                project_id=project.project_id
            )
            assert any(allocation.key_pool_id == pool.id for allocation in allocations)
        stale = client.post(
            f"{BASE}/{key_id}/rotate",
            headers=headers,
            json={"expected_generation": 1, "secret": "stale-secret"},
        )
        assert stale.status_code == 409
        assert "stale-secret" not in stale.text
        envelope = await repository.get_runtime_setting(
            "secret.enc:" + credential_secret_slot(key_id, 2)
        )
        assert envelope and "second-secret" not in envelope
        updated = client.patch(
            f"{BASE}/{key_id}",
            headers=headers,
            json={"label": "renamed", "overcommit": False, "contention_mode": "ratio"},
        )
        assert updated.status_code == 200, updated.text
        assert updated.json()["overcommit"] is False
        assert updated.json()["contention_mode"] == "ratio"
        assert updated.json()["label"] == "renamed"
        deleted = client.delete(f"{BASE}/{key_id}", headers=headers)
        assert deleted.status_code == 200, deleted.text
        assert deleted.json() == {
            "deleted_pools": [{"id": str(pool.id), "project_id": str(project.project_id)}]
        }
        # Only the created key went away; the owner's default keyless keys persist.
        assert _default_keys(client, headers) == defaults
        async with repository.session() as session:
            assert await KeyPoolRepository(session).get(pool.id) is None
            audit = (
                await session.execute(
                    select(SystemAuditEventRow).where(SystemAuditEventRow.target_id == str(key_id))
                )
            ).scalars()
            events = list(audit)
            assert {event.action for event in events} == {
                "vault.key_created",
                "vault.key_rotated",
                "vault.key_updated",
                "vault.key_deleted",
            }
            assert all("secret" not in event.detail for event in events)


@pytest.mark.asyncio
async def test_invalid_secret_never_appears_in_validation_response(
    repository, vault_env, auth_secret
):
    with TestClient(create_app([], repository=repository)) as client:
        owner = await register_system_admin_login(client, repository, temp_email("invalid"))
        headers = raw_auth_headers(owner["access_token"])
        response = client.post(
            BASE,
            headers=headers,
            json={"provider_type": "tavily", "label": "", "secret": "secret-sentinel"},
        )
        assert response.status_code == 422
        assert "secret-sentinel" not in response.text


@pytest.mark.asyncio
async def test_project_admin_oauth_flow_and_foreign_access(repository, vault_env, auth_secret):
    server = StubOAuthServer(poll_script=["success"])
    async with stub_client(server) as http:
        app = create_app([], repository=repository)
        app.state.credential_oauth_http_client = http
        with TestClient(app) as client:
            project_admin = register_and_login(client, temp_email("project-admin"))
            other = await register_system_admin_login(client, repository, temp_email("oauth-other"))
            owner_id = account_id_from_pair(project_admin)
            await seed_execution_project(repository, user_id=owner_id)
            headers = raw_auth_headers(project_admin["access_token"])
            other_headers = raw_auth_headers(other["access_token"])
            created = client.post(
                BASE,
                headers=headers,
                json={"provider_type": "parallel", "label": "oauth", "auth_mode": "oauth"},
            )
            assert created.status_code == 201, created.text
            key_path = f"{BASE}/{created.json()['id']}/oauth"
            assert client.get(key_path, headers=other_headers).status_code == 404
            assert client.post(f"{key_path}/device", headers=other_headers).status_code == 404
            start = client.post(f"{key_path}/device", headers=headers)
            assert start.status_code == 200, start.text
            assert set(start.json()) == {"user_code", "verification_uri", "interval", "expires_in"}
            connected = client.post(f"{key_path}/poll", headers=headers)
            assert connected.status_code == 200, connected.text
            assert connected.json()["status"] == "connected"
            assert client.get(key_path, headers=headers).json()["status"] == "connected"
            assert client.delete(key_path, headers=headers).status_code == 204
            assert client.get(key_path, headers=headers).json()["status"] == "disconnected"


@pytest.mark.asyncio
@pytest.mark.parametrize("delete_key", [False, True])
async def test_oauth_revoke_precedes_deletion_and_failure_preserves_state(
    repository, vault_env, auth_secret, delete_key
):
    server = StubOAuthServer(poll_script=["success"])
    app = create_app([], repository=repository)
    observations = []
    slots = []
    key_id = None

    async def handle(request):
        if request.url.path.lower().endswith("/token/revoke"):
            async with repository.session() as session:
                grant = await session.get(CredentialOAuthGrantRow, key_id)
                slot = oauth_secret_slot(UUID(key_id), "refresh", grant.token_generation)
                slots.append(slot)
                token_present = await app.state.secret_store.get_in_session(session, slot)
                observations.append((grant.status, token_present is not None))
            if len(observations) == 1:
                return httpx.Response(503, request=request)
        return server.handle(request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
        app.state.credential_oauth_http_client = http
        with TestClient(app) as client:
            owner = await register_system_admin_login(client, repository, temp_email("revoke"))
            headers = raw_auth_headers(owner["access_token"])
            created = client.post(
                BASE,
                headers=headers,
                json={"provider_type": "parallel", "label": "oauth", "auth_mode": "oauth"},
            )
            assert created.status_code == 201, created.text
            key_id = created.json()["id"]
            key_path = f"{BASE}/{key_id}"
            oauth_path = f"{key_path}/oauth"
            assert client.post(f"{oauth_path}/device", headers=headers).status_code == 200
            connected = client.post(f"{oauth_path}/poll", headers=headers)
            assert connected.json()["status"] == "connected"
            delete_path = key_path if delete_key else oauth_path
            failed = client.delete(delete_path, headers=headers)
            assert failed.status_code == 502, failed.text
            assert client.get(oauth_path, headers=headers).json()["status"] == "connected"
            assert await app.state.secret_store.get(slots[0]) is not None
            completed = client.delete(delete_path, headers=headers)
            assert completed.status_code == (200 if delete_key else 204), completed.text
            assert observations == [("connected", True), ("connected", True)]
            assert await app.state.secret_store.get(slots[0]) is None
            if delete_key:
                assert client.get(oauth_path, headers=headers).status_code == 404
            else:
                assert client.get(oauth_path, headers=headers).json()["status"] == "disconnected"
                assert client.delete(oauth_path, headers=headers).status_code == 204
                assert len(observations) == 2


@pytest.mark.asyncio
async def test_vault_oauth_poll_interval_and_slow_down_survive_requests(
    repository, vault_env, auth_secret, monkeypatch
):
    server = StubOAuthServer(
        poll_script=["authorization_pending", "slow_down", "authorization_pending", "success"]
    )
    clock = [datetime.now(UTC)]
    original_oauth = vault_keys._oauth

    def oauth_with_clock(request, actor):
        service = original_oauth(request, actor)
        service._clock = lambda: clock[0]
        return service

    monkeypatch.setattr(vault_keys, "_oauth", oauth_with_clock)
    async with stub_client(server) as http:
        app = create_app([], repository=repository)
        app.state.credential_oauth_http_client = http
        with TestClient(app) as client:
            owner = await register_system_admin_login(client, repository, temp_email("poll-timing"))
            headers = raw_auth_headers(owner["access_token"])
            created = client.post(
                BASE,
                headers=headers,
                json={"provider_type": "parallel", "label": "oauth", "auth_mode": "oauth"},
            )
            assert created.status_code == 201, created.text
            path = f"{BASE}/{created.json()['id']}/oauth"
            assert client.post(f"{path}/device", headers=headers).json()["interval"] == 5
            with ThreadPoolExecutor(max_workers=4) as pool:
                responses = list(
                    pool.map(lambda _: client.post(f"{path}/poll", headers=headers), range(4))
                )
            assert all(response.json()["interval"] == 5 for response in responses)
            assert server.poll_calls == 1
            async with repository.session() as session:
                timing = (
                    (
                        await session.execute(
                            select(RuntimeSettingRow).where(
                                RuntimeSettingRow.key.like("oauth.poll:%")
                            )
                        )
                    )
                    .scalars()
                    .one()
                )
                assert json.loads(timing.value_json) == {
                    "last_poll_at": clock[0].isoformat(),
                    "interval": 5,
                }
            clock[0] += timedelta(seconds=2)
            early = client.post(f"{path}/poll", headers=headers).json()
            assert early["status"] == "pending" and early["interval"] == 3
            assert server.poll_calls == 1
            clock[0] += timedelta(seconds=3)
            slowed = client.post(f"{path}/poll", headers=headers).json()
            assert slowed["status"] == "pending" and slowed["interval"] == 10
            clock[0] += timedelta(seconds=5)
            early = client.post(f"{path}/poll", headers=headers).json()
            assert early["status"] == "pending" and early["interval"] == 5
            assert server.poll_calls == 2
            clock[0] += timedelta(seconds=5)
            assert client.post(f"{path}/poll", headers=headers).json()["interval"] == 10
            assert server.poll_calls == 3
            clock[0] += timedelta(seconds=10)
            assert client.post(f"{path}/poll", headers=headers).json()["status"] == "connected"
            assert server.poll_calls == 4
            async with repository.session() as session:
                rows = await session.execute(
                    select(RuntimeSettingRow).where(RuntimeSettingRow.key.like("oauth.poll:%"))
                )
                assert rows.scalars().all() == []
            assert client.delete(path, headers=headers).status_code == 204
            server.device_expires_in = 3
            server.poll_script = ["authorization_pending"]
            assert client.post(f"{path}/device", headers=headers).status_code == 200
            assert client.post(f"{path}/poll", headers=headers).json()["status"] == "pending"
            assert server.poll_calls == 5
            clock[0] += timedelta(seconds=3)
            expired = client.post(f"{path}/poll", headers=headers).json()
            assert expired["status"] == "disconnected"
            assert expired["last_error_code"] == "expired_token"
            assert server.poll_calls == 5
            async with repository.session() as session:
                rows = await session.execute(
                    select(RuntimeSettingRow).where(RuntimeSettingRow.key.like("oauth.poll:%"))
                )
                assert rows.scalars().all() == []
