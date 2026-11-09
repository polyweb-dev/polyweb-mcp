"""ExecutionAuthorityRepository: fenced leases, takeover recovery, dispatch records."""

from __future__ import annotations

import sqlite3
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
import pytest_asyncio

from polyweb.models.credentials import CredentialOperation
from polyweb.models.observability import ActorType
from polyweb.models.projects import DEFAULT_INSTALLATION_ACCOUNT_ID
from polyweb.models.schema_enums import AuthorityState, DispatchState, UpstreamScope
from polyweb.persistence.execution_authority import (
    ExecutionAuthorityRepository,
    StoredLease,
)
from polyweb.persistence.pools import UpstreamPoolRepository
from polyweb.persistence.storage import SQLiteRepository
from tests.fixtures.execution import seed_execution_project

_T0 = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)
_TTL = timedelta(seconds=30)
_RECOVERY = timedelta(seconds=60)
_KEY = "scheduler"


@dataclass(frozen=True)
class _World:
    repo: SQLiteRepository
    project_a: UUID
    project_b: UUID
    user_id: UUID
    pool_id: UUID
    other_pool_id: UUID


@pytest_asyncio.fixture
async def world(tmp_path: Path) -> AsyncIterator[_World]:
    repo = await SQLiteRepository.open(tmp_path / "authority.db")
    try:
        a = await seed_execution_project(repo, name="A")
        b = await seed_execution_project(repo, user_id=a.actor_id, name="B")
        async with repo.session() as session:
            pools = UpstreamPoolRepository(session)
            pool = await pools.create_pool(
                account_id=DEFAULT_INSTALLATION_ACCOUNT_ID,
                provider_type="tavily",
                upstream_scope=UpstreamScope.ACCOUNT,
                pool_key="tavily-main",
                label="tavily",
                constraints=[],
                now=_T0,
            )
            other = await pools.create_pool(
                account_id=DEFAULT_INSTALLATION_ACCOUNT_ID,
                provider_type="exa",
                upstream_scope=UpstreamScope.ACCOUNT,
                pool_key="exa-main",
                label="exa",
                constraints=[],
                now=_T0,
            )
            await session.commit()
        yield _World(repo, a.project_id, b.project_id, a.actor_id, pool.id, other.id)
    finally:
        await repo.close()


async def _acquire(world: _World, holder: str, now: datetime) -> StoredLease | None:
    async with world.repo.session() as session:
        lease = await ExecutionAuthorityRepository(session).acquire(
            authority_key=_KEY, holder_id=holder, now=now, ttl=_TTL, recovery=_RECOVERY
        )
        await session.commit()
    return lease


async def _dispatch(
    world: _World,
    *,
    token: int,
    now: datetime,
    project_id: UUID | None = None,
    pool_id: UUID | None = None,
    attempt_id: str | None = None,
    actor_type: ActorType = ActorType.HUMAN,
) -> tuple[bool, str]:
    attempt = attempt_id or f"attempt-{uuid4().hex[:10]}"
    async with world.repo.session() as session:
        recorded = await ExecutionAuthorityRepository(session).record_dispatch(
            authority_key=_KEY,
            fencing_token=token,
            attempt_id=attempt,
            request_id=f"req-{attempt}",
            project_id=project_id or world.project_a,
            pool_id=pool_id or world.pool_id,
            operation=CredentialOperation.SEARCH,
            actor_type=actor_type,
            actor_id=world.user_id,
            now=now,
        )
        await session.commit()
    return recorded, attempt


async def _current(world: _World) -> StoredLease | None:
    async with world.repo.session() as session:
        return await ExecutionAuthorityRepository(session).current(authority_key=_KEY)


async def _open_count(world: _World, pool_id: UUID | None = None) -> int:
    async with world.repo.session() as session:
        return await ExecutionAuthorityRepository(session).open_dispatch_count(
            pool_id=pool_id or world.pool_id
        )


def _dispatch_states(world: _World) -> dict[str, str]:
    connection = sqlite3.connect(world.repo.database_path)
    try:
        rows = connection.execute("SELECT attempt_id, state FROM execution_dispatches").fetchall()
    finally:
        connection.close()
    return {str(attempt): str(state) for attempt, state in rows}


async def test_second_holder_cannot_acquire_a_live_lease(world: _World) -> None:
    first = await _acquire(world, "holder-1", _T0)
    assert first is not None
    assert first.holder_id == "holder-1"
    assert first.state is AuthorityState.ACTIVE
    assert first.fencing_token >= 1
    assert first.expires_at == _T0 + _TTL

    assert await _acquire(world, "holder-2", _T0 + timedelta(seconds=10)) is None
    assert await _acquire(world, "holder-2", _T0 + _TTL - timedelta(microseconds=1)) is None
    current = await _current(world)
    assert current is not None
    assert current.holder_id == "holder-1"
    assert current.fencing_token == first.fencing_token


