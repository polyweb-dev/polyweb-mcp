"""Required keyless pools: assigned pools only, actionable missing-pool errors."""

from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from polyweb.configuration.config import get_settings
from polyweb.configuration.provider_config import ProviderConfigUpdate
from polyweb.infrastructure.encrypted_store import EncryptedDbSecretStore, load_secret_codec
from polyweb.infrastructure.secrets import ProviderName
from polyweb.models.execution_failures import ExecutionBindingMissing
from polyweb.models.projects import (
    DEFAULT_INSTALLATION_ACCOUNT_ID,
    CredentialOwnerScope,
    HumanPrincipal,
    PermissionAction,
    ProjectContext,
)
from polyweb.models.provider_limits import AuthMode
from polyweb.persistence.bindings import ProjectBindingRepository
from polyweb.persistence.credentials import CredentialRepository
from polyweb.persistence.key_pools import KeyPoolRepository, KeyPoolValues
from polyweb.persistence.storage import SQLiteRepository
from polyweb.routers.api import create_app
from polyweb.services.pool_materializer import (
    ensure_keyless_credentials,
    materialize_pools,
)
from polyweb.services.provider_runtime import initialize_provider_configs, patch_provider_config
from tests.fixtures.a2_execution import RecordingAdapter, build_execution_world, search_request
from tests.fixtures.auth import (
    account_id_from_pair,
    raw_auth_headers,
    register_system_admin_login,
    temp_email,
)
from tests.fixtures.execution import seed_execution_project
from tests.fixtures.project_order import seed_order_pools


@pytest.mark.asyncio
async def test_public_dispatch_pool_switch_kill_switch_and_vault(
    tmp_path: Path, auth_secret: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("POLYWEB_ENCRYPTION_KEY", "keyless-integration-passphrase")
    get_settings.cache_clear()
    repository = await SQLiteRepository.open(tmp_path / "keyless.db")
    store = EncryptedDbSecretStore(repository, load_secret_codec(get_settings()))
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"results": []})

    upstream = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    app = create_app([], repository=repository, secret_store=store)
    try:
        with TestClient(app) as client:
            app.state.execution._client = upstream
            pair = await register_system_admin_login(client, repository, temp_email("keyless"))
            headers = raw_auth_headers(pair["access_token"])
            project = await seed_execution_project(repository, user_id=account_id_from_pair(pair))
            async with repository.session() as session:
                await ensure_keyless_credentials(session)
                await ensure_keyless_credentials(session)
                await materialize_pools(session, project_id=project.project_id)
                await materialize_pools(session, project_id=project.project_id)
                rows = (
                    await session.execute(
                        text(
                            "SELECT provider_type,owner_scope,owner_user_id,created_by FROM "
                            "provider_credentials WHERE auth_mode='keyless' ORDER BY provider_type"
                        )
                    )
                ).all()
                assert rows == [
                    ("keenable", "system", None, None),
                    ("tavily", "system", None, None),
                ]
                bindings = await ProjectBindingRepository(session).list_for_project(
                    project_id=project.project_id
                )
                assert bindings == []
                await session.commit()
            await initialize_provider_configs(repository)
            await initialize_provider_configs(repository)
            async with repository.session() as session:
                bindings = await ProjectBindingRepository(session).list_for_project(
                    project_id=project.project_id
                )
                assert bindings == []
            path = f"/api/v1/projects/{project.project_id}"
            order = client.get(f"{path}/routing/order", headers=headers).json()
            assert "keenable" not in [p["provider"] for p in order["search"]["providers"]]
            vault = client.get("/api/v1/account/vault/keys", headers=headers)
            assert vault.status_code == 200 and vault.json() == []
            request = {
                "project_id": str(project.project_id),
                "query": "keyless",
                "routing": {"mode": "require", "providers": ["keenable"]},
            }
            calls_before = len(seen)
            response = client.post("/search", headers=headers, json=request)
            assert response.status_code == 503, response.text
            assert "no required provider is configured" in response.json()["detail"]
            assert "keenable" in response.json()["detail"]
            assert "pool" in response.json()["detail"]
            assert "timeout" not in response.json()["detail"].lower()
            assert len(seen) == calls_before

            await patch_provider_config(
                repository, ProviderName.KEENABLE, ProviderConfigUpdate(enabled=False)
            )
            disabled = client.get(f"{path}/routing/order", headers=headers).json()
            assert "keenable" not in [p["provider"] for p in disabled["search"]["providers"]]
            assert client.post("/search", headers=headers, json=request).status_code == 503
            await patch_provider_config(
                repository, ProviderName.KEENABLE, ProviderConfigUpdate(enabled=True)
            )

            await seed_order_pools(
                repository,
                project_id=project.project_id,
                actor_id=project.actor_id,
                store=store,
                providers=("keenable",),
            )
            async with repository.session() as session:
                await session.commit()
            order = client.get(f"{path}/routing/order", headers=headers).json()
            assert not next(p for p in order["search"]["providers"] if p["provider"] == "keenable")[
                "keyless"
            ]
            response = client.post("/search", headers=headers, json=request)
            assert response.status_code == 200, response.text
            assert not seen[-1].url.path.endswith("/search/public")
            assert "x-api-key" in seen[-1].headers
            async with repository.session() as session:
                pool = next(
                    p
                    for p in await KeyPoolRepository(session).list_for_project(project.project_id)
                    if p.provider_type == "keenable"
                )
                await KeyPoolRepository(session).unassign(pool.id)
                await materialize_pools(session, project_id=project.project_id)
                await session.commit()
            calls_before = len(seen)
            order = client.get(f"{path}/routing/order", headers=headers).json()
            assert "keenable" not in [p["provider"] for p in order["search"]["providers"]]
            response = client.post("/search", headers=headers, json=request)
            assert response.status_code == 503, response.text
            assert "pool" in response.json()["detail"]
            assert "timeout" not in response.json()["detail"].lower()
            assert len(seen) == calls_before
    finally:
        await upstream.aclose()
        await repository.close()


