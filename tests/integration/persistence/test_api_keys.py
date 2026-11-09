"""ProjectApiKeyRepository: digest-only storage, null expiry, project isolation."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import AsyncIterator
from dataclasses import dataclass, fields
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from sqlalchemy.exc import IntegrityError

from polyweb.persistence.api_keys import ProjectApiKeyRepository, StoredApiKey
from polyweb.persistence.storage import SQLiteRepository
from tests.fixtures.execution import seed_execution_project, seed_execution_user

_NOW = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)
_SCOPES = frozenset({"search.execute", "fetch.execute"})


@dataclass(frozen=True)
class _World:
    repo: SQLiteRepository
    project_a: UUID
    project_b: UUID
    user_id: UUID


@pytest_asyncio.fixture
async def world(tmp_path: Path) -> AsyncIterator[_World]:
    repo = await SQLiteRepository.open(tmp_path / "api keys.db")
    try:
        a = await seed_execution_project(repo, name="A")
        b = await seed_execution_project(repo, user_id=a.actor_id, name="B")
        yield _World(repo, a.project_id, b.project_id, a.actor_id)
    finally:
        await repo.close()


def _digest(label: str) -> str:
    return hashlib.sha256(f"verifier-{label}".encode()).hexdigest()


async def _create(
    world: _World,
    *,
    project_id: UUID,
    prefix: str,
    expires_at: datetime | None = None,
    now: datetime = _NOW,
    rotated_from_id: UUID | None = None,
) -> StoredApiKey:
    async with world.repo.session() as session:
        stored = await ProjectApiKeyRepository(session).create(
            project_id=project_id,
            label=f"label {prefix}",
            prefix=prefix,
            verifier_digest=_digest(prefix),
            scopes=_SCOPES,
            created_by=world.user_id,
            expires_at=expires_at,
            rotated_from_id=rotated_from_id,
            now=now,
        )
        await session.commit()
    return stored


def _raw(world: _World, sql: str, *params: object) -> list[tuple[object, ...]]:
    connection = sqlite3.connect(world.repo.database_path)
    try:
        return connection.execute(sql, params).fetchall()
    finally:
        connection.close()


async def test_null_expiry_is_stored_as_null_and_read_back_as_none(world: _World) -> None:
    created = await _create(world, project_id=world.project_a, prefix="fsk_nullexp")

    assert created.expires_at is None
    assert _raw(world, "SELECT expires_at FROM project_api_keys WHERE id = ?", str(created.id)) == [
        (None,)
    ]
    async with world.repo.session() as session:
        repository = ProjectApiKeyRepository(session)
        fetched = await repository.get(project_id=world.project_a, api_key_id=created.id)
        by_prefix = await repository.find_by_prefix(prefix="fsk_nullexp")
    assert fetched is not None and fetched.expires_at is None
    assert by_prefix is not None and by_prefix.expires_at is None


async def test_expires_at_has_no_default(world: _World) -> None:
    async with world.repo.session() as session:
        with pytest.raises(TypeError):
            await ProjectApiKeyRepository(session).create(  # type: ignore[call-arg]
                project_id=world.project_a,
                label="no expiry argument",
                prefix="fsk_noarg",
                verifier_digest=_digest("noarg"),
                scopes=_SCOPES,
                created_by=world.user_id,
                now=_NOW,
            )


async def test_create_round_trips_fields_and_stores_only_a_digest(world: _World) -> None:
    expires = _NOW + timedelta(days=30)
    created = await _create(
        world, project_id=world.project_a, prefix="fsk_roundtrip", expires_at=expires
    )

    assert isinstance(created.id, UUID)
    assert created.project_id == world.project_a
    assert created.prefix == "fsk_roundtrip"
    assert created.verifier_digest == _digest("fsk_roundtrip")
    assert created.scopes == _SCOPES
    assert created.created_by == world.user_id
    assert created.created_at == _NOW
    assert created.created_at.tzinfo is not None
    assert created.expires_at == expires
    assert created.revoked_at is None
    assert created.last_used_at is None
    assert created.rotated_from_id is None
    assert created.version == 1
    assert {field.name for field in fields(StoredApiKey)} == {
        "id",
        "project_id",
        "label",
        "prefix",
        "verifier_digest",
        "scopes",
        "created_by",
        "created_at",
        "expires_at",
        "revoked_at",
        "last_used_at",
        "rotated_from_id",
        "version",
    }
    raw_scopes = _raw(world, "SELECT scopes FROM project_api_keys WHERE id = ?", str(created.id))
    assert json.loads(str(raw_scopes[0][0])) == sorted(_SCOPES)


async def test_empty_scopes_raise_and_write_nothing(world: _World) -> None:
    async with world.repo.session() as session:
        with pytest.raises(ValueError):
            await ProjectApiKeyRepository(session).create(
                project_id=world.project_a,
                label="empty",
                prefix="fsk_empty",
                verifier_digest=_digest("empty"),
                scopes=frozenset(),
                created_by=world.user_id,
                expires_at=None,
                now=_NOW,
            )
        await session.commit()
    assert _raw(world, "SELECT COUNT(*) FROM project_api_keys") == [(0,)]


async def test_repository_flushes_but_never_commits(world: _World) -> None:
    async with world.repo.session() as session:
        await ProjectApiKeyRepository(session).create(
            project_id=world.project_a,
            label="uncommitted",
            prefix="fsk_uncommitted",
            verifier_digest=_digest("uncommitted"),
            scopes=_SCOPES,
            created_by=world.user_id,
            expires_at=None,
            now=_NOW,
        )
        await session.rollback()
    assert _raw(world, "SELECT COUNT(*) FROM project_api_keys") == [(0,)]


async def test_find_by_prefix_returns_the_key_with_its_own_project(world: _World) -> None:
    key_b = await _create(world, project_id=world.project_b, prefix="fsk_bbbb")
    await _create(world, project_id=world.project_a, prefix="fsk_aaaa")

    async with world.repo.session() as session:
        repository = ProjectApiKeyRepository(session)
        found = await repository.find_by_prefix(prefix="fsk_bbbb")
        missing = await repository.find_by_prefix(prefix="fsk_missing")

    assert found is not None
    assert found.id == key_b.id
    assert found.project_id == world.project_b
    assert missing is None


async def test_prefix_is_globally_unique(world: _World) -> None:
    await _create(world, project_id=world.project_a, prefix="fsk_dup")
    async with world.repo.session() as session:
        with pytest.raises(IntegrityError):
            await ProjectApiKeyRepository(session).create(
                project_id=world.project_b,
                label="dup",
                prefix="fsk_dup",
                verifier_digest=_digest("dup2"),
                scopes=_SCOPES,
                created_by=world.user_id,
                expires_at=None,
                now=_NOW,
            )
        await session.rollback()


async def test_rotation_must_stay_inside_one_project(world: _World) -> None:
    original = await _create(world, project_id=world.project_a, prefix="fsk_orig")

    async with world.repo.session() as session:
        with pytest.raises(IntegrityError):
            await ProjectApiKeyRepository(session).create(
                project_id=world.project_b,
                label="stolen rotation",
                prefix="fsk_rot_b",
                verifier_digest=_digest("rot_b"),
                scopes=_SCOPES,
                created_by=world.user_id,
                expires_at=None,
                rotated_from_id=original.id,
                now=_NOW,
            )
        await session.rollback()

    rotated = await _create(
        world, project_id=world.project_a, prefix="fsk_rot_a", rotated_from_id=original.id
    )
    assert rotated.rotated_from_id == original.id


async def test_revoke_foreign_key_returns_false_and_leaves_the_row(world: _World) -> None:
    key_a = await _create(world, project_id=world.project_a, prefix="fsk_revoke")

    async with world.repo.session() as session:
        repository = ProjectApiKeyRepository(session)
        assert (
            await repository.revoke(
                project_id=world.project_b, api_key_id=key_a.id, revoked_at=_NOW
            )
            is False
        )
        await session.commit()

    assert _raw(
        world, "SELECT revoked_at, version FROM project_api_keys WHERE id = ?", str(key_a.id)
    ) == [(None, 1)]

    async with world.repo.session() as session:
        repository = ProjectApiKeyRepository(session)
        assert (
            await repository.revoke(
                project_id=world.project_a, api_key_id=key_a.id, revoked_at=_NOW
            )
            is True
        )
        assert (
            await repository.revoke(
                project_id=world.project_a,
                api_key_id=key_a.id,
                revoked_at=_NOW + timedelta(minutes=1),
            )
            is False
        )
        assert (
            await repository.revoke(project_id=world.project_a, api_key_id=uuid4(), revoked_at=_NOW)
            is False
        )
        await session.commit()
        revoked = await repository.get(project_id=world.project_a, api_key_id=key_a.id)
    assert revoked is not None
    assert revoked.revoked_at == _NOW
    assert revoked.version == 2


async def test_record_use_is_project_scoped(world: _World) -> None:
    key_a = await _create(world, project_id=world.project_a, prefix="fsk_use")
    used_at = _NOW + timedelta(hours=1)

    async with world.repo.session() as session:
        repository = ProjectApiKeyRepository(session)
        assert (
            await repository.record_use(
                project_id=world.project_b, api_key_id=key_a.id, used_at=used_at
            )
            is False
        )
        await session.commit()
    assert _raw(world, "SELECT last_used_at FROM project_api_keys WHERE id = ?", str(key_a.id)) == [
        (None,)
    ]

    async with world.repo.session() as session:
        repository = ProjectApiKeyRepository(session)
        assert (
            await repository.record_use(
                project_id=world.project_a, api_key_id=key_a.id, used_at=used_at
            )
            is True
        )
        await session.commit()
        fetched = await repository.get(project_id=world.project_a, api_key_id=key_a.id)
    assert fetched is not None and fetched.last_used_at == used_at


async def test_record_use_never_moves_last_used_backwards(world: _World) -> None:
    """rework_1 nit: a late, older use report cannot rewind ``last_used_at``."""

    key_a = await _create(world, project_id=world.project_a, prefix="fsk_monotonic")
    newer = _NOW + timedelta(hours=2)
    older = _NOW + timedelta(hours=1)

    async with world.repo.session() as session:
        repository = ProjectApiKeyRepository(session)
        assert await repository.record_use(
            project_id=world.project_a, api_key_id=key_a.id, used_at=newer
        )
        await repository.record_use(project_id=world.project_a, api_key_id=key_a.id, used_at=older)
        await session.commit()
        fetched = await repository.get(project_id=world.project_a, api_key_id=key_a.id)
    assert fetched is not None and fetched.last_used_at == newer


async def test_get_and_list_never_cross_projects(world: _World) -> None:
    first = await _create(world, project_id=world.project_a, prefix="fsk_a1", now=_NOW)
    second = await _create(
        world, project_id=world.project_a, prefix="fsk_a2", now=_NOW + timedelta(minutes=5)
    )
    key_b = await _create(world, project_id=world.project_b, prefix="fsk_b1")

    async with world.repo.session() as session:
        repository = ProjectApiKeyRepository(session)
        assert await repository.get(project_id=world.project_b, api_key_id=first.id) is None
        assert await repository.get(project_id=world.project_a, api_key_id=key_b.id) is None
        listed_a = await repository.list_for_project(project_id=world.project_a)
        listed_b = await repository.list_for_project(project_id=world.project_b)
        listed_none = await repository.list_for_project(project_id=uuid4())

    assert [key.id for key in listed_a] == [second.id, first.id]  # created_at desc
    assert [key.id for key in listed_b] == [key_b.id]
    assert listed_none == []


async def test_naive_datetimes_are_rejected(world: _World) -> None:
    key_a = await _create(world, project_id=world.project_a, prefix="fsk_naive")
    async with world.repo.session() as session:
        repository = ProjectApiKeyRepository(session)
        with pytest.raises(ValueError):
            await repository.revoke(
                project_id=world.project_a,
                api_key_id=key_a.id,
                revoked_at=datetime(2026, 10, 1, 12, 0),
            )
        with pytest.raises(ValueError):
            await repository.create(
                project_id=world.project_a,
                label="naive expiry",
                prefix="fsk_naive2",
                verifier_digest=_digest("naive2"),
                scopes=_SCOPES,
                created_by=world.user_id,
                expires_at=datetime(2027, 1, 1),
                now=_NOW,
            )


async def test_deleting_the_creator_keeps_the_key(world: _World) -> None:
    creator = await seed_execution_user(world.repo, "keycreator")
    async with world.repo.session() as session:
        created = await ProjectApiKeyRepository(session).create(
            project_id=world.project_a,
            label="by departed human",
            prefix="fsk_departed",
            verifier_digest=_digest("departed"),
            scopes=_SCOPES,
            created_by=creator.id,
            expires_at=None,
            now=_NOW,
        )
        await session.commit()

    connection = sqlite3.connect(world.repo.database_path)
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("DELETE FROM user WHERE id = ?", (str(creator.id),))
        connection.commit()
    finally:
        connection.close()

    async with world.repo.session() as session:
        fetched = await ProjectApiKeyRepository(session).get(
            project_id=world.project_a, api_key_id=created.id
        )
    assert fetched is not None
    assert fetched.created_by == creator.id
