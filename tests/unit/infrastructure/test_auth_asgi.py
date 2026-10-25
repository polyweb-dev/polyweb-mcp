"""Unit tests for the whole-application Bearer guard (P3, T2/T20 parts).

The middleware is pure ASGI with injected callbacks, so these tests run with
no database and no network. They pin the exact public exceptions, the
access/refresh credential separation, duplicate-header rejection, unknown-path
coverage, challenge headers, fail-closed verification, and the streamed
4096-byte public body cap with pre-dispatch registration reservation.
"""

from __future__ import annotations

import asyncio
from typing import Any

from freesearch.infrastructure.auth_asgi import (
    MAX_PUBLIC_AUTH_BODY_BYTES,
    MAX_PUBLIC_OPERATION_BODY_BYTES,
    BearerAuthMiddleware,
)
from freesearch.models.users import UserPrincipal, UserRole


def _principal() -> UserPrincipal:
    from uuid import uuid4

    return UserPrincipal(
        id=uuid4(),
        email="guard@example.com",
        role=UserRole.AGENT,
        session_id=uuid4(),
        is_active=True,
        is_superuser=False,
        is_verified=False,
    )


_PRINCIPAL = _principal()


async def _verify_access(token: str) -> UserPrincipal | None:
    return _PRINCIPAL if token == "good-access" else None


async def _verify_refresh(token: str) -> UserPrincipal | None:
    return _PRINCIPAL if token == "good-refresh" else None


async def _exploding_verifier(token: str) -> UserPrincipal | None:
    raise RuntimeError("verifier exploded")


async def _accept_limit(peer: str) -> int | None:
    return None


def _ok_app(seen: dict[str, Any]) -> Any:
    async def _app(scope: dict[str, Any], receive: Any, send: Any) -> None:
        seen["state_user"] = (scope.get("state") or {}).get("user")
        seen["path"] = scope.get("path")
        body = b""
        while True:
            message = await receive()
            if message.get("type") != "http.request":
                break
            body += message.get("body") or b""
            if not message.get("more_body", False):
                break
        seen["body"] = body
        await send(
            {"type": "http.response.start", "status": 200, "headers": [(b"content-length", b"2")]}
        )
        await send({"type": "http.response.body", "body": b"ok"})

    return _app


def _run(
    app: Any,
    *,
    method: str = "GET",
    path: str = "/search",
    headers: list[tuple[bytes, bytes]] | None = None,
    body_chunks: list[bytes] | None = None,
) -> tuple[int, dict[bytes, bytes], bytes]:
    scope: dict[str, Any] = {
        "type": "http",
        "method": method,
        "path": path,
        "headers": headers or [],
        "client": ("127.0.0.1", 5000),
        "state": {},
    }
    messages = [
        {"type": "http.request", "body": chunk, "more_body": i < len(body_chunks or []) - 1}
        for i, chunk in enumerate(body_chunks or [b""])
    ]
    if not messages:
        messages = [{"type": "http.request", "body": b"", "more_body": False}]

    async def _receive() -> dict[str, Any]:
        return messages.pop(0) if messages else {"type": "http.disconnect"}

    sent: list[dict[str, Any]] = []

    async def _send(message: dict[str, Any]) -> None:
        sent.append(message)

    asyncio.run(app(scope, _receive, _send))
    start = next(m for m in sent if m["type"] == "http.response.start")
    body = b"".join(m.get("body") or b"" for m in sent if m["type"] == "http.response.body")
    return int(start["status"]), dict(start["headers"]), body


def _bearer(token: str) -> list[tuple[bytes, bytes]]:
    return [(b"authorization", f"Bearer {token}".encode("ascii"))]


def _guard(**overrides: Any) -> tuple[BearerAuthMiddleware, dict[str, Any]]:
    seen: dict[str, Any] = {}
    params: dict[str, Any] = {
        "verify_token": _verify_access,
        "verify_refresh_token": _verify_refresh,
        "registration_limit": _accept_limit,
    }
    params.update(overrides)
    return BearerAuthMiddleware(_ok_app(seen), **params), seen


def test_public_register_and_login_pass_without_credential() -> None:
    for path in ("/auth/register", "/auth/jwt/login"):
        guard, seen = _guard()
        status, _, _ = _run(guard, method="POST", path=path, body_chunks=[b"{}"])
        assert status == 200
        assert seen["path"] == path


def test_protected_surfaces_reject_anonymous_with_challenge() -> None:
    paths = [
        ("GET", "/stats"),
        ("GET", "/dashboard"),
        ("GET", "/api/v1/providers"),
        ("GET", "/api/v1/traces"),
        ("GET", "/no-such-route"),
        ("POST", "/auth/jwt/refresh"),
    ]
    for method, path in paths:
        guard, seen = _guard()
        status, headers, body = _run(guard, method=method, path=path)
        assert status == 401
        assert headers[b"www-authenticate"] == b"Bearer"
        assert b"not authenticated" in body
        assert "state_user" not in seen


