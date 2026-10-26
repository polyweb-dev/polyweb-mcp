"""CredentialRepository mutations act only on the named owner (rework_1 m3).

``advance_generation`` and ``mark_deleted`` take a required owner pair. A
foreign owner behaves like an absent credential (False, row unchanged), and an
inconsistent pair (system with a project id, project without one) raises.
"""

from __future__ import annotations

import inspect
import sqlite3
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

import pytest
import pytest_asyncio

from freesearch.models.projects import DEFAULT_INSTALLATION_ACCOUNT_ID, CredentialOwnerScope
from freesearch.persistence.credentials import CredentialRepository
from freesearch.persistence.storage import SQLiteRepository
from tests.fixtures.execution import seed_execution_project

_SYSTEM = CredentialOwnerScope.SYSTEM
_PROJECT = CredentialOwnerScope.PROJECT


@dataclass(frozen=True)
class _World:
    repo: SQLiteRepository
    project_a: UUID
    project_b: UUID
    private_a: UUID
    shared: UUID


@pytest_asyncio.fixture
async def world(tmp_path: Path) -> AsyncIterator[_World]:
    repo = await SQLiteRepository.open(tmp_path / "credential owner.db")
    try:
        a = await seed_execution_project(repo, name="A")
        b = await seed_execution_project(repo, user_id=a.actor_id, name="B")
        async with repo.session() as session:
            credentials = CredentialRepository(session)
            private_a = await credentials.insert_credential(
                account_id=DEFAULT_INSTALLATION_ACCOUNT_ID,
                provider_type="exa",
                owner_scope=_PROJECT,
                owner_project_id=a.project_id,
                label="private a",
                auth_mode="api_key",
                created_by=a.actor_id,
            )
            shared = await credentials.insert_credential(
                account_id=DEFAULT_INSTALLATION_ACCOUNT_ID,
                provider_type="tavily",
                owner_scope=_SYSTEM,
                owner_project_id=None,
                label="shared",
                auth_mode="api_key",
                created_by=a.actor_id,
            )
            await session.commit()
        yield _World(repo, a.project_id, b.project_id, private_a.id, shared.id)
    finally:
        await repo.close()


def _state(world: _World, credential_id: UUID) -> tuple[object, ...]:
    connection = sqlite3.connect(world.repo.database_path)
    try:
        row = connection.execute(
            "SELECT generation, status, version FROM provider_credentials WHERE id = ?",
            (str(credential_id),),
        ).fetchone()
    finally:
        connection.close()
    assert row is not None
    return tuple(row)


def test_owner_pair_is_required_on_credential_mutations() -> None:
    for name in ("advance_generation", "mark_deleted"):
        parameters = inspect.signature(getattr(CredentialRepository, name)).parameters
        for required in ("owner_scope", "owner_project_id"):
            parameter = parameters.get(required)
            assert parameter is not None, (name, required)
            assert parameter.default is inspect.Parameter.empty, (name, required)
            assert parameter.kind is inspect.Parameter.KEYWORD_ONLY, (name, required)


@pytest.mark.parametrize(
    ("scope", "owner"),
    [(_PROJECT, "project_b"), (_SYSTEM, None)],
    ids=["other-project", "as-system"],
)
async def test_wrong_owner_leaves_a_private_credential_unchanged(
    world: _World, scope: CredentialOwnerScope, owner: str | None
) -> None:
    owner_project_id = getattr(world, owner) if owner else None
    before = _state(world, world.private_a)

    async with world.repo.session() as session:
        repository = CredentialRepository(session)
        assert (
            await repository.advance_generation(
                credential_id=world.private_a,
                owner_scope=scope,
                owner_project_id=owner_project_id,
                expected_generation=1,
            )
            is False
        )
        assert (
            await repository.mark_deleted(
                credential_id=world.private_a,
                owner_scope=scope,
                owner_project_id=owner_project_id,
            )
            is False
        )
        await session.commit()

    assert _state(world, world.private_a) == before


async def test_project_owner_cannot_mutate_a_shared_credential(world: _World) -> None:
    before = _state(world, world.shared)
    async with world.repo.session() as session:
        repository = CredentialRepository(session)
        assert (
            await repository.advance_generation(
                credential_id=world.shared,
                owner_scope=_PROJECT,
                owner_project_id=world.project_a,
                expected_generation=1,
            )
            is False
        )
        assert (
            await repository.mark_deleted(
                credential_id=world.shared,
                owner_scope=_PROJECT,
                owner_project_id=world.project_a,
            )
            is False
        )
        await session.commit()
    assert _state(world, world.shared) == before


async def test_inconsistent_owner_pair_raises(world: _World) -> None:
    async with world.repo.session() as session:
        repository = CredentialRepository(session)
        with pytest.raises(ValueError):
            await repository.advance_generation(
                credential_id=world.shared,
                owner_scope=_SYSTEM,
                owner_project_id=world.project_a,
                expected_generation=1,
            )
        with pytest.raises(ValueError):
            await repository.mark_deleted(
                credential_id=world.private_a,
                owner_scope=_PROJECT,
                owner_project_id=None,
            )
    assert _state(world, world.shared)[0] == 1
    assert _state(world, world.private_a)[1] == "active"


async def test_the_right_owner_mutates(world: _World) -> None:
    async with world.repo.session() as session:
        repository = CredentialRepository(session)
        assert await repository.advance_generation(
            credential_id=world.private_a,
            owner_scope=_PROJECT,
            owner_project_id=world.project_a,
            expected_generation=1,
        )
        assert await repository.advance_generation(
            credential_id=world.shared,
            owner_scope=_SYSTEM,
            owner_project_id=None,
            expected_generation=1,
        )
        assert await repository.mark_deleted(
            credential_id=world.private_a,
            owner_scope=_PROJECT,
            owner_project_id=world.project_a,
        )
        await session.commit()
    assert _state(world, world.private_a)[:2] == (2, "deleted")
    assert _state(world, world.shared)[:2] == (2, "active")
