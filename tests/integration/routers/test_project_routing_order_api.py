"""Project provider-order API with real project and credential rows."""

from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient

from polyweb.configuration.config import get_settings
from polyweb.configuration.provider_config import ProviderConfigUpdate
from polyweb.infrastructure.encrypted_store import EncryptedDbSecretStore, load_secret_codec
from polyweb.infrastructure.secrets import ProviderName
from polyweb.models.projects import BuiltinRole
from polyweb.persistence.storage import SQLiteRepository
from polyweb.routers.api import create_app
from polyweb.services.provider_runtime import patch_provider_config
from tests.fixtures.auth import (
    account_id_from_pair,
    raw_auth_headers,
    register_and_login,
    register_system_admin_login,
    temp_email,
)
from tests.fixtures.execution import (
    add_execution_member,
    seed_execution_project,
)
from tests.fixtures.project_order import seed_order_pools


@pytest_asyncio.fixture
async def repository(tmp_path: Path) -> AsyncIterator[SQLiteRepository]:
    repo = await SQLiteRepository.open(tmp_path / "routing.db")
    try:
        yield repo
    finally:
        await repo.close()


@pytest.mark.asyncio
async def test_order_presets_custom_restore_and_stale(
    repository: SQLiteRepository, auth_secret: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("POLYWEB_ENCRYPTION_KEY", "routing-test-passphrase-9f31")
    get_settings.cache_clear()
    store = EncryptedDbSecretStore(repository, load_secret_codec(get_settings()))
    with TestClient(create_app([], repository=repository, secret_store=store)) as client:
        pair = await register_system_admin_login(client, repository, temp_email("project-order"))
        await patch_provider_config(
            repository, ProviderName.TAVILY, ProviderConfigUpdate(enabled=False)
        )
        headers = raw_auth_headers(pair["access_token"])
        project = await seed_execution_project(repository, user_id=account_id_from_pair(pair))
        await seed_order_pools(
            repository,
            project_id=project.project_id,
            actor_id=project.actor_id,
            store=store,
            providers=("brave", "keenable", "exa"),
        )
        path = f"/api/v1/projects/{project.project_id}/routing/order"
        initial = client.get(path, headers=headers)
        assert initial.status_code == 200
        assert initial.json()["search"]["strategy"] == "lowest_cost"
        assert [item["provider"] for item in initial.json()["search"]["providers"]] == [
            "keenable",
            "brave",
            "exa",
        ]
        assert [item["provider"] for item in initial.json()["fetch"]["providers"]] == [
            "keenable",
            "exa",
        ]
        assert (
            client.put(f"{path}/search", headers=headers, json={"strategy": "custom"}).status_code
            == 409
        )
        assert (
            client.put(
                f"{path}/search",
                headers=headers,
                json={"strategy": "custom", "order": ["exa"]},
            ).status_code
            == 409
        )
        saved = client.put(
            f"{path}/search",
            headers=headers,
            json={"strategy": "custom", "order": ["exa", "brave", "keenable"]},
        )
        assert saved.status_code == 200
        assert (
            client.put(
                f"{path}/search", headers=headers, json={"strategy": "free_first"}
            ).status_code
            == 200
        )
        restored = client.put(f"{path}/search", headers=headers, json={"strategy": "custom"})
        assert restored.status_code == 200
        assert [item["provider"] for item in restored.json()["search"]["providers"]] == [
            "exa",
            "brave",
            "keenable",
        ]
        assert (
            client.put(
                f"{path}/search", headers=headers, json={"strategy": "free_first", "order": []}
            ).status_code
            == 422
        )


@pytest.mark.asyncio
async def test_order_requires_project_membership_and_provider_configuration(
    repository: SQLiteRepository, auth_secret: str
) -> None:
    with TestClient(create_app([], repository=repository)) as client:
        admin = await register_system_admin_login(client, repository, temp_email("order-admin"))
        member = register_and_login(client, temp_email("order-member"))
        outsider = register_and_login(client, temp_email("order-outsider"))
        project = await seed_execution_project(repository, user_id=account_id_from_pair(admin))
        await add_execution_member(
            repository,
            project_id=project.project_id,
            user_id=account_id_from_pair(member),
            role_key=BuiltinRole.PROJECT_MEMBER,
            granted_by=project.actor_id,
        )
        path = f"/api/v1/projects/{project.project_id}/routing/order"
        member_headers = raw_auth_headers(member["access_token"])
        admin_headers = raw_auth_headers(admin["access_token"])
        outsider_headers = raw_auth_headers(outsider["access_token"])
        assert client.get(path, headers=member_headers).status_code == 200
        assert (
            client.put(
                f"{path}/search", headers=member_headers, json={"strategy": "free_first"}
            ).status_code
            == 403
        )
        assert (
            client.put(
                f"{path}/search", headers=admin_headers, json={"strategy": "free_first"}
            ).status_code
            == 200
        )
        assert client.get(path, headers=outsider_headers).status_code == 404
        assert (
            client.put(
                f"{path}/search", headers=outsider_headers, json={"strategy": "free_first"}
            ).status_code
            == 404
        )
