"""Public credentials use the same durable execution path as vault pools."""

from pathlib import Path
from uuid import UUID

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from polyweb.configuration.config import get_settings
from polyweb.configuration.provider_config import ProviderConfigUpdate
from polyweb.infrastructure.encrypted_store import EncryptedDbSecretStore, load_secret_codec
from polyweb.infrastructure.secrets import ProviderName
from polyweb.persistence.bindings import ProjectBindingRepository
from polyweb.persistence.key_pools import KeyPoolRepository
from polyweb.persistence.storage import SQLiteRepository
from polyweb.routers.api import create_app
from polyweb.services.pool_materializer import (
    ensure_keyless_credentials,
    keyless_credential_id,
    materialize_pools,
)
from polyweb.services.provider_runtime import initialize_provider_configs, patch_provider_config
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
                public = next(
                    b
                    for b in bindings
                    if b.credential_id == UUID(keyless_credential_id("keenable"))
                )
                await session.commit()
            await initialize_provider_configs(repository)
            await initialize_provider_configs(repository)
            async with repository.session() as session:
                bindings = await ProjectBindingRepository(session).list_for_project(
                    project_id=project.project_id
                )
                assert any(b.id == public.id for b in bindings)
            path = f"/api/v1/projects/{project.project_id}"
            order = client.get(f"{path}/routing/order", headers=headers).json()
            keenable = next(p for p in order["search"]["providers"] if p["provider"] == "keenable")
            assert keenable["keyless"] is True and float(keenable["call_cost_usd"]) == 0
            view = client.get(f"{path}/providers", headers=headers).json()
            assert next(p for p in view["providers"] if p["provider_type"] == "keenable")["keyless"]
            vault = client.get("/api/v1/account/vault/keys", headers=headers)
            assert vault.status_code == 200 and vault.json() == []
            request = {
                "project_id": str(project.project_id),
                "query": "keyless",
                "routing": {"mode": "require", "providers": ["keenable"]},
            }
            response = client.post("/search", headers=headers, json=request)
            assert response.status_code == 200, response.text
            assert seen[-1].url.path.endswith("/search/public")
            assert "x-api-key" not in seen[-1].headers

            await patch_provider_config(
                repository, ProviderName.KEENABLE, ProviderConfigUpdate(enabled=False)
            )
            disabled = client.get(f"{path}/routing/order", headers=headers).json()
            assert "keenable" not in [p["provider"] for p in disabled["search"]["providers"]]
            assert client.post("/search", headers=headers, json=request).status_code == 503
            await patch_provider_config(
                repository, ProviderName.KEENABLE, ProviderConfigUpdate(enabled=True)
            )
            async with repository.session() as session:
                bindings = await ProjectBindingRepository(session).list_for_project(
                    project_id=project.project_id
                )
                assert any(b.id == public.id for b in bindings)

            await seed_order_pools(
                repository,
                project_id=project.project_id,
                actor_id=project.actor_id,
                store=store,
                providers=("keenable",),
            )
            async with repository.session() as session:
                bindings = await ProjectBindingRepository(session).list_for_project(
                    project_id=project.project_id
                )
                assert all(b.id != public.id for b in bindings)
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
            order = client.get(f"{path}/routing/order", headers=headers).json()
            assert next(p for p in order["search"]["providers"] if p["provider"] == "keenable")[
                "keyless"
            ]
            response = client.post("/search", headers=headers, json=request)
            assert response.status_code == 200, response.text
            assert seen[-1].url.path.endswith("/search/public")
    finally:
        await upstream.aclose()
        await repository.close()
