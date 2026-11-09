"""Unit coverage for the pure trace data contracts.

No OTel, database, or transport imports: strict validation, UTC/duration
rules, the operation-specific output union, and the small helper functions.
"""

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from polyweb.models.observability import (
    TraceDetail,
    TraceError,
    TraceEventDetail,
    TraceFetchOutput,
    TraceListResponse,
    TraceOperation,
    TraceOutcome,
    TraceSearchOutput,
    TraceSpanDetail,
    TraceSpanKind,
    TraceSpanRecord,
    TraceStatusCode,
    TraceSummary,
    display_stage,
    is_trace_id,
    parse_trace_output,
    trace_error,
    trace_outcome_for,
)


def _aware(year: int = 2026, month: int = 9, day: int = 29) -> datetime:
    return datetime(year, month, day, 9, 15, tzinfo=UTC)


def test_trace_operation_and_outcome_members() -> None:
    assert TraceOperation.SEARCH.value == "search"
    assert TraceOperation.FETCH.value == "fetch"
    assert {item.value for item in TraceOperation} == {"search", "fetch"}
    assert {item.value for item in TraceOutcome} == {"success", "partial", "error"}


def test_strict_models_reject_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        TraceSummary(
            trace_id="e" * 32,
            started_at=_aware(),
            duration_ms=10,
            outcome=TraceOutcome.SUCCESS,
            unknown="field",  # type: ignore[call-arg]
        )


def test_summary_requires_aware_datetimes() -> None:
    with pytest.raises(ValidationError):
        TraceSummary(
            trace_id="e" * 32,
            started_at=datetime(2026, 9, 29, 9, 15),  # naive: no tzinfo
            duration_ms=10,
            outcome=TraceOutcome.SUCCESS,
        )


def test_duration_must_be_non_negative() -> None:
    with pytest.raises(ValidationError):
        TraceSummary(
            trace_id="e" * 32,
            started_at=_aware(),
            duration_ms=-1,
            outcome=TraceOutcome.SUCCESS,
        )


def test_search_output_union_shape() -> None:
    output = TraceSearchOutput(
        query="distributed consensus",
        results=[
            {
                "title": "Consensus explained",
                "url": "https://docs.polyweb.dev/consensus",
                "snippet": "Raft and Paxos.",
                "source": "keenable",
                "score": 0.94,
            }
        ],
    )

    assert output.kind == "search_results"
    assert output.query == "distributed consensus"
    assert output.results[0].url == "https://docs.polyweb.dev/consensus"
    assert output.results[0].score == 0.94


def test_fetch_output_union_shape() -> None:
    output = TraceFetchOutput(
        url="https://docs.polyweb.dev/page",
        title="Page",
        content="hello",
        content_length=5,
        truncated=False,
    )

    assert output.kind == "fetch_document"
    assert output.content_length == 5
    assert output.truncated is False


def test_fetch_output_rejects_negative_content_length() -> None:
    with pytest.raises(ValidationError):
        TraceFetchOutput(url="https://docs.polyweb.dev/page", content_length=-1)


def test_parse_trace_output_decodes_tagged_union() -> None:
    search_json = TraceSearchOutput(
        query="q",
        results=[
            {
                "title": "t",
                "url": "https://example.com/r",
                "snippet": "s",
                "source": "keenable",
                "score": 0.5,
            }
        ],
    ).model_dump_json()
    fetch_json = TraceFetchOutput(
        url="https://example.com/page", content="body", content_length=4
    ).model_dump_json()

    search = parse_trace_output(search_json)
    fetch = parse_trace_output(fetch_json)

    assert isinstance(search, TraceSearchOutput)
    assert search.query == "q"
    assert search.results[0].url == "https://example.com/r"
    assert isinstance(fetch, TraceFetchOutput)
    assert fetch.content == "body"


def test_parse_trace_output_absent_or_legacy_is_none() -> None:
    assert parse_trace_output(None) is None
    assert parse_trace_output("") is None
    assert parse_trace_output('{"kind": "unknown_shape"}') is None
    assert parse_trace_output("not json") is None


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("e1c2d3a4b5c6d7e8f9012345678abcde", True),
        ("0f1e2d3c4b5a69788796a5b4c3d2e1f0", True),
        ("E1C2D3A4B5C6D7E8F9012345678ABCDE", False),
        ("e1c2d3a4", False),
        ("e1c2d3a4b5c6d7e8f9012345678abcdeff", False),
        ("not-a-trace-id-at-all-000000000000", False),
        ("", False),
    ],
)
def test_is_trace_id_accepts_only_32_lowercase_hex(value: str, expected: bool) -> None:
    assert is_trace_id(value) is expected


