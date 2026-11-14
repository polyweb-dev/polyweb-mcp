"""Span durations survive wall-clock steps (NTP / VM clock sync)."""

from __future__ import annotations

import pytest
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from polyweb.infrastructure.observability import OtelObservability
from polyweb.models.observability import INTERNAL_ATTRIBUTES, TraceAttribute
from polyweb.persistence import otel_exporter
from polyweb.persistence.otel_exporter import span_record


def _runtime() -> tuple[OtelObservability, InMemorySpanExporter]:
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    return OtelObservability(provider.get_tracer("test"), provider), exporter


def test_monotonic_duration_is_internal() -> None:
    assert TraceAttribute.MONOTONIC_DURATION_NS in INTERNAL_ATTRIBUTES


def test_duration_uses_monotonic_clock_when_wall_clock_steps_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime, exporter = _runtime()
    # The span really takes 464 ms on the monotonic clock ...
    ticks = iter([1_000_000_000, 1_464_000_000])
    monkeypatch.setattr(
        "polyweb.infrastructure.observability.time.perf_counter_ns", lambda: next(ticks)
    )
    with runtime.span("POST /fetch"):
        pass
    (span,) = exporter.get_finished_spans()
    # ... but the wall clock stepped back 1.2 s between its start and end.
    span._end_time = span.start_time - 1_216_000_000  # type: ignore[attr-defined,operator]
    record = span_record(span)
    assert record.duration_ms == 464
    assert TraceAttribute.MONOTONIC_DURATION_NS not in record.attributes


def test_duration_falls_back_to_wall_clock_without_monotonic_value() -> None:
    assert otel_exporter._duration_ms(1_000_000_000, 1_250_000_000) == 250
    assert otel_exporter._duration_ms(2_000_000_000, 1_000_000_000) == 0
    assert otel_exporter._duration_ms(0, 0, monotonic_ns=7_000_000) == 7
    # Malformed monotonic values are ignored rather than trusted.
    assert otel_exporter._duration_ms(0, 3_000_000, monotonic_ns=-5) == 3
    assert otel_exporter._duration_ms(0, 3_000_000, monotonic_ns=True) == 3


def test_monotonic_duration_is_stamped_on_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    runtime, exporter = _runtime()
    ticks = iter([10, 10 + 42_000_000])
    monkeypatch.setattr(
        "polyweb.infrastructure.observability.time.perf_counter_ns", lambda: next(ticks)
    )
    with pytest.raises(ValueError), runtime.span("mcp fetch"):
        raise ValueError("boom")
    (span,) = exporter.get_finished_spans()
    assert span_record(span).duration_ms == 42
