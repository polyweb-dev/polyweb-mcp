"""App-scoped OpenTelemetry facade: the only module importing the OTel SDK.

The application never imports ``opentelemetry.*`` in routers, services, or
adapters. Everything instrumented code needs is behind
:class:`ObservabilityRuntime`:

* ``span(name, kind=..., attributes=...)`` — a context manager yielding a
  :class:`SpanHandle`; an exception propagating through it marks the span
  ``ERROR``, records ``error.type`` and exactly one ``exception`` event, then
  re-raises unchanged.
* ``annotate_root(...)`` — attaches the request/response projection to the
  inbound root span (the exporter's summary source).
* ``current_trace_id()``, ``force_flush(...)``, ``shutdown()``.

Providers are app-scoped (obtained from :class:`TracerProvider` directly, never
``trace.set_tracer_provider``), so repeated ``create_app()`` compositions and
per-test databases cannot collide through process-global state.

Future-export seam: :func:`build_span_processors` is the single place that
decides where finished spans go. Adding OTLP/Langfuse/LangSmith support means
adding a span processor/exporter there (optionally driven by the standard
``OTEL_EXPORTER_OTLP_*`` variables); no route, service, or adapter call site
changes. Content capture funnels through :func:`trace_content_attributes`, the
single redaction hook.
"""

import asyncio
import json
import logging
from collections.abc import Iterator, Mapping
from contextlib import AbstractContextManager, contextmanager
from contextvars import ContextVar
from enum import StrEnum
from pathlib import Path
from typing import Any, Protocol, cast, runtime_checkable

from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import SpanProcessor, TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.trace import (
    Span,
    SpanKind,
    Status,
    StatusCode,
    Tracer,
    format_trace_id,
    get_current_span,
)

from freesearch.configuration.config import Settings
from freesearch.models.observability import TRACE_SCHEMA_VERSION, TraceAttribute

logger = logging.getLogger(__name__)

type AttributeValue = str | bool | int | float | list[AttributeValue] | None
"""Serializable span/event attribute value accepted by the facade."""

DEFAULT_FLUSH_TIMEOUT_MILLIS: int = 5_000

# Credential-shaped keys that must never reach a span, an event, or the trace
# table. Matched against the canonical (lowercased, alphanumeric) key.
_SENSITIVE_KEY_FRAGMENTS = frozenset(
    {
        "authorization",
        "authtoken",
        "apikey",
        "authheader",
        "bearer",
        "cookie",
        "credential",
        "header",
        "password",
        "passwd",
        "privatekey",
        "secret",
        "sessionid",
        "token",
    }
)


class SpanKindName(StrEnum):
    """Facade span kinds, mapped to OpenTelemetry span kinds."""

    INTERNAL = "internal"
    SERVER = "server"
    CLIENT = "client"


_SPAN_KINDS: dict[SpanKindName, SpanKind] = {
    SpanKindName.INTERNAL: SpanKind.INTERNAL,
    SpanKindName.SERVER: SpanKind.SERVER,
    SpanKindName.CLIENT: SpanKind.CLIENT,
}


def is_sensitive_key(key: str) -> bool:
    """Return whether ``key`` looks like a credential, header, or token name."""

    canonical = "".join(character for character in key.lower() if character.isalnum())
    return any(fragment in canonical for fragment in _SENSITIVE_KEY_FRAGMENTS)


def _redact(value: object) -> AttributeValue:
    """Coerce one value into a serializable, credential-free attribute value."""

    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, (dict, list, tuple)):
        try:
            return cast(AttributeValue, json.loads(json.dumps(value, default=str, allow_nan=False)))
        except (TypeError, ValueError):
            return str(value)
    return str(value)


def trace_content_attributes(payload: Mapping[str, object]) -> dict[str, AttributeValue]:
    """Allowlist request/response content into span attributes.

    This is the single redaction hook for trace content: credential-, header-,
    cookie-, and token-shaped keys are dropped here (so they are never
    persisted), while the required query text and normalized results pass
    through. Nested mappings are filtered with the same rule.
    """

    attributes: dict[str, AttributeValue] = {}
    for key, value in payload.items():
        name = str(key)
        if is_sensitive_key(name):
            continue
        if isinstance(value, Mapping):
            nested = trace_content_attributes(value)
            if nested:
                attributes[name] = cast(AttributeValue, nested)
            continue
        if isinstance(value, (list, tuple)):
            attributes[name] = [_redact(item) for item in value]
            continue
        redacted = _redact(value)
        if redacted is not None:
            attributes[name] = redacted
    return attributes


def _span_attributes(attributes: Mapping[str, object] | None) -> dict[str, AttributeValue]:
    """Drop ``None`` values, then apply the shared content/redaction hook."""

    if attributes is None:
        return {}
    return trace_content_attributes(
        {key: value for key, value in attributes.items() if value is not None}
    )