def test_search_and_fetch_require_a_verified_bearer() -> None:
    for path in ("/search", "/fetch"):
        guard, seen = _guard()
        status, headers, _ = _run(guard, method="POST", path=path)
        assert status == 401
        assert headers[b"www-authenticate"] == b"Bearer"
        assert "state_user" not in seen

        guard, _ = _guard()
        status, headers, _ = _run(guard, method="POST", path=path, headers=_bearer("bad-access"))
        assert status == 401
        assert headers[b"www-authenticate"] == b"Bearer"

        guard, seen = _guard()
        status, _, _ = _run(guard, method="POST", path=path, headers=_bearer("good-access"))
        assert status == 200
        assert seen["state_user"] == _PRINCIPAL


def test_search_fetch_body_cap_supports_large_provider_options() -> None:
    guard, seen = _guard()
    payload = b"x" * (MAX_PUBLIC_AUTH_BODY_BYTES + 1)
    status, _, _ = _run(
        guard,
        method="POST",
        path="/search",
        headers=_bearer("good-access"),
        body_chunks=[payload],
    )
    assert status == 200
    assert seen["body"] == payload

    guard, seen = _guard()
    payload = b"x" * (MAX_PUBLIC_OPERATION_BODY_BYTES + 1)
    status, _, body = _run(
        guard,
        method="POST",
        path="/fetch",
        headers=_bearer("good-access"),
        body_chunks=[payload],
    )
    assert status == 413
    assert body == b'{"detail": "request body is too large"}'
    assert "state_user" not in seen


def test_valid_access_reaches_app_with_principal_in_state() -> None:
    guard, seen = _guard()
    status, _, _ = _run(guard, method="POST", path="/search", headers=_bearer("good-access"))
    assert status == 200
    assert seen["state_user"] == _PRINCIPAL


def test_duplicate_and_wrong_scheme_headers_reject() -> None:
    guard, _ = _guard()
    duplicated = [
        (b"authorization", b"Bearer good-access"),
        (b"authorization", b"Bearer good-access"),
    ]
    status, headers, _ = _run(guard, method="GET", path="/stats", headers=duplicated)
    assert status == 401
    assert headers[b"www-authenticate"] == b"Bearer"

    guard, _ = _guard()
    status, _, _ = _run(
        guard, method="GET", path="/stats", headers=[(b"authorization", b"Token good-access")]
    )
    assert status == 401


def test_tokens_in_query_cookies_or_user_headers_reject() -> None:
    guard, _ = _guard()
    status, _, _ = _run(guard, method="GET", path="/stats?access_token=good-access")
    assert status == 401

    guard, _ = _guard()
    status, _, _ = _run(
        guard,
        method="GET",
        path="/stats",
        headers=[(b"cookie", b"access_token=good-access"), (b"x-user-id", b"someone")],
    )
    assert status == 401


def test_refresh_route_uses_only_the_refresh_verifier() -> None:
    guard, _ = _guard()
    status, _, _ = _run(
        guard, method="POST", path="/auth/jwt/refresh", headers=_bearer("good-refresh")
    )
    assert status == 200

    guard, _ = _guard()
    status, _, _ = _run(
        guard, method="POST", path="/auth/jwt/refresh", headers=_bearer("good-access")
    )
    assert status == 401

    guard, _ = _guard()
    status, _, _ = _run(guard, method="POST", path="/search", headers=_bearer("good-refresh"))
    assert status == 401


def test_verifier_failure_fails_closed() -> None:
    guard, _ = _guard(verify_token=_exploding_verifier)
    status, headers, _ = _run(guard, method="POST", path="/search", headers=_bearer("anything"))
    assert status == 401
    assert headers[b"www-authenticate"] == b"Bearer"


def test_public_body_cap_counts_streamed_bytes() -> None:
    assert MAX_PUBLIC_AUTH_BODY_BYTES == 4096
    big = b"A" * 4097
    for path in ("/auth/register", "/auth/jwt/login"):
        guard, _ = _guard()
        status, _, body = _run(guard, method="POST", path=path, body_chunks=[big])
        assert status == 413
        assert body == b'{"detail": "request body is too large"}'
        assert b"A" not in body

    guard, seen = _guard()
    status, _, _ = _run(guard, method="POST", path="/auth/register", body_chunks=[b"B" * 4096])
    assert status == 200
    assert seen["body"] == b"B" * 4096

    guard, _ = _guard()
    status, _, _ = _run(
        guard,
        method="POST",
        path="/auth/register",
        headers=[(b"content-length", b"10")],
        body_chunks=[b"C" * 2000, b"C" * 2097],
    )
    assert status == 413


def test_registration_reservation_runs_before_dispatch() -> None:
    calls: list[str] = []

    async def _limited(peer: str) -> int | None:
        calls.append(peer)
        return 30

    guard, seen = _guard(registration_limit=_limited)
    status, headers, _ = _run(guard, method="POST", path="/auth/register", body_chunks=[b"{}"])
    assert status == 429
    assert headers[b"retry-after"] == b"30"
    assert "state_user" not in seen
    assert calls == ["127.0.0.1"]

    async def _broken(peer: str) -> int | None:
        raise RuntimeError("counter store is down")

    guard, _ = _guard(registration_limit=_broken)
    status, _, body = _run(guard, method="POST", path="/auth/register", body_chunks=[b"{}"])
    assert status == 503
    assert b"temporarily unavailable" in body


