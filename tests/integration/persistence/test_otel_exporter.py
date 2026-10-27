"""SQLite span exporter integration tests: real SDK spans into a real database.

Exercises ``span_record`` + ``SQLiteSpanExporter`` + ``write_trace_spans``
against a migrated SQLite file read back through ``SQLiteRepository``. No live
network; the only I/O is the isolated ``tmp_path`` database.
"""

import json
import sqlite3
from collections.abc import AsyncIterator, Sequence
from datetime import UTC, datetime
from pathlib import Path

import pytest
import pytest_asyncio
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor, SpanExporter, SpanExportResult
from opentelemetry.trace import SpanKind, Status, StatusCode

from freesearch.models.observability import (
    ActorType,
    TraceAttribute,
    TraceOperation,
    TraceOutcome,
    TraceSearchOutput,
    TraceSpanKind,
    TraceSpanRecord,
    TraceStatusCode,
)
from freesearch.persistence.otel_exporter import (
    SQLiteSpanExporter,
    span_record,
    write_trace_spans,
)
from freesearch.persistence.storage import SQLiteRepository
from tests.fixtures.execution import seed_execution_project

_SEARCH_OUTPUT = TraceSearchOutput(
    query="distributed consensus",
    results=[
        {
            "title": "Consensus explained",
            "url": "https://docs.freesearch.dev/consensus",
            "snippet": "Raft and Paxos.",
            "source": "keenable",
            "score": 0.94,
        },
        {
            "title": "Raft vs Paxos",
            "url": "https://docs.freesearch.dev/raft-vs-paxos",
            "snippet": "A practical comparison.",
            "source": "keenable",
            "score": 0.81,
        },
    ],
)


class _CapturingExporter(SpanExporter):
    """In-memory exporter that retains finished spans for direct assertions."""

    def __init__(self) -> None:
        self.spans: list[ReadableSpan] = []

    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        self.spans.extend(spans)
        return SpanExportResult.SUCCESS

    def shutdown(self) -> None:
        return None


@pytest_asyncio.fixture
async def repository(tmp_path: Path) -> AsyncIterator[SQLiteRepository]:
    repo = await SQLiteRepository.open(tmp_path / "exporter.db")
    yield repo
    await repo.close()


def _exporting_tracer(database: Path) -> tuple[TracerProvider, object]:
    provider = TracerProvider(resource=Resource.create({"service.name": "otel-test"}))
    provider.add_span_processor(SimpleSpanProcessor(SQLiteSpanExporter(database)))
    return provider, provider.get_tracer("exporter-test")


def _row_count(database: Path) -> int:
    with sqlite3.connect(database) as connection:
        return int(connection.execute("SELECT COUNT(*) FROM trace_spans").fetchone()[0])


