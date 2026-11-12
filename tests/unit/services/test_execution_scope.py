"""Trace-policy read failures suppress optional capture without affecting audits."""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

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
from polyweb.models.contracts import SearchRequest, UsageOperation
from polyweb.models.observability import TraceAttribute
from polyweb.models.projects import ProjectTracePolicy
from polyweb.services.execution import _Candidate, _LegChain
from polyweb.services.execution_scope import resolve_trace_capture


def _candidate(provider: str) -> _Candidate:
    from unittest.mock import MagicMock

    return _Candidate(
        binding=MagicMock(),
        provider=provider,
        credential_id=uuid4(),
        credential_generation=1,
        config=MagicMock(),
        health=None,
    )


def _search_request(**overrides: object) -> SearchRequest:
    payload: dict[str, object] = {
        "project_id": uuid4(),
        "query": "keyless",
    }
    payload.update(overrides)
    return SearchRequest(**payload)  # type: ignore[arg-type]


def _chain(request: SearchRequest, candidates: list[_Candidate] | None = None) -> _LegChain:
    return _LegChain(
        SimpleNamespace(),
        list(candidates) if candidates is not None else [],
        request,
        UsageOperation.SEARCH,
        SimpleNamespace(),
        None,
    )


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


# --- Missing-pool guidance (TASK-000065 red regressions) ----------------------
#
# A project with no assigned pool must fail with an actionable message that
# names pool creation/assignment for the selected provider, never with a bare
# "no provider is configured" that reads like an unexplained timeout. The
# guidance must name no timeout: genuine provider timeouts surface through
# the 429 deadline path and 5xx provider errors instead.


def test_missing_pool_error_names_pool_assignment_not_timeout() -> None:
    error = _chain(_search_request()).missing_error()

    assert "no provider is configured" in error.detail
    assert "pool" in error.detail
    assert "timeout" not in error.detail.lower()


def test_missing_pool_error_names_required_provider_pool_assignment() -> None:
    error = _chain(
        _search_request(routing={"mode": "require", "providers": ["keenable"]})
    ).missing_error()

    assert "keenable" in error.detail
    assert "pool" in error.detail
    assert "timeout" not in error.detail.lower()


def test_missing_pool_error_distinguishes_unusable_configured_credential() -> None:
    error = _chain(
        _search_request(routing={"mode": "require", "providers": ["parallel"]}),
        candidates=[_candidate("parallel")],
    ).missing_error()

    assert "parallel" in error.detail
    assert "no assigned pool" not in error.detail
    assert "reconnect" in error.detail
    assert "timeout" not in error.detail.lower()
