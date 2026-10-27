"""P04: project-owned usage/trace writer tests on a real SQLite repository.

Covers the exporter's skip-unattributed behaviour, the write_trace_spans
attribution gate, record_usage ownership persistence, and two-project span
attribution through the real OTel pipeline.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio

from freesearch.models.contracts import UsageEvent, UsageOperation, UsageStatus
from freesearch.models.observability import (
    ActorType,
    TraceSpanKind,
    TraceSpanRecord,
)
from freesearch.persistence.otel_exporter import write_trace_spans
from freesearch.persistence.storage import SQLiteRepository
from tests.fixtures.execution import seed_execution_project


@pytest_asyncio.fixture
async def repository(tmp_path: Path) -> Any:
    repo = await SQLiteRepository.open(tmp_path / "owned.db")
    yield repo
    await repo.close()


def _record(**overrides: Any) -> TraceSpanRecord:
    base = dict(
        span_id="aa00000000000001",
        trace_id="e" * 32,
        name="POST /search",
        kind=TraceSpanKind.SERVER,
        started_at=datetime(2026, 9, 29, 9, 15, 0, tzinfo=UTC),
        ended_at=datetime(2026, 9, 29, 9, 15, 0, 248000, tzinfo=UTC),
        duration_ms=248,
    )
    base.update(overrides)
    return TraceSpanRecord(**base)


async def test_record_usage_persists_project_actor_and_trace(
    repository: SQLiteRepository,
) -> None:
    attribution = await seed_execution_project(repository)
    await repository.record_usage(
        UsageEvent(
            provider="keenable",
            operation=UsageOperation.SEARCH,
            units=Decimal("2"),
            observed_at=datetime(2026, 4, 2, 13, 0, tzinfo=UTC),
            status=UsageStatus.SUCCESS,
        ),
        attribution=attribution,
        trace_id="a" * 32,
    )
    con = sqlite3.connect(repository.database_path)
    row = con.execute(
        "SELECT project_id, actor_type, actor_id, trace_id FROM usage_events"
    ).fetchone()
    con.close()
    assert row == (
        str(attribution.project_id),
        "human",
        str(attribution.actor_id),
        "a" * 32,
    )


async def test_record_usage_without_attribution_fails(repository: SQLiteRepository) -> None:
    """The attribution keyword is required; a call without it is a TypeError."""
    with pytest.raises(TypeError):
        await repository.record_usage(  # type: ignore[call-arg]
            UsageEvent(
                provider="keenable",
                operation=UsageOperation.SEARCH,
                units=Decimal("1"),
                observed_at=datetime(2026, 4, 2, tzinfo=UTC),
            )
        )


async def test_write_trace_spans_rejects_unattributed_records(
    repository: SQLiteRepository,
) -> None:
    with pytest.raises(ValueError, match="project ownership"):
        write_trace_spans(repository.database_path, [_record()])
    con = sqlite3.connect(repository.database_path)
    count = con.execute("SELECT COUNT(*) FROM trace_spans").fetchone()[0]
    con.close()
    assert count == 0


async def test_write_trace_spans_persists_ownership(repository: SQLiteRepository) -> None:
    attribution = await seed_execution_project(repository)
    write_trace_spans(
        repository.database_path,
        [
            _record(
                project_id=attribution.project_id,
                actor_type=ActorType.HUMAN,
                actor_id=attribution.actor_id,
            )
        ],
    )
    con = sqlite3.connect(repository.database_path)
    row = con.execute("SELECT project_id, actor_type, actor_id FROM trace_spans").fetchone()
    con.close()
    assert row == (str(attribution.project_id), "human", str(attribution.actor_id))


async def test_exporter_skips_unattributed_spans_in_a_mixed_batch(
    repository: SQLiteRepository,
) -> None:
    """An unattributed span is dropped while attributed siblings persist."""
    from freesearch.infrastructure.observability import (
        bind_execution_attribution,
        bind_trace_capture,
        build_observability,
        use_observability,
    )
    from freesearch.models.projects import ProjectTracePolicy
    from tests.fixtures.auth import test_settings

    attribution = await seed_execution_project(repository)
    runtime = build_observability(test_settings(), database=repository.database_path)

    with use_observability(runtime):
        bind_execution_attribution(attribution)
        bind_trace_capture(ProjectTracePolicy())
        with runtime.span("attributed-span"):
            pass
    # A fresh request cell with no bound attribution -> the span is exported
    # without ownership and the exporter must skip it.
    with use_observability(runtime):
        bind_trace_capture(ProjectTracePolicy())
        with runtime.span("unattributed-span"):
            pass
    assert runtime.force_flush()

    con = sqlite3.connect(repository.database_path)
    names = {r[0] for r in con.execute("SELECT name FROM trace_spans")}
    con.close()
    assert "attributed-span" in names
    assert "unattributed-span" not in names
    runtime.shutdown()


async def test_concurrent_two_project_spans_stay_attributed(
    repository: SQLiteRepository,
) -> None:
    """Two concurrently bound cells never leak ownership into each other's spans."""
    import asyncio

    from freesearch.infrastructure.observability import (
        bind_execution_attribution,
        bind_trace_capture,
        build_observability,
        use_observability,
    )
    from freesearch.models.projects import ProjectTracePolicy
    from tests.fixtures.auth import test_settings

    attr_a = await seed_execution_project(repository, name="A")
    attr_b = await seed_execution_project(repository, name="B")
    runtime = build_observability(test_settings(), database=repository.database_path)

    async def run_one(attr: Any, label: str) -> None:
        with use_observability(runtime):
            bind_execution_attribution(attr)
            bind_trace_capture(ProjectTracePolicy())
            with runtime.span(label):
                await asyncio.sleep(0.01)

    await asyncio.gather(
        *(run_one(attr_a, f"a-{i}") for i in range(3)),
        *(run_one(attr_b, f"b-{i}") for i in range(3)),
    )
    assert runtime.force_flush()

    con = sqlite3.connect(repository.database_path)
    rows = con.execute("SELECT name, project_id, actor_id FROM trace_spans").fetchall()
    con.close()
    assert len(rows) == 6
    for name, project_id, actor_id in rows:
        expected = attr_a if name.startswith("a-") else attr_b
        assert project_id == str(expected.project_id)
        assert actor_id == str(expected.actor_id)
    runtime.shutdown()