async def test_exported_root_and_children_round_trip(
    repository: SQLiteRepository, tmp_path: Path
) -> None:
    from uuid import UUID

    owner = UUID("33333333-3333-4333-8333-333333333333")
    attribution = await seed_execution_project(repository)
    ownership = {
        TraceAttribute.SAMPLED: True,
        TraceAttribute.CAPTURE_PAYLOAD: True,
        TraceAttribute.PROJECT_ID: str(attribution.project_id),
        TraceAttribute.ACTOR_TYPE: attribution.actor_type.value,
        TraceAttribute.ACTOR_ID: str(attribution.actor_id),
    }
    database = repository.database_path
    _provider, tracer = _exporting_tracer(database)
    # Capture finished spans in-memory so the test can assert the
    # span_record projection directly, alongside the persisted SQL row and
    # the repository detail read.
    capture = _CapturingExporter()
    _provider.add_span_processor(SimpleSpanProcessor(capture))

    with tracer.start_as_current_span(
        "POST /search",
        kind=SpanKind.SERVER,
        attributes={
            "freesearch.operation.name": "search",
            "freesearch.provider.name": "keenable",
            "freesearch.request.query": "distributed consensus",
            "freesearch.response.result_count": 2,
            "freesearch.response.output_json": _SEARCH_OUTPUT.model_dump_json(),
            TraceAttribute.USER_ID: str(owner),
            **ownership,
        },
    ):
        with tracer.start_as_current_span(
            "freesearch.backend", kind=SpanKind.INTERNAL, attributes=dict(ownership)
        ):
            pass
        with tracer.start_as_current_span(
            "freesearch.provider",
            kind=SpanKind.CLIENT,
            attributes={
                "error.type": "http_error",
                # RED (PLAN §6.1 item 2): the child provider span carries its
                # own identity, distinct from the root summary provider.
                "freesearch.provider.name": "brave",
                **ownership,
            },
        ) as failed:
            failed.record_exception(RuntimeError("HTTP 502"))
            failed.set_status(Status(StatusCode.ERROR))

    # RED: span_record must project the child span's own provider attribute
    # instead of dropping it (exporter only projects provider for the root).
    child_finished = next(span for span in capture.spans if span.name == "freesearch.provider")
    assert span_record(child_finished).provider == "brave"

    # RED: the persisted child row must preserve the child provider
    # independently of the root summary provider.
    with sqlite3.connect(database) as connection:
        child_row = connection.execute(
            "SELECT provider FROM trace_spans WHERE name = 'freesearch.provider'"
        ).fetchone()
        root_row = connection.execute(
            "SELECT provider FROM trace_spans WHERE parent_span_id IS NULL"
        ).fetchone()
    assert child_row[0] == "brave"
    assert root_row[0] == "keenable"

    summaries = await repository.list_trace_summaries(user_id=owner)
    assert len(summaries) == 1
    summary = summaries[0]
    assert summary.user_id == str(owner)
    assert summary.operation is TraceOperation.SEARCH
    assert summary.provider == "keenable"
    assert summary.outcome is TraceOutcome.SUCCESS
    assert summary.result_count == 2

    detail = await repository.get_trace(summary.trace_id, user_id=owner)
    assert detail is not None
    assert detail.user_id == str(owner)
    assert detail.input == "distributed consensus"
    assert isinstance(detail.output, TraceSearchOutput)
    assert [item.title for item in detail.output.results] == [
        "Consensus explained",
        "Raft vs Paxos",
    ]
    assert {span.name for span in detail.spans} == {
        "POST /search",
        "freesearch.backend",
        "freesearch.provider",
    }
    # The detail timeline is stable under (started_at, span_id) ordering even
    # when spans share a microsecond.
    assert [(span.started_at, span.span_id) for span in detail.spans] == sorted(
        [(span.started_at, span.span_id) for span in detail.spans]
    )
    failed_span = next(span for span in detail.spans if span.name == "freesearch.provider")
    assert failed_span.outcome is TraceOutcome.ERROR
    assert failed_span.error is not None
    assert failed_span.error.type == "http_error"
    assert [event.name for event in failed_span.events] == ["exception"]
    # RED: the repository detail must preserve the child provider identity
    # independently of the root summary provider.
    assert failed_span.provider == "brave"
    assert summary.provider == "keenable"


async def test_root_content_columns_stored_once_not_in_attributes_json(
    repository: SQLiteRepository,
) -> None:
    database = repository.database_path
    attribution = await seed_execution_project(repository)
    _provider, tracer = _exporting_tracer(database)

    with tracer.start_as_current_span(
        "POST /search",
        kind=SpanKind.SERVER,
        attributes={
            "freesearch.operation.name": "search",
            "freesearch.provider.name": "keenable",
            "freesearch.request.query": "stored-query",
            "freesearch.response.result_count": 1,
            "freesearch.response.output_json": _SEARCH_OUTPUT.model_dump_json(),
            TraceAttribute.SAMPLED: True,
            TraceAttribute.CAPTURE_PAYLOAD: True,
            TraceAttribute.PROJECT_ID: str(attribution.project_id),
            TraceAttribute.ACTOR_TYPE: attribution.actor_type.value,
            TraceAttribute.ACTOR_ID: str(attribution.actor_id),
        },
    ):
        pass

    with sqlite3.connect(database) as connection:
        row = connection.execute(
            "SELECT input_text, output_json, attributes_json, events_json, resource_json"
            " FROM trace_spans WHERE parent_span_id IS NULL"
        ).fetchone()

    assert row[0] == "stored-query"
    assert json.loads(row[1])["kind"] == "search_results"
    attributes = json.loads(row[2])
    assert "freesearch.request.query" not in attributes
    assert "freesearch.response.output_json" not in attributes
    assert "freesearch.provider.name" in attributes
    assert isinstance(json.loads(row[3]), list)
    assert json.loads(row[4])["service.name"] == "otel-test"


