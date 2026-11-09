"""Unit coverage for the app-scoped observability facade.

Fast and isolated: a real ``OtelObservability`` over an in-memory SDK exporter
for hierarchy/status assertions, plus direct redaction-hook assertions. No live
network, no database, no process-global provider registration.
"""

import asyncio
import json
import re
from datetime import UTC, datetime

import pytest
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import StatusCode

from freesearch.configuration.config import Settings
from freesearch.infrastructure.observability import (
    NO_OP_OBSERVABILITY,
    NO_OP_SPAN,
    NoOpObservability,
    OtelObservability,
    SpanHandle,
    SpanKindName,
    bind_trace_capture,
    build_observability,
    build_span_processors,
    current_observability,
    error_type_of,
    is_sensitive_key,
    trace_content_attributes,
    use_observability,
)
from freesearch.infrastructure.resilience import ProviderOperationError
from freesearch.infrastructure.trace_payloads import _annotate_fetch_root, _annotate_search_root
from freesearch.models.contracts import (
    FetchedDocument,
    FetchRequest,
    FetchResponse,
    ProviderError,
    SearchRequest,
    SearchResponse,
    SearchResult,
)
from freesearch.models.observability import (
    ActorType,
    ExecutionAttribution,
    TraceAttribute,
)
from freesearch.models.projects import ProjectTracePolicy, TraceDetailPolicy
from freesearch.services.execution import _provider_response_event

_TRACE_ID_RE = re.compile(r"^[0-9a-f]{32}$")


def _memory_runtime() -> tuple[OtelObservability, InMemorySpanExporter]:
    provider = TracerProvider()
    exporter = InMemorySpanExporter()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    return OtelObservability(provider.get_tracer("test"), provider), exporter


def test_noop_span_handle_records_nothing() -> None:
    assert NO_OP_SPAN.trace_id is None
    # None of these may raise; they record nothing.
    NO_OP_SPAN.set_attributes({"freesearch.request.query": "q"})
    NO_OP_SPAN.add_event("freesearch.provider.request", {"query": "q"})
    NO_OP_SPAN.record_exception(RuntimeError("boom"))
    NO_OP_SPAN.mark_error(RuntimeError("boom"))


def test_noop_runtime_is_inert() -> None:
    runtime = NoOpObservability()

    with runtime.span("freesearch.backend") as span:
        assert span.trace_id is None
        span.set_attributes({"k": "v"})
        span.add_event("event")
    runtime.annotate_root({"freesearch.request.query": "q"})

    assert runtime.current_trace_id() is None
    assert runtime.force_flush() is True
    assert runtime.shutdown() is None


def test_noop_runtime_propagates_exceptions_unchanged() -> None:
    runtime = NoOpObservability()
    marker = RuntimeError("propagate me")

    with pytest.raises(RuntimeError) as raised, runtime.span("freesearch.backend"):
        raise marker

    assert raised.value is marker


def test_default_runtime_outside_request_is_noop() -> None:
    assert current_observability() is NO_OP_OBSERVABILITY
    assert current_observability().current_trace_id() is None


def test_nested_spans_share_one_stable_trace_id() -> None:
    runtime, _exporter = _memory_runtime()

    with use_observability(runtime):
        with runtime.span("POST /search", kind=SpanKindName.SERVER) as root:
            root_id = root.trace_id
            assert root_id is not None
            assert _TRACE_ID_RE.match(root_id) is not None
            assert runtime.current_trace_id() == root_id
            with runtime.span("freesearch.backend") as child:
                assert child.trace_id == root_id
                assert runtime.current_trace_id() == root_id
        assert runtime.current_trace_id() is None


def test_exception_is_recorded_exactly_once_across_nesting() -> None:
    runtime, exporter = _memory_runtime()
    marker = RuntimeError("inner failure")

    with (
        use_observability(runtime),
        pytest.raises(RuntimeError),
        runtime.span("POST /search", kind=SpanKindName.SERVER),
        runtime.span("freesearch.provider"),
    ):
        raise marker

    spans = {span.name: span for span in exporter.get_finished_spans()}
    assert set(spans) == {"POST /search", "freesearch.provider"}
    assert spans["freesearch.provider"].status.status_code is StatusCode.ERROR
    assert spans["POST /search"].status.status_code is StatusCode.ERROR
    exception_events = [
        event
        for span in spans.values()
        for event in (span.events or ())
        if event.name == "exception"
    ]
    assert len(exception_events) == 1
    assert spans["freesearch.provider"].attributes.get("error.type") == "RuntimeError"
    assert spans["POST /search"].attributes.get("error.type") == "RuntimeError"