async def test_record_dispatch_requires_the_current_token_and_a_live_active_lease(
    world: _World,
) -> None:
    lease = await _acquire(world, "holder-1", _T0)
    assert lease is not None
    token = lease.fencing_token

    ok, attempt = await _dispatch(world, token=token, now=_T0 + timedelta(seconds=1))
    assert ok is True
    wrong, wrong_attempt = await _dispatch(world, token=token + 1, now=_T0 + timedelta(seconds=1))
    assert wrong is False
    expired, expired_attempt = await _dispatch(world, token=token, now=_T0 + _TTL)
    assert expired is False
    assert _dispatch_states(world) == {attempt: "dispatched"}
    assert wrong_attempt not in _dispatch_states(world)
    assert expired_attempt not in _dispatch_states(world)


async def test_takeover_after_expiry_fences_and_recovers(world: _World) -> None:
    first = await _acquire(world, "holder-1", _T0)
    assert first is not None
    old_token = first.fencing_token
    _, open_attempt = await _dispatch(world, token=old_token, now=_T0 + timedelta(seconds=1))
    _, done_attempt = await _dispatch(world, token=old_token, now=_T0 + timedelta(seconds=2))
    async with world.repo.session() as session:
        assert await ExecutionAuthorityRepository(session).resolve_dispatch(
            project_id=world.project_a,
            attempt_id=done_attempt,
            state=DispatchState.COMPLETED,
            now=_T0 + timedelta(seconds=3),
        )
        await session.commit()

    takeover_at = _T0 + _TTL  # expires_at <= now: the lease has expired
    second = await _acquire(world, "holder-2", takeover_at)

    assert second is not None
    assert second.holder_id == "holder-2"
    assert second.fencing_token == old_token + 1
    assert second.state is AuthorityState.RECOVERING
    assert second.recovery_until == takeover_at + _RECOVERY
    assert _dispatch_states(world) == {open_attempt: "uncertain", done_attempt: "completed"}

    # Uncertain attempts still hold pool concurrency until resolved.
    assert await _open_count(world) == 1
    async with world.repo.session() as session:
        repository = ExecutionAuthorityRepository(session)
        uncertain_a = await repository.list_uncertain(project_id=world.project_a)
        uncertain_b = await repository.list_uncertain(project_id=world.project_b)
    assert [dispatch.attempt_id for dispatch in uncertain_a] == [open_attempt]
    assert uncertain_a[0].state is DispatchState.UNCERTAIN
    assert uncertain_a[0].fencing_token == old_token
    assert uncertain_b == []

    # No dispatch while recovering, neither with the new nor the old token.
    before = _dispatch_states(world)
    recovering_new, _ = await _dispatch(world, token=second.fencing_token, now=takeover_at)
    recovering_old, _ = await _dispatch(world, token=old_token, now=takeover_at)
    assert recovering_new is False
    assert recovering_old is False
    assert _dispatch_states(world) == before

    # The old holder can no longer renew or release.
    async with world.repo.session() as session:
        repository = ExecutionAuthorityRepository(session)
        assert (
            await repository.renew(
                authority_key=_KEY,
                holder_id="holder-1",
                fencing_token=old_token,
                now=takeover_at,
                ttl=_TTL,
            )
            is None
        )
        assert (
            await repository.release(
                authority_key=_KEY, holder_id="holder-1", fencing_token=old_token, now=takeover_at
            )
            is False
        )
        await session.commit()

    # Renewal after the recovery window returns to active and dispatch resumes.
    renew_at = takeover_at + _RECOVERY
    for seconds in (20, 45):  # each renewal keeps the 30 s lease live until renew_at
        async with world.repo.session() as session:
            renewed = await ExecutionAuthorityRepository(session).renew(
                authority_key=_KEY,
                holder_id="holder-2",
                fencing_token=second.fencing_token,
                now=takeover_at + timedelta(seconds=seconds),
                ttl=_TTL,
            )
            await session.commit()
        assert renewed is not None and renewed.state is AuthorityState.RECOVERING
        assert renewed.expires_at == takeover_at + timedelta(seconds=seconds) + _TTL
    async with world.repo.session() as session:
        active = await ExecutionAuthorityRepository(session).renew(
            authority_key=_KEY,
            holder_id="holder-2",
            fencing_token=second.fencing_token,
            now=renew_at,
            ttl=_TTL,
        )
        await session.commit()
    assert active is not None
    assert active.state is AuthorityState.ACTIVE
    assert active.fencing_token == second.fencing_token
    resumed, _ = await _dispatch(world, token=second.fencing_token, now=renew_at)
    assert resumed is True


