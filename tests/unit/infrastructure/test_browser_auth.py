"""Unit tests for the browser refresh-cookie transport helpers.

These tests pin the exact Origin contract, the browser evidence checks, the
duplicate-header rejection, the malformed cookie handling, and the cookie
attributes. They use no database and no network.
"""

from __future__ import annotations

from typing import Any

from starlette.responses import Response

from polyweb.infrastructure.browser_auth import (
    BROWSER_CLIENT_HEADER,
    BROWSER_CLIENT_VALUE,
    MAX_REFRESH_COOKIE_AGE_SECONDS,
    REFRESH_COOKIE_NAME,
    REFRESH_COOKIE_PATH,
    browser_transport,
    clear_refresh_cookie,
    is_loopback_host,
    normalize_origin,
    refresh_cookie_deletion_header,
    refresh_cookie_header,
    refresh_credential_from_scope,
    set_refresh_cookie,
    validate_browser_request,
)

_ORIGIN = "http://localhost:5177"
_HTTPS_ORIGIN = "https://app.example.com"


def _scope(headers: list[tuple[bytes, bytes]]) -> dict[str, Any]:
    return {"type": "http", "method": "POST", "path": "/auth/jwt/refresh", "headers": headers}


def _origin_headers(origin: str = _ORIGIN) -> list[tuple[bytes, bytes]]:
    return [
        (b"origin", origin.encode("ascii")),
        (b"x-polyweb-client", b"browser"),
    ]


def _allowed(*origins: str) -> frozenset[str]:
    return frozenset(origins)


def test_cookie_constants_use_strict_host_only_scope() -> None:
    assert REFRESH_COOKIE_NAME == "__Secure-polyweb_refresh"
    assert REFRESH_COOKIE_PATH == "/auth/jwt/refresh"
    assert BROWSER_CLIENT_HEADER == "x-polyweb-client"
    assert BROWSER_CLIENT_VALUE == "browser"
    assert MAX_REFRESH_COOKIE_AGE_SECONDS == 604800


def test_is_loopback_host_names_local_machine_only() -> None:
    assert is_loopback_host("localhost") is True
    assert is_loopback_host("127.0.0.1") is True
    assert is_loopback_host("127.0.0.9") is True
    assert is_loopback_host("::1") is True
    assert is_loopback_host("[::1]") is True
    assert is_loopback_host("example.com") is False
    assert is_loopback_host("192.168.1.10") is False
    assert is_loopback_host(None) is False
    assert is_loopback_host("") is False


def test_normalize_origin_accepts_exact_origins_only() -> None:
    assert normalize_origin(_HTTPS_ORIGIN) == _HTTPS_ORIGIN
    assert normalize_origin("http://localhost:5177") == "http://localhost:5177"
    assert normalize_origin("http://127.0.0.1:8031") == "http://127.0.0.1:8031"
    assert normalize_origin("http://[::1]:5177") == "http://[::1]:5177"
    assert normalize_origin("https://app.example.com/") == "https://app.example.com"
    assert normalize_origin("https://app.example.com:443") == "https://app.example.com:443"


def test_normalize_origin_rejects_untrusted_forms() -> None:
    assert normalize_origin("null") is None
    assert normalize_origin("") is None
    assert normalize_origin("https://*.example.com") is None
    assert normalize_origin("https://app.example.com/path") is None
    assert normalize_origin("https://user@app.example.com") is None
    assert normalize_origin("https://app.example.com?x=1") is None
    assert normalize_origin("https://app.example.com#frag") is None
    assert normalize_origin("ftp://app.example.com") is None
    assert normalize_origin("http://example.com") is None
    assert normalize_origin("http://192.168.1.10") is None
    assert normalize_origin("http://127.0.0.999") is None
    assert normalize_origin("x" * 256) is None


def test_browser_transport_detects_each_evidence_signal() -> None:
    assert browser_transport(_scope([(b"origin", b"https://app.example.com")])) is True
    assert browser_transport(_scope([(b"sec-fetch-site", b"same-origin")])) is True
    assert browser_transport(_scope([(b"x-polyweb-client", b"browser")])) is True
    assert (
        browser_transport(_scope([(b"cookie", f"{REFRESH_COOKIE_NAME}=abc".encode("ascii"))]))
        is True
    )
    assert browser_transport(_scope([])) is False


def test_validate_browser_request_accepts_exact_allowed_origin() -> None:
    scope = _scope(_origin_headers())

    assert validate_browser_request(scope, _allowed(_ORIGIN)) is True


