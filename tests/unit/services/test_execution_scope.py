"""Trace-policy read failures suppress optional capture without affecting audits."""

from unittest.mock import AsyncMock

import pytest
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from polyweb.infrastructure.observability import (
    OtelObservability,
    _AttributionSpanProcessor,
    bind_trace_capture,
    use_observability,
)
from polyweb.models.observability import TraceAttribute
from polyweb.models.projects import ProjectTracePolicy
from polyweb.services.execution_scope import resolve_trace_capture


@pytest.mark.asyncio
async def test_trace_policy_read_failure_binds_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "polyweb.services.execution_scope.project_trace_policy",
        AsyncMock(side_effect=RuntimeError("storage unavailable")),
    )
    policy = await resolve_trace_capture(object(), object())
    assert policy.captures_payload is False
    provider = TracerProvider()
    exporter = InMemorySpanExporter()
    provider.add_span_processor(_AttributionSpanProcessor())
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    runtime = OtelObservability(provider.get_tracer("policy-failure"), provider)
    with use_observability(runtime):
        bind_trace_capture(policy)
        with runtime.span("polyweb.provider") as span:
            span.add_event("request", {"query": "must never buffer", "result_count": 1})
    (finished,) = exporter.get_finished_spans()
    assert TraceAttribute.SAMPLED not in finished.attributes
    assert finished.attributes[TraceAttribute.CAPTURE_PAYLOAD] is False
    assert "must never buffer" not in finished.to_json()
    assert policy != ProjectTracePolicy()