class SpanHandle(Protocol):
    """The application-facing view of one span."""

    @property
    def trace_id(self) -> str | None: ...

    def set_attributes(self, attributes: Mapping[str, object]) -> None: ...

    def add_event(self, name: str, attributes: Mapping[str, object] | None = None) -> None: ...

    def record_exception(self, error: BaseException) -> None: ...

    def mark_error(self, error: BaseException) -> None: ...


@runtime_checkable
class ObservabilityRuntime(Protocol):
    """Instrumentation surface used by routers, services, and adapters."""

    def span(
        self,
        name: str,
        *,
        kind: SpanKindName = SpanKindName.INTERNAL,
        attributes: Mapping[str, object] | None = None,
    ) -> AbstractContextManager[SpanHandle]: ...

    def annotate_root(self, attributes: Mapping[str, object]) -> None: ...

    def current_trace_id(self) -> str | None: ...

    def force_flush(self, timeout_millis: int = DEFAULT_FLUSH_TIMEOUT_MILLIS) -> bool: ...

    def shutdown(self) -> None: ...


@contextmanager
def _swallow() -> Iterator[None]:
    """Observability failures must never fail the request being observed."""

    try:
        yield
    except Exception:  # pragma: no cover - defensive: the SDK must not break requests
        logger.warning("dropped an observability record", exc_info=False)


def error_type_of(error: BaseException) -> str:
    """Return a low-cardinality ``error.type`` for a failure.

    Provider errors carry a stable provider code (``http_error``,
    ``quota_exhausted``, ``circuit_open``, ...), which is lower-cardinality and
    more useful than a class name; anything else falls back to the exception
    class name.
    """

    provider_error = getattr(error, "error", None)
    code = getattr(provider_error, "code", None)
    if isinstance(code, str) and code:
        return code
    return type(error).__name__


class _NoOpSpan:
    """Span handle that records nothing (disabled or untraced composition)."""

    __slots__ = ()

    @property
    def trace_id(self) -> str | None:
        return None

    def set_attributes(self, attributes: Mapping[str, object]) -> None:
        del attributes

    def add_event(self, name: str, attributes: Mapping[str, object] | None = None) -> None:
        del name, attributes

    def record_exception(self, error: BaseException) -> None:
        del error

    def mark_error(self, error: BaseException) -> None:
        del error


NO_OP_SPAN = _NoOpSpan()


class NoOpObservability:
    """Runtime used when tracing is disabled or no trace database exists."""

    __slots__ = ()

    @contextmanager
    def span(
        self,
        name: str,
        *,
        kind: SpanKindName = SpanKindName.INTERNAL,
        attributes: Mapping[str, object] | None = None,
    ) -> Iterator[SpanHandle]:
        del name, kind, attributes
        yield NO_OP_SPAN

    def annotate_root(self, attributes: Mapping[str, object]) -> None:
        del attributes

    def current_trace_id(self) -> str | None:
        return None

    def force_flush(self, timeout_millis: int = DEFAULT_FLUSH_TIMEOUT_MILLIS) -> bool:
        del timeout_millis
        return True

    def shutdown(self) -> None:
        return None


NO_OP_OBSERVABILITY = NoOpObservability()

_CURRENT_RUNTIME: ContextVar[ObservabilityRuntime] = ContextVar(
    "freesearch_observability_runtime", default=NO_OP_OBSERVABILITY
)
_ROOT_SPAN: ContextVar[SpanHandle | None] = ContextVar("freesearch_root_span", default=None)
_EXCEPTION_RECORDED: ContextVar[bool] = ContextVar("freesearch_exception_recorded", default=False)


class _OtelSpan:
    """Span handle backed by a live OpenTelemetry SDK span."""

    __slots__ = ("_span",)

    def __init__(self, span: Span) -> None:
        self._span = span

    @property
    def trace_id(self) -> str | None:
        context = self._span.get_span_context()
        return format_trace_id(context.trace_id) if context.is_valid else None

    def set_attributes(self, attributes: Mapping[str, object]) -> None:
        with _swallow():
            self._span.set_attributes(cast("Mapping[str, Any]", _span_attributes(attributes)))

    def add_event(self, name: str, attributes: Mapping[str, object] | None = None) -> None:
        with _swallow():
            self._span.add_event(
                name, attributes=cast("Mapping[str, Any]", _span_attributes(attributes))
            )

    def record_exception(self, error: BaseException) -> None:
        with _swallow():
            self._span.record_exception(error)
        self.mark_error(error)

    def mark_error(self, error: BaseException) -> None:
        """Mark the span failed without adding a second ``exception`` event."""

        with _swallow():
            self._span.set_attribute(TraceAttribute.ERROR_TYPE, error_type_of(error))
            self._span.set_status(Status(StatusCode.ERROR))


