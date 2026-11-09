"""App-scoped OpenTelemetry facade: the only module importing the OTel SDK.

The application never imports ``opentelemetry.*`` in routers, services, or
adapters. Everything instrumented code needs is behind
:class:`ObservabilityRuntime`:

* ``span(name, kind=..., attributes=...)`` — a context manager yielding a
  :class:`SpanHandle`; an exception propagating through it marks the span
  ``ERROR``, records ``error.type`` and exactly one ``exception`` event that
  carries only the error type (never the message or stack trace), then
  re-raises unchanged.
* ``annotate_root(...)`` — attaches the request/response projection to the
  inbound root span (the exporter's summary source).
* ``bind_execution_attribution(...)`` / ``bind_trace_capture(...)`` — stamp the
  trusted ownership and the immutable trace-policy decision that the execution
  boundary resolved once for the request.
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
    NonRecordingSpan,
    Span,
    SpanContext,
    SpanKind,
    Status,
    StatusCode,
    TraceFlags,
    Tracer,
    format_trace_id,
    get_current_span,
    set_span_in_context,
)

from polyweb.configuration.config import Settings
from polyweb.models.observability import (
    INTERNAL_ATTRIBUTES,
    TRACE_CONTENT_ATTRIBUTES,
    TRACE_SAFE_EVENT_ATTRIBUTES,
    TRACE_SCHEMA_VERSION,
    ExecutionAttribution,
    TraceAttribute,
)
from polyweb.models.projects import ProjectTracePolicy

logger = logging.getLogger(__name__)

type AttributeValue = str | bool | int | float | list[AttributeValue] | None
"""Serializable span/event attribute value accepted by the facade."""

DEFAULT_FLUSH_TIMEOUT_MILLIS: int = 5_000
_MAX_JSON_TEXT_CHARS = 3_000_000
_OMITTED_JSON = "[JSON content omitted: capture limit exceeded]"

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


def _scrub_json_text(value: str) -> str:
    """Scrub JSON containers in text; never buffer oversized JSON candidates."""

    if not value.lstrip().startswith(("{", "[")):
        return value
    if len(value) > _MAX_JSON_TEXT_CHARS:
        return _OMITTED_JSON
    try:
        decoded = json.loads(value)
    except json.JSONDecodeError:
        return value
    except (RecursionError, ValueError):
        return _OMITTED_JSON
    try:
        cleaned = _redact(decoded, json_mode=True)
        return json.dumps(cleaned) if cleaned != decoded else value
    except (RecursionError, ValueError):
        return _OMITTED_JSON


def _redact(value: object, *, json_mode: bool = False) -> AttributeValue:
    """Coerce one value into a serializable, credential-free attribute value.

    Mappings and sequences are filtered recursively with the same
    credential-key rule as their parent, so a credential nested inside a
    provider result list never reaches the span buffer. A non-serializable
    leaf is stringified; a value that cannot be traversed still cannot carry
    a keyed credential, because only its scalar form survives.
    """

    if isinstance(value, str):
        return _scrub_json_text(value)
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, Mapping):
        return cast(AttributeValue, trace_content_attributes(value, json_mode=json_mode))
    if isinstance(value, (list, tuple)):
        entries = [_redact(entry, json_mode=json_mode) for entry in value]
        return entries if json_mode else [item for item in entries if item is not None]
    return str(value)


def trace_content_attributes(
    payload: Mapping[str, object], *, json_mode: bool = False
) -> dict[str, AttributeValue]:
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
            nested = trace_content_attributes(value, json_mode=json_mode)
            if nested or json_mode:
                attributes[name] = cast(AttributeValue, nested)
            continue
        if isinstance(value, (list, tuple)):
            attributes[name] = [_redact(item, json_mode=json_mode) for item in value]
            continue
        redacted = _redact(value, json_mode=json_mode)
        if redacted is not None or json_mode:
            attributes[name] = redacted
    return attributes


def _otel_attributes(attributes: dict[str, AttributeValue]) -> dict[str, AttributeValue]:
    """Encode nested values because the OTel SDK only accepts scalar arrays."""

    return {
        key: (
            json.dumps(value, ensure_ascii=False)
            if isinstance(value, Mapping)
            or (
                isinstance(value, list) and any(isinstance(item, (Mapping, list)) for item in value)
            )
            else value
        )
        for key, value in attributes.items()
    }


def _payload_capture_allowed() -> bool:
    """Return whether the bound policy lets this span keep payload content.

    Capture is metadata-only until the execution boundary binds a policy that
    permits full detail. Without a bound policy the answer is ``False``, so a
    database or request that never resolved a policy can never buffer content.
    """

    cell = _ATTRIBUTION_CELL.get()
    return cell is not None and cell.policy is not None and cell.policy.captures_payload


def _span_attributes(attributes: Mapping[str, object] | None) -> dict[str, AttributeValue]:
    """Drop ``None``/internal keys, apply the capture policy, then redact.

    ``INTERNAL_ATTRIBUTES`` are stripped from every caller-supplied mapping so
    only the trusted binders can stamp ownership and capture decisions. Content
    keys are dropped here — at capture time — when the bound project policy is
    metadata-only, so they never reach the finished-span buffer.
    """

    if attributes is None:
        return {}
    capture = _payload_capture_allowed()
    return _otel_attributes(
        trace_content_attributes(
            {
                key: value
                for key, value in attributes.items()
                if value is not None
                and key not in INTERNAL_ATTRIBUTES
                and (capture or key not in TRACE_CONTENT_ATTRIBUTES)
            }
        )
    )


def _event_attributes(attributes: Mapping[str, object] | None) -> dict[str, AttributeValue]:
    """Filter one span event at capture time.

    Provider request/response events carry content under provider-native keys
    (``query``, ``url``, ``results``), so the span-attribute content allowlist
    cannot identify them. Under metadata-only capture, keep
    only the documented request-shape/count keys; under full capture keep the
    documented content but still apply the credential-shaped redaction hook.
    Internal decision keys never reach an event.
    """

    if attributes is None:
        return {}
    capture = _payload_capture_allowed()
    return _otel_attributes(
        trace_content_attributes(
            {
                key: value
                for key, value in attributes.items()
                if value is not None
                and key not in INTERNAL_ATTRIBUTES
                and (capture or key in TRACE_SAFE_EVENT_ATTRIBUTES)
            }
        )
    )


def _ownership_attributes(attribution: ExecutionAttribution) -> dict[str, str]:
    """Render one attribution as the three trusted span ownership keys."""

    return {
        TraceAttribute.PROJECT_ID: str(attribution.project_id),
        TraceAttribute.ACTOR_TYPE: attribution.actor_type.value,
        TraceAttribute.ACTOR_ID: str(attribution.actor_id),
    }


def _capture_attributes(policy: ProjectTracePolicy) -> dict[str, bool]:
    """Render one immutable capture decision for the trace this span belongs to."""

    return {
        TraceAttribute.CAPTURE_PAYLOAD: policy.captures_payload,
    }


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
        trace_id: str | None = None,
        parent_span_id: str | None = None,
    ) -> AbstractContextManager[SpanHandle]: ...

    def annotate_root(self, attributes: Mapping[str, object]) -> None: ...

    def current_trace_id(self) -> str | None: ...

    def current_span_id(self) -> str | None: ...

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
        trace_id: str | None = None,
        parent_span_id: str | None = None,
    ) -> Iterator[SpanHandle]:
        del name, kind, attributes, trace_id, parent_span_id
        yield NO_OP_SPAN

    def annotate_root(self, attributes: Mapping[str, object]) -> None:
        del attributes

    def current_trace_id(self) -> str | None:
        return None

    def current_span_id(self) -> str | None:
        return None

    def force_flush(self, timeout_millis: int = DEFAULT_FLUSH_TIMEOUT_MILLIS) -> bool:
        del timeout_millis
        return True

    def shutdown(self) -> None:
        return None


NO_OP_OBSERVABILITY = NoOpObservability()

_CURRENT_RUNTIME: ContextVar[ObservabilityRuntime] = ContextVar(
    "polyweb_observability_runtime", default=NO_OP_OBSERVABILITY
)
_ROOT_SPAN: ContextVar[SpanHandle | None] = ContextVar("polyweb_root_span", default=None)
_EXCEPTION_RECORDED: ContextVar[bool] = ContextVar("polyweb_exception_recorded", default=False)


class _AttributionCell:
    """Per-request mutable holder for the bound ownership and capture decisions.

    Fanout tasks inherit the same cell object through their context copy, so a
    binding made by the request handler is visible to every child span started
    afterwards, wherever it runs.
    """

    __slots__ = ("attribution", "policy")

    def __init__(self) -> None:
        self.attribution: ExecutionAttribution | None = None
        self.policy: ProjectTracePolicy | None = None


_ATTRIBUTION_CELL: ContextVar[_AttributionCell | None] = ContextVar(
    "polyweb_attribution_cell", default=None
)


class _AttributionSpanProcessor(SpanProcessor):
    """Stamp the bound ownership and capture decisions on every span at start.

    Registered before the exporter processors so each span carries the trusted
    project/actor identity and its immutable payload decision from its first
    instant. Unattributed spans are not persisted; spans without a payload
    decision are stored as metadata only.
    """

    def on_start(self, span: Span, parent_context: Any = None) -> None:
        cell = _ATTRIBUTION_CELL.get()
        if cell is None:
            return
        stamped: dict[str, object] = {}
        if cell.attribution is not None:
            stamped.update(_ownership_attributes(cell.attribution))
        if cell.policy is not None:
            context = span.get_span_context()
            if context.is_valid:
                stamped.update(_capture_attributes(cell.policy))
        if stamped:
            span.set_attributes(cast("Mapping[str, Any]", stamped))


def bind_execution_attribution(attribution: ExecutionAttribution) -> None:
    """Bind the verified execution identity to the current request's spans.

    Without an active observability scope this is a no-op. Rebinding the same
    attribution is idempotent; a different attribution fails closed. The live
    root span is stamped through the trusted handle path so a REST root opened
    before the handler resolved its scope still carries ownership.
    """

    cell = _ATTRIBUTION_CELL.get()
    if cell is None:
        return
    if cell.attribution is not None:
        if cell.attribution != attribution:
            raise ValueError("execution attribution is already bound to a different identity")
        return
    cell.attribution = attribution
    root = _ROOT_SPAN.get()
    if isinstance(root, _OtelSpan):
        root._stamp_ownership(attribution)


def bind_trace_capture(policy: ProjectTracePolicy) -> None:
    """Bind the project's resolved trace policy to the current request's spans.

    Resolved once at the trusted execution boundary, so a later settings edit
    cannot change an in-flight trace, and every child sees the same detail
    decision. Rebinding the same policy is idempotent; a different policy
    fails closed. Without an active observability scope this is a no-op.
    """

    cell = _ATTRIBUTION_CELL.get()
    if cell is None:
        return
    if cell.policy is not None:
        if cell.policy != policy:
            raise ValueError("trace policy is already bound to a different project policy")
        return
    cell.policy = policy
    root = _ROOT_SPAN.get()
    if isinstance(root, _OtelSpan):
        root._stamp_capture(policy)


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

    def _stamp_ownership(self, attribution: ExecutionAttribution) -> None:
        """Set the three ownership keys verbatim; internal to the binder only."""

        with _swallow():
            self._span.set_attributes(cast("Mapping[str, Any]", _ownership_attributes(attribution)))

    def _stamp_capture(self, policy: ProjectTracePolicy) -> None:
        """Set the capture decision verbatim; internal to the binder only."""

        trace_id = self.trace_id
        if trace_id is None:
            return
        with _swallow():
            self._span.set_attributes(cast("Mapping[str, Any]", _capture_attributes(policy)))

    def add_event(self, name: str, attributes: Mapping[str, object] | None = None) -> None:
        with _swallow():
            self._span.add_event(
                name, attributes=cast("Mapping[str, Any]", _event_attributes(attributes))
            )

    def record_exception(self, error: BaseException) -> None:
        """Record a sanitized ``exception`` event, then mark the span failed.

        Only the low-cardinality error type is kept: an arbitrary exception
        message or stack trace can embed a query, a provider response body, or a
        credential, and trace events are persisted. The span's ``error.type``
        and status carry the failure for Activity.
        """

        with _swallow():
            self._span.add_event("exception", attributes={"exception.type": error_type_of(error)})
        self.mark_error(error)

    def mark_error(self, error: BaseException) -> None:
        """Mark the span failed without adding a second ``exception`` event."""

        with _swallow():
            self._span.set_attribute(TraceAttribute.ERROR_TYPE, error_type_of(error))
            self._span.set_status(Status(StatusCode.ERROR))


def _remote_parent(trace_id: str | None, parent_span_id: str | None) -> Any | None:
    """Build an OTel parent context for a verified remote parent span.

    Both ids must be well-formed nonzero lowercase hex: the trace (32) and the
    real parent span (16). A missing/invalid parent starts a fresh root rather
    than inventing a synthetic span id that Activity cannot resolve.
    """

    if trace_id is None or len(trace_id) != 32 or trace_id != trace_id.lower():
        return None
    if (
        parent_span_id is None
        or len(parent_span_id) != 16
        or parent_span_id != parent_span_id.lower()
    ):
        return None
    try:
        parsed_trace = int(trace_id, 16)
        parsed_span = int(parent_span_id, 16)
    except ValueError:
        return None
    if parsed_trace <= 0 or parsed_span <= 0:
        return None
    context = SpanContext(
        trace_id=parsed_trace,
        span_id=parsed_span,
        is_remote=True,
        trace_flags=TraceFlags(TraceFlags.SAMPLED),
    )
    return set_span_in_context(NonRecordingSpan(context))


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
        trace_id: str | None = None,
        parent_span_id: str | None = None,
    ) -> Iterator[SpanHandle]:
        initial: dict[str, object] = {TraceAttribute.SCHEMA_VERSION: TRACE_SCHEMA_VERSION}
        initial.update(attributes or {})
        parent = _remote_parent(trace_id, parent_span_id) if kind is SpanKindName.SERVER else None
        with self._tracer.start_as_current_span(
            name,
            kind=_SPAN_KINDS[kind],
            attributes=cast("Mapping[str, Any]", _span_attributes(initial)),
            context=parent,
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

    def current_span_id(self) -> str | None:
        context = get_current_span().get_span_context()
        return format(context.span_id, "016x") if context.is_valid else None

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
    attribution_token = _ATTRIBUTION_CELL.set(_AttributionCell())
    try:
        yield
    finally:
        _ATTRIBUTION_CELL.reset(attribution_token)
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
    from polyweb.persistence.otel_exporter import SQLiteSpanExporter

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
    # The attribution processor runs first so ownership lands on every span at
    # start, before any exporter ever sees the finished span.
    provider.add_span_processor(_AttributionSpanProcessor())
    for processor in processors:
        provider.add_span_processor(processor)
    return OtelObservability(provider.get_tracer("polyweb"), provider)


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
    "bind_execution_attribution",
    "bind_trace_capture",
    "build_observability",
    "build_span_processors",
    "current_observability",
    "error_type_of",
    "is_sensitive_key",
    "trace_content_attributes",
    "use_observability",
]