def test_trace_outcome_for_projects_status_and_partial() -> None:
    assert trace_outcome_for(status_code=TraceStatusCode.ERROR) is TraceOutcome.ERROR
    assert trace_outcome_for(status_code=TraceStatusCode.ERROR, partial=True) is TraceOutcome.ERROR
    assert trace_outcome_for(status_code=TraceStatusCode.UNSET) is TraceOutcome.SUCCESS
    assert trace_outcome_for(status_code=TraceStatusCode.OK) is TraceOutcome.SUCCESS
    assert trace_outcome_for(status_code=TraceStatusCode.UNSET, partial=True) is (
        TraceOutcome.PARTIAL
    )


def test_trace_error_projection() -> None:
    assert trace_error(None, None) is None
    assert trace_error("HTTP 502", None) is None

    error = trace_error("HTTP 502", "http_error")

    assert error == TraceError(type="http_error", message="HTTP 502")
    assert trace_error(None, "http_error") == TraceError(type="http_error", message="http_error")


def test_span_detail_carries_stage_and_outcome() -> None:
    span = TraceSpanDetail(
        span_id="aa00000000000001",
        parent_span_id=None,
        name="POST /search",
        stage="Search request",
        kind=TraceSpanKind.SERVER,
        started_at=_aware(),
        ended_at=_aware(),
        duration_ms=248,
        outcome=TraceOutcome.SUCCESS,
    )

    assert span.stage == "Search request"
    assert span.outcome is TraceOutcome.SUCCESS
    assert span.error is None
    assert span.events == []
    # RED (PLAN §6.1 item 5): span-level provider identity is nullable and
    # defaults to None when the exporter recorded no provider for the span.
    assert span.provider is None


def test_span_detail_provider_accepts_explicit_identity() -> None:
    # RED (PLAN §6.1 item 5): an explicit per-span provider must survive the
    # detail contract. Fails because TraceSpanDetail has no `provider` field.
    span = TraceSpanDetail(
        span_id="cc00000000000003",
        parent_span_id="bb00000000000002",
        name="polyweb.provider",
        stage="Provider request",
        kind=TraceSpanKind.CLIENT,
        started_at=_aware(),
        ended_at=_aware(),
        duration_ms=208,
        outcome=TraceOutcome.SUCCESS,
        provider="brave",
    )

    assert span.provider == "brave"


def test_span_detail_rejects_negative_duration() -> None:
    with pytest.raises(ValidationError):
        TraceSpanDetail(
            span_id="aa00000000000001",
            name="POST /search",
            stage="Search request",
            kind=TraceSpanKind.SERVER,
            started_at=_aware(),
            ended_at=_aware(),
            duration_ms=-5,
            outcome=TraceOutcome.SUCCESS,
        )


def test_event_detail_requires_aware_timestamp() -> None:
    with pytest.raises(ValidationError):
        TraceEventDetail(name="exception", timestamp=datetime(2026, 9, 29, 9, 15))


def test_display_stage_labels_are_user_safe() -> None:
    assert display_stage("POST /search") == "Search request"
    assert display_stage("POST /fetch") == "Fetch request"
    assert display_stage("polyweb.backend") == "Backend handling"
    assert display_stage("polyweb.provider.http") == "Provider HTTP call"
    assert display_stage("polyweb.provider.parse") == "Provider response parse"
    assert display_stage("polyweb.results") == "Results assembly"
    assert display_stage("polyweb.response") == "Response to caller"
    assert display_stage("something.unknown") == "Stage"


def test_detail_extends_summary_with_input_output_spans() -> None:
    detail = TraceDetail(
        trace_id="e" * 32,
        operation=TraceOperation.SEARCH,
        started_at=_aware(),
        duration_ms=248,
        provider="keenable",
        outcome=TraceOutcome.SUCCESS,
        result_count=2,
        input="distributed consensus",
        output=TraceSearchOutput(query="distributed consensus", results=[]),
        spans=[],
    )

    assert detail.input == "distributed consensus"
    assert isinstance(detail.output, TraceSearchOutput)
    assert detail.spans == []
    assert detail.error is None


def test_list_response_carries_generation_instant() -> None:
    response = TraceListResponse(items=[], generated_at=_aware())

    assert response.items == []
    assert response.generated_at == _aware()


def test_span_record_defaults_to_success_unset() -> None:
    record = TraceSpanRecord(
        span_id="aa00000000000001",
        trace_id="e" * 32,
        name="polyweb.backend",
        kind=TraceSpanKind.INTERNAL,
        started_at=_aware(),
        ended_at=_aware(),
        duration_ms=10,
    )

    assert record.status_code is TraceStatusCode.UNSET
    assert record.outcome is TraceOutcome.SUCCESS
    assert record.operation is None
    assert record.parent_span_id is None
    assert record.attributes == {}
    assert record.events == []
