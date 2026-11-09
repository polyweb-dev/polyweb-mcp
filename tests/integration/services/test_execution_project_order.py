"""Execution follows project-local search and fetch orders."""

from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from freesearch.configuration.config import get_settings
from freesearch.configuration.provider_config import ProviderConfigUpdate
from freesearch.infrastructure.encrypted_store import EncryptedDbSecretStore, load_secret_codec
from freesearch.infrastructure.secrets import ProviderName
from freesearch.models.credentials import CredentialOperation
from freesearch.models.project_routing import OperationOrderUpdate, RoutingOperation
from freesearch.models.projects import CredentialOwnerScope
from freesearch.persistence.audit import AuditRepository
from freesearch.persistence.bindings import ProjectBindingRepository
from freesearch.persistence.credentials import CredentialRepository
from freesearch.persistence.key_pools import KeyPoolRepository, KeyPoolValues
from freesearch.persistence.settings import ProjectSettingsRepository
from freesearch.persistence.storage import SQLiteRepository
from freesearch.routers.api import create_app
from freesearch.services.execution import ExecutionService
from freesearch.services.pool_materializer import materialize_pools
from freesearch.services.project_routing import ProjectPoolOperations, ProjectRoutingService
from freesearch.services.provider_runtime import patch_provider_config
from tests.fixtures.alpha_fixtures import bootstrap_fresh_alpha
from tests.fixtures.auth import (
    account_id_from_pair,
    raw_auth_headers,
    register_system_admin_login,
    temp_email,
    temp_principal,
)
from tests.fixtures.execution import (
    install_adapter_map,
    seed_execution_project,
)
from tests.fixtures.project_order import seed_order_pools
from tests.integration.routers.test_control_api import ControlAdapter


@pytest_asyncio.fixture
async def repository(tmp_path: Path) -> AsyncIterator[SQLiteRepository]:
    repo = await SQLiteRepository.open(tmp_path / "project-order.db")
    try:
        yield repo
    finally:
        await repo.close()


