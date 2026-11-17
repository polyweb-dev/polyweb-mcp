"""The common request pipeline in front of every provider handler.

For one request the pipeline:

1. reads the body and draws the fault plan for ``(provider, operation)``;
2. authenticates the presented key against the key table, or admits the
   keyless rail within its budget;
3. sleeps the stacked latency, then lets a fault outcome replace the
   response (outage, HTTP error, rate limit, quota, invalid key, timeout,
   connection drop), or runs the handler; credit exhaustion from
   :meth:`OperationContext.charge` becomes the provider's quota error;
4. damages a successful body for a ``malformed`` fault;
5. writes the request log without secrets: no presented key, no auth or
   cookie header, no token, secret, or key field of a body, no JWT-shaped
   string, and no body at all for an operation with ``log_body=False``.

A ``timeout`` fault holds the request for its ``seconds`` (default
:data:`DEFAULT_TIMEOUT_SECONDS`, longer than Polyweb's 20 second default
``POLYWEB_HTTP_TIMEOUT_SECONDS``) and then closes the connection without a
response, as an upstream that never answers does. Only a rule with an
explicit ``status`` answers after the hold, with that status in the
provider's format (for example 504).
"""

import asyncio
import json
import logging
import random
import re
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Final

from fastapi import FastAPI
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import Receive, Scope, Send

from polyweb_provider_mock.faults import FaultKind, FaultRule, MalformedVariant
from polyweb_provider_mock.providers.base import (
    Credentials,
    ErrorContext,
    ErrorKind,
    MockResponse,
    Operation,
    OperationContext,
    ProviderPlugin,
    kind_for_status,
)
from polyweb_provider_mock.store import MockStore, Principal, QuotaExhausted

__all__ = [
    "DEFAULT_TIMEOUT_SECONDS",
    "REDACTED",
    "TRANSPORT_STATE_KEY",
    "build_provider_app",
    "redact_body",
]

logger = logging.getLogger(__name__)

#: ``scope["state"]`` key under which the dispatcher stores the server transport.
TRANSPORT_STATE_KEY: Final = "polyweb_mock_transport"
#: How long a ``timeout`` fault without ``seconds`` holds the request.
DEFAULT_TIMEOUT_SECONDS: Final = 30.0
#: The value that replaces a secret in the request log.
REDACTED: Final = "<redacted>"

#: Request header, query, and body names whose values are never logged.
_SENSITIVE = ("authorization", "key", "token", "secret", "cookie", "subscription", "password")
#: Response body fields (lowercase, letters and digits only) that hold secrets.
_SECRET_FIELDS = frozenset(
    {
        "accesstoken",
        "apikey",
        "authorization",
        "clientsecret",
        "cookie",
        "devicecode",
        "idtoken",
        "key",
        "password",
        "privatekey",
        "rawapikey",
        "refreshtoken",
        "secret",
        "setcookie",
        "subscriptiontoken",
        "token",
        "xapikey",
    }
)
_SECRET_SUFFIXES = ("secret", "password", "token", "apikey")
_JWT = re.compile(r"eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}")
_BODY_LOG_LIMIT = 4096
_RESPONSE_LOG_LIMIT = 512 * 1024
_DEFAULT_RETRY_AFTER = 60


def _sensitive(name: str) -> bool:
    lowered = name.lower()
    return any(part in lowered for part in _SENSITIVE)


def _secret_field(name: str) -> bool:
    normalized = "".join(char for char in name.lower() if char.isalnum())
    return normalized in _SECRET_FIELDS or normalized.endswith(_SECRET_SUFFIXES)


