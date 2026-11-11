"""Quota polling keeps vault identities private to their owners."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete

from polyweb.configuration.config import get_settings
from polyweb.models.contracts import UnitKind
from polyweb.models.provider_limits import (
    AuthMode,
    NativeUsageSnapshot,
    UsageSyncRequest,
    native_pool_id,
)
from polyweb.persistence.projects import SystemRoleAssignmentRow
from polyweb.persistence.storage import SQLiteRepository
from polyweb.routers.api import create_app
from tests.fixtures.auth import (
    account_id_from_pair,
    bare_login,
    raw_auth_headers,
    register_and_login,
    register_system_admin_login,
    temp_email,
)
from tests.fixtures.execution import add_execution_member, seed_execution_project
from tests.integration.services.oauth.oauth_stubs import (
    ACCESS_TOKEN_VALUE,
    TOKEN_SENTINELS,
    StubOAuthServer,
    stub_client,
)


@pytest.mark.asyncio
async def test_key_reads_and_refresh_are_owner_scoped(tmp_path, monkeypatch, auth_secret) -> None:
    import polyweb.routers.limits as limits_router
    import polyweb.services.execution as execution_module

    monkeypatch.setenv("POLYWEB_ENCRYPTION_KEY", "quota-vault-test-encryption-key")
    monkeypatch.setenv("POLYWEB_ENCRYPTION_KEY_FILE", str(tmp_path / "encryption-key"))
    get_settings.cache_clear()
    calls = []

    class UsageAdapter:
        name = "firecrawl"
        limit_auth_mode = AuthMode.KEYED

        def __init__(self, secret):
            self.secret = secret

        async def usage_snapshot(self, request: UsageSyncRequest) -> NativeUsageSnapshot:
            calls.append(self.secret)
            return NativeUsageSnapshot(
                pool_id=native_pool_id("firecrawl", AuthMode.KEYED, UnitKind.CREDIT),
                provider="firecrawl",
                auth_mode=AuthMode.KEYED,
                native_unit=UnitKind.CREDIT,
                observed_at=request.observed_at,
                remaining=Decimal("640"),
                allowance=Decimal("1000"),
                credential_generation=request.credential_generation,
            )

        async def aclose(self) -> None:
            pass

    def factory(client, api_key=None):
        assert api_key is not None
        return UsageAdapter(api_key.get_secret_value())

    monkeypatch.setattr(
        execution_module, "adapter_factory", lambda name: factory if name == "firecrawl" else None
    )
    repository = await SQLiteRepository.open(tmp_path / "quota.db")
    try:
        with TestClient(create_app([], repository=repository)) as client:
            email = temp_email("quota-owner")
            owner = await register_system_admin_login(client, repository, email)
            project = await seed_execution_project(repository, user_id=account_id_from_pair(owner))
            admin = await register_system_admin_login(client, repository, temp_email("quota-admin"))
            await add_execution_member(
                repository,
                project_id=project.project_id,
                user_id=account_id_from_pair(admin),
                granted_by=account_id_from_pair(owner),
            )
            # The member has no project of its own and so no vault authority; a
            # public signup would now own a Default project and hold vault use.
            member = await bare_login(client, repository, temp_email("quota-member"))
            owner_headers = raw_auth_headers(owner["access_token"])
            admin_headers = raw_auth_headers(admin["access_token"])
            member_headers = raw_auth_headers(member["access_token"])
            secret = "sensitive-firecrawl-usage-key"
            created = client.post(
                "/api/v1/account/vault/keys",
                headers=owner_headers,
                json={"provider_type": "firecrawl", "label": "Owner key", "secret": secret},
            )
            assert created.status_code == 201, created.text
            key_id = created.json()["id"]
            second_secret = "another-sensitive-firecrawl-usage-key"
            second = client.post(
                "/api/v1/account/vault/keys",
                headers=admin_headers,
                json={"provider_type": "firecrawl", "label": "Admin key", "secret": second_secret},
            )
            assert second.status_code == 201, second.text
            assert (
                client.patch(
                    f"/api/v1/account/vault/keys/{key_id}", headers=admin_headers, json={}
                ).status_code
                == 404
            )
            sync_url = f"/api/v1/providers/firecrawl/limits/keys/{key_id}/sync"

            denied = client.post(sync_url, headers=member_headers)
            assert denied.status_code in (403, 404)
            assert (
                client.post("/api/v1/providers/firecrawl/limits/sync", headers=member_headers)
            ).status_code == 403
            assert calls == []
            sync = client.post("/api/v1/providers/firecrawl/limits/sync", headers=admin_headers)
            assert sync.status_code == 200, sync.text
            assert sync.json()["status"] == "synced", sync.text
            assert calls == [secret, second_secret]

            view = client.get("/api/v1/providers/firecrawl/limits", headers=admin_headers)
            keys = client.get("/api/v1/providers/firecrawl/limits/keys", headers=admin_headers)
            assert view.status_code == 200
            assert keys.status_code == 200, keys.text
            assert len(keys.json()) == 1
            assert keys.json()[0]["key_id"] == second.json()["id"]
            assert keys.json()[0]["label"] == "Admin key"
            assert "owner_email" not in keys.json()[0]
            assert (
                key_id not in keys.text and "Owner key" not in keys.text and email not in keys.text
            )
            assert keys.json()[0]["auth_mode"] == "api_key"
            assert keys.json()[0]["oauth_connected"] is None
            assert Decimal(keys.json()[0]["balance"]["remaining"]) == 640
            keyed = next(item for item in view.json()["auths"] if item["auth_mode"] == "keyed")
            assert Decimal(keyed["aggregate_pool"]["remaining"]) == 1280
            assert "crd" not in (view.text + keys.text).lower()
            assert all(value not in sync.text + view.text + keys.text for value in calls)
            assert (
                client.get(
                    "/api/v1/providers/firecrawl/limits/keys", headers=member_headers
                ).status_code
                == 403
            )
            now = datetime.now(UTC)

            class FutureDatetime(datetime):
                @classmethod
                def now(cls, tz=None):
                    return now

            monkeypatch.setattr(limits_router, "datetime", FutureDatetime)
            assert client.post(sync_url, headers=admin_headers).status_code == 404
            now += timedelta(minutes=2)
            response = client.post(sync_url, headers=owner_headers)
            assert response.status_code == 200, response.text
            assert secret not in response.text
            assert response.json()["status"] == "synced", response.text
            assert calls == [secret, second_secret, secret]

            pool = client.post(
                f"/api/v1/account/vault/keys/{key_id}/pools",
                headers=owner_headers,
                json={"label": "Assigned"},
            )
            assert pool.status_code == 201, pool.text
            assigned = client.post(
                f"/api/v1/account/vault/pools/{pool.json()['id']}/assign",
                headers=owner_headers,
                json={"project_id": str(project.project_id)},
            )
            assert assigned.status_code == 200, assigned.text
            now += timedelta(minutes=2)
            assert client.post(sync_url, headers=owner_headers).status_code == 200
            view = client.get("/api/v1/providers/firecrawl/limits", headers=admin_headers)
            keyed = next(item for item in view.json()["auths"] if item["auth_mode"] == "keyed")
            assert Decimal(keyed["aggregate_pool"]["remaining"]) == 1280
            rotated = client.post(
                f"/api/v1/account/vault/keys/{key_id}/rotate",
                headers=owner_headers,
                json={"expected_generation": 1, "secret": "replacement-secret"},
            )
            assert rotated.status_code == 200, rotated.text
            view = client.get("/api/v1/providers/firecrawl/limits", headers=admin_headers)
            keyed = next(item for item in view.json()["auths"] if item["auth_mode"] == "keyed")
            assert Decimal(keyed["aggregate_pool"]["remaining"]) == 640
            assert (
                client.delete(
                    f"/api/v1/account/vault/keys/{key_id}", headers=owner_headers
                ).status_code
                == 200
            )
            view = client.get("/api/v1/providers/firecrawl/limits", headers=admin_headers)
            keyed = next(item for item in view.json()["auths"] if item["auth_mode"] == "keyed")
            assert Decimal(keyed["aggregate_pool"]["remaining"]) == 640

            async with repository.session() as session:
                await session.execute(
                    delete(SystemRoleAssignmentRow).where(
                        SystemRoleAssignmentRow.user_id == str(account_id_from_pair(admin))
                    )
                )
                await session.commit()
            own_sync = f"/api/v1/providers/firecrawl/limits/keys/{second.json()['id']}/sync"
            assert client.post(own_sync, headers=admin_headers).status_code == 403
            assert (
                client.get(
                    "/api/v1/providers/firecrawl/limits/keys", headers=admin_headers
                ).status_code
                == 403
            )
            assert calls == [secret, second_secret, secret, secret]
    finally:
        await repository.close()
        get_settings.cache_clear()


@pytest.mark.asyncio
async def test_parallel_oauth_state_is_only_visible_to_owner(
    tmp_path, monkeypatch, auth_secret
) -> None:
    monkeypatch.setenv("POLYWEB_ENCRYPTION_KEY", "quota-oauth-test-encryption-key")
    monkeypatch.setenv("POLYWEB_ENCRYPTION_KEY_FILE", str(tmp_path / "encryption-key"))
    get_settings.cache_clear()
    repository = await SQLiteRepository.open(tmp_path / "oauth-quota.db")
    server = StubOAuthServer(poll_script=["success"])
    try:
        async with stub_client(server) as http:
            app = create_app([], repository=repository)
            app.state.credential_oauth_http_client = http
            with TestClient(app) as client:
                app.state.execution._client = http
                email = temp_email("oauth-owner")
                owner = register_and_login(client, email)
                await seed_execution_project(repository, user_id=account_id_from_pair(owner))
                admin = await register_system_admin_login(client, repository, temp_email("admin"))
                owner_headers = raw_auth_headers(owner["access_token"])
                admin_headers = raw_auth_headers(admin["access_token"])
                created = client.post(
                    "/api/v1/account/vault/keys",
                    headers=owner_headers,
                    json={"provider_type": "parallel", "label": "OAuth", "auth_mode": "oauth"},
                )
                assert created.status_code == 201, created.text
                oauth = f"/api/v1/account/vault/keys/{created.json()['id']}/oauth"
                url = "/api/v1/providers/parallel/limits/keys"
                keys = client.get(url, headers=admin_headers)
                assert keys.json() == []
                keys = client.get(url, headers=owner_headers)
                assert keys.json()[0]["auth_mode"] == "oauth"
                assert keys.json()[0]["oauth_connected"] is False
                assert client.post(f"{oauth}/device", headers=owner_headers).status_code == 200
                keys = client.get(url, headers=owner_headers)
                assert keys.json()[0]["oauth_connected"] is False
                assert client.post(f"{oauth}/poll", headers=owner_headers).status_code == 200
                sync = client.post("/api/v1/providers/parallel/limits/sync", headers=admin_headers)
                assert sync.status_code == 200, sync.text
                assert sync.json()["status"] == "synced", sync.text
                assert server.balance_calls == 1
                assert server.seen_requests[-1]["auth"] == f"Bearer {ACCESS_TOKEN_VALUE}"
                keys = client.get("/api/v1/providers/parallel/limits/keys", headers=owner_headers)
                assert keys.status_code == 200, keys.text
                assert "owner_email" not in keys.json()[0]
                assert keys.json()[0]["auth_mode"] == "oauth"
                assert keys.json()[0]["oauth_connected"] is True
                assert Decimal(keys.json()[0]["balance"]["remaining"]) == 10
                assert all(token not in sync.text + keys.text for token in TOKEN_SENTINELS)
                assert client.get(url, headers=admin_headers).json() == []
                assert (
                    client.post(
                        f"{url}/{created.json()['id']}/sync", headers=admin_headers
                    ).status_code
                    == 404
                )
                assert client.delete(oauth, headers=owner_headers).status_code == 204
                assert client.get(url, headers=admin_headers).json() == []
                keys = client.get(url, headers=owner_headers)
                assert keys.json()[0]["oauth_connected"] is False
                assert all(token not in keys.text for token in TOKEN_SENTINELS)
    finally:
        await repository.close()
        get_settings.cache_clear()