class OtelObservability:
    """Runtime backed by an app-scoped SDK ``TracerProvider``."""

    __slots__ = ("_provider", "_tracer")

    def __init__(self, tracer: Tracer, provider: TracerProvider) -> None:
        self._tracer = tracer
        self._provider = provider

    @contextmanager
    def span(
        self,
        name: str,
        *,
        kind: SpanKindName = SpanKindName.INTERNAL,
        attributes: Mapping[str, object] | None = None,
    ) -> Iterator[SpanHandle]:
        initial: dict[str, object] = {TraceAttribute.SCHEMA_VERSION: TRACE_SCHEMA_VERSION}
        initial.update(attributes or {})
        with self._tracer.start_as_current_span(
            name,
            kind=_SPAN_KINDS[kind],
            attributes=cast("Mapping[str, Any]", _span_attributes(initial)),
            record_exception=False,
            set_status_on_exception=False,
        ) as span:
            handle: SpanHandle = _OtelSpan(span)
            token = _ROOT_SPAN.set(handle) if kind is SpanKindName.SERVER else None
            try:
                yield handle
            except asyncio.CancelledError:
                # A cancelled request is not a failed request.
                raise
            except BaseException as error:
                # The innermost span records the standard ``exception`` event;
                # the spans the failure propagates through are marked ERROR with
                # ``error.type`` but do not duplicate the event.
                if _EXCEPTION_RECORDED.get():
                    handle.mark_error(error)
                else:
                    handle.record_exception(error)
                    _EXCEPTION_RECORDED.set(True)
                raise
            finally:
                if token is not None:
                    _ROOT_SPAN.reset(token)

    def annotate_root(self, attributes: Mapping[str, object]) -> None:
        root = _ROOT_SPAN.get()
        if root is not None:
            root.set_attributes(attributes)

    def current_trace_id(self) -> str | None:
        context = get_current_span().get_span_context()
        return format_trace_id(context.trace_id) if context.is_valid else None

    def force_flush(self, timeout_millis: int = DEFAULT_FLUSH_TIMEOUT_MILLIS) -> bool:
        try:
            return bool(self._provider.force_flush(timeout_millis))
        except Exception:
            logger.warning("trace flush failed", exc_info=False)
            return False

    def shutdown(self) -> None:
        with _swallow():
            self._provider.shutdown()


def current_observability() -> ObservabilityRuntime:
    """Return the runtime of the request being handled (``no-op`` otherwise).

    The selective ASGI middleware binds the app's runtime for traced requests
    only, so instrumentation placed in a handler or adapter cannot create spans
    for untraced routes.
    """

    return _CURRENT_RUNTIME.get()


@contextmanager
def use_observability(runtime: ObservabilityRuntime) -> Iterator[None]:
    """Bind ``runtime`` for the duration of the current request."""

    runtime_token = _CURRENT_RUNTIME.set(runtime)
    exception_token = _EXCEPTION_RECORDED.set(False)
    try:
        yield
    finally:
        _EXCEPTION_RECORDED.reset(exception_token)
        _CURRENT_RUNTIME.reset(runtime_token)


def build_span_processors(settings: Settings, database: Path) -> list[SpanProcessor]:
    """Return the span processors for the configured exporter seam.

    Today: ``database`` -> batch export into the local ``trace_spans`` table,
    ``none`` -> no processors. Future OTLP/Langfuse/LangSmith exporters are
    registered here and nowhere else.
    """

    if settings.otel_processor != "database":
        return []
    # Imported lazily so the facade stays importable without the SQLite
    # exporter's dependencies (and to keep the layered import one-way).
    from freesearch.persistence.otel_exporter import SQLiteSpanExporter

    return [BatchSpanProcessor(SQLiteSpanExporter(database))]


def build_observability(settings: Settings, *, database: Path | None) -> ObservabilityRuntime:
    """Build the app-scoped runtime, or the no-op runtime when unavailable.

    Called by ``create_app`` once a trace database is known. A processor
    failure (unwritable database) disables tracing for the process instead of
    failing the application.
    """

    if database is None:
        return NO_OP_OBSERVABILITY
    try:
        processors = build_span_processors(settings, database)
    except Exception:
        logger.warning("could not build the trace exporter; tracing disabled", exc_info=False)
        return NO_OP_OBSERVABILITY
    if not processors:
        return NO_OP_OBSERVABILITY
    provider = TracerProvider(
        resource=Resource.create({"service.name": settings.otel_service_name})
    )
    for processor in processors:
        provider.add_span_processor(processor)
    return OtelObservability(provider.get_tracer("freesearch"), provider)


__all__ = [
    "DEFAULT_FLUSH_TIMEOUT_MILLIS",
    "NO_OP_OBSERVABILITY",
    "NO_OP_SPAN",
    "AttributeValue",
    "NoOpObservability",
    "ObservabilityRuntime",
    "OtelObservability",
    "SpanHandle",
    "SpanKindName",
    "build_observability",
    "build_span_processors",
    "current_observability",
    "error_type_of",
    "is_sensitive_key",
    "trace_content_attributes",
    "use_observability",
]
