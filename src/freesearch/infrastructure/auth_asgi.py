"""Whole-application Bearer guard for the API surface.

Pure ASGI, so the guard runs before routing, before the trace middleware, and
before any endpoint dependency. It is composed with injected callbacks, so this
module never imports the service layer.

Policy (PLAN P3):

* Registration, login, and documentation are public exceptions. Every other
  path, including Search, Fetch, and unknown paths, requires a credential;
  there is no anonymous execution.
* A Bearer credential that starts with ``fs_live_`` is a project API key. It is
  verified by the injected API key verifier only on the configured API key
  routes (REST Search and Fetch, the MCP transport) and is rejected with HTTP
  401 everywhere else, without ever reaching the human verifier. Every other
  Bearer credential is verified as a human access token, and a composition
  without a human verifier (MCP) rejects it.
* ``POST /auth/jwt/refresh`` is validated by the refresh-credential callback when
  one is injected. Every other protected surface uses the access verifier, so the
  refresh credential is rejected everywhere except that one route.
* Cookie transport exists only when API composition supplies an operator origin
  allowlist, only on the approved refresh method and path pairs, and only for a
  request with browser evidence that passes every evidence check. An invalid
  browser request returns HTTP 403 before any token verification, so it can
  never rotate a credential or revoke a family. Every other surface accepts a
  Bearer credential only, so no cookie authenticates an ordinary API or MCP call.
* A missing, duplicated, non-Bearer, or invalid credential returns HTTP 401 with
  ``WWW-Authenticate: Bearer`` header. Only the verified principal reaches
  ``scope["state"]["user"]``. On an approved cookie route, that 401 also expires
  the refresh cookie, because the presented cookie is not trustworthy.
* Public auth bodies are read from the stream and capped at 4096 bytes; Search
  and Fetch bodies use a separate 1 MiB cap for provider options. A declared
  ``Content-Length`` cannot bypass either limit.
* An authenticated ``POST /api/v1/users`` body is capped at the same 4096 bytes
  before endpoint dispatch, so a provisioning request cannot stream an unbounded
  body into the endpoint.
* Public registration reserves its peer and deployment capacity before endpoint
  dispatch, before schema validation, and before any password hash work.
"""

import json
import logging
from collections.abc import Awaitable, Callable
from contextvars import ContextVar
from typing import Any

from freesearch.infrastructure.browser_auth import (
    REFRESH_COOKIE_PATH,
    browser_transport,
    refresh_cookie_deletion_header,
    refresh_credential_from_scope,
    validate_browser_request,
)
from freesearch.models.projects import PROJECT_API_KEY_PREFIX, ProjectApiKeyPrincipal
from freesearch.models.users import UserPrincipal

logger = logging.getLogger(__name__)

Scope = dict[str, Any]
Message = dict[str, Any]
Receive = Callable[[], Awaitable[Message]]
Send = Callable[[Message], Awaitable[None]]
ASGIApp = Callable[[Scope, Receive, Send], Awaitable[None]]

#: A principal the guard verified: a human session or a project API key.
VerifiedPrincipal = UserPrincipal | ProjectApiKeyPrincipal

VerifyToken = Callable[[str], Awaitable[UserPrincipal | None]]
VerifyApiKey = Callable[[str], Awaitable[ProjectApiKeyPrincipal | None]]
RegistrationLimit = Callable[[str], Awaitable[int | None]]

#: Explicit public API operations and documentation routes.
PUBLIC_ROUTES: frozenset[tuple[str, str]] = frozenset(
    {
        ("POST", "/auth/register"),
        ("POST", "/auth/jwt/login"),
        ("GET", "/docs"),
        ("GET", "/redoc"),
        ("GET", "/openapi.json"),
    }
)

#: Authenticated provider-execution routes whose JSON bodies may carry the
#: larger provider-options payload.
OPERATION_ROUTES: frozenset[tuple[str, str]] = frozenset({("POST", "/search"), ("POST", "/fetch")})

#: Search, Fetch and MCP requests can carry the provider options object, which
#: is larger than the small registration and login payloads.
MAX_PUBLIC_OPERATION_BODY_BYTES: int = 1_048_576

#: The one route whose credential is an opaque refresh token.
REFRESH_ROUTE: tuple[str, str] = ("POST", REFRESH_COOKIE_PATH)