async def test_span_upsert_is_idempotent(repository: SQLiteRepository) -> None:
    from uuid import UUID

    owner = UUID("44444444-4444-4444-8444-444444444444")
    started = datetime(2026, 9, 29, 9, 15, tzinfo=UTC)
    ended = datetime(2026, 9, 29, 9, 15, 0, 248000, tzinfo=UTC)
    records = [
        TraceSpanRecord(
            project_id=UUID("00000000-0000-4000-8000-0000000000aa"),
            actor_type=ActorType.HUMAN,
            actor_id=UUID("00000000-0000-4000-8000-0000000000bb"),
            span_id="aa00000000000001",
            trace_id="e" * 32,
            name="POST /search",
            kind=TraceSpanKind.SERVER,
            started_at=started,
            ended_at=ended,
            duration_ms=248,
            operation=TraceOperation.SEARCH,
            provider="keenable",
            input_text="consensus",
            result_count=1,
            user_id=str(owner),
        ),
        TraceSpanRecord(
            project_id=UUID("00000000-0000-4000-8000-0000000000aa"),
            actor_type=ActorType.HUMAN,
            actor_id=UUID("00000000-0000-4000-8000-0000000000bb"),
            span_id="bb00000000000002",
            trace_id="e" * 32,
            parent_span_id="aa00000000000001",
            name="freesearch.backend",
            kind=TraceSpanKind.INTERNAL,
            started_at=started,
            ended_at=ended,
            duration_ms=240,
        ),
    ]

    write_trace_spans(repository.database_path, records)
    assert _row_count(repository.database_path) == 2
    write_trace_spans(repository.database_path, records)

    assert _row_count(repository.database_path) == 2
    detail = await repository.get_trace("e" * 32, user_id=owner)
    assert detail is not None
    assert detail.user_id == str(owner)
    assert [span.span_id for span in detail.spans] == [
        "aa00000000000001",
        "bb00000000000002",
    ]


async def test_null_owner_rows_stay_intact_but_invisible(
    repository: SQLiteRepository,
) -> None:
    from uuid import UUID

    owner = UUID("55555555-5555-4555-8555-555555555555")
    started = datetime(2026, 9, 29, 9, 15, tzinfo=UTC)
    write_trace_spans(
        repository.database_path,
        [
            TraceSpanRecord(
                project_id=UUID("00000000-0000-4000-8000-0000000000aa"),
                actor_type=ActorType.HUMAN,
                actor_id=UUID("00000000-0000-4000-8000-0000000000bb"),
                span_id="cc00000000000003",
                trace_id="d" * 32,
                name="POST /search",
                kind=TraceSpanKind.SERVER,
                started_at=started,
                ended_at=started,
                duration_ms=5,
                operation=TraceOperation.SEARCH,
                provider="keenable",
            )
        ],
    )

    assert _row_count(repository.database_path) == 1
    assert await repository.list_trace_summaries(user_id=owner) == []
    assert await repository.get_trace("d" * 32, user_id=owner) is None
    with sqlite3.connect(repository.database_path) as connection:
        row = connection.execute(
            "SELECT trace_id, user_id FROM trace_spans WHERE parent_span_id IS NULL"
        ).fetchone()
    assert row[0] == "d" * 32
    assert row[1] is None


async def test_write_trace_spans_with_no_records_is_a_noop(
    repository: SQLiteRepository,
) -> None:
    write_trace_spans(repository.database_path, [])

    assert _row_count(repository.database_path) == 0


async def test_span_record_maps_status_kind_and_duration() -> None:
    capture = _CapturingExporter()
    capture_provider = TracerProvider()
    capture_provider.add_span_processor(SimpleSpanProcessor(capture))
    tracer = capture_provider.get_tracer("map-test")
    with tracer.start_as_current_span("freesearch.backend", kind=SpanKind.INTERNAL):
        pass

    (finished,) = capture.spans
    record = span_record(finished)

    assert record.name == "freesearch.backend"
    assert record.kind is TraceSpanKind.INTERNAL
    assert record.status_code is TraceStatusCode.UNSET
    assert record.outcome is TraceOutcome.SUCCESS
    assert len(record.span_id) == 16
    assert len(record.trace_id) == 32
    assert record.duration_ms >= 0
    assert record.ended_at >= record.started_at


def test_export_failure_returns_failure_without_raising(tmp_path: Path) -> None:
    exporter = SQLiteSpanExporter(tmp_path)

    capture = _CapturingExporter()
    capture_provider = TracerProvider()
    capture_provider.add_span_processor(SimpleSpanProcessor(capture))
    with capture_provider.get_tracer("failure-test").start_as_current_span(
        "work",
        attributes={
            TraceAttribute.SAMPLED: True,
            TraceAttribute.CAPTURE_PAYLOAD: False,
            "freesearch.project.id": "00000000-0000-4000-8000-0000000000aa",
            "freesearch.actor.type": "human",
            "freesearch.actor.id": "00000000-0000-4000-8000-0000000000bb",
        },
    ):
        pass

    result = exporter.export(capture.spans)

    assert result is SpanExportResult.FAILURE


