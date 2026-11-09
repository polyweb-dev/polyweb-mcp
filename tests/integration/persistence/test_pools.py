"""Upstream pools, credential links and strict-cap allocations (TASK-000040)."""

from __future__ import annotations

import inspect
import sqlite3
from collections.abc import AsyncIterator
from dataclasses import dataclass, fields
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from sqlalchemy.exc import IntegrityError

from polyweb.models.credentials import CredentialOperation
from polyweb.models.projects import DEFAULT_INSTALLATION_ACCOUNT_ID, CredentialOwnerScope
from polyweb.models.schema_enums import PoolStatus, UpstreamScope
from polyweb.persistence.credentials import CredentialRepository
from polyweb.persistence.pools import (
    PoolAllocationRepository,
    StoredAllocation,
    StoredPool,
    StoredPoolLink,
    UpstreamPoolRepository,
)
from polyweb.persistence.storage import SQLiteRepository
from tests.fixtures.execution import seed_execution_project

_NOW = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)
_SEARCH = CredentialOperation.SEARCH
_FETCH = CredentialOperation.FETCH
_ACCOUNT = DEFAULT_INSTALLATION_ACCOUNT_ID
_BALANCE_WORDS = ("remaining", "balance", "allowance", "spend")


@dataclass(frozen=True)
class _World:
    repo: SQLiteRepository
    project_a: UUID
    project_b: UUID
    user_id: UUID
    tavily_credential: UUID


@pytest_asyncio.fixture
async def world(tmp_path: Path) -> AsyncIterator[_World]:
    repo = await SQLiteRepository.open(tmp_path / "pools.db")
    try:
        a = await seed_execution_project(repo, name="A")
        b = await seed_execution_project(repo, user_id=a.actor_id, name="B")
        async with repo.session() as session:
            credential = await CredentialRepository(session).insert_credential(
                account_id=_ACCOUNT,
                provider_type="tavily",
                owner_scope=CredentialOwnerScope.SYSTEM,
                owner_project_id=None,
                label="shared tavily",
                auth_mode="api_key",
                created_by=a.actor_id,
            )
            await session.commit()
        yield _World(repo, a.project_id, b.project_id, a.actor_id, credential.id)
    finally:
        await repo.close()


async def _pool(world: _World, *, provider: str = "tavily", key: str | None = None) -> StoredPool:
    async with world.repo.session() as session:
        pool = await UpstreamPoolRepository(session).create_pool(
            account_id=_ACCOUNT,
            provider_type=provider,
            upstream_scope=UpstreamScope.ACCOUNT,
            pool_key=key or f"{provider}-{uuid4().hex[:8]}",
            label=f"{provider} pool",
            constraints=[{"algorithm": "fixed_window", "window_seconds": 60, "limit": 100}],
            now=_NOW,
        )
        await session.commit()
    return pool


async def _allocate(
    world: _World, *, project_id: UUID, pool_id: UUID, **values: Any
) -> StoredAllocation:
    payload: dict[str, Any] = {
        "operation": _SEARCH,
        "base_rate": 10,
        "rate_window_seconds": 60,
        "granted_by": world.user_id,
        "now": _NOW,
    }
    payload.update(values)
    async with world.repo.session() as session:
        allocation = await PoolAllocationRepository(session).create(
            project_id=project_id, pool_id=pool_id, **payload
        )
        await session.commit()
    return allocation


def _update_kwargs(world: _World, **overrides: Any) -> dict[str, Any]:
    """All tunable fields for ``update``; ``granted_by`` only if the signature takes it."""

    payload: dict[str, Any] = {
        "base_rate": 10,
        "rate_window_seconds": 60,
        "borrow_enabled": False,
        "max_rate": None,
        "weight": 1,
        "best_effort": False,
        "max_concurrency": None,
        "max_queued_requests": None,
        "max_queued_bytes": None,
        "max_queue_wait_ms": None,
    }
    if "granted_by" in inspect.signature(PoolAllocationRepository.update).parameters:
        payload["granted_by"] = world.user_id
    payload.update(overrides)
    return payload


def _raw(world: _World, sql: str, *params: object) -> list[tuple[object, ...]]:
    connection = sqlite3.connect(world.repo.database_path)
    try:
        return connection.execute(sql, params).fetchall()
    finally:
        connection.close()


def test_pool_records_carry_no_balance() -> None:
    for record in (StoredPool, StoredPoolLink, StoredAllocation):
        names = {field.name for field in fields(record)}
        assert not [name for name in names if any(word in name for word in _BALANCE_WORDS)], (
            record.__name__
        )
    assert "project_id" not in {field.name for field in fields(StoredPool)}
    assert "project_id" not in {field.name for field in fields(StoredPoolLink)}