#: The method and path pairs that may present the refresh cookie instead of a
#: Bearer credential. Cookie auth exists on no other surface.
REFRESH_COOKIE_ROUTES: frozenset[tuple[str, str]] = frozenset(
    {REFRESH_ROUTE, ("DELETE", REFRESH_COOKIE_PATH)}
)

#: The one browser evidence failure message, which carries no request content.
_FORBIDDEN_PAYLOAD: dict[str, object] = {"detail": "browser request rejected"}

#: The one body-cap failure message, which carries no request content.
_TOO_LARGE_PAYLOAD: dict[str, object] = {"detail": "request body is too large"}

#: The one protected route that accepts a credential-bearing JSON body.
PROVISION_ROUTE: tuple[str, str] = ("POST", "/api/v1/users")

#: Maximum accepted body for a public auth request.
MAX_PUBLIC_AUTH_BODY_BYTES: int = 4096

_CHALLENGE = [(b"www-authenticate", b"Bearer")]
_CURRENT_PRINCIPAL: ContextVar[VerifiedPrincipal | None] = ContextVar(
    "freesearch_verified_principal", default=None
)


def current_verified_principal() -> VerifiedPrincipal | None:
    """Return the verified principal for the active ASGI request, if any."""

    return _CURRENT_PRINCIPAL.get()


async def _send_json(
    send: Send,
    status: int,
    payload: dict[str, object],
    headers: list[tuple[bytes, bytes]] | None = None,
) -> None:
    """Send one small JSON response and close the body."""

    body = json.dumps(payload).encode("utf-8")
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode("ascii")),
                *(headers or []),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})


async def _reject_unauthorized(send: Send, *, clear_refresh_cookie: bool = False) -> None:
    """Reject a request that carries no usable credential.

    On an approved cookie route, the rejection also expires the refresh cookie:
    the presented cookie failed verification, so the browser must not keep it.
    """

    headers = list(_CHALLENGE)
    if clear_refresh_cookie:
        header = refresh_cookie_deletion_header().encode("ascii")
        headers.append((b"set-cookie", header))
    await _send_json(
        send,
        status=401,
        payload={"detail": "not authenticated"},
        headers=headers,
    )


async def _reject_forbidden(send: Send) -> None:
    """Reject a browser request whose evidence checks failed.

    No cookie is expired and no account side effect occurs, so a rejected CSRF
    attempt cannot clear a live session or revoke a credential family.
    """

    await _send_json(send, status=403, payload=dict(_FORBIDDEN_PAYLOAD))


async def _reject_too_large(send: Send) -> None:
    """Reject a request body that exceeds the accepted cap."""

    await _send_json(send, status=413, payload=dict(_TOO_LARGE_PAYLOAD))


def bearer_credential_from_scope(scope: Scope) -> str | None:
    """Return the request's single Bearer credential, else ``None``.

    A duplicated ``Authorization`` header, another scheme, a cookie, a query
    parameter, or a user-id header never counts as a credential.
    """

    values = [
        value for name, value in scope.get("headers") or [] if name.lower() == b"authorization"
    ]
    if len(values) != 1:
        return None
    raw = values[0]
    if raw[:7].lower() != b"bearer ":
        return None
    try:
        token = raw[7:].strip().decode("ascii")
    except UnicodeDecodeError:
        return None
    return token or None


def peer_address_from_scope(scope: Scope) -> str:
    """Return the actual peer address, ignoring any forwarded header."""

    client = scope.get("client")
    if isinstance(client, (tuple, list)) and client:
        return str(client[0])
    return "unknown"


def store_principal(scope: Scope, principal: VerifiedPrincipal) -> None:
    """Publish the verified principal for downstream transport layers."""

    state = scope.get("state")
    if not isinstance(state, dict):
        state = {}
        scope["state"] = state
    state["user"] = principal


def store_forwarding_credential(scope: Scope, token: str) -> None:
    """Keep the verified project key in-process for forwarding-signature checks.

    Only a verified project API key reaches this cell; the value never enters a
    response, a log, or a span attribute. The trace middleware uses it to
    authenticate the MCP forwarding envelope, so an ordinary REST caller's
    ``x-trace-id`` is never trusted as continuation provenance.
    """

    state = scope.get("state")
    if not isinstance(state, dict):
        state = {}
        scope["state"] = state
    state["forwarding_credential"] = token


def _replay_receive(messages: list[Message], receive: Receive) -> Receive:
    """Return a receive that replays buffered body messages, then defers."""

    buffered = list(messages)

    async def _receive() -> Message:
        if buffered:
            return buffered.pop(0)
        return await receive()

    return _receive


