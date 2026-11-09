"""Selective inbound root-span middleware: provider calls only.

Only the exact ``(method, path)`` pairs handed to
:class:`ProviderTraceMiddleware` receive a root server span — today
``POST /search`` and ``POST /fetch``. Monitoring reads (``/stats``,
``/dashboard``), the project trace read API
(``/api/v1/projects/{project_id}/traces``), health/control routes, and static UI
requests are never traced.

Responsibilities:

* open the root span for the traced request (low-cardinality route template),
* bind the app runtime for the request so handlers/adapters can add children,
* inject ``X-Trace-Id: <32-lowercase-hex>`` into ``http.response.start``,
  including handled error responses,
* close the response child span before the final response body is handed to the
  server, then force-flush once — off the event loop, bounded, and
  failure-safe — after the root span ends, so the persisted trace is queryable
  by the time the caller can act on the response.

The flush is deliberately issued exactly once, after the root span has ended:
spans are exported by a batch processor, which only exports *finished* spans, so
a flush taken while the root is still open could carry children but never the
trace's summary row. Flushing before the last body byte would therefore buy no
visibility while holding the caller's response open.
"""

import asyncio
import hashlib
import hmac
import logging
import time
from collections.abc import Awaitable, Callable, Mapping
from contextlib import ExitStack
from typing import Any

from polyweb.infrastructure.observability import (
    ObservabilityRuntime,
    SpanHandle,
    SpanKindName,
    use_observability,
)
from polyweb.models.observability import (
    TRACE_SCHEMA_VERSION,
    TraceAttribute,
    TraceSpanName,
)
from polyweb.models.projects import ProjectApiKeyPrincipal
from polyweb.models.users import UserPrincipal

logger = logging.getLogger(__name__)

Scope = dict[str, Any]
Message = dict[str, Any]
Receive = Callable[[], Awaitable[Message]]
Send = Callable[[Message], Awaitable[None]]
ASGIApp = Callable[[Scope, Receive, Send], Awaitable[None]]
RuntimeGetter = Callable[[], ObservabilityRuntime]

TRACE_HEADER: str = "x-trace-id"
PARENT_SPAN_HEADER: str = "x-polyweb-parent-span-id"
FORWARD_SIGNATURE_HEADER: str = "x-polyweb-forward-signature"
FORWARD_TIMESTAMP_HEADER: str = "x-polyweb-forwarded-at"
INGRESS_MONOTONIC_STATE_KEY: str = "polyweb_ingress_monotonic"
#: Bounded wait: observability must never hold a user response hostage.
FLUSH_TIMEOUT_MILLIS: int = 500
#: A forwarded trace envelope older than this is rejected as a replay.
FORWARD_ENVELOPE_SECONDS: int = 60


def _strict_hex(value: str | None, length: int) -> str | None:
    """Return one non-zero lowercase hex identifier of exactly ``length``."""

    if value is None or len(value) != length or value != value.lower():
        return None
    if any(character not in "0123456789abcdef" for character in value):
        return None
    return value if int(value, 16) > 0 else None


def forwarded_trace_payload(
    *,
    trace_id: str,
    parent_span_id: str,
    project_id: str,
    timestamp: int,
    method: str,
    path: str,
) -> str:
    """Return the canonical signed material of one forwarding envelope."""

    return "\n".join((trace_id, parent_span_id, project_id, str(timestamp), method.upper(), path))