@pytest.mark.asyncio
async def test_cloud_tavily_pool_does_not_enable_keenable(
    tmp_path: Path, auth_secret: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A Tavily-only assignment leaves Keenable unavailable with zero calls."""

    monkeypatch.setenv("POLYWEB_ENCRYPTION_KEY", "keyless-integration-passphrase")
    get_settings.cache_clear()
    repository = await SQLiteRepository.open(tmp_path / "keyless-tavily.db")
    store = EncryptedDbSecretStore(repository, load_secret_codec(get_settings()))
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"results": []})

    upstream = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    app = create_app([], repository=repository, secret_store=store)
    try:
        with TestClient(app) as client:
            app.state.execution._client = upstream
            pair = await register_system_admin_login(client, repository, temp_email("tavily"))
            headers = raw_auth_headers(pair["access_token"])
            project = await seed_execution_project(repository, user_id=account_id_from_pair(pair))
            await seed_order_pools(
                repository,
                project_id=project.project_id,
                actor_id=project.actor_id,
                store=store,
                providers=("tavily",),
            )
            calls_before = len(seen)
            keenable_request = {
                "project_id": str(project.project_id),
                "query": "keyless",
                "routing": {"mode": "require", "providers": ["keenable"]},
            }
            response = client.post("/search", headers=headers, json=keenable_request)
            assert response.status_code == 503, response.text
            assert "keenable" in response.json()["detail"]
            assert "pool" in response.json()["detail"]
            assert "tavily" not in response.json()["detail"]
            assert len(seen) == calls_before
    finally:
        await upstream.aclose()
        await repository.close()


@pytest.mark.asyncio
async def test_cloud_assigned_owned_keyless_pool_succeeds_unassign_disables(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An assigned owned keyless pool dispatches; unassignment fails closed."""

    world = await build_execution_world(tmp_path, monkeypatch, limits=False)
    try:
        adapter = RecordingAdapter("keenable", auth_mode=AuthMode.KEYLESS)
        monkeypatch.setattr(
            "polyweb.services.execution.adapter_factory",
            lambda name: (lambda client, api_key=None: adapter) if name == "keenable" else None,
        )
        async with world.repository.session() as session:
            credential = await CredentialRepository(session).insert_credential(
                account_id=DEFAULT_INSTALLATION_ACCOUNT_ID,
                provider_type="keenable",
                owner_scope=CredentialOwnerScope.SYSTEM,
                owner_project_id=None,
                owner_user_id=world.project.actor_id,
                label="owned-keyless",
                auth_mode="keyless",
                created_by=world.project.actor_id,
            )
            pool = await KeyPoolRepository(session).create(
                credential_id=credential.id,
                project_id=world.project.project_id,
                provider_type="keenable",
                created_by=world.project.actor_id,
                values=KeyPoolValues(label="owned", operations=frozenset({"search", "fetch"})),
            )
            await materialize_pools(session, project_id=world.project.project_id)
            await session.commit()
        response = await world.service.search(
            search_request(world, routing={"mode": "require", "providers": ["keenable"]}),
            attribution=world.project,
            context=world.context,
        )
        assert response.provider == "keenable"
        assert adapter.search_calls == 1
        async with world.repository.session() as session:
            await KeyPoolRepository(session).unassign(pool.id)
            await materialize_pools(session, project_id=world.project.project_id)
            await session.commit()
        with pytest.raises(ExecutionBindingMissing) as error:
            await world.service.search(
                search_request(world, routing={"mode": "require", "providers": ["keenable"]}),
                attribution=world.project,
                context=world.context,
            )
        assert "keenable" in error.value.detail and "pool" in error.value.detail
        assert adapter.search_calls == 1
    finally:
        await world.aclose()


@pytest.mark.asyncio
async def test_cloud_keyless_pool_isolation_across_projects(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One project's assigned keyless pool is invisible to a foreign project."""

    world = await build_execution_world(tmp_path, monkeypatch, limits=False)
    try:
        adapter = RecordingAdapter("keenable", auth_mode=AuthMode.KEYLESS)
        monkeypatch.setattr(
            "polyweb.services.execution.adapter_factory",
            lambda name: (lambda client, api_key=None: adapter) if name == "keenable" else None,
        )
        async with world.repository.session() as session:
            credential = await CredentialRepository(session).insert_credential(
                account_id=DEFAULT_INSTALLATION_ACCOUNT_ID,
                provider_type="keenable",
                owner_scope=CredentialOwnerScope.SYSTEM,
                owner_project_id=None,
                owner_user_id=world.project.actor_id,
                label="owned-keyless",
                auth_mode="keyless",
                created_by=world.project.actor_id,
            )
            await KeyPoolRepository(session).create(
                credential_id=credential.id,
                project_id=world.project.project_id,
                provider_type="keenable",
                created_by=world.project.actor_id,
                values=KeyPoolValues(label="owned", operations=frozenset({"search", "fetch"})),
            )
            await materialize_pools(session, project_id=world.project.project_id)
            await session.commit()
        foreign = await seed_execution_project(world.repository)
        foreign_context = ProjectContext(
            account_id=DEFAULT_INSTALLATION_ACCOUNT_ID,
            project_id=foreign.project_id,
            principal=HumanPrincipal(user_id=foreign.actor_id, session_id=uuid4()),
            effective_permissions=frozenset(
                {PermissionAction.SEARCH_EXECUTE, PermissionAction.FETCH_EXECUTE}
            ),
            policy_revision=1,
        )
        async with world.repository.session() as session:
            bindings = await ProjectBindingRepository(session).list_for_project(
                project_id=world.project.project_id
            )
            assert len(bindings) == 1
            assert (
                await ProjectBindingRepository(session).list_for_project(
                    project_id=foreign.project_id
                )
                == []
            )
        calls_before = adapter.search_calls
        with pytest.raises(ExecutionBindingMissing) as error:
            await world.service.search(
                search_request(world, routing={"mode": "require", "providers": ["keenable"]}),
                attribution=foreign,
                context=foreign_context,
            )
        assert "keenable" in error.value.detail and "pool" in error.value.detail
        assert adapter.search_calls == calls_before
    finally:
        await world.aclose()