def test_exporter_shutdown_releases_nothing(tmp_path: Path) -> None:
    assert SQLiteSpanExporter(tmp_path / "shutdown.db").shutdown() is None


@pytest.mark.parametrize("redaction", ["standard", "strict"])
async def test_capture_time_policy_survives_settings_edit_and_separate_child_batches(
    repository: SQLiteRepository,
    redaction: str,
) -> None:
    """Finished children must never be re-evaluated against flush-time settings."""
    from freesearch.infrastructure.observability import (
        OtelObservability,
        SpanKindName,
        _AttributionSpanProcessor,
        bind_execution_attribution,
        bind_trace_capture,
        use_observability,
    )
    from freesearch.models.projects import ProjectTracePolicy, TraceDetailPolicy
    from tests.fixtures.execution import allow_full_trace_capture

    attribution = await seed_execution_project(repository)
    provider = TracerProvider()
    capture = _CapturingExporter()
    provider.add_span_processor(_AttributionSpanProcessor())
    provider.add_span_processor(SimpleSpanProcessor(capture))
    runtime = OtelObservability(provider.get_tracer("capture-time"), provider)
    exporter = SQLiteSpanExporter(repository.database_path)
    marker = "PRIVATE_PROVIDER_QUERY_SHOULD_NEVER_BUFFER"
    try:
        with use_observability(runtime):
            bind_execution_attribution(attribution)
            bind_trace_capture(
                ProjectTracePolicy(detail=TraceDetailPolicy.METADATA, payload_redaction=redaction)
            )
            with runtime.span("POST /search", kind=SpanKindName.SERVER):
                with runtime.span("freesearch.provider") as child:
                    child.add_event(
                        "freesearch.provider.request",
                        {"query": marker, "url": marker, "results": marker, "result_count": 1},
                    )
                    child.record_exception(RuntimeError(marker))
                assert exporter.export(capture.spans[:1]) is SpanExportResult.SUCCESS
                await allow_full_trace_capture(repository)
                with runtime.span("freesearch.backend") as child:
                    child.set_attributes({TraceAttribute.REQUEST_QUERY: marker})
            assert exporter.export(capture.spans[1:]) is SpanExportResult.SUCCESS
        assert len(capture.spans) == 3
        for span in capture.spans:
            assert span.attributes[TraceAttribute.SAMPLED] is True
            assert span.attributes[TraceAttribute.CAPTURE_PAYLOAD] is False
            assert marker not in span.to_json()
        with sqlite3.connect(repository.database_path) as connection:
            rows = connection.execute(
                "SELECT input_text, output_json, attributes_json, events_json, status_message"
                " FROM trace_spans"
            ).fetchall()
        assert len(rows) == 3
        assert marker not in str(rows)
        assert all(row[0] is None and row[1] is None and row[4] is None for row in rows)
        # Only a new trace can use the newly allowed FULL policy.
        from uuid import uuid4

        from freesearch.models.projects import HumanPrincipal
        from freesearch.services.authorization import ScopedAuthorizationService
        from freesearch.services.settings import project_trace_policy

        context = await ScopedAuthorizationService(repository).resolve_project_context(
            HumanPrincipal(user_id=attribution.actor_id, session_id=uuid4()),
            attribution.project_id,
        )
        assert context is not None
        next_policy = await project_trace_policy(repository, context)
        assert next_policy.captures_payload is True
        credential_marker = "NEVER_PERSIST_NESTED_CREDENTIAL"
        with use_observability(runtime):
            bind_execution_attribution(attribution)
            bind_trace_capture(next_policy)
            with runtime.span("POST /search", kind=SpanKindName.SERVER) as root:
                root.set_attributes({TraceAttribute.REQUEST_QUERY: "allowed next query"})
                root.add_event(
                    "freesearch.provider.response",
                    {
                        "results": [{"title": "allowed", "api_key": credential_marker}],
                    },
                )
                root.record_exception(RuntimeError(credential_marker))
        assert exporter.export(capture.spans[3:]) is SpanExportResult.SUCCESS
        assert credential_marker not in capture.spans[3].to_json()
        with sqlite3.connect(repository.database_path) as connection:
            rows = connection.execute(
                "SELECT input_text, attributes_json, events_json, status_message FROM trace_spans"
            ).fetchall()
        assert len(rows) == 4
        assert sum(row[0] == "allowed next query" for row in rows) == 1
        assert credential_marker not in str(rows)
    finally:
        runtime.shutdown()


