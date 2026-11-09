"""SQLite span exporter: the database half of the exporter seam.

The exporter maps finished OpenTelemetry spans onto the ``trace_spans`` table
(one row per span; root rows double as the Activity summary). It is deliberately
the only place that knows both OTel span objects and the trace schema, so a
future OTLP/Langfuse/LangSmith exporter is a sibling class registered in
:func:`polyweb.infrastructure.observability.build_span_processors` rather
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
import threading
import weakref
from collections.abc import Sequence
from contextlib import closing, suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.sdk.trace.export import SpanExporter, SpanExportResult
from opentelemetry.trace import SpanKind, StatusCode

from polyweb.models.observability import (
    INTERNAL_ATTRIBUTES,
    TRACE_CONTENT_ATTRIBUTES,
    ActorType,
    TraceAttribute,
    TraceEventDetail,
    TraceOperation,
    TraceOutcome,
    TraceSpanKind,
    TraceSpanRecord,
    TraceStatusCode,
    trace_outcome_for,
)
from polyweb.persistence.database_migrations import absolute_database_path
from polyweb.persistence.trace_policy import METADATA_ONLY_POLICY, apply_trace_policy

logger = logging.getLogger(__name__)

_SQLITE_TIMEOUT_SECONDS = 30.0

#: Exporters with an open batch connection, by weak reference. Closing the
#: owning repository releases these file handles even when an embedder never
#: shut the trace runtime down (Windows otherwise cannot remove the database).
_EXPORTERS: weakref.WeakSet[Any] = weakref.WeakSet()

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
_CONTENT_ATTRIBUTES = TRACE_CONTENT_ATTRIBUTES

_INSERT = """
INSERT OR REPLACE INTO trace_spans (
    span_id, trace_id, parent_span_id, user_id, project_id, actor_type,
    actor_id, name, kind, started_at, ended_at,
    duration_ms, status_code, status_message, outcome, error_type, operation,
    provider, input_text, output_json, result_count, attributes_json,
    events_json, resource_json
) VALUES (
    :span_id, :trace_id, :parent_span_id, :user_id, :project_id, :actor_type,
    :actor_id, :name, :kind, :started_at,
    :ended_at, :duration_ms, :status_code, :status_message, :outcome,
    :error_type, :operation, :provider, :input_text, :output_json,
    :result_count, :attributes_json, :events_json, :resource_json
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
    user_id = attributes.get(TraceAttribute.USER_ID)
    return {
        "user_id": str(user_id) if user_id else None,
        "operation": str(operation) if operation else None,
        "input_text": str(input_text) if input_text is not None else None,
        "output_json": output if isinstance(output, str) else None,
        "result_count": int(result_count) if isinstance(result_count, (int, float)) else None,
    }


def _uuid_attribute(attributes: dict[str, Any], key: str) -> UUID | None:
    """Parse one UUID ownership attribute defensively; invalid data is ``None``."""

    raw = attributes.get(key)
    if raw is None:
        return None
    try:
        return UUID(str(raw))
    except (ValueError, AttributeError, TypeError):
        return None


def _actor_type(attributes: dict[str, Any]) -> ActorType | None:
    """Parse the actor-type ownership attribute, tolerating unknown values."""

    raw = attributes.get(TraceAttribute.ACTOR_TYPE)
    try:
        return ActorType(str(raw)) if raw else None
    except ValueError:
        return None


def _provider(attributes: dict[str, Any]) -> str | None:
    """Return the provider identity a span recorded, or ``None`` when absent.

    Every span that talks to one provider (root summary and provider children
    alike) attaches ``polyweb.provider.name``, so this reads the attribute
    for all spans rather than only the root: a fanout child must keep its own
    identity independently of the request-level summary provider.
    """

    value = attributes.get(TraceAttribute.PROVIDER)
    return str(value) if value else None


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
        # No exception text is ever persisted: the safe projection is the
        # low-cardinality ``error_type`` that the facade records.
        status_message=None,
        outcome=_outcome(status, attributes, is_root=is_root, http_status=_http_status(attributes)),
        error_type=_error_type(span),
        user_id=summary.get("user_id"),
        project_id=_uuid_attribute(attributes, TraceAttribute.PROJECT_ID),
        actor_type=_actor_type(attributes),
        actor_id=_uuid_attribute(attributes, TraceAttribute.ACTOR_ID),
        operation=_operation(summary.get("operation")),
        provider=_provider(attributes),
        input_text=summary.get("input_text"),
        output_json=summary.get("output_json"),
        result_count=summary.get("result_count"),
        attributes={
            key: value
            for key, value in attributes.items()
            if key not in INTERNAL_ATTRIBUTES and not (is_root and key in _CONTENT_ATTRIBUTES)
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


def _record_rows(records: Sequence[TraceSpanRecord]) -> list[dict[str, Any]]:
    """Validate ownership, then render every record as SQL parameters."""

    if not records:
        return []
    for record in records:
        if record.project_id is None or record.actor_type is None or record.actor_id is None:
            raise ValueError(
                "trace span records must carry project ownership and actor attribution"
            )
    return [_row(record) for record in records]


def _write_rows(connection: sqlite3.Connection, rows: Sequence[dict[str, Any]]) -> None:
    """Upsert one batch in one transaction on an already-open connection."""

    if not rows:
        return
    connection.executemany(_INSERT, rows)
    connection.commit()


def _close_connection(connection: sqlite3.Connection) -> None:
    """Best-effort close for interpreter/finalizer teardown."""

    with suppress(Exception):
        connection.close()


def write_trace_spans(database: Path, records: Sequence[TraceSpanRecord]) -> None:
    """Upsert span rows in one short transaction (also the fixture seed path).

    This is the raw storage path: the caller supplies the rows to persist.
    Project trace detail policy is applied by
    :class:`SQLiteSpanExporter` before it reaches this function, so fixture
    seeds can intentionally write rows of a project whose current policy is
    narrower.

    Every record must carry project ownership and actor attribution; an
    unattributed record raises ``ValueError`` before any write. The connection
    is closed explicitly: seed callers are one-shot, so a leaked handle would
    keep the database file locked (and on Windows block its owner from removing
    it).
    """

    rows = _record_rows(records)
    if not rows:
        return
    with closing(sqlite3.connect(database, timeout=_SQLITE_TIMEOUT_SECONDS)) as connection:
        connection.execute("PRAGMA busy_timeout = 30000")
        connection.execute("PRAGMA synchronous = NORMAL")
        _write_rows(connection, rows)


def _capture_decision(span: ReadableSpan) -> bool:
    """Return the stamped trusted payload capture decision.

    A missing decision fails closed to metadata-only capture.
    """

    attributes = span.attributes or {}
    return attributes.get(TraceAttribute.CAPTURE_PAYLOAD) is True


class SQLiteSpanExporter(SpanExporter):
    """Persist finished spans into the local ``trace_spans`` table.

    One sqlite connection is reused across batches. Opening a fresh connection
    for every flushed request re-parses the schema and re-applies the pragmas
    on the batch thread; measured on the latency harness that cost dominated
    the MCP flush. Each batch still runs its own short transaction and commit,
    so the durability and one-batch-one-transaction contract is unchanged.
    """

    def __init__(self, database: Path) -> None:
        """Resolve the trace database once so exports cannot retarget it."""

        self._database = absolute_database_path(database)
        self._lock = threading.Lock()
        self._connection: sqlite3.Connection | None = None
        self._finalizer: weakref.finalize[Any, Any] | None = None
        _EXPORTERS.add(self)

    @property
    def database_path(self) -> Path:
        """Return the database this exporter writes to."""

        return self._database

    def _connection_locked(self) -> sqlite3.Connection:
        """Return the exporter's batch-thread connection, opening it once."""

        if self._connection is None:
            connection = sqlite3.connect(
                self._database,
                timeout=_SQLITE_TIMEOUT_SECONDS,
                check_same_thread=False,
            )
            connection.execute("PRAGMA busy_timeout = 30000")
            connection.execute("PRAGMA synchronous = NORMAL")
            # Match the repository's WAL checkpoint policy: the exporter is a
            # separate long-lived connection, and its commits must not trigger
            # frequent whole-WAL checkpoints either.
            connection.execute("PRAGMA cache_size = -64000")
            connection.execute("PRAGMA mmap_size = 268435456")
            connection.execute("PRAGMA temp_store = MEMORY")
            connection.execute("PRAGMA wal_autocheckpoint = 8000")
            connection.execute("PRAGMA journal_size_limit = 67108864")
            self._connection = connection
            # A provider that is never shut down must still release the file
            # handle when the exporter becomes garbage, or Windows cannot
            # remove the temporary database.
            self._finalizer = weakref.finalize(self, _close_connection, connection)
        return self._connection

    def _discard_connection_locked(self) -> None:
        """Close and forget the connection after a failed batch or shutdown."""

        connection = self._connection
        self._connection = None
        finalizer = self._finalizer
        self._finalizer = None
        if finalizer is not None:
            finalizer.detach()
        if connection is not None:
            _close_connection(connection)

    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        """Write one batch using each span's stamped capture decision.

        Spans without trusted ownership (for example a root opened before the
        handler bound its execution scope) are dropped from the batch and
        logged by count only — never with payload. A span whose payload capture is disabled is
        projected to metadata before persistence. Failures are reported, never
        raised.
        """

        try:
            retained: list[TraceSpanRecord] = []
            skipped = 0
            for span in spans:
                captures_payload = _capture_decision(span)
                record = span_record(span)
                if (
                    record.project_id is None
                    or record.actor_type is None
                    or record.actor_id is None
                ):
                    skipped += 1
                    continue
                retained.append(
                    record if captures_payload else apply_trace_policy(record, METADATA_ONLY_POLICY)
                )
            if skipped:
                logger.warning("trace export skipped %d unattributed span(s)", skipped)
            rows = _record_rows(retained)
            if not rows:
                return SpanExportResult.SUCCESS
            with self._lock:
                try:
                    _write_rows(self._connection_locked(), rows)
                except BaseException:
                    # Discard the failed transaction before another batch can
                    # use this connection and commit any of its partial rows.
                    self._discard_connection_locked()
                    raise
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
        """Close the batch connection; every batch already committed."""

        with self._lock:
            self._discard_connection_locked()


def close_trace_exporters(database: Path) -> None:
    """Close every exporter connection bound to one database path.

    The repository calls this as it closes. An embedder can forget to shut an
    injected trace runtime down, and a persistent SQLite connection would then
    keep the file handle open (Windows refuses to remove or replace the file).
    Closing here is safe: the next export reopens the connection.
    """

    resolved = absolute_database_path(database)
    for exporter in list(_EXPORTERS):
        if exporter.database_path == resolved:
            exporter.shutdown()


__all__ = [
    "SQLiteSpanExporter",
    "close_trace_exporters",
    "span_record",
    "write_trace_spans",
]