def sign_forwarded_trace(
    credential: str,
    *,
    trace_id: str,
    parent_span_id: str,
    project_id: str,
    timestamp: int,
    method: str,
    path: str,
) -> str:
    """Sign a forwarding envelope with the verified project credential."""

    payload = forwarded_trace_payload(
        trace_id=trace_id,
        parent_span_id=parent_span_id,
        project_id=project_id,
        timestamp=timestamp,
        method=method,
        path=path,
    )
    return hmac.new(credential.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()


class IngressDeadlineMiddleware:
    """Stamp the arrival instant before authentication and body processing."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope.get("type") == "http":
            state = scope.get("state")
            if not isinstance(state, dict):
                state = {}
                scope["state"] = state
            state.setdefault(INGRESS_MONOTONIC_STATE_KEY, time.monotonic())
        await self.app(scope, receive, send)


class _ResponseRecorder:
    """Owns the root/response spans of one traced request across ``send`` calls."""

    def __init__(self, runtime: ObservabilityRuntime, root: SpanHandle) -> None:
        self._runtime = runtime
        self._root = root
        self._stack: ExitStack | None = None
        self._finished = False

    def wrap(self, send: Send) -> Send:
        """Return a ``send`` that records the response stage and headers."""

        async def _send(message: Message) -> None:
            if message.get("type") == "http.response.start":
                self._start_response(message)
                await send(message)
                return
            if message.get("type") == "http.response.body" and not message.get("more_body", False):
                await self._finish_response()
            await send(message)

        return _send

    def _start_response(self, message: Message) -> None:
        status = message.get("status")
        if isinstance(status, int):
            self._root.set_attributes({TraceAttribute.HTTP_RESPONSE_STATUS_CODE: status})
        self._inject_trace_id(message)
        self._stack = ExitStack()
        self._stack.enter_context(
            self._runtime.span(
                TraceSpanName.RESPONSE,
                attributes={TraceAttribute.HTTP_RESPONSE_STATUS_CODE: status},
            )
        )

    def _inject_trace_id(self, message: Message) -> None:
        trace_id = self._root.trace_id
        if trace_id is None:
            return
        headers = [
            (name, value)
            for name, value in message.get("headers") or []
            if name.lower() != TRACE_HEADER.encode("ascii")
        ]
        headers.append((TRACE_HEADER.encode("ascii"), trace_id.encode("ascii")))
        message["headers"] = headers

    async def _finish_response(self) -> None:
        """End the response child before the last bytes are handed to the server.

        No flush here: the single bounded flush belongs to :meth:`finish`, after
        the root span has ended — see the module docstring.
        """

        if self._stack is not None:
            self._stack.close()
            self._stack = None

    async def finish(self) -> None:
        """End any open response child and force-flush exactly once per request."""

        if self._finished:
            return
        self._finished = True
        if self._stack is not None:
            self._stack.close()
            self._stack = None
        await flush_traces(self._runtime)


async def flush_traces(runtime: ObservabilityRuntime) -> None:
    """Force-flush the batch processor without blocking the event loop."""

    try:
        await asyncio.to_thread(runtime.force_flush, FLUSH_TIMEOUT_MILLIS)
    except Exception:  # pragma: no cover - defensive, mirrors the facade's contract
        logger.warning("trace flush skipped", exc_info=False)


class ProviderTraceMiddleware:
    """ASGI middleware tracing only the configured provider-querying routes."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        runtime_getter: RuntimeGetter,
        traced_routes: Mapping[tuple[str, str], str],
    ) -> None:
        self.app = app
        self._runtime_getter = runtime_getter
        self._traced_routes = {
            (method.upper(), path): name for (method, path), name in traced_routes.items()
        }

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        span_name = self._root_span_name(scope)
        if span_name is None:
            await self.app(scope, receive, send)
            return
        runtime = self._runtime_getter()
        recorder: _ResponseRecorder | None = None
        with use_observability(runtime):
            try:
                trace_id, parent_span_id = trusted_trace_parent(scope) or (None, None)
                with runtime.span(
                    span_name,
                    kind=SpanKindName.SERVER,
                    attributes=self._request_attributes(scope),
                    trace_id=trace_id,
                    parent_span_id=parent_span_id,
                ) as root:
                    recorder = _ResponseRecorder(runtime, root)
                    await self.app(scope, receive, recorder.wrap(send))
            finally:
                if recorder is not None:
                    await recorder.finish()

    def _root_span_name(self, scope: Scope) -> str | None:
        """Return the root span name for a traced request, else ``None``."""

        if scope.get("type") != "http":
            return None
        method = str(scope.get("method", "")).upper()
        path = str(scope.get("path", ""))
        return self._traced_routes.get((method, path))

    @staticmethod
    def _request_attributes(scope: Scope) -> dict[str, object]:
        """Root attributes: HTTP semantic conventions, schema version, account.

        The operation is the traced route's first path segment, so a request
        failing routing before its handler runs still gets a filterable
        Activity row. The account UUID comes from the verified principal that
        the transport guard stored in ASGI state, so the root itself carries the
        owner that every later read checks.
        """

        path = str(scope.get("path", ""))
        operation = path.strip("/").split("/")[0]
        return {
            TraceAttribute.SCHEMA_VERSION: TRACE_SCHEMA_VERSION,
            TraceAttribute.HTTP_REQUEST_METHOD: str(scope.get("method", "")).upper(),
            TraceAttribute.HTTP_ROUTE: path,
            TraceAttribute.URL_PATH: path,
            TraceAttribute.OPERATION: operation or None,
            TraceAttribute.USER_ID: principal_id(scope),
        }