def test_record_exception_marks_error_with_low_cardinality_type() -> None:
    runtime, exporter = _memory_runtime()
    error = ProviderOperationError(
        ProviderError(provider="keenable", code="http_error", message="HTTP 502")
    )

    with use_observability(runtime), runtime.span("freesearch.provider") as span:
        span.record_exception(error)

    (finished,) = exporter.get_finished_spans()
    assert finished.status.status_code is StatusCode.ERROR
    assert finished.attributes.get("error.type") == "http_error"
    assert [event.name for event in (finished.events or ())] == ["exception"]


def test_cancelled_error_is_not_marked_failed() -> None:
    runtime, exporter = _memory_runtime()

    async def _cancel_inside_span() -> None:
        with use_observability(runtime), runtime.span("freesearch.provider"):
            raise asyncio.CancelledError("gone")

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(_cancel_inside_span())

    (finished,) = exporter.get_finished_spans()
    assert finished.status.status_code is not StatusCode.ERROR
    assert [event.name for event in (finished.events or ())] == []


def test_trace_content_attributes_rejects_secrets_but_keeps_query_results() -> None:
    payload = {
        "freesearch.request.query": "distributed consensus",
        "freesearch.response.result_count": 2,
        "credentials": "hunter2",
        "Authorization": "Bearer abc",
        "Cookie": "session=1",
        "X-API-Key": "keen_secret",
        "raw_secret_value": "shh",
        "apiKey": "key-123",
        "authToken": "tok",
        "request_headers": {"x": "y"},
    }

    attributes = trace_content_attributes(payload)

    assert attributes["freesearch.request.query"] == "distributed consensus"
    assert attributes["freesearch.response.result_count"] == 2
    for rejected in (
        "credentials",
        "Authorization",
        "Cookie",
        "X-API-Key",
        "raw_secret_value",
        "apiKey",
        "authToken",
        "request_headers",
    ):
        assert rejected not in attributes


def test_trace_content_attributes_filters_nested_mappings() -> None:
    payload = {
        "outer": {"query": "kept", "password": "dropped", "deep": {"cookie": "x"}},
        "results": [{"title": "t", "url": "https://example.com"}],
    }

    attributes = trace_content_attributes(payload)

    assert attributes["outer"] == {"query": "kept"}
    assert attributes["results"] == [{"title": "t", "url": "https://example.com"}]


def test_full_capture_scrubs_json_documents_and_preserves_provider_results() -> None:
    runtime, exporter = _memory_runtime()
    document = (
        '{"public":[{"API_Key":"sentinel-key","nested":{"PassWord":"sentinel-pass",'
        '"ok":"visible"}},null,{}],"empty":{},"none":null,"Cookie":"sentinel-cookie"}'
    )
    fetch = FetchResponse(
        provider="test",
        document=FetchedDocument(
            url="https://example.com", content=document, fetched_at=datetime.now(UTC)
        ),
    )
    search = SearchResponse(
        query="query",
        provider="test",
        results=[
            SearchResult(
                title="visible result",
                url="https://example.com",
                snippet='{"Authorization":"sentinel-auth","safe":"visible snippet"}',
            )
        ],
    )
    with use_observability(runtime):
        bind_trace_capture(ProjectTracePolicy(detail=TraceDetailPolicy.FULL))
        with runtime.span("fetch", kind=SpanKindName.SERVER):
            _annotate_fetch_root(runtime, FetchRequest(url="https://example.com"), fetch)
            with runtime.span("provider") as span:
                span.add_event(
                    "freesearch.provider.response",
                    {"payload": document, **_provider_response_event(search)},
                )
        with runtime.span("search", kind=SpanKindName.SERVER):
            _annotate_search_root(runtime, SearchRequest(query="query"), search)

    spans = {span.name: span for span in exporter.get_finished_spans()}
    output = json.loads(spans["fetch"].attributes[TraceAttribute.RESPONSE_OUTPUT_JSON])
    cleaned = {"public": [{"nested": {"ok": "visible"}}, None, {}], "empty": {}, "none": None}
    assert json.loads(output["content"]) == cleaned
    event = spans["provider"].events[0]
    assert json.loads(event.attributes["payload"]) == cleaned
    assert json.loads(event.attributes["results"])[0]["title"] == "visible result"
    assert json.loads(json.loads(event.attributes["results"])[0]["snippet"]) == {
        "safe": "visible snippet"
    }
    search_output = json.loads(spans["search"].attributes[TraceAttribute.RESPONSE_OUTPUT_JSON])
    assert search_output["results"][0]["title"] == "visible result"
    assert json.loads(search_output["results"][0]["snippet"]) == {"safe": "visible snippet"}
    assert "sentinel-" not in str(spans)