async def _capped_body(receive: Receive, limit: int) -> Receive | None:
    """Read one request body from the stream, capped at ``limit`` bytes.

    Returns a replaying ``receive`` for an accepted body, or ``None`` when the
    streamed size exceeds the cap. ``Content-Length`` is never trusted.
    """

    messages: list[Message] = []
    total = 0
    while True:
        message = await receive()
        messages.append(message)
        if message.get("type") != "http.request":
            break
        body = message.get("body") or b""
        total += len(body)
        if total > limit:
            return None
        if not message.get("more_body", False):
            break
    return _replay_receive(messages, receive)


class BearerAuthMiddleware:
    """Guard HTTP surfaces and allow anonymous calls on explicit public routes only.

    The default public set is authentication/docs routes only; provider
    Search/Fetch require a verified Bearer credential and keep the larger
    provider-options body cap. ``api_key_routes`` names the routes where a
    project API key is accepted; ``verify_api_key`` verifies it there.
    ``verify_token`` verifies human access tokens; ``None`` accepts none.

    ``browser_origins`` is empty by default, so this guard accepts no cookie
    unless API composition supplies the operator origin allowlist. The MCP
    composition never supplies one.
    """

    def __init__(
        self,
        app: ASGIApp,
        *,
        verify_token: VerifyToken | None,
        verify_refresh_token: VerifyToken | None = None,
        verify_api_key: VerifyApiKey | None = None,
        api_key_routes: frozenset[tuple[str, str]] = frozenset(),
        registration_limit: RegistrationLimit | None = None,
        public_routes: frozenset[tuple[str, str]] = PUBLIC_ROUTES,
        operation_routes: frozenset[tuple[str, str]] = OPERATION_ROUTES,
        browser_origins: frozenset[str] = frozenset(),
    ) -> None:
        self.app = app
        self._verify_token = verify_token
        self._verify_refresh_token = verify_refresh_token
        self._verify_api_key = verify_api_key
        self._api_key_routes = api_key_routes
        self._registration_limit = registration_limit
        self._public_routes = public_routes
        self._operation_routes = operation_routes
        self._browser_origins = browser_origins

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return
        method = str(scope.get("method", "")).upper()
        path = str(scope.get("path", ""))
        route = (method, path)
        if route in self._public_routes:
            await self._public_request(scope, receive, send, method, path)
            return
        if self._cookie_transport(method, path, scope):
            await self._cookie_request(scope, receive, send)
            return
        await self._bearer_request(scope, receive, send, method, path)

    def _cookie_transport(self, method: str, path: str, scope: Scope) -> bool:
        """Return whether this request may present the refresh cookie.

        Cookie transport needs all three conditions: an operator origin
        allowlist from API composition, one approved method and path pair, and
        browser evidence on the request.
        """

        if not self._browser_origins:
            return False
        if (method, path) not in REFRESH_COOKIE_ROUTES:
            return False
        return browser_transport(scope)

    async def _cookie_request(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Authenticate one approved cookie request before any rotation.

        A failed evidence check returns HTTP 403 without cookie deletion or
        account side effects. A failed cookie verification returns HTTP 401 and
        expires the presented cookie.
        """

        if not validate_browser_request(scope, self._browser_origins):
            await _reject_forbidden(send)
            return
        token = refresh_credential_from_scope(scope, self._browser_origins)
        verifier = self._refresh_verifier()
        principal = None if verifier is None else await self._verified(verifier, token)
        if principal is None:
            await _reject_unauthorized(send, clear_refresh_cookie=True)
            return
        store_principal(scope, principal)
        await self._call_app(scope, receive, send, principal)

    async def _bearer_request(
        self, scope: Scope, receive: Receive, send: Send, method: str, path: str
    ) -> None:
        """Authenticate one protected request from its Bearer credential.

        The provisioning route also receives the streamed body cap, so its body
        is bounded before the endpoint can read it.
        """

        token = bearer_credential_from_scope(scope)
        principal = await self._authenticate(method, path, token)
        if principal is None:
            await _reject_unauthorized(send)
            return
        store_principal(scope, principal)
        if isinstance(principal, ProjectApiKeyPrincipal) and token is not None:
            store_forwarding_credential(scope, token)
        body_limit: int | None = None
        if (method, path) == PROVISION_ROUTE:
            body_limit = MAX_PUBLIC_AUTH_BODY_BYTES
        elif (method, path) in self._operation_routes:
            body_limit = MAX_PUBLIC_OPERATION_BODY_BYTES
        if body_limit is not None:
            replay = await _capped_body(receive, body_limit)
            if replay is None:
                await _reject_too_large(send)
                return
            receive = replay
        await self._call_app(scope, receive, send, principal)

    async def _authenticate(
        self, method: str, path: str, token: str | None
    ) -> VerifiedPrincipal | None:
        """Verify one Bearer credential with the one verifier its kind and route allow.

        A project API key is verified only on an API key route and never by the
        human verifier; a human credential never reaches the API key verifier.
        """

        if token is None:
            return None
        if token.startswith(PROJECT_API_KEY_PREFIX):
            if (method, path) not in self._api_key_routes or self._verify_api_key is None:
                return None
            return await self._verified(self._verify_api_key, token)
        verifier = self._verifier_for(method, path)
        if verifier is None:
            return None
        return await self._verified(verifier, token)

    @staticmethod
    async def _verified[P: (UserPrincipal, ProjectApiKeyPrincipal)](
        verifier: Callable[[str], Awaitable[P | None]], token: str | None
    ) -> P | None:
        """Return the verified principal, or ``None`` for any failure.

        A verifier failure must fail closed instead of becoming a server error
        that reveals which credential step failed.
        """

        if token is None:
            return None
        try:
            return await verifier(token)
        except Exception:
            logger.warning("credential verification failed", exc_info=False)
            return None

    def _refresh_verifier(self) -> VerifyToken | None:
        """Return the verifier for the opaque refresh credential."""

        return self._verify_refresh_token or self._verify_token

    def _verifier_for(self, method: str, path: str) -> VerifyToken | None:
        """Select the human credential verifier for one protected route."""

        if (method, path) == REFRESH_ROUTE and self._verify_refresh_token is not None:
            return self._verify_refresh_token
        return self._verify_token

    async def _public_request(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
        method: str,
        path: str,
    ) -> None:
        """Serve a public route with its route-specific body bound."""

        route = (method, path)
        is_registration = route == ("POST", "/auth/register")
        if (
            is_registration
            and self._registration_limit is not None
            and not await self._reserve_registration(scope, send)
        ):
            return
        body_limit = MAX_PUBLIC_AUTH_BODY_BYTES if route in PUBLIC_ROUTES else None
        if body_limit is not None:
            replay = await _capped_body(receive, body_limit)
            if replay is None:
                await _reject_too_large(send)
                return
            receive = replay
        await self._call_app(scope, receive, send, None)

    async def _call_app(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
        principal: VerifiedPrincipal | None,
    ) -> None:
        """Run the downstream app with request-local verified identity."""

        principal_marker = _CURRENT_PRINCIPAL.set(principal)
        try:
            await self.app(scope, receive, send)
        finally:
            _CURRENT_PRINCIPAL.reset(principal_marker)

    async def _reserve_registration(self, scope: Scope, send: Send) -> bool:
        """Reserve registration capacity before the endpoint runs.

        Returns ``True`` when the request may proceed, and ``False`` after this
        method already sent an HTTP 429 or HTTP 503 response.
        """

        limit = self._registration_limit
        assert limit is not None
        try:
            retry = await limit(peer_address_from_scope(scope))
        except Exception:
            logger.warning("registration limit unavailable", exc_info=False)
            await _send_json(
                send,
                status=503,
                payload={"detail": "registration is temporarily unavailable"},
            )
            return False
        if retry is None:
            return True
        await _send_json(
            send,
            status=429,
            payload={"detail": "too many registration attempts"},
            headers=[(b"retry-after", str(max(1, retry)).encode("ascii"))],
        )
        return False


__all__ = [
    "MAX_PUBLIC_AUTH_BODY_BYTES",
    "MAX_PUBLIC_OPERATION_BODY_BYTES",
    "OPERATION_ROUTES",
    "PROVISION_ROUTE",
    "PUBLIC_ROUTES",
    "REFRESH_COOKIE_ROUTES",
    "REFRESH_ROUTE",
    "BearerAuthMiddleware",
    "VerifiedPrincipal",
    "VerifyApiKey",
    "VerifyToken",
    "bearer_credential_from_scope",
    "current_verified_principal",
    "peer_address_from_scope",
    "store_principal",
]