def _header(scope: Scope, name: str) -> str | None:
    """Return one header value decoded strictly as ASCII."""

    target = name.encode("ascii")
    values = [value for header, value in (scope.get("headers") or []) if header.lower() == target]
    if len(values) != 1 or not isinstance(values[0], (bytes, bytearray)):
        return None
    try:
        return bytes(values[0]).decode("ascii")
    except (UnicodeDecodeError, AttributeError):
        return None


def incoming_trace_id(scope: Scope) -> str | None:
    """Return a well-formed inbound ``x-trace-id``, without trusting it.

    Shape validation is not provenance: callers that continue a trace must use
    :func:`trusted_trace_parent`, which also verifies the forwarding signature.
    """

    return _strict_hex(_header(scope, TRACE_HEADER), 32)


def trusted_trace_parent(scope: Scope) -> tuple[str, str] | None:
    """Return ``(trace_id, parent_span_id)`` for a trusted forwarding hop.

    Continuation requires all of: a verified project API key on this request,
    a signed envelope bound to that key and project, a fresh timestamp, and
    strict hexadecimal trace/parent ids. An ordinary REST caller's trace header
    (with no valid forwarding provenance) starts a fresh root instead.
    """

    if scope.get("type") != "http":
        return None
    state = scope.get("state")
    if not isinstance(state, dict):
        return None
    principal = state.get("user")
    credential = state.get("forwarding_credential")
    if not isinstance(principal, ProjectApiKeyPrincipal) or not isinstance(credential, str):
        return None
    trace_id = _strict_hex(_header(scope, TRACE_HEADER), 32)
    parent_span_id = _strict_hex(_header(scope, PARENT_SPAN_HEADER), 16)
    signature = _strict_hex(_header(scope, FORWARD_SIGNATURE_HEADER), 64)
    timestamp_raw = _header(scope, FORWARD_TIMESTAMP_HEADER)
    if trace_id is None or parent_span_id is None or signature is None:
        return None
    try:
        timestamp = int(timestamp_raw or "")
    except (TypeError, ValueError):
        return None
    if abs(int(time.time()) - timestamp) > FORWARD_ENVELOPE_SECONDS:
        return None
    expected = sign_forwarded_trace(
        credential,
        trace_id=trace_id,
        parent_span_id=parent_span_id,
        project_id=str(principal.project_id),
        timestamp=timestamp,
        method=str(scope.get("method", "")),
        path=str(scope.get("path", "")),
    )
    if not hmac.compare_digest(signature, expected):
        return None
    return trace_id, parent_span_id


def principal_id(scope: Scope) -> str | None:
    """Return the verified account UUID of a guarded scope, else ``None``.

    Only the principal the guard verified counts. A client header, a query
    parameter, or a body value never reaches this state cell.
    """

    state = scope.get("state")
    principal = state.get("user") if isinstance(state, dict) else None
    return str(principal.id) if isinstance(principal, UserPrincipal) else None


__all__ = [
    "FLUSH_TIMEOUT_MILLIS",
    "FORWARD_SIGNATURE_HEADER",
    "FORWARD_TIMESTAMP_HEADER",
    "INGRESS_MONOTONIC_STATE_KEY",
    "PARENT_SPAN_HEADER",
    "TRACE_HEADER",
    "IngressDeadlineMiddleware",
    "ProviderTraceMiddleware",
    "flush_traces",
    "forwarded_trace_payload",
    "incoming_trace_id",
    "principal_id",
    "sign_forwarded_trace",
    "trusted_trace_parent",
]
