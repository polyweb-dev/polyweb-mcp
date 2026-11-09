"""ProjectBindingRepository: ownership/grant enforcement, disabled start, isolation."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from sqlalchemy.exc import IntegrityError

from polyweb.models.credentials import CredentialOperation
from polyweb.models.projects import DEFAULT_INSTALLATION_ACCOUNT_ID, CredentialOwnerScope
from polyweb.persistence.bindings import ProjectBindingRepository, StoredBinding
from polyweb.persistence.credentials import CredentialRepository
from polyweb.persistence.storage import SQLiteRepository
from tests.fixtures.execution import seed_execution_project

_NOW = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)
_BOTH = frozenset({CredentialOperation.SEARCH, CredentialOperation.FETCH})


@dataclass(frozen=True)
class _World:
    repo: SQLiteRepository
    project_a: UUID
    project_b: UUID
    user_id: UUID
    private_a: UUID
    private_b: UUID
    shared: UUID


@pytest_asyncio.fixture
async def world(tmp_path: Path) -> AsyncIterator[_World]:
    repo = await SQLiteRepository.open(tmp_path / "bindings.db")
    try:
        a = await seed_execution_project(repo, name="A")
        b = await seed_execution_project(repo, user_id=a.actor_id, name="B")
        async with repo.session() as session:
            credentials = CredentialRepository(session)
            private_a = await credentials.insert_credential(
                account_id=DEFAULT_INSTALLATION_ACCOUNT_ID,
                provider_type="exa",
                owner_scope=CredentialOwnerScope.PROJECT,
                owner_project_id=a.project_id,
                label="private-a",
                auth_mode="api_key",
                created_by=a.actor_id,
            )
            private_b = await credentials.insert_credential(
                account_id=DEFAULT_INSTALLATION_ACCOUNT_ID,
                provider_type="exa",
                owner_scope=CredentialOwnerScope.PROJECT,
                owner_project_id=b.project_id,
                label="private-b",
                auth_mode="api_key",
                created_by=a.actor_id,
            )
            shared = await credentials.insert_credential(
                account_id=DEFAULT_INSTALLATION_ACCOUNT_ID,
                provider_type="tavily",
                owner_scope=CredentialOwnerScope.SYSTEM,
                owner_project_id=None,
                label="shared",
                auth_mode="api_key",
                created_by=a.actor_id,
            )
            await session.commit()
        yield _World(
            repo,
            a.project_id,
            b.project_id,
            a.actor_id,
            private_a.id,
            private_b.id,
            shared.id,
        )
    finally:
        await repo.close()


async def _grant(world: _World, project_id: UUID) -> None:
    async with world.repo.session() as session:
        await CredentialRepository(session).upsert_grant(
            credential_id=world.shared,
            project_id=project_id,
            permitted_operations=frozenset({CredentialOperation.SEARCH}),
            granted_by=world.user_id,
        )
        await session.commit()


async def _bind(
    world: _World,
    *,
    project_id: UUID,
    credential_id: UUID,
    scope: CredentialOwnerScope,
    route_label: str = "default",
    priority: int = 100,
) -> StoredBinding:
    async with world.repo.session() as session:
        stored = await ProjectBindingRepository(session).create(
            project_id=project_id,
            credential_id=credential_id,
            credential_scope=scope,
            route_label=route_label,
            created_by=world.user_id,
            priority=priority,
            now=_NOW,
        )
        await session.commit()
    return stored


async def _bind_fails(
    world: _World, *, project_id: UUID, credential_id: UUID, scope: CredentialOwnerScope
) -> None:
    async with world.repo.session() as session:
        with pytest.raises(IntegrityError):
            await ProjectBindingRepository(session).create(
                project_id=project_id,
                credential_id=credential_id,
                credential_scope=scope,
                route_label=f"route-{uuid4().hex[:6]}",
                created_by=world.user_id,
                now=_NOW,
            )
        await session.rollback()


def _count(world: _World, sql: str, *params: object) -> int:
    connection = sqlite3.connect(world.repo.database_path)
    try:
        return int(connection.execute(sql, params).fetchone()[0])
    finally:
        connection.close()


async def test_private_binding_starts_disabled_with_ownership_columns(world: _World) -> None:
    binding = await _bind(
        world,
        project_id=world.project_a,
        credential_id=world.private_a,
        scope=CredentialOwnerScope.PROJECT,
    )

    assert binding.project_id == world.project_a
    assert binding.credential_id == world.private_a
    assert binding.credential_scope is CredentialOwnerScope.PROJECT
    assert binding.enabled_operations == frozenset()
    assert binding.priority == 100
    assert binding.overrides == {}
    assert binding.version == 1
    assert binding.created_at == _NOW
    connection = sqlite3.connect(world.repo.database_path)
    try:
        row = connection.execute(
            "SELECT private_project_id, granted_project_id, enabled_operations "
            "FROM project_provider_bindings WHERE id = ?",
            (str(binding.id),),
        ).fetchone()
    finally:
        connection.close()
    assert row[0] == str(world.project_a)
    assert row[1] is None
    assert json.loads(row[2]) == []


async def test_binding_another_projects_private_credential_fails(world: _World) -> None:
    await _bind_fails(
        world,
        project_id=world.project_a,
        credential_id=world.private_b,
        scope=CredentialOwnerScope.PROJECT,
    )
    # Mislabeling a private credential as system does not bypass the rule either.
    await _bind_fails(
        world,
        project_id=world.project_a,
        credential_id=world.private_b,
        scope=CredentialOwnerScope.SYSTEM,
    )
    await _bind_fails(
        world,
        project_id=world.project_a,
        credential_id=world.private_a,
        scope=CredentialOwnerScope.SYSTEM,
    )
    assert _count(world, "SELECT COUNT(*) FROM project_provider_bindings") == 0


async def test_system_credential_requires_a_grant_to_this_project(world: _World) -> None:
    await _bind_fails(
        world,
        project_id=world.project_a,
        credential_id=world.shared,
        scope=CredentialOwnerScope.SYSTEM,
    )
    await _grant(world, world.project_b)
    await _bind_fails(
        world,
        project_id=world.project_a,
        credential_id=world.shared,
        scope=CredentialOwnerScope.SYSTEM,
    )
    # Claiming the shared credential as private never works.
    await _bind_fails(
        world,
        project_id=world.project_a,
        credential_id=world.shared,
        scope=CredentialOwnerScope.PROJECT,
    )

    await _grant(world, world.project_a)
    binding = await _bind(
        world,
        project_id=world.project_a,
        credential_id=world.shared,
        scope=CredentialOwnerScope.SYSTEM,
    )
    assert binding.credential_scope is CredentialOwnerScope.SYSTEM
    assert binding.enabled_operations == frozenset()


async def test_deleting_the_grant_cascades_the_binding(world: _World) -> None:
    await _grant(world, world.project_a)
    await _grant(world, world.project_b)
    binding_a = await _bind(
        world,
        project_id=world.project_a,
        credential_id=world.shared,
        scope=CredentialOwnerScope.SYSTEM,
    )
    binding_b = await _bind(
        world,
        project_id=world.project_b,
        credential_id=world.shared,
        scope=CredentialOwnerScope.SYSTEM,
    )

    async with world.repo.session() as session:
        assert await CredentialRepository(session).delete_grant(
            credential_id=world.shared, project_id=world.project_a
        )
        await session.commit()

    async with world.repo.session() as session:
        repository = ProjectBindingRepository(session)
        assert await repository.get(project_id=world.project_a, binding_id=binding_a.id) is None
        assert await repository.get(project_id=world.project_b, binding_id=binding_b.id) is not None


async def test_route_label_is_unique_per_project_and_credential(world: _World) -> None:
    await _bind(
        world,
        project_id=world.project_a,
        credential_id=world.private_a,
        scope=CredentialOwnerScope.PROJECT,
        route_label="primary",
    )
    async with world.repo.session() as session:
        with pytest.raises(IntegrityError):
            await ProjectBindingRepository(session).create(
                project_id=world.project_a,
                credential_id=world.private_a,
                credential_scope=CredentialOwnerScope.PROJECT,
                route_label="primary",
                created_by=world.user_id,
                now=_NOW,
            )
        await session.rollback()
    await _bind(
        world,
        project_id=world.project_a,
        credential_id=world.private_a,
        scope=CredentialOwnerScope.PROJECT,
        route_label="secondary",
    )


async def test_negative_priority_is_rejected(world: _World) -> None:
    async with world.repo.session() as session:
        with pytest.raises(IntegrityError):
            await ProjectBindingRepository(session).create(
                project_id=world.project_a,
                credential_id=world.private_a,
                credential_scope=CredentialOwnerScope.PROJECT,
                route_label="negative",
                created_by=world.user_id,
                priority=-1,
                now=_NOW,
            )
        await session.rollback()


async def test_set_enabled_operations_compare_and_set(world: _World) -> None:
    binding = await _bind(
        world,
        project_id=world.project_a,
        credential_id=world.private_a,
        scope=CredentialOwnerScope.PROJECT,
    )
    later = _NOW + timedelta(minutes=3)

    async with world.repo.session() as session:
        repository = ProjectBindingRepository(session)
        stale = await repository.set_enabled_operations(
            project_id=world.project_a,
            binding_id=binding.id,
            operations=_BOTH,
            expected_version=binding.version + 1,
            now=later,
        )
        foreign = await repository.set_enabled_operations(
            project_id=world.project_b,
            binding_id=binding.id,
            operations=_BOTH,
            expected_version=binding.version,
            now=later,
        )
        await session.commit()
    assert stale is None
    assert foreign is None

    async with world.repo.session() as session:
        repository = ProjectBindingRepository(session)
        unchanged = await repository.get(project_id=world.project_a, binding_id=binding.id)
        assert unchanged is not None
        assert unchanged.enabled_operations == frozenset()
        assert unchanged.version == 1

        updated = await repository.set_enabled_operations(
            project_id=world.project_a,
            binding_id=binding.id,
            operations=_BOTH,
            expected_version=1,
            now=later,
        )
        await session.commit()
    assert updated is not None
    assert updated.enabled_operations == _BOTH
    assert updated.version == 2
    assert updated.updated_at == later

    async with world.repo.session() as session:
        replay = await ProjectBindingRepository(session).set_enabled_operations(
            project_id=world.project_a,
            binding_id=binding.id,
            operations=frozenset(),
            expected_version=1,
            now=later,
        )
    assert replay is None


async def test_get_list_delete_never_cross_projects(world: _World) -> None:
    await _grant(world, world.project_a)
    shared_a = await _bind(
        world,
        project_id=world.project_a,
        credential_id=world.shared,
        scope=CredentialOwnerScope.SYSTEM,
        route_label="b-route",
        priority=5,
    )
    private_a = await _bind(
        world,
        project_id=world.project_a,
        credential_id=world.private_a,
        scope=CredentialOwnerScope.PROJECT,
        route_label="a-route",
        priority=5,
    )
    low_a = await _bind(
        world,
        project_id=world.project_a,
        credential_id=world.private_a,
        scope=CredentialOwnerScope.PROJECT,
        route_label="z-route",
        priority=1,
    )
    binding_b = await _bind(
        world,
        project_id=world.project_b,
        credential_id=world.private_b,
        scope=CredentialOwnerScope.PROJECT,
    )

    async with world.repo.session() as session:
        repository = ProjectBindingRepository(session)
        assert await repository.get(project_id=world.project_b, binding_id=private_a.id) is None
        assert await repository.get(project_id=world.project_a, binding_id=binding_b.id) is None
        listed_a = await repository.list_for_project(project_id=world.project_a)
        listed_b = await repository.list_for_project(project_id=world.project_b)
        assert await repository.delete(project_id=world.project_b, binding_id=private_a.id) is False
        assert await repository.delete(project_id=world.project_a, binding_id=uuid4()) is False
        await session.commit()

    # priority, route_label, id
    assert [binding.id for binding in listed_a] == [low_a.id, private_a.id, shared_a.id]
    assert [binding.id for binding in listed_b] == [binding_b.id]
    assert _count(world, "SELECT COUNT(*) FROM project_provider_bindings") == 4

    async with world.repo.session() as session:
        repository = ProjectBindingRepository(session)
        assert await repository.delete(project_id=world.project_a, binding_id=private_a.id) is True
        await session.commit()
        assert await repository.get(project_id=world.project_a, binding_id=private_a.id) is None
    assert _count(world, "SELECT COUNT(*) FROM project_provider_bindings") == 3


async def test_repository_flushes_but_never_commits(world: _World) -> None:
    async with world.repo.session() as session:
        await ProjectBindingRepository(session).create(
            project_id=world.project_a,
            credential_id=world.private_a,
            credential_scope=CredentialOwnerScope.PROJECT,
            route_label="uncommitted",
            created_by=world.user_id,
            now=_NOW,
        )
        await session.rollback()
    assert _count(world, "SELECT COUNT(*) FROM project_provider_bindings") == 0