async def test_unstamped_or_unsampled_spans_are_never_persisted(
    repository: SQLiteRepository,
) -> None:
    from freesearch.infrastructure.observability import (
        OtelObservability,
        _AttributionSpanProcessor,
        bind_execution_attribution,
        bind_trace_capture,
        use_observability,
    )
    from freesearch.models.projects import ProjectTracePolicy

    attribution = await seed_execution_project(repository)
    provider = TracerProvider()
    capture = _CapturingExporter()
    provider.add_span_processor(_AttributionSpanProcessor())
    provider.add_span_processor(SimpleSpanProcessor(capture))
    runtime = OtelObservability(provider.get_tracer("unsampled"), provider)
    try:
        for policy in (None, ProjectTracePolicy(sampling_rate=0.0)):
            with use_observability(runtime):
                bind_execution_attribution(attribution)
                if policy is not None:
                    bind_trace_capture(policy)
                with runtime.span("freesearch.provider"):
                    pass
        assert len(capture.spans) == 2
        assert TraceAttribute.SAMPLED not in capture.spans[0].attributes
        assert capture.spans[1].attributes[TraceAttribute.SAMPLED] is False
        assert (
            SQLiteSpanExporter(repository.database_path).export(capture.spans)
            is SpanExportResult.SUCCESS
        )
        assert _row_count(repository.database_path) == 0
    finally:
        runtime.shutdown()