def test_json_text_scrubbing_preserves_non_json_and_bounds_large_json() -> None:
    raw = "{not json"
    attributes = trace_content_attributes({"raw": raw, "large": '{"x":"' + "x" * 4_000_000 + '"}'})
    assert attributes["raw"] == raw
    assert "x" * 100 not in str(attributes["large"])


@pytest.mark.parametrize(
    ("key", "expected"),
    [
        ("credentials", True),
        ("Authorization", True),
        ("cookie", True),
        ("X-API-Key", True),
        ("x-api-key", True),
        ("apiKey", True),
        ("authToken", True),
        ("secret", True),
        ("raw_secret_value", True),
        ("request_headers", True),
        ("freesearch.request.query", False),
        ("freesearch.response.result_count", False),
        ("query", False),
        ("result_count", False),
    ],
)
def test_is_sensitive_key_fragments(key: str, expected: bool) -> None:
    assert is_sensitive_key(key) is expected


def test_set_attributes_and_events_apply_the_redaction_hook() -> None:
    runtime, exporter = _memory_runtime()

    with use_observability(runtime):
        bind_trace_capture(ProjectTracePolicy(detail=TraceDetailPolicy.FULL))
        with runtime.span("freesearch.provider") as span:
            _set_full_attributes(span)

    (finished,) = exporter.get_finished_spans()
    assert finished.attributes.get("freesearch.request.query") == "kept query"
    assert "X-API-Key" not in dict(finished.attributes or {})
    assert "Authorization" not in dict(finished.attributes or {})
    (event,) = finished.events or ()
    assert event.name == "freesearch.provider.request"
    assert dict(event.attributes or {}) == {"query": "kept"}


def _set_full_attributes(span: SpanHandle) -> None:
    span.set_attributes(
        {
            "freesearch.request.query": "kept query",
            "X-API-Key": "keen_secret",
            "Authorization": "Bearer abc",
        }
    )
    span.add_event(
        "freesearch.provider.request",
        {"query": "kept", "secret": "dropped"},
    )


def test_annotate_root_targets_the_server_span() -> None:
    runtime, exporter = _memory_runtime()

    with use_observability(runtime):
        bind_trace_capture(ProjectTracePolicy(detail=TraceDetailPolicy.FULL))
        with (
            runtime.span("POST /search", kind=SpanKindName.SERVER),
            runtime.span("freesearch.backend"),
        ):
            runtime.annotate_root({"freesearch.request.query": "annotated"})

    spans = {span.name: span for span in exporter.get_finished_spans()}
    assert spans["POST /search"].attributes.get("freesearch.request.query") == "annotated"
    assert "freesearch.request.query" not in dict(spans["freesearch.backend"].attributes or {})


def test_error_type_of_prefers_provider_code() -> None:
    provider_error = ProviderOperationError(
        ProviderError(provider="keenable", code="http_error", message="HTTP 502")
    )

    assert error_type_of(provider_error) == "http_error"
    assert error_type_of(RuntimeError("boom")) == "RuntimeError"
    assert error_type_of(ValueError("bad")) == "ValueError"


def test_build_span_processors_selects_database_or_none(tmp_path) -> None:  # type: ignore[no-untyped-def]
    database_settings = Settings(otel_processor="database")
    none_settings = Settings(otel_processor="none")

    assert len(build_span_processors(database_settings, tmp_path / "traces.db")) == 1
    assert build_span_processors(none_settings, tmp_path / "traces.db") == []


