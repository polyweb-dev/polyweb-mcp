"""RetentionRunRepository: every run names one project and stays inside it."""

from __future__ import annotations

import sqlite3
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
import pytest_asyncio

from polyweb.models.schema_enums import RetentionDataClass, RetentionRunStatus
from polyweb.persistence.retention import RetentionRunRepository, StoredRetentionRun
from polyweb.persistence.storage import SQLiteRepository
from tests.fixtures.execution import seed_execution_project

_NOW = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)
_CUTOFF = _NOW - timedelta(days=30)


@dataclass(frozen=True)
class _World:
    repo: SQLiteRepository
    project_a: UUID
    project_b: UUID


@pytest_asyncio.fixture
async def world(tmp_path: Path) -> AsyncIterator[_World]:
    repo = await SQLiteRepository.open(tmp_path / "retention.db")
    try:
        a = await seed_execution_project(repo, name="A")
        b = await seed_execution_project(repo, user_id=a.actor_id, name="B")
        yield _World(repo, a.project_id, b.project_id)
    finally:
        await repo.close()


async def _start(
    world: _World,
    project_id: UUID,
    data_class: RetentionDataClass = RetentionDataClass.TRACES,
    *,
    now: datetime = _NOW,
) -> StoredRetentionRun:
    async with world.repo.session() as session:
        run = await RetentionRunRepository(session).start(
            project_id=project_id, data_class=data_class, cutoff=_CUTOFF, now=now
        )
        await session.commit()
    return run


def _row(world: _World, run_id: UUID) -> tuple[object, ...]:
    connection = sqlite3.connect(world.repo.database_path)
    try:
        row = connection.execute(
            "SELECT project_id, status, finished_at, deleted_rows FROM retention_runs WHERE id = ?",
            (str(run_id),),
        ).fetchone()
    finally:
        connection.close()
    assert row is not None
    return tuple(row)


async def test_start_records_a_running_run_for_one_project(world: _World) -> None:
    run = await _start(world, world.project_a)

    assert run.project_id == world.project_a
    assert run.data_class is RetentionDataClass.TRACES
    assert run.cutoff == _CUTOFF
    assert run.status is RetentionRunStatus.RUNNING
    assert run.started_at == _NOW
    assert run.finished_at is None
    assert run.error_code is None
    assert _row(world, run.id)[0] == str(world.project_a)


async def test_finish_of_a_foreign_projects_run_returns_false(world: _World) -> None:
    run = await _start(world, world.project_a)
    before = _row(world, run.id)

    async with world.repo.session() as session:
        repository = RetentionRunRepository(session)
        assert (
            await repository.finish(
                project_id=world.project_b,
                run_id=run.id,
                status=RetentionRunStatus.COMPLETED,
                deleted_rows=99,
                now=_NOW + timedelta(minutes=1),
            )
            is False
        )
        assert (
            await repository.finish(
                project_id=world.project_a,
                run_id=uuid4(),
                status=RetentionRunStatus.COMPLETED,
                deleted_rows=1,
                now=_NOW,
            )
            is False
        )
        await session.commit()
    assert _row(world, run.id) == before
    assert before[:3] == (str(world.project_a), "running", None)


async def test_finish_completes_once(world: _World) -> None:
    run = await _start(world, world.project_a)
    finished_at = _NOW + timedelta(minutes=2)

    async with world.repo.session() as session:
        repository = RetentionRunRepository(session)
        assert (
            await repository.finish(
                project_id=world.project_a,
                run_id=run.id,
                status=RetentionRunStatus.COMPLETED,
                deleted_rows=12,
                now=finished_at,
            )
            is True
        )
        assert (
            await repository.finish(
                project_id=world.project_a,
                run_id=run.id,
                status=RetentionRunStatus.FAILED,
                deleted_rows=0,
                error_code="late",
                now=finished_at,
            )
            is False
        )
        await session.commit()
        latest = await repository.latest(
            project_id=world.project_a, data_class=RetentionDataClass.TRACES
        )
    assert latest is not None
    assert latest.status is RetentionRunStatus.COMPLETED
    assert latest.deleted_rows == 12
    assert latest.finished_at == finished_at
    assert latest.error_code is None


async def test_finish_rejects_running_status(world: _World) -> None:
    run = await _start(world, world.project_a)
    async with world.repo.session() as session:
        with pytest.raises(ValueError):
            await RetentionRunRepository(session).finish(
                project_id=world.project_a,
                run_id=run.id,
                status=RetentionRunStatus.RUNNING,
                deleted_rows=0,
                now=_NOW,
            )


async def test_failed_run_keeps_its_error_code(world: _World) -> None:
    run = await _start(world, world.project_a, RetentionDataClass.USAGE)
    async with world.repo.session() as session:
        repository = RetentionRunRepository(session)
        assert await repository.finish(
            project_id=world.project_a,
            run_id=run.id,
            status=RetentionRunStatus.FAILED,
            deleted_rows=0,
            error_code="database_locked",
            now=_NOW,
        )
        await session.commit()
        latest = await repository.latest(
            project_id=world.project_a, data_class=RetentionDataClass.USAGE
        )
    assert latest is not None
    assert latest.status is RetentionRunStatus.FAILED
    assert latest.error_code == "database_locked"


async def test_latest_is_scoped_by_project_and_data_class(world: _World) -> None:
    await _start(world, world.project_a, now=_NOW)
    newest_a = await _start(world, world.project_a, now=_NOW + timedelta(hours=1))
    await _start(world, world.project_a, RetentionDataClass.AUDIT, now=_NOW + timedelta(hours=2))
    newest_b = await _start(world, world.project_b, now=_NOW + timedelta(hours=3))

    async with world.repo.session() as session:
        repository = RetentionRunRepository(session)
        latest_a = await repository.latest(
            project_id=world.project_a, data_class=RetentionDataClass.TRACES
        )
        latest_b = await repository.latest(
            project_id=world.project_b, data_class=RetentionDataClass.TRACES
        )
        latest_b_usage = await repository.latest(
            project_id=world.project_b, data_class=RetentionDataClass.USAGE
        )
    assert latest_a is not None and latest_a.id == newest_a.id
    assert latest_b is not None and latest_b.id == newest_b.id
    assert latest_b_usage is None
