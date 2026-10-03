"""Selective inbound root-span middleware: provider calls only.

Only the exact ``(method, path)`` pairs handed to
:class:`ProviderTraceMiddleware` receive a root server span — today
``POST /search`` and ``POST /fetch``. Monitoring reads (``/stats``,
``/dashboard``), the trace read API (``/api/v1/traces``), health/control
routes, and static UI requests are never traced.

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
import logging
from collections.abc import Awaitable, Callable, Mapping
from contextlib import ExitStack
from typing import Any

from freesearch.infrastructure.observability import (
    ObservabilityRuntime,
    SpanHandle,
    SpanKindName,
    use_observability,
)
from freesearch.models.observability import (
    TRACE_SCHEMA_VERSION,
    TraceAttribute,
    TraceSpanName,
)

logger = logging.getLogger(__name__)

Scope = dict[str, Any]
Message = dict[str, Any]
Receive = Callable[[], Awaitable[Message]]
Send = Callable[[Message], Awaitable[None]]
ASGIApp = Callable[[Scope, Receive, Send], Awaitable[None]]
RuntimeGetter = Callable[[], ObservabilityRuntime]

TRACE_HEADER: str = "x-trace-id"
# Bounded wait: observability must never hold a user response hostage.
FLUSH_TIMEOUT_MILLIS: int = 500


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
        await _flush(self._runtime)


async def _flush(runtime: ObservabilityRuntime) -> None:
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
                with runtime.span(
                    span_name,
                    kind=SpanKindName.SERVER,
                    attributes=self._request_attributes(scope),
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
        """Root attributes: HTTP semantic conventions plus the schema version.

        The operation is the traced route's first path segment, so a request
        failing routing before its handler runs still gets a filterable
        Activity row.
        """

        path = str(scope.get("path", ""))
        operation = path.strip("/").split("/")[0]
        return {
            TraceAttribute.SCHEMA_VERSION: TRACE_SCHEMA_VERSION,
            TraceAttribute.HTTP_REQUEST_METHOD: str(scope.get("method", "")).upper(),
            TraceAttribute.HTTP_ROUTE: path,
            TraceAttribute.URL_PATH: path,
            TraceAttribute.OPERATION: operation or None,
        }


__all__ = ["FLUSH_TIMEOUT_MILLIS", "TRACE_HEADER", "ProviderTraceMiddleware"]