def test_build_observability_noop_cases(tmp_path) -> None:  # type: ignore[no-untyped-def]
    assert build_observability(Settings(otel_processor="database"), database=None) is (
        NO_OP_OBSERVABILITY
    )
    assert build_observability(
        Settings(otel_processor="none"), database=tmp_path / "traces.db"
    ) is (NO_OP_OBSERVABILITY)


def test_build_observability_database_runtime_has_no_trace_outside_spans(
    tmp_path,  # type: ignore[no-untyped-def]
) -> None:
    runtime = build_observability(
        Settings(otel_processor="database"), database=tmp_path / "traces.db"
    )
    assert runtime is not NO_OP_OBSERVABILITY

    try:
        with use_observability(runtime):
            assert runtime.current_trace_id() is None
            with runtime.span("POST /search", kind=SpanKindName.SERVER) as root:
                assert root.trace_id is not None
                assert _TRACE_ID_RE.match(root.trace_id) is not None
            assert runtime.force_flush() is True
    finally:
        runtime.shutdown()


def test_span_initial_attributes_always_carry_schema_version() -> None:
    runtime, exporter = _memory_runtime()

    with use_observability(runtime), runtime.span("freesearch.backend"):
        pass

    (finished,) = exporter.get_finished_spans()
    assert finished.attributes.get(TraceAttribute.SCHEMA_VERSION) == 1


def _attributed_memory_runtime() -> tuple[OtelObservability, InMemorySpanExporter]:
    """A real runtime with the ownership stamping processor plus in-memory export."""

    from freesearch.infrastructure.observability import _AttributionSpanProcessor

    provider = TracerProvider()
    exporter = InMemorySpanExporter()
    provider.add_span_processor(_AttributionSpanProcessor())
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    return OtelObservability(provider.get_tracer("test"), provider), exporter


def _attr(
    project: str = "00000000-0000-4000-8000-0000000000aa",
    actor: str = "00000000-0000-4000-8000-0000000000bb",
) -> ExecutionAttribution:
    from uuid import UUID

    return ExecutionAttribution(
        project_id=UUID(project), actor_type=ActorType.HUMAN, actor_id=UUID(actor)
    )


def test_caller_supplied_ownership_attributes_are_ignored() -> None:
    """Spoofed ownership keys never persist on any caller-facing attribute path."""
    runtime, exporter = _attributed_memory_runtime()
    bound = _attr()
    forged = {
        TraceAttribute.PROJECT_ID: "11111111-1111-4111-8111-111111111111",
        TraceAttribute.ACTOR_TYPE: "project_api_key",
        TraceAttribute.ACTOR_ID: "22222222-2222-4222-8222-222222222222",
    }
    from freesearch.infrastructure.observability import bind_execution_attribution

    with use_observability(runtime):
        bind_execution_attribution(bound)
        with runtime.span("POST /search", kind=SpanKindName.SERVER):
            runtime.annotate_root(dict(forged))
            with runtime.span("freesearch.provider", attributes=dict(forged)) as span:
                span.set_attributes(dict(forged))
                span.add_event("freesearch.provider.response", attributes=dict(forged))

    finished = exporter.get_finished_spans()
    assert len(finished) == 2
    for span in finished:
        assert span.attributes[TraceAttribute.PROJECT_ID] == str(bound.project_id)
        assert span.attributes[TraceAttribute.ACTOR_TYPE] == "human"
        assert span.attributes[TraceAttribute.ACTOR_ID] == str(bound.actor_id)
    provider_span = next(s for s in finished if s.name == "freesearch.provider")
    for event in provider_span.events:
        assert TraceAttribute.PROJECT_ID not in (event.attributes or {})


def test_caller_supplied_ownership_attributes_leave_unbound_spans_clean() -> None:
    """Without a bound attribution, spoofed keys are stripped to nothing."""
    runtime, exporter = _attributed_memory_runtime()
    forged = {
        TraceAttribute.PROJECT_ID: "11111111-1111-4111-8111-111111111111",
        TraceAttribute.ACTOR_TYPE: "project_api_key",
        TraceAttribute.ACTOR_ID: "22222222-2222-4222-8222-222222222222",
    }

    with (
        use_observability(runtime),
        runtime.span("POST /search", kind=SpanKindName.SERVER, attributes=dict(forged)),
    ):
        runtime.annotate_root(dict(forged))

    (finished,) = exporter.get_finished_spans()
    assert TraceAttribute.PROJECT_ID not in finished.attributes
    assert TraceAttribute.ACTOR_TYPE not in finished.attributes
    assert TraceAttribute.ACTOR_ID not in finished.attributes


