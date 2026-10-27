"""Pure trace-policy helpers: sampling and payload redaction (TASK-000044 A5)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from freesearch.models.observability import (
    TraceAttribute,
    TraceEventDetail,
    TraceSpanKind,
    TraceSpanRecord,
)
from freesearch.models.projects import (
    ProjectTracePolicy,
    TraceDetailPolicy,
    TraceRedactionPolicy,
)
from freesearch.persistence.trace_policy import apply_trace_policy, trace_is_sampled


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


def test_zero_sampling_drops_every_trace_and_full_sampling_keeps_all() -> None:
    """The 0.0 and 1.0 boundaries are absolute, not probabilistic."""

    assert trace_is_sampled("0" * 32, 0.0) is False
    assert trace_is_sampled("f" * 32, 0.0) is False
    assert trace_is_sampled("0" * 32, 1.0) is True
    assert trace_is_sampled("f" * 32, 1.0) is True


def test_mid_rate_sampling_is_deterministic_per_trace_id() -> None:
    """One trace id always decides the same way, so a whole trace agrees."""

    low = "0" * 32
    high = "f" * 32
    assert trace_is_sampled(low, 0.5) is True
    assert trace_is_sampled(high, 0.5) is False
    assert trace_is_sampled(low, 0.5) == trace_is_sampled(low, 0.5)
    assert trace_is_sampled(high, 0.5) == trace_is_sampled(high, 0.5)


def test_unparseable_trace_id_is_kept() -> None:
    """A malformed id fails open to capture rather than silently dropping."""

    assert trace_is_sampled("not-a-trace-id", 0.5) is True


def test_full_standard_policy_preserves_payload() -> None:
    """FULL detail with STANDARD redaction keeps request/response content."""

    policy = ProjectTracePolicy(
        sampling_rate=1.0,
        detail=TraceDetailPolicy.FULL,
        payload_redaction=TraceRedactionPolicy.STANDARD,
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


def test_strict_redaction_strips_payload_even_with_full_detail() -> None:
    """STRICT redaction never persists payload content, whatever the detail."""

    policy = ProjectTracePolicy(
        detail=TraceDetailPolicy.FULL,
        payload_redaction=TraceRedactionPolicy.STRICT,
    )
    stripped = apply_trace_policy(_record(), policy)
    assert stripped.input_text is None
    assert stripped.output_json is None
    assert TraceAttribute.REQUEST_QUERY not in stripped.attributes
