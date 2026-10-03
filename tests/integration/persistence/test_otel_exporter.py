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

import pytest_asyncio
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor, SpanExporter, SpanExportResult
from opentelemetry.trace import SpanKind, Status, StatusCode

from freesearch.models.observability import (
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
        },
    ):
        with tracer.start_as_current_span("freesearch.backend", kind=SpanKind.INTERNAL):
            pass
        with tracer.start_as_current_span(
            "freesearch.provider",
            kind=SpanKind.CLIENT,
            attributes={
                "error.type": "http_error",
                # RED (PLAN §6.1 item 2): the child provider span carries its
                # own identity, distinct from the root summary provider.
                "freesearch.provider.name": "brave",
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

    summaries = await repository.list_trace_summaries()
    assert len(summaries) == 1
    summary = summaries[0]
    assert summary.operation is TraceOperation.SEARCH
    assert summary.provider == "keenable"
    assert summary.outcome is TraceOutcome.SUCCESS
    assert summary.result_count == 2

    detail = await repository.get_trace(summary.trace_id)
    assert detail is not None
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
    started = datetime(2026, 9, 29, 9, 15, tzinfo=UTC)
    ended = datetime(2026, 9, 29, 9, 15, 0, 248000, tzinfo=UTC)
    records = [
        TraceSpanRecord(
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
        ),
        TraceSpanRecord(
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
    detail = await repository.get_trace("e" * 32)
    assert detail is not None
    assert [span.span_id for span in detail.spans] == [
        "aa00000000000001",
        "bb00000000000002",
    ]


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
    with capture_provider.get_tracer("failure-test").start_as_current_span("work"):
        pass

    result = exporter.export(capture.spans)

    assert result is SpanExportResult.FAILURE


def test_exporter_shutdown_releases_nothing(tmp_path: Path) -> None:
    assert SQLiteSpanExporter(tmp_path / "shutdown.db").shutdown() is None
