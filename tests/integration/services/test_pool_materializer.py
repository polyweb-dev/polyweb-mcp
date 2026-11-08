"""Vault pools materialize into the actual SQLite execution lookup."""

from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text

from freesearch.models.contracts import UsageEvent, UsageOperation
from freesearch.models.credentials import CredentialOperation
from freesearch.models.projects import DEFAULT_INSTALLATION_ACCOUNT_ID, CredentialOwnerScope
from freesearch.models.schema_enums import UpstreamScope
from freesearch.models.users import UserPrincipal
from freesearch.persistence.bindings import ProjectBindingRepository
from freesearch.persistence.credentials import CredentialRepository
from freesearch.persistence.key_pools import KeyPoolRepository, KeyPoolValues
from freesearch.persistence.pools import PoolAllocationRepository, UpstreamPoolRepository
from freesearch.services.credentials import credential_secret_slot
from freesearch.services.pool_materializer import (
    KEYLESS_PROVIDERS,
    keyless_credential_id,
    materialize_pools,
)
from freesearch.services.provider_runtime import initialize_provider_configs
from freesearch.services.vault_keys import VaultKeyService
from tests.fixtures.a2_execution import ExecutionWorld, build_execution_world, search_request
from tests.fixtures.execution import seed_execution_project

SEARCH = CredentialOperation.SEARCH
FETCH = CredentialOperation.FETCH


async def _seed_pool(world: ExecutionWorld) -> tuple[UUID, UUID]:
    async with world.repository.session() as session:
        credential = await CredentialRepository(session).insert_credential(
            account_id=DEFAULT_INSTALLATION_ACCOUNT_ID,
            provider_type="exa",
            owner_scope=CredentialOwnerScope.SYSTEM,
            owner_project_id=None,
            owner_user_id=world.project.actor_id,
            label="vault-key",
            auth_mode="api_key",
            created_by=world.project.actor_id,
        )
        await world.store.create_slot_in_session(
            session, credential_secret_slot(credential.id, 1), "vault-secret"
        )
        pool = await KeyPoolRepository(session).create(
            credential_id=credential.id,
            project_id=world.project.project_id,
            provider_type="exa",
            created_by=world.project.actor_id,
            values=KeyPoolValues(label="shared", operations=frozenset({"search", "fetch"})),
        )
        await session.commit()
    world.adapters_by_secret["vault-secret"] = world.adapters["a1"]
    return credential.id, pool.id


async def _bindings(world: ExecutionWorld):
    async with world.repository.session() as session:
        bindings = await ProjectBindingRepository(session).list_for_project(
            project_id=world.project.project_id
        )
        public_ids = {UUID(keyless_credential_id(provider)) for provider in KEYLESS_PROVIDERS}
        return [binding for binding in bindings if binding.credential_id not in public_ids]


@pytest.mark.asyncio
async def test_lookup_edit_unassign_and_idempotence(tmp_path: Path, monkeypatch) -> None:
    world = await build_execution_world(tmp_path, monkeypatch, limits=False)
    try:
        credential_id, pool_id = await _seed_pool(world)
        async with world.repository.session() as session:
            result = await materialize_pools(session, project_id=world.project.project_id)
            assert result.pools == 1
            await session.commit()
        binding = (await _bindings(world))[0]
        assert binding.credential_id == credential_id
        for operation in (SEARCH, FETCH):
            leg = await world.service._resolve_binding(
                world.context, binding, operation, providers=None
            )
            assert leg is not None and leg.allocation is not None
            assert leg.allocation.base_rate is None
            if operation == SEARCH:
                spec = world.service._strict_spec(
                    leg, search_request(world), UsageOperation.SEARCH, world.project
                )
                assert spec is not None and spec.windows == ()
        async with world.repository.session() as session:
            result = await materialize_pools(session, project_id=world.project.project_id)
            assert result.pools == 1
            await session.commit()
        assert (await _bindings(world))[0].id == binding.id
        async with world.repository.session() as session:
            pools = KeyPoolRepository(session)
            await pools.update(
                pool_id, KeyPoolValues(label="shared", operations=frozenset({"search"}))
            )
            await materialize_pools(session, project_id=world.project.project_id)
            await session.commit()
        binding = (await _bindings(world))[0]
        assert await world.service._resolve_binding(world.context, binding, SEARCH, providers=None)
        assert (
            await world.service._resolve_binding(world.context, binding, FETCH, providers=None)
            is None
        )
        async with world.repository.session() as session:
            await KeyPoolRepository(session).unassign(pool_id)
            await materialize_pools(session, project_id=world.project.project_id)
            await session.commit()
        assert await _bindings(world) == []
        async with world.repository.session() as session:
            assert (
                await PoolAllocationRepository(session).list_for_project(
                    project_id=world.project.project_id
                )
                == []
            )
            assert (
                await UpstreamPoolRepository(session).pool_for_credential(
                    credential_id=credential_id, operation=SEARCH
                )
                is None
            )
    finally:
        await world.aclose()


