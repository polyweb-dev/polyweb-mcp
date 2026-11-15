import json
from datetime import UTC, datetime

import pytest
from pydantic import AnyHttpUrl

from polyweb.models.contracts import FetchedDocument, FetchResponse
from polyweb.models.observability import TraceEventDetail, TraceSpanKind, TraceSpanRecord
from polyweb.models.projects import ProjectTracePolicy, TraceDetailPolicy
from polyweb.persistence.storage import _trace_events
from polyweb.persistence.trace_policy import apply_trace_policy
from polyweb.services.execution import _provider_response_event


@pytest.mark.parametrize(
    "raw, expected",
    [
        ('[{"title":"one"}]', [{"title": "one"}]),
        ('{"count":1}', {"count": 1}),
        ("[{broken", "[{broken"),
    ],
)
def test_stored_provider_results_are_decoded_safely(raw: str, expected: object) -> None:
    events = _trace_events(
        json.dumps(
            [
                {
                    "name": "polyweb.provider.response",
                    "timestamp": "2026-01-01T00:00:00Z",
                    "attributes": {"results": raw},
                }
            ]
        )
    )
    assert events[0].attributes["results"] == expected


@pytest.mark.parametrize("size", [3, 1000, 1001])
def test_fetch_preview_is_bounded_and_redacted(size: int) -> None:
    now = datetime.now(UTC)
    response = FetchResponse(
        provider="example",
        document=FetchedDocument(
            url=AnyHttpUrl("https://example.com"), content="x" * size, fetched_at=now
        ),
    )
    attributes = _provider_response_event(response)
    assert attributes["content_preview"] == "x" * min(size, 1000)
    assert attributes["content_truncated"] is (size > 1000)
    record = TraceSpanRecord(
        span_id="1",
        trace_id="1",
        name="provider",
        kind=TraceSpanKind.INTERNAL,
        started_at=now,
        ended_at=now,
        duration_ms=0,
        events=[
            TraceEventDetail(name="polyweb.provider.response", timestamp=now, attributes=attributes)
        ],
    )
    stripped = apply_trace_policy(record, ProjectTracePolicy(detail=TraceDetailPolicy.METADATA))
    assert "content_preview" not in stripped.events[0].attributes
    assert "content_truncated" not in stripped.events[0].attributes
    assert stripped.events[0].attributes["content_length"] == size


def test_negative_span_duration_is_logged(caplog: pytest.LogCaptureFixture) -> None:
    from polyweb.persistence.otel_exporter import _duration_ms

    with caplog.at_level("WARNING"):
        assert _duration_ms(2_000_000, 1_000_000) == 0
    assert "ended before its start" in caplog.text
