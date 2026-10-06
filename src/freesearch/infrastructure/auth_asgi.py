"""Whole-application Bearer guard for the API surface.

Pure ASGI, so the guard runs before routing, before the trace middleware, and
before any endpoint dependency. It is composed with injected callbacks, so this
module never imports the service layer.

Policy (PLAN P3):

* ``POST /auth/register`` and ``POST /auth/jwt/login`` are the only public
  exceptions (Q1). Every other path — including documentation, unknown paths, and
  the MCP HTTP application's metadata routes — requires a credential.
* ``POST /auth/jwt/refresh`` is validated by the refresh-credential callback when
  one is injected. Every other protected surface uses the access verifier, so the
  refresh credential is rejected everywhere except that one route.
* A missing, duplicated, non-Bearer, or invalid credential returns HTTP 401 with
  ``WWW-Authenticate: Bearer``. Only the verified principal reaches
  ``scope["state"]["user"]`.
* A public auth body is read from the stream and capped at 4096 bytes, so a
  declared ``Content-Length`` cannot bypass the limit. An excess body returns
  HTTP 413 without any credential content.
* Public registration reserves its peer and deployment capacity before endpoint
  dispatch, before schema validation, and before any password hash work.
"""

import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from freesearch.models.users import UserPrincipal

logger = logging.getLogger(__name__)

Scope = dict[str, Any]
Message = dict[str, Any]
Receive = Callable[[], Awaitable[Message]]
Send = Callable[[Message], Awaitable[None]]
ASGIApp = Callable[[Scope, Receive, Send], Awaitable[None]]

VerifyToken = Callable[[str], Awaitable[UserPrincipal | None]]
RegistrationLimit = Callable[[str], Awaitable[int | None]]

#: The exact public exceptions from Q1.
PUBLIC_ROUTES: frozenset[tuple[str, str]] = frozenset(
    {("POST", "/auth/register"), ("POST", "/auth/jwt/login")}
)

#: The one route whose credential is an opaque refresh token.
REFRESH_ROUTE: tuple[str, str] = ("POST", "/auth/jwt/refresh")

#: Maximum accepted body for a public auth request.
MAX_PUBLIC_AUTH_BODY_BYTES: int = 4096

_CHALLENGE = [(b"www-authenticate", b"Bearer")]


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


async def _reject_unauthorized(send: Send) -> None:
    """Reject a request that carries no usable credential."""

    await _send_json(
        send,
        status=401,
        payload={"detail": "not authenticated"},
        headers=list(_CHALLENGE),
    )


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


def store_principal(scope: Scope, principal: UserPrincipal) -> None:
    """Publish the verified principal for downstream transport layers."""

    state = scope.get("state")
    if not isinstance(state, dict):
        state = {}
        scope["state"] = state
    state["user"] = principal


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
    """Require a verified account on every HTTP surface except the public set.

    The default public set holds the two Q1 exceptions of the API surface. The
    MCP composition passes an empty set, because that transport mounts no
    account route and must answer 401 on every path.
    """

    def __init__(
        self,
        app: ASGIApp,
        *,
        verify_token: VerifyToken,
        verify_refresh_token: VerifyToken | None = None,
        registration_limit: RegistrationLimit | None = None,
        public_routes: frozenset[tuple[str, str]] = PUBLIC_ROUTES,
    ) -> None:
        self.app = app
        self._verify_token = verify_token
        self._verify_refresh_token = verify_refresh_token
        self._registration_limit = registration_limit
        self._public_routes = public_routes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return
        method = str(scope.get("method", "")).upper()
        path = str(scope.get("path", ""))
        if (method, path) in self._public_routes:
            await self._public_request(scope, receive, send, method)
            return
        verifier = self._verifier_for(method, path)
        token = bearer_credential_from_scope(scope)
        if token is None:
            await _reject_unauthorized(send)
            return
        try:
            principal = await verifier(token)
        except Exception:
            # A verifier failure must fail closed instead of becoming a server
            # error that reveals which credential step failed.
            logger.warning("credential verification failed", exc_info=False)
            await _reject_unauthorized(send)
            return
        if principal is None:
            await _reject_unauthorized(send)
            return
        store_principal(scope, principal)
        await self.app(scope, receive, send)

    def _verifier_for(self, method: str, path: str) -> VerifyToken:
        """Select the credential verifier for one protected route."""

        if (method, path) == REFRESH_ROUTE and self._verify_refresh_token is not None:
            return self._verify_refresh_token
        return self._verify_token

    async def _public_request(
        self, scope: Scope, receive: Receive, send: Send, method: str
    ) -> None:
        """Serve one of the two public exceptions with capacity and body bounds."""

        is_registration = (method, scope.get("path")) == ("POST", "/auth/register")
        if (
            is_registration
            and self._registration_limit is not None
            and not await self._reserve_registration(scope, send)
        ):
            return
        replay = await _capped_body(receive, MAX_PUBLIC_AUTH_BODY_BYTES)
        if replay is None:
            await _send_json(send, status=413, payload={"detail": "request body is too large"})
            return
        await self.app(scope, replay, send)

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
    "PUBLIC_ROUTES",
    "REFRESH_ROUTE",
    "BearerAuthMiddleware",
    "bearer_credential_from_scope",
    "peer_address_from_scope",
    "store_principal",
]