def test_concurrent_export_failure_cleanup_discards_failed_connection_without_lock_gap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Batch A failure cleanup must discard connection while holding lock so Batch B cannot
    commit partial rows.

    Batch A inserts 1 row and then fails on the second row.
    Batch B tries to export concurrently during Batch A's failure handling.
    Assert Batch A returns FAILURE, Batch B returns SUCCESS.
    Assert ZERO rows from Batch A persist and ONLY Batch B rows persist in SQLite.
    Assert exporter remains usable after failure and shuts down cleanly, including
    post-shutdown contract.
    """
    import threading
    from typing import Any
    from uuid import uuid4

    from freesearch.persistence.database_migrations import upgrade_database
    from freesearch.persistence.otel_exporter import _INSERT, _write_rows

    class DeterministicLockHandoff:
        """Controlled lock scheduling wrapper guaranteeing handoff order.

        Under an implementation with a failure-cleanup lock gap, Batch A
        releases the lock after failure and then reacquires it for cleanup.
        This wrapper schedules Thread B to acquire the lock during that gap before
        Thread A can reacquire it.
        Under the corrected implementation, Batch A discards the connection
        inside its original critical section before releasing the lock, so Thread B
        always acquires the lock after connection discard.
        """

        def __init__(self) -> None:
            self._real_lock = threading.Lock()
            self._thread_a: threading.Thread | None = None
            self._thread_b: threading.Thread | None = None
            self.b_attempting_acquire = threading.Event()
            self.b_completed = threading.Event()
            self._a_release_count = 0

        def bind_threads(self, thread_a: threading.Thread, thread_b: threading.Thread) -> None:
            self._thread_a = thread_a
            self._thread_b = thread_b

        def acquire(self, blocking: bool = True, timeout: float = -1.0) -> bool:
            current = threading.current_thread()
            if current is self._thread_b:
                self.b_attempting_acquire.set()
            elif current is self._thread_a and self._a_release_count > 0:
                waited = self.b_completed.wait(timeout=10.0 if timeout < 0 else timeout)
                assert waited, (
                    "Deadlock guard: Thread B did not complete before Thread A reacquired"
                )

            return self._real_lock.acquire(blocking=blocking, timeout=timeout)

        def release(self) -> None:
            current = threading.current_thread()
            if current is self._thread_a:
                self._a_release_count += 1
            elif current is self._thread_b:
                self.b_completed.set()
            self._real_lock.release()

        def __enter__(self) -> bool:
            return self.acquire()

        def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
            self.release()

    db_path = tmp_path / "concurrent_failure.db"
    upgrade_database(db_path)
    exporter = SQLiteSpanExporter(db_path)

    handoff_lock = DeterministicLockHandoff()
    exporter._lock = handoff_lock

    provider = TracerProvider()
    capture = _CapturingExporter()
    provider.add_span_processor(SimpleSpanProcessor(capture))
    tracer = provider.get_tracer("concurrency-test")

    project_id = str(uuid4())
    actor_id = str(uuid4())
    common_attrs = {
        TraceAttribute.SAMPLED: True,
        TraceAttribute.CAPTURE_PAYLOAD: False,
        TraceAttribute.PROJECT_ID: project_id,
        TraceAttribute.ACTOR_TYPE: "human",
        TraceAttribute.ACTOR_ID: actor_id,
    }

    # Generate 2 spans for Batch A, 1 span for Batch B, 1 span for Batch C, 1 span for Batch D
    with tracer.start_as_current_span("span_a1", attributes=common_attrs):
        pass
    with tracer.start_as_current_span("span_a2", attributes=common_attrs):
        pass
    with tracer.start_as_current_span("span_b1", attributes=common_attrs):
        pass
    with tracer.start_as_current_span("span_c1", attributes=common_attrs):
        pass
    with tracer.start_as_current_span("span_d1", attributes=common_attrs):
        pass

    spans_a = capture.spans[0:2]
    spans_b = capture.spans[2:3]
    spans_c = capture.spans[3:4]
    spans_d = capture.spans[4:5]

    a_inserted = threading.Event()
    original_write_rows = _write_rows
    call_count = 0

    def intercepted_write_rows(
        connection: sqlite3.Connection, rows: Sequence[dict[str, Any]]
    ) -> None:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            # Batch A: Insert the first row, leaving it uncommitted in connection
            connection.execute(_INSERT, rows[0])
            a_inserted.set()
            # Wait until Thread B is attempting to acquire exporter's lock
            waited = handoff_lock.b_attempting_acquire.wait(timeout=5.0)
            assert waited, "Thread B did not attempt lock acquisition"
            raise RuntimeError("simulated Batch A failure on second row")
        original_write_rows(connection, rows)

    monkeypatch.setattr("freesearch.persistence.otel_exporter._write_rows", intercepted_write_rows)

    res_a: list[SpanExportResult] = []
    res_b: list[SpanExportResult] = []

    def run_a() -> None:
        res_a.append(exporter.export(spans_a))

    def run_b() -> None:
        waited = a_inserted.wait(timeout=5.0)
        assert waited, "Thread A did not insert first row"
        res_b.append(exporter.export(spans_b))

    thread_a = threading.Thread(target=run_a)
    thread_b = threading.Thread(target=run_b)
    handoff_lock.bind_threads(thread_a, thread_b)

    thread_a.start()
    thread_b.start()

    thread_a.join(timeout=10.0)
    thread_b.join(timeout=10.0)

    assert not thread_a.is_alive()
    assert not thread_b.is_alive()

    assert res_a == [SpanExportResult.FAILURE]
    assert res_b == [SpanExportResult.SUCCESS]

    with sqlite3.connect(db_path) as conn:
        persisted_rows = conn.execute("SELECT span_id FROM trace_spans").fetchall()

    persisted_span_ids = {row[0] for row in persisted_rows}
    a_span_ids = {span_record(s).span_id for s in spans_a}
    b_span_ids = {span_record(s).span_id for s in spans_b}

    # ZERO rows from Batch A must persist!
    assert persisted_span_ids.intersection(a_span_ids) == set()
    # ONLY Batch B rows must persist from the concurrent runs!
    assert b_span_ids.issubset(persisted_span_ids)
    assert len(persisted_span_ids) == len(b_span_ids)

    # Exporter must remain usable after failure
    res_c = exporter.export(spans_c)
    assert res_c is SpanExportResult.SUCCESS

    with sqlite3.connect(db_path) as conn:
        c_count = conn.execute(
            "SELECT COUNT(*) FROM trace_spans WHERE span_id = ?",
            (span_record(spans_c[0]).span_id,),
        ).fetchone()[0]
    assert c_count == 1

    # Clean shutdown
    exporter.shutdown()

    # Post-shutdown usability contract
    res_d = exporter.export(spans_d)
    assert res_d is SpanExportResult.SUCCESS
    with sqlite3.connect(db_path) as conn:
        d_count = conn.execute(
            "SELECT COUNT(*) FROM trace_spans WHERE span_id = ?",
            (span_record(spans_d[0]).span_id,),
        ).fetchone()[0]
    assert d_count == 1

    exporter.shutdown()