def test_validate_browser_request_rejects_evidence_failures() -> None:
    allowed = _allowed(_ORIGIN)

    assert validate_browser_request(_scope([]), allowed) is False
    assert validate_browser_request(_scope([]), frozenset()) is False
    assert (
        validate_browser_request(_scope(_origin_headers("https://evil.example.com")), allowed)
        is False
    )
    assert validate_browser_request(_scope(_origin_headers("null")), allowed) is False
    assert (
        validate_browser_request(_scope([(b"origin", _ORIGIN.encode("ascii"))]), allowed) is False
    )
    assert (
        validate_browser_request(
            _scope(
                [
                    (b"origin", _ORIGIN.encode("ascii")),
                    (b"x-polyweb-client", b"browser"),
                    (b"x-polyweb-client", b"browser"),
                ]
            ),
            allowed,
        )
        is False
    )
    assert (
        validate_browser_request(
            _scope([*_origin_headers(), (b"origin", _ORIGIN.encode("ascii"))]),
            allowed,
        )
        is False
    )
    assert (
        validate_browser_request(
            _scope(
                [
                    *_origin_headers(),
                    (b"authorization", b"Bearer one"),
                    (b"authorization", b"Bearer two"),
                ]
            ),
            allowed,
        )
        is False
    )


def test_validate_browser_request_rejects_duplicate_refresh_cookie_names() -> None:
    scope = _scope(
        [
            *_origin_headers(),
            (b"cookie", f"{REFRESH_COOKIE_NAME}=one; {REFRESH_COOKIE_NAME}=two".encode()),
        ]
    )

    assert validate_browser_request(scope, _allowed(_ORIGIN)) is False


def test_validate_browser_request_rejects_duplicate_cookie_headers() -> None:
    scope = _scope(
        [
            *_origin_headers(),
            (b"cookie", b"a=1"),
            (b"cookie", b"b=2"),
        ]
    )

    assert validate_browser_request(scope, _allowed(_ORIGIN)) is False


def test_refresh_credential_from_scope_returns_single_safe_value() -> None:
    token = "AbcDEF123-_456"
    scope = _scope([*_origin_headers(), (b"cookie", f"{REFRESH_COOKIE_NAME}={token}".encode())])

    assert refresh_credential_from_scope(scope, _allowed(_ORIGIN)) == token


def test_refresh_credential_from_scope_rejects_absent_and_malformed_values() -> None:
    allowed = _allowed(_ORIGIN)

    assert refresh_credential_from_scope(_scope(_origin_headers()), allowed) is None
    assert (
        refresh_credential_from_scope(
            _scope([*_origin_headers(), (b"cookie", f"{REFRESH_COOKIE_NAME}=".encode())]),
            allowed,
        )
        is None
    )
    assert (
        refresh_credential_from_scope(
            _scope([*_origin_headers(), (b"cookie", f"{REFRESH_COOKIE_NAME}=bad value!".encode())]),
            allowed,
        )
        is None
    )
    assert (
        refresh_credential_from_scope(
            _scope(
                [
                    *_origin_headers("https://evil.example.com"),
                    (b"cookie", f"{REFRESH_COOKIE_NAME}=Abc123".encode()),
                ]
            ),
            allowed,
        )
        is None
    )


def test_refresh_cookie_header_carries_strict_attributes() -> None:
    header = refresh_cookie_header("opaque-token-123", 604800)

    assert header.startswith(f"{REFRESH_COOKIE_NAME}=opaque-token-123; ")
    assert "Path=/auth/jwt/refresh" in header
    assert "Max-Age=604800" in header
    assert "HttpOnly" in header
    assert "Secure" in header
    assert "SameSite=Strict" in header
    assert "Domain=" not in header
    assert "__Host-" not in header


def test_refresh_cookie_header_clamps_age_to_family_lifetime() -> None:
    assert "Max-Age=604800" in refresh_cookie_header("t", 999999)
    assert "Max-Age=0" in refresh_cookie_header("t", -5)


def test_refresh_cookie_deletion_expires_scoped_cookie() -> None:
    header = refresh_cookie_deletion_header()

    assert header.startswith(f"{REFRESH_COOKIE_NAME}=; ")
    assert "Path=/auth/jwt/refresh" in header
    assert "Max-Age=0" in header
    assert "HttpOnly" in header
    assert "Secure" in header
    assert "SameSite=Strict" in header
    assert "Domain=" not in header


def test_set_and_clear_cookie_append_exact_headers() -> None:
    issued = Response(content="ok")
    set_refresh_cookie(issued, "opaque-token-123", 604800)

    raw = issued.headers.get("set-cookie", "")
    assert REFRESH_COOKIE_NAME in raw
    assert "Path=/auth/jwt/refresh" in raw
    assert "HttpOnly" in raw

    expired = Response(content="ok")
    clear_refresh_cookie(expired)

    deleted = expired.headers.get("set-cookie", "")
    assert deleted.startswith(f"{REFRESH_COOKIE_NAME}=; ")
    assert "Max-Age=0" in deleted
