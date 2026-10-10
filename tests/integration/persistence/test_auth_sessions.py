"""Session-family and refresh-digest tests on real SQLite (P2a rotation support).

These tests pin the storage contracts behind the protected refresh route:
single-successor rotation, committed reuse revocation, no grace interval,
absolute expiry, digest-only rows, and cascading deletes.
"""

import asyncio
import secrets
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from freesearch.models.users import AuthFamily
from freesearch.persistence.auth_sessions import (
    AuthSessionRepository,
    AuthSessionRow,
    RefreshTokenRow,
    parse_timestamp,
    stored_timestamp,
)
from freesearch.persistence.storage import SQLiteRepository
from freesearch.persistence.users import UserRow
from freesearch.services.users import refresh_token_digest
from tests.fixtures.auth import create_temp_user, temp_email


def _token() -> str:
    return secrets.token_urlsafe(32)


def _now() -> datetime:
    return datetime.now(UTC)


@pytest_asyncio.fixture
async def repository(tmp_path: Path) -> SQLiteRepository:
    repository = await SQLiteRepository.open(tmp_path / "auth-sessions.db")
    yield repository
    await repository.close()


async def _family_with_token(
    repository: SQLiteRepository, user_id: UUID, lifetime: int = 604800
) -> tuple[AuthFamily, str, str]:
    """Create one family plus its first digest; return family, token, digest."""

    now = _now()
    async with repository.session() as session:
        store = AuthSessionRepository(session)
        family = await store.create_family(
            user_id,
            expires_at=now + timedelta(seconds=lifetime),
            now=now,
        )
        token = _token()
        digest = refresh_token_digest(token)
        assert digest is not None
        await store.add_refresh(
            family.id, digest, expires_at=now + timedelta(seconds=lifetime), now=now
        )
        await session.commit()
        return family, token, digest


async def test_create_and_get_enforces_ownership_and_revocation(
    repository: SQLiteRepository,
) -> None:
    user = await create_temp_user(repository, temp_email("owner"))
    family, _, digest = await _family_with_token(repository, user.id)
    now = _now()

    async with repository.session() as session:
        store = AuthSessionRepository(session)
        assert await store.get_family(family.id, user_id=user.id, now=now) is not None
        assert await store.get_family(family.id, user_id=uuid4(), now=now) is None
        assert await store.get_refresh_family(digest, now=now) is not None

        await store.revoke_family(family.id, user_id=user.id, now=now)
        await session.commit()
        assert await store.get_family(family.id, user_id=user.id, now=now) is None
        assert await store.get_refresh_family(digest, now=now) is None


async def test_revoke_user_families_revokes_every_family(repository: SQLiteRepository) -> None:
    user = await create_temp_user(repository, temp_email("bulk"))
    first, _, _ = await _family_with_token(repository, user.id)
    second, _, _ = await _family_with_token(repository, user.id)
    now = _now()

    async with repository.session() as session:
        store = AuthSessionRepository(session)
        await store.revoke_user_families(user.id, now=now)
        await session.commit()
        assert await store.get_family(first.id, user_id=user.id, now=now) is None
        assert await store.get_family(second.id, user_id=user.id, now=now) is None


async def test_expired_family_authorizes_nothing(repository: SQLiteRepository) -> None:
    user = await create_temp_user(repository, temp_email("expired"))
    family, _, digest = await _family_with_token(repository, user.id, lifetime=-10)

    async with repository.session() as session:
        store = AuthSessionRepository(session)
        assert await store.get_family(family.id, user_id=user.id, now=_now()) is None
        assert await store.get_refresh_family(digest, now=_now()) is None


async def test_rotation_keeps_absolute_expiry_with_one_successor(
    repository: SQLiteRepository,
) -> None:
    user = await create_temp_user(repository, temp_email("rotate"))
    family, _, digest = await _family_with_token(repository, user.id)
    successor_digest = refresh_token_digest(_token())
    assert successor_digest is not None

    async with repository.session() as session:
        store = AuthSessionRepository(session)
        rotated = await store.consume_and_rotate(digest, successor_digest, now=_now())
        assert rotated is not None
        assert rotated.expires_at == family.expires_at

    async with repository.session() as session:
        rows = (
            (
                await session.execute(
                    select(RefreshTokenRow).where(RefreshTokenRow.family_id == family.id)
                )
            )
            .scalars()
            .all()
        )
        assert {row.token_hash for row in rows} == {digest, successor_digest}
        old = next(row for row in rows if row.token_hash == digest)
        new = next(row for row in rows if row.token_hash == successor_digest)
        assert old.consumed_at is not None
        assert new.consumed_at is None
        assert new.expires_at == old.expires_at


