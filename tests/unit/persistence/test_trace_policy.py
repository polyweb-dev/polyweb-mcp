"""Pure trace-policy payload projection."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest.mock import Mock
from uuid import uuid4

from opentelemetry.sdk.trace.export import SpanExportResult

from freesearch.models.observability import (
    ActorType,
    TraceAttribute,
    TraceEventDetail,
    TraceSpanKind,
    TraceSpanRecord,
)
from freesearch.models.projects import (
    ProjectTracePolicy,
    TraceDetailPolicy,
)
from freesearch.persistence.otel_exporter import SQLiteSpanExporter
from freesearch.persistence.trace_policy import apply_trace_policy


def _record(**overrides: Any) -> TraceSpanRecord:
    """Build one content-bearing span row for policy projection."""

    now = datetime.now(UTC)
    payload: dict[str, Any] = {
        "span_id": "span-1",
        "trace_id": "0" * 32,
        "name": "freesearch.backend",
        "kind": TraceSpanKind.INTERNAL,
        "started_at": now,
        "ended_at": now,
        "duration_ms": 0,
        "input_text": "secret query",
        "output_json": '{"results": []}',
        "attributes": {
            TraceAttribute.REQUEST_QUERY: "secret query",
            TraceAttribute.REQUEST_URL: "https://example.com/?q=secret",
            "safe.attribute": "kept",
        },
        "events": [
            TraceEventDetail(
                name="freesearch.provider.response",
                timestamp=now,
                attributes={
                    TraceAttribute.RESPONSE_OUTPUT_JSON: '{"results": []}',
                    "result_count": 2,
                    "exception.type": "RuntimeError",
                    "query": "secret query",
                    "url": "https://secret.invalid",
                    "results": "secret results",
                },
            )
        ],
    }
    payload.update(overrides)
    return TraceSpanRecord(**payload)


def test_full_policy_preserves_payload() -> None:
    """FULL detail keeps request/response content."""

    policy = ProjectTracePolicy(
        detail=TraceDetailPolicy.FULL,
    )
    record = _record()
    assert apply_trace_policy(record, policy) == record
    assert apply_trace_policy(record, policy).input_text == "secret query"


def test_metadata_policy_strips_content_but_keeps_safe_attributes() -> None:
    """METADATA detail drops payload content while keeping timing metadata."""

    policy = ProjectTracePolicy(detail=TraceDetailPolicy.METADATA)
    stripped = apply_trace_policy(_record(), policy)
    assert stripped.input_text is None
    assert stripped.output_json is None
    assert TraceAttribute.REQUEST_QUERY not in stripped.attributes
    assert TraceAttribute.REQUEST_URL not in stripped.attributes
    assert TraceAttribute.RESPONSE_OUTPUT_JSON not in stripped.attributes
    assert stripped.attributes["safe.attribute"] == "kept"
    assert stripped.events[0].attributes == {"result_count": 2, "exception.type": "RuntimeError"}


def test_exporter_does_not_drop_legacy_unsampled_spans(monkeypatch: Any, tmp_path: Path) -> None:
    span = Mock()
    span.attributes = {TraceAttribute.SAMPLED: False, TraceAttribute.CAPTURE_PAYLOAD: True}
    record = _record(project_id=uuid4(), actor_type=ActorType.HUMAN, actor_id=uuid4())
    collect = Mock(return_value=[])
    monkeypatch.setattr("freesearch.persistence.otel_exporter.span_record", lambda _: record)
    monkeypatch.setattr("freesearch.persistence.otel_exporter._record_rows", collect)
    assert SQLiteSpanExporter(tmp_path / "unused.db").export([span]) is SpanExportResult.SUCCESS
    collect.assert_called_once_with([record])
