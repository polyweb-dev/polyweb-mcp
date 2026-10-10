"""Attempt-limit contracts on real SQLite (T7 full, T20 persistence part).

Login limits from Q2a and registration limits from Q5b share the persistent
counter table. Each test uses an isolated database. No test needs an HTTP
client or a signed token.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest_asyncio

from freesearch.persistence.login_throttle import (
    LOGIN_PAIR_LIMIT,
    LOGIN_PEER_LIMIT,
    REGISTRATION_GLOBAL_LIMIT,
    REGISTRATION_PEER_LIMIT,
    clear_pair,
    delete_expired,
    reserve_attempt,
    reserve_registration_attempt,
)
from freesearch.persistence.storage import SQLiteRepository


@pytest_asyncio.fixture
async def repository(tmp_path: Path) -> SQLiteRepository:
    repo = await SQLiteRepository.open(tmp_path / "throttle.db")
    yield repo
    await repo.close()


def _now() -> datetime:
    return datetime.now(UTC)


async def test_pair_limit_rejects_sixth_attempt_with_retry(repository: SQLiteRepository) -> None:
    async with repository.session() as session:
        for _ in range(LOGIN_PAIR_LIMIT):
            assert (
                await reserve_attempt(
                    session, email="ops@example.com", peer_address="10.0.0.1", now=_now()
                )
                is None
            )
        retry = await reserve_attempt(
            session, email="ops@example.com", peer_address="10.0.0.1", now=_now()
        )
        assert retry is not None
        assert retry >= 1


async def test_window_expiry_permits_another_attempt(repository: SQLiteRepository) -> None:
    async with repository.session() as session:
        for _ in range(LOGIN_PAIR_LIMIT + 1):
            await reserve_attempt(
                session, email="late@example.com", peer_address="10.0.0.2", now=_now()
            )
        later = _now() + timedelta(seconds=901)
        assert (
            await reserve_attempt(
                session, email="late@example.com", peer_address="10.0.0.2", now=later
            )
            is None
        )


async def test_success_clears_only_the_pair_counter(repository: SQLiteRepository) -> None:
    async with repository.session() as session:
        for _ in range(4):
            assert (
                await reserve_attempt(
                    session, email="clear@example.com", peer_address="10.0.0.3", now=_now()
                )
                is None
            )
        await clear_pair(session, email="clear@example.com", peer_address="10.0.0.3")
        for _ in range(LOGIN_PAIR_LIMIT):
            assert (
                await reserve_attempt(
                    session, email="clear@example.com", peer_address="10.0.0.3", now=_now()
                )
                is None
            )
        assert (
            await reserve_attempt(
                session, email="clear@example.com", peer_address="10.0.0.3", now=_now()
            )
            is not None
        )


async def test_peer_limit_covers_distinct_accounts(repository: SQLiteRepository) -> None:
    async with repository.session() as session:
        for index in range(LOGIN_PEER_LIMIT):
            assert (
                await reserve_attempt(
                    session, email=f"user-{index}@example.com", peer_address="10.0.0.4", now=_now()
                )
                is None
            )
        assert (
            await reserve_attempt(
                session, email="extra@example.com", peer_address="10.0.0.4", now=_now()
            )
            is not None
        )


async def test_counters_survive_a_new_repository_on_the_same_file(tmp_path: Path) -> None:
    path = tmp_path / "restart.db"
    first = await SQLiteRepository.open(path)
    try:
        async with first.session() as session:
            for _ in range(LOGIN_PAIR_LIMIT):
                await reserve_attempt(
                    session, email="stay@example.com", peer_address="10.0.0.5", now=_now()
                )
    finally:
        await first.close()
    second = await SQLiteRepository.open(path)
    try:
        async with second.session() as session:
            assert (
                await reserve_attempt(
                    session, email="stay@example.com", peer_address="10.0.0.5", now=_now()
                )
                is not None
            )
    finally:
        await second.close()


async def test_concurrent_pair_reservations_stay_inside_one_allowance(
    repository: SQLiteRepository,
) -> None:
    async def _one() -> int | None:
        async with repository.session() as session:
            return await reserve_attempt(
                session, email="race@example.com", peer_address="10.0.0.6", now=_now()
            )

    results = await asyncio.gather(*(_one() for _ in range(10)))
    assert sum(1 for item in results if item is None) == LOGIN_PAIR_LIMIT


async def test_login_keys_never_collide_with_registration_keys(
    repository: SQLiteRepository,
) -> None:
    async with repository.session() as session:
        for _ in range(LOGIN_PAIR_LIMIT):
            await reserve_attempt(
                session, email="split@example.com", peer_address="10.0.0.7", now=_now()
            )
        assert (
            await reserve_registration_attempt(session, peer_address="10.0.0.7", now=_now()) is None
        )


async def test_registration_peer_limit_rejects_sixth_attempt(repository: SQLiteRepository) -> None:
    async with repository.session() as session:
        for _ in range(REGISTRATION_PEER_LIMIT):
            assert (
                await reserve_registration_attempt(session, peer_address="10.0.0.8", now=_now())
                is None
            )
        retry = await reserve_registration_attempt(session, peer_address="10.0.0.8", now=_now())
        assert retry is not None
        assert retry >= 1


async def test_successful_registration_clears_neither_counter(
    repository: SQLiteRepository,
) -> None:
    async with repository.session() as session:
        for _ in range(REGISTRATION_PEER_LIMIT):
            assert (
                await reserve_registration_attempt(session, peer_address="10.0.0.9", now=_now())
                is None
            )
        assert (
            await reserve_registration_attempt(session, peer_address="10.0.0.9", now=_now())
            is not None
        )


async def test_registration_global_limit_rejects_after_one_hundred(
    repository: SQLiteRepository,
) -> None:
    async with repository.session() as session:
        for index in range(REGISTRATION_GLOBAL_LIMIT):
            assert (
                await reserve_registration_attempt(
                    session, peer_address=f"10.1.0.{index % 250 + 1}", now=_now()
                )
                is None
            )
        assert (
            await reserve_registration_attempt(session, peer_address="10.9.9.9", now=_now())
            is not None
        )


async def test_registration_window_expiry_permits_another_attempt(
    repository: SQLiteRepository,
) -> None:
    async with repository.session() as session:
        for _ in range(REGISTRATION_PEER_LIMIT + 1):
            await reserve_registration_attempt(session, peer_address="10.0.0.10", now=_now())
        later = _now() + timedelta(seconds=901)
        assert (
            await reserve_registration_attempt(session, peer_address="10.0.0.10", now=later) is None
        )


async def test_delete_expired_removes_only_expired_rows(repository: SQLiteRepository) -> None:
    async with repository.session() as session:
        await reserve_attempt(
            session, email="old@example.com", peer_address="10.0.0.11", now=_now()
        )
        await reserve_registration_attempt(session, peer_address="10.0.0.12", now=_now())
        removed = await delete_expired(session, now=_now() + timedelta(seconds=901))
        assert removed == 4
        assert (
            await reserve_attempt(
                session, email="old@example.com", peer_address="10.0.0.11", now=_now()
            )
            is None
        )