async def test_create_pool_round_trip_and_account_bound_reads(world: _World) -> None:
    pool = await _pool(world, key="tavily-account-1")

    assert pool.account_id == _ACCOUNT
    assert pool.provider_type == "tavily"
    assert pool.upstream_scope is UpstreamScope.ACCOUNT
    assert pool.pool_key == "tavily-account-1"
    assert pool.constraints == [{"algorithm": "fixed_window", "window_seconds": 60, "limit": 100}]
    assert pool.status is PoolStatus.ACTIVE
    assert pool.native_pool_id is None
    assert pool.version == 1

    async with world.repo.session() as session:
        repository = UpstreamPoolRepository(session)
        assert await repository.get_pool(account_id=_ACCOUNT, pool_id=pool.id) == pool
        assert await repository.get_pool(account_id=uuid4(), pool_id=pool.id) is None
        assert await repository.list_pools(account_id=uuid4()) == []
        assert [p.id for p in await repository.list_pools(account_id=_ACCOUNT)] == [pool.id]


async def test_pool_key_is_unique_per_account_and_provider(world: _World) -> None:
    await _pool(world, provider="tavily", key="shared-key")
    await _pool(world, provider="exa", key="shared-key")
    async with world.repo.session() as session:
        with pytest.raises(IntegrityError):
            await UpstreamPoolRepository(session).create_pool(
                account_id=_ACCOUNT,
                provider_type="tavily",
                upstream_scope=UpstreamScope.CREDENTIAL,
                pool_key="shared-key",
                label="duplicate",
                constraints=[],
                now=_NOW,
            )
        await session.rollback()


async def test_relinking_a_credential_replaces_the_pool(world: _World) -> None:
    first = await _pool(world)
    second = await _pool(world)

    async with world.repo.session() as session:
        repository = UpstreamPoolRepository(session)
        link = await repository.link_credential(
            credential_id=world.tavily_credential,
            operation=_SEARCH,
            pool_id=first.id,
            provider_type="tavily",
            now=_NOW,
        )
        await session.commit()
    assert link.pool_id == first.id
    assert link.operation is _SEARCH
    assert link.version == 1

    async with world.repo.session() as session:
        repository = UpstreamPoolRepository(session)
        relinked = await repository.link_credential(
            credential_id=world.tavily_credential,
            operation=_SEARCH,
            pool_id=second.id,
            provider_type="tavily",
            now=_NOW + timedelta(minutes=1),
        )
        await session.commit()
        current = await repository.pool_for_credential(
            credential_id=world.tavily_credential, operation=_SEARCH
        )
        fetch_link = await repository.pool_for_credential(
            credential_id=world.tavily_credential, operation=_FETCH
        )
        old_links = await repository.links_for_pool(pool_id=first.id)
        new_links = await repository.links_for_pool(pool_id=second.id)

    assert relinked.pool_id == second.id
    assert relinked.version == 2
    assert current is not None and current.pool_id == second.id
    assert fetch_link is None
    assert old_links == []
    assert [entry.credential_id for entry in new_links] == [world.tavily_credential]
    assert _raw(world, "SELECT COUNT(*) FROM credential_pool_links") == [(1,)]


async def test_link_across_provider_types_fails(world: _World) -> None:
    exa_pool = await _pool(world, provider="exa")
    for provider_type in ("tavily", "exa"):
        async with world.repo.session() as session:
            with pytest.raises(IntegrityError):
                await UpstreamPoolRepository(session).link_credential(
                    credential_id=world.tavily_credential,
                    operation=_SEARCH,
                    pool_id=exa_pool.id,
                    provider_type=provider_type,
                    now=_NOW,
                )
            await session.rollback()
    assert _raw(world, "SELECT COUNT(*) FROM credential_pool_links") == [(0,)]


async def test_allocation_defaults_to_strict_caps(world: _World) -> None:
    pool = await _pool(world)

    allocation = await _allocate(world, project_id=world.project_a, pool_id=pool.id)

    assert allocation.borrow_enabled is False
    assert allocation.max_rate is None
    assert allocation.weight == 1
    assert allocation.best_effort is False
    assert allocation.max_concurrency is None
    assert allocation.max_queued_requests is None
    assert allocation.max_queued_bytes is None
    assert allocation.max_queue_wait_ms is None
    assert allocation.effective_max_rate == allocation.base_rate == 10
    assert allocation.version == 1
    assert _raw(world, "SELECT borrow_enabled FROM project_pool_allocations") == [(0,)]


async def test_effective_max_rate_uses_max_rate_only_with_loans(world: _World) -> None:
    pool = await _pool(world)

    loaned = await _allocate(
        world, project_id=world.project_a, pool_id=pool.id, borrow_enabled=True, max_rate=25
    )
    strict = await _allocate(world, project_id=world.project_b, pool_id=pool.id, max_rate=10)

    assert loaned.effective_max_rate == 25
    assert strict.effective_max_rate == 10