async def test_takeover_without_open_dispatches_is_active(world: _World) -> None:
    first = await _acquire(world, "holder-1", _T0)
    assert first is not None
    second = await _acquire(world, "holder-2", _T0 + _TTL + timedelta(seconds=5))
    assert second is not None
    assert second.state is AuthorityState.ACTIVE
    assert second.fencing_token == first.fencing_token + 1


async def test_release_never_resolves_dispatches(world: _World) -> None:
    lease = await _acquire(world, "holder-1", _T0)
    assert lease is not None
    _, attempt = await _dispatch(world, token=lease.fencing_token, now=_T0 + timedelta(seconds=1))

    async with world.repo.session() as session:
        repository = ExecutionAuthorityRepository(session)
        assert (
            await repository.release(
                authority_key=_KEY,
                holder_id="holder-2",
                fencing_token=lease.fencing_token,
                now=_T0 + timedelta(seconds=2),
            )
            is False
        )
        assert (
            await repository.release(
                authority_key=_KEY,
                holder_id="holder-1",
                fencing_token=lease.fencing_token,
                now=_T0 + timedelta(seconds=2),
            )
            is True
        )
        await session.commit()

    vacant = await _current(world)
    assert vacant is not None
    assert vacant.state is AuthorityState.VACANT
    assert vacant.holder_id is None
    assert vacant.expires_at is None
    assert _dispatch_states(world) == {attempt: "dispatched"}
    assert await _open_count(world) == 1

    # A released lease cannot dispatch.
    after_release, _ = await _dispatch(
        world, token=lease.fencing_token, now=_T0 + timedelta(seconds=3)
    )
    assert after_release is False

    # A vacant lease is acquirable at once; the orphaned dispatch becomes uncertain.
    next_lease = await _acquire(world, "holder-3", _T0 + timedelta(seconds=4))
    assert next_lease is not None
    assert next_lease.fencing_token == lease.fencing_token + 1
    assert next_lease.state is AuthorityState.RECOVERING
    assert _dispatch_states(world) == {attempt: "uncertain"}


async def test_resolve_dispatch_is_project_scoped(world: _World) -> None:
    lease = await _acquire(world, "holder-1", _T0)
    assert lease is not None
    _, attempt_a = await _dispatch(world, token=lease.fencing_token, now=_T0)
    _, attempt_b = await _dispatch(
        world, token=lease.fencing_token, now=_T0, project_id=world.project_b
    )
    _, attempt_other_pool = await _dispatch(
        world,
        token=lease.fencing_token,
        now=_T0,
        pool_id=world.other_pool_id,
        actor_type=ActorType.PROJECT_API_KEY,
    )
    assert await _open_count(world) == 2
    assert await _open_count(world, world.other_pool_id) == 1

    async with world.repo.session() as session:
        repository = ExecutionAuthorityRepository(session)
        assert (
            await repository.resolve_dispatch(
                project_id=world.project_b,
                attempt_id=attempt_a,
                state=DispatchState.COMPLETED,
                now=_T0,
            )
            is False
        )
        with pytest.raises(ValueError):
            await repository.resolve_dispatch(
                project_id=world.project_a,
                attempt_id=attempt_a,
                state=DispatchState.DISPATCHED,
                now=_T0,
            )
        await session.commit()
    assert _dispatch_states(world)[attempt_a] == "dispatched"

    async with world.repo.session() as session:
        repository = ExecutionAuthorityRepository(session)
        assert (
            await repository.resolve_dispatch(
                project_id=world.project_a,
                attempt_id=attempt_a,
                state=DispatchState.FAILED,
                now=_T0 + timedelta(seconds=1),
            )
            is True
        )
        await session.commit()
    assert _dispatch_states(world) == {
        attempt_a: "failed",
        attempt_b: "dispatched",
        attempt_other_pool: "dispatched",
    }
    assert await _open_count(world) == 1


async def test_same_holder_reacquire_starts_a_new_incarnation(world: _World) -> None:
    """rework_1 m6: re-acquiring by the same holder fences its previous incarnation."""

    first = await _acquire(world, "holder-1", _T0)
    assert first is not None
    _, open_attempt = await _dispatch(world, token=first.fencing_token, now=_T0)

    again = await _acquire(world, "holder-1", _T0 + timedelta(seconds=5))

    assert again is not None
    assert again.holder_id == "holder-1"
    assert again.fencing_token == first.fencing_token + 1
    assert again.state is AuthorityState.RECOVERING
    assert _dispatch_states(world) == {open_attempt: "uncertain"}
    stale, stale_attempt = await _dispatch(
        world, token=first.fencing_token, now=_T0 + timedelta(seconds=6)
    )
    assert stale is False
    assert stale_attempt not in _dispatch_states(world)
    assert await _open_count(world) == 1