@pytest.mark.asyncio
async def test_execution_uses_separate_project_and_operation_orders(
    repository: SQLiteRepository, auth_secret: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FREESEARCH_ENCRYPTION_KEY", "routing-execution-test-passphrase")
    get_settings.cache_clear()
    store = EncryptedDbSecretStore(repository, load_secret_codec(get_settings()))
    exa, keenable = ControlAdapter("exa"), ControlAdapter("keenable")
    first_secrets: dict[str, str] = {}
    second_secrets: dict[str, str] = {}
    third_secrets: dict[str, str] = {}
    fourth_secrets: dict[str, str] = {}

    async def no_health(*args: Any, **kwargs: Any) -> dict[Any, Any]:
        return {}

    monkeypatch.setattr(ExecutionService, "_health_snapshots", no_health)
    install_adapter_map(monkeypatch, [exa, keenable], secrets=first_secrets)
    install_adapter_map(monkeypatch, [exa, keenable], secrets=second_secrets)
    install_adapter_map(monkeypatch, [exa, keenable], secrets=third_secrets)
    install_adapter_map(monkeypatch, [exa, keenable], secrets=fourth_secrets)
    with TestClient(
        create_app([exa, keenable], repository=repository, secret_store=store)
    ) as client:
        pair = await register_system_admin_login(client, repository, temp_email("order-exec"))
        await patch_provider_config(
            repository, ProviderName.TAVILY, ProviderConfigUpdate(enabled=False)
        )
        headers = raw_auth_headers(pair["access_token"])
        first = await seed_execution_project(repository, user_id=account_id_from_pair(pair))
        second = await seed_execution_project(repository, user_id=account_id_from_pair(pair))
        third = await seed_execution_project(repository, user_id=account_id_from_pair(pair))
        fourth = await seed_execution_project(repository, user_id=account_id_from_pair(pair))
        for project, secrets in ((first, first_secrets), (second, second_secrets)):
            await seed_order_pools(
                repository,
                project_id=project.project_id,
                actor_id=project.actor_id,
                store=store,
                providers=("exa", "keenable"),
                secrets=secrets,
            )
        await seed_order_pools(
            repository,
            project_id=third.project_id,
            actor_id=third.actor_id,
            store=store,
            providers=("exa", "keenable"),
            secrets=third_secrets,
            operations={"keenable": frozenset({"fetch"})},
        )
        await seed_order_pools(
            repository,
            project_id=fourth.project_id,
            actor_id=fourth.actor_id,
            store=store,
            providers=("exa", "keenable"),
            secrets=fourth_secrets,
            missing=frozenset({"keenable"}),
        )
        async with repository.session() as session:
            assert await ProjectSettingsRepository(session).compare_and_set(
                project_id=third.project_id,
                namespace="provider_order",
                schema_version=1,
                overrides={"search": {"strategy": "custom", "custom_order": ["keenable", "exa"]}},
                expected_revision=0,
            )
            await session.commit()

        first_path = f"/api/v1/projects/{first.project_id}/routing/order"
        second_path = f"/api/v1/projects/{second.project_id}/routing/order"
        fourth_path = f"/api/v1/projects/{fourth.project_id}/routing/order"
        for path, operation, order in (
            (first_path, "search", ["exa", "keenable"]),
            (first_path, "fetch", ["keenable", "exa"]),
            (second_path, "search", ["keenable", "exa"]),
            (fourth_path, "search", ["keenable", "exa"]),
        ):
            result = client.put(
                f"{path}/{operation}", headers=headers, json={"strategy": "custom", "order": order}
            )
            assert result.status_code == 200, result.text
        first_search = client.post(
            "/search", headers=headers, json={"project_id": str(first.project_id), "query": "one"}
        )
        second_search = client.post(
            "/search", headers=headers, json={"project_id": str(second.project_id), "query": "two"}
        )
        first_fetch = client.post(
            "/fetch",
            headers=headers,
            json={"project_id": str(first.project_id), "url": "https://example.com"},
        )
        preferred = client.post(
            "/search",
            headers=headers,
            json={
                "project_id": str(first.project_id),
                "query": "preference",
                "routing": {"mode": "prefer", "providers": ["keenable"]},
            },
        )
        missing_pool = client.post(
            "/search", headers=headers, json={"project_id": str(third.project_id), "query": "three"}
        )
        missing_material = client.post(
            "/search", headers=headers, json={"project_id": str(fourth.project_id), "query": "four"}
        )
        for response in (
            first_search,
            second_search,
            first_fetch,
            preferred,
            missing_pool,
            missing_material,
        ):
            assert response.status_code == 200, response.text
        assert first_search.json()["provider"] == "exa"
        assert second_search.json()["provider"] == "keenable"
        assert first_fetch.json()["provider"] == "keenable"
        assert preferred.json()["provider"] == "keenable"
        assert missing_pool.json()["provider"] == "exa"
        assert missing_material.json()["provider"] == "exa"


@pytest.mark.asyncio
async def test_pool_seam_preserves_hidden_custom_slots_and_audits(tmp_path: Path) -> None:
    class FakePoolOperations(ProjectPoolOperations):
        allow_keenable_search = True

        async def for_project(
            self, session: AsyncSession, project_id: UUID
        ) -> dict[str, frozenset[CredentialOperation]]:
            both = frozenset({CredentialOperation.SEARCH, CredentialOperation.FETCH})
            return {
                "exa": both,
                "tavily": both,
                "keenable": both
                if self.allow_keenable_search
                else frozenset({CredentialOperation.FETCH}),
            }

    boot = await bootstrap_fresh_alpha(tmp_path / "hidden-slot.db")
    try:
        pools = FakePoolOperations()
        service = ProjectRoutingService(boot.repository, pool_operations=pools)
        actor, project_id = temp_principal(boot.admin_user), boot.default_project.id
        await service.set(
            actor,
            project_id,
            RoutingOperation.SEARCH,
            OperationOrderUpdate(strategy="custom", order=["exa", "keenable", "tavily"]),
        )
        pools.allow_keenable_search = False
        hidden = await service.get(actor, project_id)
        assert [item.provider for item in hidden.search.providers] == ["exa", "tavily"]
        assert hidden.search.not_allowed == ["keenable"]
        await service.set(
            actor,
            project_id,
            RoutingOperation.SEARCH,
            OperationOrderUpdate(strategy="custom", order=["tavily", "exa"]),
        )
        pools.allow_keenable_search = True
        restored = await service.get(actor, project_id)
        assert [item.provider for item in restored.search.providers] == [
            "tavily",
            "keenable",
            "exa",
        ]
        preset = await service.set(
            actor, project_id, RoutingOperation.SEARCH, OperationOrderUpdate(strategy="free_first")
        )
        assert preset.search.providers[0].provider == "keenable"
        assert preset.fetch.strategy == "lowest_cost"
        async with boot.repository.session() as session:
            events = await AuditRepository(session).list_project_events(project_id=project_id)
        assert sum(event.action == "routing.order_changed" for event in events) == 3
    finally:
        await boot.repository.close()


@pytest.mark.asyncio
async def test_membership_follows_grant_not_binding_switch(tmp_path: Path) -> None:
    boot = await bootstrap_fresh_alpha(tmp_path / "grant-membership.db")
    try:
        project_id = boot.default_project.id
        async with boot.repository.session() as session:
            credentials = CredentialRepository(session)
            credential = await credentials.insert_credential(
                account_id=boot.account_id,
                provider_type="keenable",
                owner_scope=CredentialOwnerScope.SYSTEM,
                owner_project_id=None,
                owner_user_id=boot.admin_user.id,
                label="shared",
                auth_mode="api_key",
                created_by=boot.admin_user.id,
            )
            pool = await KeyPoolRepository(session).create(
                credential_id=credential.id,
                project_id=project_id,
                provider_type="keenable",
                created_by=boot.admin_user.id,
                values=KeyPoolValues(label="shared", operations=frozenset({"fetch"})),
            )
            await materialize_pools(session, project_id=project_id)
            await session.commit()
        service = ProjectRoutingService(boot.repository)
        actor = temp_principal(boot.admin_user)
        limited = await service.get(actor, project_id)
        assert "keenable" not in [item.provider for item in limited.search.providers]
        assert limited.search.not_allowed == ["keenable"]
        assert "keenable" in [item.provider for item in limited.fetch.providers]

        async with boot.repository.session() as session:
            bindings = ProjectBindingRepository(session)
            binding = next(
                b
                for b in await bindings.list_for_project(project_id=project_id)
                if b.credential_id == credential.id
            )
            assert await bindings.set_enabled_operations(
                project_id=project_id,
                binding_id=binding.id,
                operations=frozenset(),
                expected_version=binding.version,
            )
            await session.commit()
        assert "keenable" in [
            item.provider for item in (await service.get(actor, project_id)).fetch.providers
        ]

        async with boot.repository.session() as session:
            await KeyPoolRepository(session).update(
                pool.id,
                KeyPoolValues(label="shared", operations=frozenset({"search", "fetch"})),
            )
            await materialize_pools(session, project_id=project_id)
            await session.commit()
        allowed = await service.get(actor, project_id)
        assert "keenable" in [item.provider for item in allowed.search.providers]
        assert allowed.search.not_allowed == []
    finally:
        await boot.repository.close()
