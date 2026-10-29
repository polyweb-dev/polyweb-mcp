"""Only genuine SQLite writer contention can retry before capacity work starts."""

import asyncio
import sqlite3
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from freesearch.models.provider_limits import AuthMode, LimitOperation, LimitStoreUnavailable
from freesearch.persistence.limit_repository import LimitRepository, StrictWindowSpec
from tests.integration.persistence.test_strict_capacity import (
    CapacityWorld,
    _attempt_rows,
    seed_capacity_world,
)


def _busy_factory(real_factory: Any, seen: list[int], blocked: asyncio.Event) -> Any:
    class Session:
        def __init__(self) -> None:
            self.session = real_factory()

        async def __aenter__(self) -> Any:
            await self.session.__aenter__()
            await self.session.execute(text("PRAGMA busy_timeout=0"))
            return self

        async def __aexit__(self, *exc: Any) -> Any:
            return await self.session.__aexit__(*exc)

        async def execute(self, statement: Any, *args: Any, **kwargs: Any) -> Any:
            try:
                return await self.session.execute(statement, *args, **kwargs)
            except OperationalError as error:
                if str(statement) == "BEGIN IMMEDIATE":
                    seen.append(error.orig.sqlite_errorcode)
                    blocked.set()
                raise

        def __getattr__(self, name: str) -> Any:
            return getattr(self.session, name)

    return Session


@pytest.mark.parametrize("release_writer", [True, False])
async def test_real_busy_at_begin_retries_boundedly_without_duplicate_debits(
    tmp_path: Any, release_writer: bool
) -> None:
    from freesearch.persistence.storage import SQLiteRepository

    repository = await SQLiteRepository.open(tmp_path / "contention.db")
    try:
        world: CapacityWorld = await seed_capacity_world(repository)
        seen: list[int] = []
        blocked = asyncio.Event()
        limits = LimitRepository(_busy_factory(repository._session_factory, seen, blocked))
        spec = world.spec("a1", windows=(StrictWindowSpec("busy-window", 3600, 1),))
        async with repository.session() as holder:
            await holder.execute(text("BEGIN IMMEDIATE"))
            task = asyncio.create_task(
                limits.reserve_strict(
                    attempt_id="busy-attempt",
                    provider="exa",
                    operation=LimitOperation.SEARCH,
                    auth_mode=AuthMode.KEYED,
                    spec=spec,
                )
            )
            try:
                await asyncio.wait_for(blocked.wait(), timeout=5)
                if release_writer:
                    await holder.rollback()
                    reservation = await asyncio.wait_for(task, timeout=5)
                    assert reservation.attempt_id == "busy-attempt"
                else:
                    with pytest.raises(LimitStoreUnavailable) as caught:
                        await asyncio.wait_for(task, timeout=5)
                    assert isinstance(caught.value.__cause__, OperationalError)
                    assert len(seen) == 5
            finally:
                await holder.rollback()
                if not task.done():
                    task.cancel()
                await asyncio.gather(task, return_exceptions=True)

        assert seen and all(code == sqlite3.SQLITE_BUSY for code in seen)
        rows = await _attempt_rows(repository, "busy-window")
        admission = await repository.limits.get_admission("busy-attempt")
        if release_writer:
            assert len(rows) == 1
            assert rows[0].units_text == "1"
            assert admission is not None
            # Retrying the same reservation never adds another rate debit.
            await limits.reserve_strict(
                attempt_id="busy-attempt",
                provider="exa",
                operation=LimitOperation.SEARCH,
                auth_mode=AuthMode.KEYED,
                spec=spec,
            )
            assert len(await _attempt_rows(repository, "busy-window")) == 1
        else:
            assert rows == []
            assert admission is None
    finally:
        await repository.close()
