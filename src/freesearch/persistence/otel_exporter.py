"""SQLite span exporter: the database half of the exporter seam.

The exporter maps finished OpenTelemetry spans onto the ``trace_spans`` table
(one row per span; root rows double as the Activity summary). It is deliberately
the only place that knows both OTel span objects and the trace schema, so a
future OTLP/Langfuse/LangSmith exporter is a sibling class registered in
:func:`freesearch.infrastructure.observability.build_span_processors` rather
than a change to routes, services, or adapters.

Export is failure-safe by contract: a locked or unwritable database reports
``SpanExportResult.FAILURE`` and is logged without payload — it never fails (or
even slows) the user request being observed beyond the bounded flush wait. Each
batch uses one short transaction with the repository's busy-timeout discipline,
and rows are upserted by ``span_id`` so a re-export cannot duplicate a span.
"""

import json
import logging
import sqlite3
from collections.abc import Sequence
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.sdk.trace.export import SpanExporter, SpanExportResult
from opentelemetry.trace import SpanKind, StatusCode

from freesearch.models.observability import (
    TraceAttribute,
    TraceEventDetail,
    TraceOperation,
    TraceOutcome,
    TraceSpanKind,
    TraceSpanRecord,
    TraceStatusCode,
    trace_outcome_for,
)
from freesearch.persistence.database_migrations import absolute_database_path

logger = logging.getLogger(__name__)

_SQLITE_TIMEOUT_SECONDS = 30.0

_KINDS: dict[SpanKind, TraceSpanKind] = {
    SpanKind.INTERNAL: TraceSpanKind.INTERNAL,
    SpanKind.SERVER: TraceSpanKind.SERVER,
    SpanKind.CLIENT: TraceSpanKind.CLIENT,
    SpanKind.PRODUCER: TraceSpanKind.INTERNAL,
    SpanKind.CONSUMER: TraceSpanKind.INTERNAL,
}

_STATUS_CODES: dict[StatusCode, TraceStatusCode] = {
    StatusCode.UNSET: TraceStatusCode.UNSET,
    StatusCode.OK: TraceStatusCode.OK,
    StatusCode.ERROR: TraceStatusCode.ERROR,
}

# Content-bearing attributes are projected into their own summary columns; they
# are dropped from ``attributes_json`` so one fetch payload is stored once.
_CONTENT_ATTRIBUTES = frozenset(
    {
        TraceAttribute.REQUEST_QUERY,
        TraceAttribute.REQUEST_URL,
        TraceAttribute.RESPONSE_OUTPUT_JSON,
    }
)

_INSERT = """
INSERT OR REPLACE INTO trace_spans (
    span_id, trace_id, parent_span_id, name, kind, started_at, ended_at,
    duration_ms, status_code, status_message, outcome, error_type, operation,
    provider, input_text, output_json, result_count, attributes_json,
    events_json, resource_json
) VALUES (
    :span_id, :trace_id, :parent_span_id, :name, :kind, :started_at, :ended_at,
    :duration_ms, :status_code, :status_message, :outcome, :error_type,
    :operation, :provider, :input_text, :output_json, :result_count,
    :attributes_json, :events_json, :resource_json
)
"""


def _timestamp(nanoseconds: int) -> datetime:
    """Convert an OTel nanosecond timestamp into an aware UTC datetime."""

    return datetime.fromtimestamp(nanoseconds / 1_000_000_000, tz=UTC)


def _duration_ms(started: int, ended: int) -> int:
    """Return a non-negative whole-millisecond duration, rounding up sub-ms spans."""

    return max(0, round((ended - started) / 1_000_000))


def _jsonable(value: object) -> Any:
    """Coerce an OTel attribute value into something JSON can carry."""

    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    return str(value)


def _attributes(span: ReadableSpan) -> dict[str, Any]:
    """Return the span's attributes as JSON-safe primitives."""

    return {str(key): _jsonable(value) for key, value in dict(span.attributes or {}).items()}