@pytest.mark.parametrize(
    "values",
    [
        {"max_rate": 20},  # max_rate != base_rate without borrowing
        {"borrow_enabled": True, "max_rate": 5},  # loans with max_rate < base_rate
        {"borrow_enabled": True, "max_rate": None},
        {"base_rate": 0},  # zero base without best_effort
        {"weight": 0},
        {"rate_window_seconds": 0},
        {"max_concurrency": 0},
    ],
)
async def test_allocation_rejects_loose_caps(world: _World, values: dict[str, Any]) -> None:
    pool = await _pool(world)
    payload: dict[str, Any] = {
        "operation": _SEARCH,
        "base_rate": 10,
        "rate_window_seconds": 60,
        "granted_by": world.user_id,
        "now": _NOW,
    }
    payload.update(values)
    async with world.repo.session() as session:
        with pytest.raises(IntegrityError):
            await PoolAllocationRepository(session).create(
                project_id=world.project_a, pool_id=pool.id, **payload
            )
        await session.rollback()


async def test_zero_base_rate_is_allowed_for_best_effort(world: _World) -> None:
    pool = await _pool(world)
    allocation = await _allocate(
        world, project_id=world.project_a, pool_id=pool.id, base_rate=0, best_effort=True
    )
    assert allocation.base_rate == 0
    assert allocation.best_effort is True


async def test_allocation_update_compare_and_set(world: _World) -> None:
    pool = await _pool(world)
    created = await _allocate(world, project_id=world.project_a, pool_id=pool.id)
    later = _NOW + timedelta(minutes=2)

    async with world.repo.session() as session:
        repository = PoolAllocationRepository(session)
        stale = await repository.update(
            project_id=world.project_a,
            pool_id=pool.id,
            operation=_SEARCH,
            expected_version=created.version + 1,
            now=later,
            **_update_kwargs(world, base_rate=20),
        )
        foreign = await repository.update(
            project_id=world.project_b,
            pool_id=pool.id,
            operation=_SEARCH,
            expected_version=created.version,
            now=later,
            **_update_kwargs(world, base_rate=20),
        )
        await session.commit()
    assert stale is None
    assert foreign is None
    assert _raw(world, "SELECT base_rate, version FROM project_pool_allocations") == [(10, 1)]

    async with world.repo.session() as session:
        updated = await PoolAllocationRepository(session).update(
            project_id=world.project_a,
            pool_id=pool.id,
            operation=_SEARCH,
            expected_version=1,
            now=later,
            **_update_kwargs(world, base_rate=20, borrow_enabled=True, max_rate=40, weight=3),
        )
        await session.commit()
    assert updated is not None
    assert updated.base_rate == 20
    assert updated.borrow_enabled is True
    assert updated.effective_max_rate == 40
    assert updated.weight == 3
    assert updated.version == 2


async def test_allocations_never_cross_projects(world: _World) -> None:
    pool = await _pool(world)
    other_pool = await _pool(world)
    allocation_a = await _allocate(world, project_id=world.project_a, pool_id=pool.id)
    allocation_a_fetch = await _allocate(
        world, project_id=world.project_a, pool_id=other_pool.id, operation=_FETCH
    )
    allocation_b = await _allocate(world, project_id=world.project_b, pool_id=pool.id, base_rate=7)

    async with world.repo.session() as session:
        repository = PoolAllocationRepository(session)
        assert (
            await repository.get(
                project_id=world.project_b, pool_id=other_pool.id, operation=_FETCH
            )
            is None
        )
        own_b = await repository.get(project_id=world.project_b, pool_id=pool.id, operation=_SEARCH)
        listed_a = await repository.list_for_project(project_id=world.project_a)
        listed_b = await repository.list_for_project(project_id=world.project_b)
        shared_view = await repository.list_for_pool(pool_id=pool.id)
        assert (
            await repository.delete(
                project_id=world.project_b, pool_id=other_pool.id, operation=_FETCH
            )
            is False
        )
        await session.commit()

    assert own_b is not None and own_b.base_rate == 7 and own_b.project_id == world.project_b
    assert {(a.pool_id, a.operation) for a in listed_a} == {
        (allocation_a.pool_id, allocation_a.operation),
        (allocation_a_fetch.pool_id, allocation_a_fetch.operation),
    }
    assert {a.project_id for a in listed_a} == {world.project_a}
    assert [(a.project_id, a.base_rate) for a in listed_b] == [(world.project_b, 7)]
    assert {a.project_id for a in shared_view} == {world.project_a, world.project_b}
    assert allocation_b.project_id == world.project_b
    assert _raw(world, "SELECT COUNT(*) FROM project_pool_allocations") == [(3,)]

    async with world.repo.session() as session:
        repository = PoolAllocationRepository(session)
        assert (
            await repository.delete(
                project_id=world.project_a, pool_id=other_pool.id, operation=_FETCH
            )
            is True
        )
        await session.commit()
    assert _raw(world, "SELECT COUNT(*) FROM project_pool_allocations") == [(2,)]