async def test_reuse_commits_revocation_before_none(repository: SQLiteRepository) -> None:
    user = await create_temp_user(repository, temp_email("replay"))
    family, _, digest = await _family_with_token(repository, user.id)
    successor_digest = refresh_token_digest(_token())
    assert successor_digest is not None

    async with repository.session() as session:
        store = AuthSessionRepository(session)
        assert await store.consume_and_rotate(digest, successor_digest, now=_now()) is not None

    async with repository.session() as session:
        store = AuthSessionRepository(session)
        assert await store.get_refresh_family(digest, now=_now()) is None

    async with repository.session() as session:
        row = await session.get(AuthSessionRow, family.id)
        assert row is not None
        assert row.revoked_at is not None
        store = AuthSessionRepository(session)
        assert await store.get_family(family.id, user_id=user.id, now=_now()) is None
        assert await store.get_refresh_family(successor_digest, now=_now()) is None


async def test_concurrent_rotation_issues_one_successor(repository: SQLiteRepository) -> None:
    user = await create_temp_user(repository, temp_email("race"))
    family, _, digest = await _family_with_token(repository, user.id)

    async def _rotate() -> bool:
        async with repository.session() as session:
            store = AuthSessionRepository(session)
            candidate = refresh_token_digest(_token())
            assert candidate is not None
            return await store.consume_and_rotate(digest, candidate, now=_now()) is not None

    results = await asyncio.gather(*(_rotate() for _ in range(4)))

    assert sum(results) == 1
    async with repository.session() as session:
        rows = (
            (
                await session.execute(
                    select(RefreshTokenRow).where(RefreshTokenRow.family_id == family.id)
                )
            )
            .scalars()
            .all()
        )
        assert len(rows) == 2


async def test_raw_tokens_never_reach_storage(repository: SQLiteRepository) -> None:
    user = await create_temp_user(repository, temp_email("digest"))
    _, token, digest = await _family_with_token(repository, user.id)

    async with repository.session() as session:
        stored = (await session.execute(select(RefreshTokenRow.token_hash))).scalars().all()

    assert digest in stored
    assert token not in stored
    assert len(digest) == 64


async def test_delete_expired_keeps_live_consumed_digests(repository: SQLiteRepository) -> None:
    user = await create_temp_user(repository, temp_email("cleanup"))
    live_family, _, live_digest = await _family_with_token(repository, user.id)
    successor_digest = refresh_token_digest(_token())
    assert successor_digest is not None
    async with repository.session() as session:
        store = AuthSessionRepository(session)
        assert await store.consume_and_rotate(live_digest, successor_digest, now=_now()) is not None
    dead_family, _, _ = await _family_with_token(repository, user.id, lifetime=-10)

    async with repository.session() as session:
        store = AuthSessionRepository(session)
        assert await store.delete_expired(now=_now(), limit=100) == 1
        assert await session.get(AuthSessionRow, dead_family.id) is None
        assert await session.get(AuthSessionRow, live_family.id) is not None
        assert await session.get(RefreshTokenRow, live_digest) is not None
        assert await session.get(RefreshTokenRow, successor_digest) is not None


async def test_family_for_unknown_user_violates_foreign_key(
    repository: SQLiteRepository,
) -> None:
    now = _now()
    async with repository.session() as session:
        store = AuthSessionRepository(session)
        with pytest.raises(IntegrityError):
            await store.create_family(uuid4(), expires_at=now + timedelta(seconds=60), now=now)


async def test_user_delete_cascades_families_and_digests(repository: SQLiteRepository) -> None:
    user = await create_temp_user(repository, temp_email("cascade"))
    family, _, digest = await _family_with_token(repository, user.id)

    async with repository.session() as session:
        row = await session.get(UserRow, user.id)
        assert row is not None
        await session.delete(row)
        await session.commit()

    async with repository.session() as session:
        assert await session.get(AuthSessionRow, family.id) is None
        assert await session.get(RefreshTokenRow, digest) is None


async def test_timestamp_helpers_round_trip_and_reject_naive() -> None:
    now = datetime(2026, 5, 1, 12, 30, 45, 123456, tzinfo=UTC)

    assert parse_timestamp(stored_timestamp(now)) == now

    with pytest.raises(ValueError, match="timezone-aware"):
        stored_timestamp(datetime(2026, 5, 1, 12, 30, 45))