def _redacted(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: REDACTED if _sensitive(str(key)) else _redacted(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redacted(item) for item in value]
    return value


def _scrub_text(text: str, secrets: tuple[str, ...]) -> str:
    for secret in secrets:
        text = text.replace(secret, REDACTED)
    return _JWT.sub(REDACTED, text)


def _scrub(value: Any, secrets: tuple[str, ...]) -> Any:
    if isinstance(value, dict):
        return {
            key: REDACTED if _secret_field(str(key)) and item is not None else _scrub(item, secrets)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_scrub(item, secrets) for item in value]
    if isinstance(value, str):
        return _scrub_text(value, secrets)
    return value


def redact_body(data: bytes, secrets: tuple[str, ...] = ()) -> str:
    """Return a response body for the request log with every secret replaced.

    JSON bodies lose the values of secret fields (``access_token``,
    ``refresh_token``, ``raw_api_key``, ``client_secret``, ``key``, ...);
    every body loses JWT-shaped strings and the given ``secrets`` (the
    presented key).
    """

    text = data.decode("utf-8", errors="replace")
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return _scrub_text(text, secrets)
    return json.dumps(_scrub(parsed, secrets), ensure_ascii=False, separators=(",", ":"))


def _summary(request: Request, raw_body: bytes, *, log_body: bool) -> dict[str, Any]:
    """Return a log-safe request summary: no key, token, or secret values."""

    headers = {
        name: REDACTED if _sensitive(name) else value
        for name, value in request.headers.items()
        if name not in {"content-length", "connection", "accept-encoding"}
    }
    body: Any = None
    if raw_body and not log_body:
        body = {"bytes": len(raw_body), "logged": False}
    elif raw_body:
        try:
            parsed = _scrub(_redacted(json.loads(raw_body)), ())
            text = json.dumps(parsed, ensure_ascii=False)
            body = parsed if len(text) <= _BODY_LOG_LIMIT else text[:_BODY_LOG_LIMIT]
        except (json.JSONDecodeError, UnicodeDecodeError):
            body = {"bytes": len(raw_body), "content_type": request.headers.get("content-type")}
    return {
        "method": request.method,
        "path": request.url.path,
        "query": _redacted(dict(request.query_params)),
        "headers": headers,
        "body": body,
    }


@dataclass(frozen=True)
class _Auth:
    principal: Principal
    label: str
    error: MockResponse | None = None


def _authenticate(
    plugin: ProviderPlugin,
    operation: Operation,
    store: MockStore,
    credentials: Credentials,
    request: Request,
) -> _Auth:
    anonymous = Principal(provider=plugin.name)

    def fail(kind: ErrorKind, label: str, principal: Principal = anonymous, **values: Any) -> _Auth:
        context = ErrorContext(
            operation=operation.name,
            store=store,
            account=principal.account,
            request=request,
            presented_key=credentials.key,
            **values,
        )
        return _Auth(principal, label, plugin.error(kind, context))

    if operation.auth == "none":
        return _Auth(anonymous, "anonymous")
    if credentials.key is not None:
        principal = store.resolve(plugin.name, credentials.key)
        if principal is None or principal.key is None:
            return fail(ErrorKind.AUTH_INVALID, "invalid-key")
        if principal.key.status == "revoked":
            return fail(ErrorKind.AUTH_REVOKED, principal.label, principal)
        if operation.scopes and not operation.scopes & set(principal.key.scopes):
            scope = ",".join(operation.scopes)
            return fail(ErrorKind.FORBIDDEN, principal.label, principal, scope=scope)
        return _Auth(principal, principal.label)
    if credentials.keyless and operation.keyless:
        setting = store.keyless(plugin.name)
        if setting is None or not setting.enabled:
            return fail(ErrorKind.AUTH_INVALID, "keyless", keyless=True, missing_key=True)
        limited = store.keyless_retry_after(plugin.name)
        if limited is not None:
            window, seconds = limited
            return fail(
                ErrorKind.RATE_LIMITED, "keyless", keyless=True, scope=window, retry_after=seconds
            )
        return _Auth(Principal(provider=plugin.name, keyless=True), "keyless")
    return fail(
        ErrorKind.AUTH_INVALID, "missing-key", missing_key=True, keyless=credentials.keyless
    )


def _fault_kind(rule: FaultRule) -> tuple[ErrorKind, int | None]:
    params = rule.params
    if rule.kind is FaultKind.HTTP_ERROR:
        status = params.status or 500
        return kind_for_status(status), status
    if rule.kind is FaultKind.OUTAGE:
        status = params.status or 503
        return kind_for_status(status), status
    fixed = {
        FaultKind.RATE_LIMIT: ErrorKind.RATE_LIMITED,
        FaultKind.QUOTA_EXHAUSTED: ErrorKind.QUOTA_EXHAUSTED,
        FaultKind.AUTH_INVALID: ErrorKind.AUTH_INVALID,
    }
    if rule.kind in fixed:
        return fixed[rule.kind], params.status
    status = params.status or 504
    return kind_for_status(status), status


def _fault_response(
    plugin: ProviderPlugin, operation: Operation, rule: FaultRule, base: ErrorContext
) -> MockResponse:
    """Return the provider-format response that a fault rule forces."""

    params = rule.params
    kind, status = _fault_kind(rule)
    retry_after = None
    if kind is ErrorKind.RATE_LIMITED:
        retry_after = params.retry_after if params.retry_after is not None else _DEFAULT_RETRY_AFTER
    context = ErrorContext(
        operation=operation.name,
        status=status,
        message=params.message,
        retry_after=retry_after,
        retry_after_header=params.retry_after_header,
        keyless=base.keyless,
        scope=params.scope,
        store=base.store,
        account=base.account,
        request=base.request,
        presented_key=base.presented_key,
    )
    return plugin.error(kind, context)


def _malformed(
    plugin: ProviderPlugin,
    operation: Operation,
    response: MockResponse,
    variant: MalformedVariant | None,
) -> MockResponse:
    """Damage a successful response as a ``malformed`` fault asks."""

    chosen = variant or "invalid_json"
    if chosen == "missing_field":
        body = plugin.drop_required_field(operation.name, response.body)
        return MockResponse(response.status, body, dict(response.headers), response.media_type)
    if chosen == "wrong_content_type":
        return MockResponse(
            response.status, response.content(), dict(response.headers), "text/html; charset=utf-8"
        )
    if chosen == "truncated":
        data = response.content()
        return MockResponse(response.status, data[: max(1, len(data) // 2)], dict(response.headers))
    html = b"<html><head><title>Error</title></head><body>upstream response</body></html>"
    return MockResponse(response.status, html, dict(response.headers))


class _DroppedResponse(Response):
    """Close the connection without a complete response.

    With the uvicorn transport available the connection is aborted before
    any byte is sent. Otherwise the response sends headers and part of the
    body, then fails, which makes the ASGI server close the connection.
    """

    def __init__(self, transport: Any) -> None:
        super().__init__()
        self._transport = transport

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        abort = getattr(self._transport, "abort", None)
        if callable(abort):
            abort()
            await asyncio.sleep(0)
            return
        await send(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": [(b"content-type", b"application/json"), (b"content-length", b"4096")],
            }
        )
        await send({"type": "http.response.body", "body": b'{"partial":', "more_body": True})
        raise ConnectionAbortedError("provider mock connection_drop fault")


class _Pipeline:
    def __init__(
        self,
        plugin: ProviderPlugin,
        operation: Operation,
        store: MockStore,
        rng: random.Random,
    ) -> None:
        self.plugin = plugin
        self.operation = operation
        self.store = store
        self.rng = rng

    async def __call__(self, request: Request) -> Response:
        started = time.perf_counter()
        raw_body = await request.body()
        credentials = self.plugin.credentials(request, self.store)
        auth = _authenticate(self.plugin, self.operation, self.store, credentials, request)
        plan = self.store.draw_faults(
            self.plugin.name,
            self.operation.name,
            billable=self.operation.billable,
            rng=self.rng,
        )
        if plan.delay_seconds:
            await asyncio.sleep(plan.delay_seconds)
        action = plan.action
        log = _LogWriter(self, request, raw_body, credentials, auth.label, started, plan.label)
        if action is not None and action.kind is FaultKind.TIMEOUT:
            seconds = action.params.seconds
            await asyncio.sleep(DEFAULT_TIMEOUT_SECONDS if seconds is None else seconds)
        if action is not None and _drops(action):
            log(None, None)
            return _DroppedResponse(request.scope.get("state", {}).get(TRANSPORT_STATE_KEY))
        match_key: str | None = None
        if action is not None and action.kind is not FaultKind.MALFORMED:
            keyless = auth.principal.keyless or (credentials.key is None and credentials.keyless)
            base = ErrorContext(
                operation=self.operation.name,
                keyless=keyless,
                store=self.store,
                account=auth.principal.account,
                request=request,
                presented_key=credentials.key,
            )
            result = _fault_response(self.plugin, self.operation, action, base)
        elif auth.error is not None:
            result = auth.error
        else:
            result, match_key = await self._handle(request, raw_body, auth.principal, credentials)
            if action is not None and 200 <= result.status < 300:
                result = _malformed(self.plugin, self.operation, result, action.params.variant)
        log(match_key, result)
        return result.to_response(self.plugin.response_headers())

    async def _handle(
        self, request: Request, raw_body: bytes, principal: Principal, credentials: Credentials
    ) -> tuple[MockResponse, str | None]:
        context = OperationContext(
            plugin=self.plugin,
            operation=self.operation,
            request=request,
            raw_body=raw_body,
            principal=principal,
            store=self.store,
            sequence=self.store.next_sequence(self.plugin.name),
            credentials=credentials,
        )
        try:
            return await self.operation.handler(context), context.match_key
        except QuotaExhausted as exc:
            return context.error(ErrorKind.QUOTA_EXHAUSTED, scope=exc.scope), context.match_key
        except Exception:
            logger.exception("%s %s handler failed", self.plugin.name, self.operation.name)
            return context.error(ErrorKind.SERVER_ERROR), context.match_key


def _drops(rule: FaultRule) -> bool:
    """Return whether a rule ends the request without any response."""

    if rule.kind is FaultKind.CONNECTION_DROP:
        return True
    return rule.kind is FaultKind.TIMEOUT and rule.params.status is None


@dataclass(frozen=True)
class _LogWriter:
    """Write one request-log row for a request, without any secret."""

    pipeline: _Pipeline
    request: Request
    raw_body: bytes
    credentials: Credentials
    label: str
    started: float
    fault: str | None

    def __call__(self, match_key: str | None, response: MockResponse | None) -> None:
        operation = self.pipeline.operation
        body: str | None = None
        if response is not None and operation.log_body:
            data = response.content()
            if len(data) <= _RESPONSE_LOG_LIMIT:
                secrets = () if self.credentials.key is None else (self.credentials.key,)
                body = redact_body(data, secrets)
        self.pipeline.store.log_request(
            provider=self.pipeline.plugin.name,
            operation=operation.name,
            method=self.request.method,
            path=self.request.url.path,
            key_label=self.label,
            status=None if response is None else response.status,
            latency_ms=(time.perf_counter() - self.started) * 1000.0,
            fault=self.fault,
            match_key=match_key,
            summary=_summary(self.request, self.raw_body, log_body=operation.log_body),
            response_body=body,
        )


def _route(pipeline: _Pipeline) -> Callable[[Request], Awaitable[Response]]:
    async def endpoint(request: Request) -> Response:
        return await pipeline(request)

    return endpoint


def build_provider_app(
    plugin: ProviderPlugin, store: MockStore, rng: random.Random, host: str | None = None
) -> FastAPI:
    """Return the ASGI app that serves one provider's real paths.

    With ``host`` set, only the operations served on that host are routed
    (see :attr:`Operation.hosts`).
    """

    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    for operation in plugin.operations():
        unknown_hosts = operation.hosts - plugin.hosts
        if unknown_hosts:
            raise ValueError(
                f"{plugin.name} {operation.name} names hosts it does not claim: "
                f"{', '.join(sorted(unknown_hosts))}"
            )
        if host is not None and operation.hosts and host not in operation.hosts:
            continue
        app.add_api_route(
            operation.path,
            _route(_Pipeline(plugin, operation, store, rng)),
            methods=[operation.method],
            include_in_schema=False,
        )

    async def unknown(request: Request, exc: Exception) -> Response:
        status = exc.status_code if isinstance(exc, StarletteHTTPException) else 404
        return plugin.not_found(request, status).to_response(plugin.response_headers())

    app.add_exception_handler(StarletteHTTPException, unknown)
    return app