def test_rebinding_a_different_attribution_fails_closed() -> None:
    """A second bind with a different attribution raises; the same one is a no-op."""
    runtime, _exporter = _attributed_memory_runtime()
    first = _attr()
    other = _attr(
        project="33333333-3333-4333-8333-333333333333",
        actor="44444444-4444-4444-8444-444444444444",
    )
    from freesearch.infrastructure.observability import bind_execution_attribution

    with use_observability(runtime):
        bind_execution_attribution(first)
        bind_execution_attribution(first)  # idempotent
        with pytest.raises(ValueError, match="different identity"):
            bind_execution_attribution(other)


def test_bind_without_an_attribution_cell_is_a_noop() -> None:
    """Outside ``use_observability`` the binder does nothing and never raises."""
    from freesearch.infrastructure.observability import bind_execution_attribution

    bind_execution_attribution(_attr())


@pytest.mark.parametrize(
    "policy",
    [None, ProjectTracePolicy(detail="metadata")],
)
def test_metadata_provider_events_never_buffer_query_url_or_results(policy) -> None:
    """Inspect finished memory spans before any exporter can sanitize them."""
    runtime, exporter = _attributed_memory_runtime()
    marker = "DO_NOT_BUFFER_PROVIDER_CONTENT"
    with use_observability(runtime):
        if policy is not None:
            bind_trace_capture(policy)
        with runtime.span("POST /search", kind=SpanKindName.SERVER) as root:
            root.set_attributes({TraceAttribute.REQUEST_QUERY: marker})
            with runtime.span("freesearch.provider") as child:
                child.add_event(
                    "freesearch.provider.response",
                    {
                        "query": marker,
                        "url": "https://private.invalid/" + marker,
                        "results": marker,
                        "unknown.attribute": marker,
                        "result_count": 2,
                        "exception.type": "RuntimeError",
                    },
                )
                child.record_exception(RuntimeError(marker))
    spans = exporter.get_finished_spans()
    assert len(spans) == 2
    for span in spans:
        assert marker not in span.to_json()
        assert span.status.description is None
    child = next(span for span in spans if span.name == "freesearch.provider")
    assert dict(child.events[0].attributes) == {"result_count": 2, "exception.type": "RuntimeError"}
    assert dict(child.events[1].attributes) == {"exception.type": "RuntimeError"}


def test_full_capture_redacts_nested_credentials_and_exception_messages_in_memory() -> None:
    runtime, exporter = _attributed_memory_runtime()
    marker = "DO_NOT_BUFFER_CREDENTIAL"
    with use_observability(runtime):
        bind_trace_capture(ProjectTracePolicy(detail="full"))
        with runtime.span("POST /search", kind=SpanKindName.SERVER) as root:
            root.add_event(
                "freesearch.provider.request",
                {
                    "query": "explicitly allowed query",
                    "api_key": marker,
                    "results": [{"title": "kept", "password": marker, "Authorization": marker}],
                },
            )
            root.record_exception(RuntimeError(marker))
    (span,) = exporter.get_finished_spans()
    assert marker not in span.to_json()
    assert span.events[0].attributes["query"] == "explicitly allowed query"
    assert span.status.description is None


def test_capture_policy_cannot_be_rebound_mid_trace_and_children_keep_decision() -> None:
    runtime, exporter = _attributed_memory_runtime()
    with use_observability(runtime):
        bind_trace_capture(ProjectTracePolicy(detail="metadata"))
        with runtime.span("POST /search", kind=SpanKindName.SERVER):
            with pytest.raises(ValueError):
                bind_trace_capture(ProjectTracePolicy(detail="full"))
            with runtime.span("freesearch.provider"):
                pass
    for span in exporter.get_finished_spans():
        assert TraceAttribute.SAMPLED not in span.attributes
        assert span.attributes[TraceAttribute.CAPTURE_PAYLOAD] is False