def _events(span: ReadableSpan) -> list[TraceEventDetail]:
    """Project span events (attributes included) into the stored event list."""

    return [
        TraceEventDetail(
            name=event.name,
            timestamp=_timestamp(event.timestamp),
            attributes={
                str(key): _jsonable(value) for key, value in dict(event.attributes or {}).items()
            },
        )
        for event in span.events or ()
    ]


def _operation(raw: object) -> TraceOperation | None:
    """Parse the operation attribute, tolerating unknown future operations."""

    try:
        return TraceOperation(str(raw)) if raw else None
    except ValueError:
        return None


def _resource(span: ReadableSpan) -> dict[str, Any]:
    """Project the (secret-free) resource attributes of the span's provider."""

    attributes = getattr(span.resource, "attributes", None) or {}
    return {str(key): _jsonable(value) for key, value in dict(attributes).items()}


def _error_type(span: ReadableSpan) -> str | None:
    value = (span.attributes or {}).get(TraceAttribute.ERROR_TYPE)
    return str(value) if value else None


def _span_kind(span: ReadableSpan) -> TraceSpanKind:
    return _KINDS.get(span.kind, TraceSpanKind.INTERNAL)


def _outcome(
    status: TraceStatusCode, attributes: dict[str, Any], *, is_root: bool, http_status: int | None
) -> TraceOutcome:
    """Project the span (or the whole request) onto ``success|partial|error``.

    A root span counts as failed when it recorded an error, carries a
    low-cardinality ``error.type``, or answered with an HTTP error status — a
    handled failure (``all providers failed``) must not be labelled successful.
    """

    if status is TraceStatusCode.ERROR or attributes.get(TraceAttribute.ERROR_TYPE):
        return TraceOutcome.ERROR
    if not is_root:
        return TraceOutcome.SUCCESS
    if http_status is not None and http_status >= 400:
        return TraceOutcome.ERROR
    return trace_outcome_for(
        status_code=status, partial=bool(attributes.get(TraceAttribute.RESPONSE_PARTIAL))
    )


def _http_status(attributes: dict[str, Any]) -> int | None:
    value = attributes.get(TraceAttribute.HTTP_RESPONSE_STATUS_CODE)
    return value if isinstance(value, int) else None


def _status_message(span: ReadableSpan, attributes: dict[str, Any]) -> str | None:
    """Prefer the OTel status description, else the annotated failure message."""

    message = attributes.get(TraceAttribute.ERROR_MESSAGE)
    if isinstance(message, str) and message:
        return message
    return span.status.description


def _summary_attributes(attributes: dict[str, Any], *, is_root: bool) -> dict[str, Any]:
    """Return the root-summary column values (empty for child spans)."""

    if not is_root:
        return {}
    input_text = attributes.get(TraceAttribute.REQUEST_QUERY)
    if input_text is None:
        input_text = attributes.get(TraceAttribute.REQUEST_URL)
    operation = attributes.get(TraceAttribute.OPERATION)
    output = attributes.get(TraceAttribute.RESPONSE_OUTPUT_JSON)
    result_count = attributes.get(TraceAttribute.RESPONSE_RESULT_COUNT)
    return {
        "operation": str(operation) if operation else None,
        "provider": (
            str(attributes[TraceAttribute.PROVIDER])
            if attributes.get(TraceAttribute.PROVIDER)
            else None
        ),
        "input_text": str(input_text) if input_text is not None else None,
        "output_json": output if isinstance(output, str) else None,
        "result_count": int(result_count) if isinstance(result_count, (int, float)) else None,
    }