@pytest.mark.asyncio
async def test_unrelated_pool_edit_preserves_attribution(tmp_path: Path, monkeypatch) -> None:
    world = await build_execution_world(tmp_path, monkeypatch, limits=False)
    try:
        credential_id, _ = await _seed_pool(world)
        async with world.repository.session() as session:
            other = await CredentialRepository(session).insert_credential(
                account_id=DEFAULT_INSTALLATION_ACCOUNT_ID,
                provider_type="brave",
                owner_scope=CredentialOwnerScope.SYSTEM,
                owner_project_id=None,
                owner_user_id=world.project.actor_id,
                label="other-key",
                auth_mode="api_key",
                created_by=world.project.actor_id,
            )
            other_pool = await KeyPoolRepository(session).create(
                credential_id=other.id,
                project_id=world.project.project_id,
                provider_type="brave",
                created_by=world.project.actor_id,
                values=KeyPoolValues(label="other", operations=frozenset({"search"})),
            )
            await materialize_pools(session, project_id=world.project.project_id)
            allocation = (
                await session.execute(
                    text(
                        "SELECT rowid, pool_id FROM project_pool_allocations "
                        "WHERE key_pool_id != :other AND operation_scope='search'"
                    ),
                    {"other": str(other_pool.id)},
                )
            ).one()
            await session.commit()
        binding = next(
            item for item in await _bindings(world) if item.credential_id == credential_id
        )
        await world.repository.record_usage(
            UsageEvent(
                provider="exa",
                operation=UsageOperation.SEARCH,
                units=1,
                observed_at=datetime.now(UTC),
            ),
            attribution=world.project,
            credential_id=credential_id,
            binding_id=binding.id,
            pool_id=UUID(allocation.pool_id),
        )
        async with world.repository.session() as session:
            await KeyPoolRepository(session).update(
                other_pool.id,
                KeyPoolValues(label="edited", operations=frozenset({"search"}), rate_limit=12),
            )
            await materialize_pools(session, project_id=world.project.project_id)
            assert (
                await session.execute(
                    text("SELECT binding_id,pool_id FROM usage_events WHERE credential_id=:id"),
                    {"id": str(credential_id)},
                )
            ).one() == (str(binding.id), allocation.pool_id)
            assert (
                await session.execute(
                    text(
                        "SELECT rowid FROM project_pool_allocations WHERE project_id=:project "
                        "AND pool_id=:pool AND operation_scope='search'"
                    ),
                    {"project": str(world.project.project_id), "pool": allocation.pool_id},
                )
            ).scalar_one() == allocation.rowid
            await session.commit()
    finally:
        await world.aclose()


@pytest.mark.asyncio
async def test_operation_limits_budget_and_strict_zero(tmp_path: Path, monkeypatch) -> None:
    world = await build_execution_world(tmp_path, monkeypatch, limits=False)
    try:
        _, pool_id = await _seed_pool(world)
        async with world.repository.session() as session:
            await KeyPoolRepository(session).update(
                pool_id,
                KeyPoolValues(
                    label="shared",
                    operations=frozenset({"search", "fetch"}),
                    rate_limit=17,
                    budget_limit=123456,
                    budget_window_seconds=604800,
                    operation_limits={"search": 0, "fetch": 9},
                ),
            )
            await materialize_pools(session, project_id=world.project.project_id)
            rows = (
                await session.execute(
                    text(
                        "SELECT operation_scope,base_rate,limit_scope,budget_limit,"
                        "budget_window_seconds FROM project_pool_allocations "
                        "WHERE project_id=:project ORDER BY operation_scope"
                    ),
                    {"project": str(world.project.project_id)},
                )
            ).all()
            assert rows == [
                ("fetch", 9, "operation", 123456, 604800),
                ("search", 0, "operation", 123456, 604800),
            ]
            await session.commit()
    finally:
        await world.aclose()