def test_oversize_registration_still_consumes_one_reservation() -> None:
    calls: list[str] = []

    async def _counting(peer: str) -> int | None:
        calls.append(peer)
        return None

    guard, _ = _guard(registration_limit=_counting)
    status, _, _ = _run(guard, method="POST", path="/auth/register", body_chunks=[b"Z" * 4097])
    assert status == 413
    assert calls == ["127.0.0.1"]


def test_login_route_skips_the_registration_counter() -> None:
    calls: list[str] = []

    async def _counting(peer: str) -> int | None:
        calls.append(peer)
        return None

    guard, _ = _guard(registration_limit=_counting)
    status, _, _ = _run(guard, method="POST", path="/auth/jwt/login", body_chunks=[b"{}"])
    assert status == 200
    assert calls == []


_BROWSER_ORIGIN = "http://localhost:5177"


def _browser_cookie_headers(token: str = "good-refresh") -> list[tuple[bytes, bytes]]:
    return [
        (b"origin", _BROWSER_ORIGIN.encode("ascii")),
        (b"x-freesearch-client", b"browser"),
        (b"cookie", f"__Secure-freesearch_refresh={token}".encode("ascii")),
    ]


def test_cookie_routes_accept_valid_browser_cookie() -> None:
    for method in ("POST", "DELETE"):
        guard, seen = _guard(browser_origins=frozenset({_BROWSER_ORIGIN}))
        status, _, _ = _run(
            guard,
            method=method,
            path="/auth/jwt/refresh",
            headers=_browser_cookie_headers(),
        )
        assert status == 200
        assert seen["state_user"] == _PRINCIPAL


def test_cookie_transport_needs_operator_allowlist() -> None:
    guard, _ = _guard()
    status, headers, _ = _run(
        guard, method="POST", path="/auth/jwt/refresh", headers=_browser_cookie_headers()
    )
    assert status == 401
    assert headers[b"www-authenticate"] == b"Bearer"
    assert b"set-cookie" not in headers


def test_cookie_evidence_failure_returns_403_without_cookie_deletion() -> None:
    guard, _ = _guard(browser_origins=frozenset({_BROWSER_ORIGIN}))
    status, headers, body = _run(
        guard,
        method="POST",
        path="/auth/jwt/refresh",
        headers=[(b"origin", b"https://evil.example.com"), *_browser_cookie_headers()[1:]],
    )
    assert status == 403
    assert b"browser request rejected" in body
    assert b"set-cookie" not in headers

    guard, _ = _guard(browser_origins=frozenset({_BROWSER_ORIGIN}))
    status, _, _ = _run(
        guard,
        method="POST",
        path="/auth/jwt/refresh",
        headers=[(b"cookie", b"__Secure-freesearch_refresh=good-refresh")],
    )
    assert status == 403


def test_invalid_cookie_returns_401_and_expires_cookie() -> None:
    guard, _ = _guard(browser_origins=frozenset({_BROWSER_ORIGIN}))
    status, headers, _ = _run(
        guard,
        method="POST",
        path="/auth/jwt/refresh",
        headers=_browser_cookie_headers("bad-refresh"),
    )
    assert status == 401
    assert headers[b"www-authenticate"] == b"Bearer"
    deletion = headers[b"set-cookie"].decode("ascii")
    assert deletion.startswith("__Secure-freesearch_refresh=; ")
    assert "Max-Age=0" in deletion
    assert "Path=/auth/jwt/refresh" in deletion


def test_cookie_never_authenticates_ordinary_routes() -> None:
    guard, _ = _guard(browser_origins=frozenset({_BROWSER_ORIGIN}))
    status, _, _ = _run(guard, method="GET", path="/stats", headers=_browser_cookie_headers())
    assert status == 401

    guard, seen = _guard(browser_origins=frozenset({_BROWSER_ORIGIN}))
    status, _, _ = _run(guard, method="POST", path="/search", headers=_browser_cookie_headers())
    assert status == 401
    assert "state_user" not in seen


def test_provisioning_body_cap_applies_before_dispatch() -> None:
    """T2-PROVISION: POST /api/v1/users carries the 4096-byte cap with Bearer auth."""

    guard, seen = _guard()
    status, _, body = _run(
        guard,
        method="POST",
        path="/api/v1/users",
        headers=_bearer("good-access"),
        body_chunks=[b"X" * 4097],
    )
    assert status == 413
    assert body == b'{"detail": "request body is too large"}'
    assert "state_user" not in seen

    guard, seen = _guard()
    status, _, _ = _run(
        guard,
        method="POST",
        path="/api/v1/users",
        headers=_bearer("good-access"),
        body_chunks=[b"Y" * 4096],
    )
    assert status == 200
    assert seen["body"] == b"Y" * 4096

    guard, _ = _guard()
    status, _, _ = _run(guard, method="POST", path="/api/v1/users", headers=_bearer("bad-access"))
    assert status == 401