def span_record(span: ReadableSpan) -> TraceSpanRecord:
    """Project one finished OTel span into its persisted row."""

    started = span.start_time or 0
    ended = span.end_time or started
    attributes = _attributes(span)
    context = span.context
    status = _STATUS_CODES.get(span.status.status_code, TraceStatusCode.UNSET)
    is_root = span.parent is None
    summary = _summary_attributes(attributes, is_root=is_root)
    return TraceSpanRecord(
        span_id=format(context.span_id, "016x"),
        trace_id=format(context.trace_id, "032x"),
        parent_span_id=format(span.parent.span_id, "016x") if span.parent else None,
        name=span.name,
        kind=_span_kind(span),
        started_at=_timestamp(started),
        ended_at=_timestamp(ended),
        duration_ms=_duration_ms(started, ended),
        status_code=status,
        status_message=_status_message(span, attributes),
        outcome=_outcome(status, attributes, is_root=is_root, http_status=_http_status(attributes)),
        error_type=_error_type(span),
        operation=_operation(summary.get("operation")),
        provider=summary.get("provider"),
        input_text=summary.get("input_text"),
        output_json=summary.get("output_json"),
        result_count=summary.get("result_count"),
        attributes={
            key: value
            for key, value in attributes.items()
            if not (is_root and key in _CONTENT_ATTRIBUTES)
        },
        events=_events(span),
        resource=_resource(span),
    )


_TIMESTAMP_FORMAT = "%Y-%m-%dT%H:%M:%S.%f+00:00"


def _stored_timestamp(value: datetime) -> str:
    """Render one instant as a fixed-width UTC string.

    The stored columns are read with lexicographic ordering, so every timestamp
    must have the same shape: always microseconds, always a ``+00:00`` offset.
    Without that, ``...T09:15:00Z`` sorts after ``...T09:15:00.004000Z``
    (``.`` < ``Z``) and a stage timeline would come back out of order.
    """

    return value.astimezone(UTC).strftime(_TIMESTAMP_FORMAT)


def _row(record: TraceSpanRecord) -> dict[str, Any]:
    """Render one record as SQL parameters with stable JSON serialization."""

    payload = record.model_dump(mode="json")
    payload["started_at"] = _stored_timestamp(record.started_at)
    payload["ended_at"] = _stored_timestamp(record.ended_at)
    payload["attributes_json"] = json.dumps(
        record.attributes, separators=(",", ":"), allow_nan=False, default=str
    )
    payload["events_json"] = json.dumps(
        [
            {
                "name": event.name,
                "timestamp": _stored_timestamp(event.timestamp),
                "attributes": event.attributes,
            }
            for event in record.events
        ],
        separators=(",", ":"),
        allow_nan=False,
        default=str,
    )
    payload["resource_json"] = json.dumps(
        record.resource, separators=(",", ":"), allow_nan=False, default=str
    )
    payload["operation"] = record.operation.value if record.operation else None
    return payload


def write_trace_spans(database: Path, records: Sequence[TraceSpanRecord]) -> None:
    """Upsert span rows in one short transaction (also the fixture seed path).

    The connection is closed explicitly: exports run on the SDK's batch thread,
    so a leaked handle would keep the database file locked (and on Windows block
    its owner from removing it).
    """

    if not records:
        return
    rows = [_row(record) for record in records]
    with closing(sqlite3.connect(database, timeout=_SQLITE_TIMEOUT_SECONDS)) as connection:
        connection.execute("PRAGMA busy_timeout = 30000")
        connection.executemany(_INSERT, rows)
        connection.commit()


class SQLiteSpanExporter(SpanExporter):
    """Persist finished spans into the local ``trace_spans`` table."""

    def __init__(self, database: Path) -> None:
        """Resolve the trace database once so exports cannot retarget it."""

        self._database = absolute_database_path(database)

    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        """Write one batch; failures are reported, never raised."""

        try:
            write_trace_spans(self._database, [span_record(span) for span in spans])
        except Exception as error:
            logger.warning(
                "trace export failed for %d span(s): %s",
                len(spans),
                type(error).__name__,
                exc_info=False,
            )
            return SpanExportResult.FAILURE
        return SpanExportResult.SUCCESS

    def shutdown(self) -> None:
        """Nothing to release: every batch uses its own short-lived connection."""

        return None


__all__ = ["SQLiteSpanExporter", "span_record", "write_trace_spans"]