@pytest.mark.asyncio
async def test_other_project_retains_shared_credential_link(tmp_path: Path, monkeypatch) -> None:
    world = await build_execution_world(tmp_path, monkeypatch, limits=False)
    try:
        credential, first_pool = await _seed_pool(world)
        other = await seed_execution_project(world.repository, user_id=world.project.actor_id)
        async with world.repository.session() as session:
            await KeyPoolRepository(session).create(
                credential_id=credential,
                project_id=other.project_id,
                provider_type="exa",
                created_by=world.project.actor_id,
                values=KeyPoolValues(label="other", operations=frozenset({"search"})),
            )
            await materialize_pools(session)
            await KeyPoolRepository(session).unassign(first_pool)
            await materialize_pools(session, project_id=world.project.project_id)
            link = await UpstreamPoolRepository(session).pool_for_credential(
                credential_id=credential, operation=SEARCH
            )
            assert link is not None
            assert await PoolAllocationRepository(session).get(
                project_id=other.project_id, pool_id=link.pool_id, operation=SEARCH
            )
            await session.commit()
    finally:
        await world.aclose()


@pytest.mark.asyncio
async def test_shared_scope_and_system_pool_survive_rebuild(tmp_path: Path, monkeypatch) -> None:
    world = await build_execution_world(tmp_path, monkeypatch, limits=False)
    try:
        await _seed_pool(world)
        async with world.repository.session() as session:
            system_pool = await UpstreamPoolRepository(session).create_pool(
                account_id=DEFAULT_INSTALLATION_ACCOUNT_ID,
                provider_type="exa",
                upstream_scope=UpstreamScope.ACCOUNT,
                pool_key="system-health",
                label="System health",
                constraints=[],
            )
            await materialize_pools(session, project_id=world.project.project_id)
            scopes = (
                await session.execute(
                    text("SELECT limit_scope,base_rate FROM project_pool_allocations")
                )
            ).all()
            assert scopes == [("pool", None), ("pool", None)]
            await materialize_pools(session, project_id=world.project.project_id)
            assert await UpstreamPoolRepository(session).get_pool(
                account_id=DEFAULT_INSTALLATION_ACCOUNT_ID, pool_id=system_pool.id
            )
            await session.commit()
    finally:
        await world.aclose()


@pytest.mark.asyncio
async def test_failed_rebuild_rolls_back_existing_runtime_rows(tmp_path: Path, monkeypatch) -> None:
    world = await build_execution_world(tmp_path, monkeypatch, limits=False)
    try:
        _, pool_id = await _seed_pool(world)
        async with world.repository.session() as session:
            await materialize_pools(session, project_id=world.project.project_id)
            await session.commit()
        original = (await _bindings(world))[0]
        async with world.repository.session() as session:
            await KeyPoolRepository(session).update(
                pool_id,
                KeyPoolValues(
                    label="shared",
                    operations=frozenset({"search"}),
                    operation_limits={"search": "invalid"},
                ),
            )
            await session.commit()
        async with world.repository.session() as session:
            with pytest.raises(ValueError, match="invalid operation rate"):
                await materialize_pools(session, project_id=world.project.project_id)
            await session.rollback()
        assert await _bindings(world) == [original]
    finally:
        await world.aclose()


@pytest.mark.asyncio
async def test_startup_replaces_legacy_project_binding(tmp_path: Path, monkeypatch) -> None:
    world = await build_execution_world(tmp_path, monkeypatch, limits=False)
    try:
        assert len(await _bindings(world)) == 1
        credential, _ = await _seed_pool(world)
        await initialize_provider_configs(world.repository)
        bindings = await _bindings(world)
        assert len(bindings) == 1 and bindings[0].credential_id == credential
    finally:
        await world.aclose()


@pytest.mark.asyncio
async def test_delete_key_removes_project_capacity(tmp_path: Path, monkeypatch) -> None:
    world = await build_execution_world(tmp_path, monkeypatch, limits=False)
    try:
        credential, _ = await _seed_pool(world)
        async with world.repository.session() as session:
            await materialize_pools(session, project_id=world.project.project_id)
            await session.commit()
        actor = UserPrincipal(
            id=world.project.actor_id,
            email="admin@example.test",
            session_id=uuid4(),
            is_active=True,
            is_verified=True,
        )
        result = await VaultKeyService(world.repository, world.store).delete(actor, credential)
        assert len(result.deleted_pools) == 1
        assert await _bindings(world) == []
        async with world.repository.session() as session:
            assert (
                await PoolAllocationRepository(session).list_for_project(
                    project_id=world.project.project_id
                )
                == []
            )
            assert (
                await UpstreamPoolRepository(session).pool_for_credential(
                    credential_id=credential, operation=SEARCH
                )
                is None
            )
    finally:
        await world.aclose()
