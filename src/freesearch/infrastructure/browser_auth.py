"""Browser transport helpers for the refresh cookie.

The dashboard browser keeps its refresh credential in one host-only cookie. The
cookie uses ``HttpOnly``, ``Secure``, and ``SameSite=Strict``, and its path
covers ``/auth/jwt/refresh`` only. This module owns the cookie contract, the
exact Origin check, and the browser evidence check, so the ASGI guard and the
auth router apply one policy.

Cookie transport exists only when API composition supplies the operator origin
allowlist (``Settings.auth_browser_origins``). An empty allowlist keeps the
programmatic contract: JSON credential pairs and an opaque Bearer refresh
credential. An absent Origin never enables cookie transport.

The cookie value carries no signature and no readable payload. Only the opaque
rotating refresh credential of the service layer goes into the cookie.
"""

import ipaddress
from collections.abc import Mapping
from typing import Any
from urllib.parse import urlsplit

from starlette.responses import Response

#: A read-only ASGI scope. Both ``dict`` and Starlette's mapping satisfy it.
Scope = Mapping[str, Any]

#: The exact cookie name, path, and security attributes of the refresh cookie.
REFRESH_COOKIE_NAME = "__Secure-freesearch_refresh"
REFRESH_COOKIE_PATH = "/auth/jwt/refresh"

#: The client marker that every browser auth request must send.
BROWSER_CLIENT_HEADER = "x-freesearch-client"
BROWSER_CLIENT_VALUE = "browser"

#: Upper bound for the cookie age. It equals the absolute family lifetime.
MAX_REFRESH_COOKIE_AGE_SECONDS: int = 604800

_ORIGIN = b"origin"
_COOKIE = b"cookie"
_AUTHORIZATION = b"authorization"
_CLIENT_MARKER = BROWSER_CLIENT_HEADER.encode("ascii")
_FETCH_METADATA_HEADERS = (b"sec-fetch-mode", b"sec-fetch-site", b"sec-fetch-dest")
_LOOPBACK_NAMES = frozenset({"localhost"})
_COOKIE_VALUE_CHARACTERS = frozenset(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
)


def _header_values(scope: Scope, name: bytes) -> list[bytes]:
    """Return every raw value of one header, in wire order."""

    return [value for header, value in scope.get("headers") or [] if header.lower() == name]


def _text(value: bytes) -> str | None:
    """Decode one header value as ASCII, or return ``None``."""

    try:
        return value.decode("ascii")
    except UnicodeDecodeError:
        return None


def is_loopback_host(host: str | None) -> bool:
    """Return whether a host name or numeric address names the local machine."""

    if not host:
        return False
    normalized = host.strip().strip("[]").lower()
    if normalized in _LOOPBACK_NAMES:
        return True
    try:
        return ipaddress.ip_address(normalized).is_loopback
    except ValueError:
        return False


def normalize_origin(value: str) -> str | None:
    """Return the exact origin form of ``value``, or ``None`` when it is invalid.

    A valid origin has a scheme, a host, and an optional port. It has no
    userinfo, path, query, fragment, or wildcard. HTTPS is mandatory outside
    loopback development, where a numeric host must be a real loopback address.
    """

    text = value.strip()
    if not text or len(text) > 255 or "*" in text:
        return None
    parsed = urlsplit(text)
    if parsed.scheme not in {"http", "https"}:
        return None
    if parsed.username is not None or parsed.password is not None:
        return None
    if parsed.query or parsed.fragment:
        return None
    if parsed.path not in {"", "/"}:
        return None
    host = parsed.hostname
    if not host:
        return None
    try:
        port = parsed.port
    except ValueError:
        return None
    if parsed.scheme == "http" and not is_loopback_host(host):
        return None
    authority_host = f"[{host}]" if ":" in host else host
    authority = authority_host if port is None else f"{authority_host}:{port}"
    return f"{parsed.scheme}://{authority}"


def _cookie_pairs(scope: Scope) -> list[tuple[str, str]] | None:
    """Return the cookie pairs of the request, or ``None`` when malformed."""

    headers = _header_values(scope, _COOKIE)
    if len(headers) > 1:
        return None
    if not headers:
        return []
    text = _text(headers[0])
    if text is None:
        return None
    pairs: list[tuple[str, str]] = []
    for segment in text.split(";"):
        name, separator, value = segment.strip().partition("=")
        if not separator or not name:
            continue
        pairs.append((name, value))
    return pairs


def _refresh_cookie_values(scope: Scope) -> list[str] | None:
    """Return every value of the refresh cookie, or ``None`` when malformed."""

    pairs = _cookie_pairs(scope)
    if pairs is None:
        return None
    return [value for name, value in pairs if name == REFRESH_COOKIE_NAME]


def _sends_refresh_cookie(scope: Scope) -> bool:
    """Return whether the request carries the refresh cookie name at all."""

    marker = f"{REFRESH_COOKIE_NAME}=".encode("ascii")
    return any(marker in value for value in _header_values(scope, _COOKIE))


def _cookie_value_is_safe(value: str) -> bool:
    """Return whether a value can be an opaque refresh credential."""

    return bool(value) and all(char in _COOKIE_VALUE_CHARACTERS for char in value)


def browser_transport(scope: Scope) -> bool:
    """Return whether the request shows browser transport evidence.

    Origin, Fetch Metadata, the client marker, or the refresh cookie counts as
    evidence. Evidence alone never authorizes cookie transport: the configured
    origin allowlist and the client marker must also pass
    :func:`validate_browser_request`.
    """

    if _header_values(scope, _ORIGIN):
        return True
    if any(_header_values(scope, name) for name in _FETCH_METADATA_HEADERS):
        return True
    if _header_values(scope, _CLIENT_MARKER):
        return True
    return _sends_refresh_cookie(scope)


def _exact_origin_allowed(scope: Scope, allowed_origins: frozenset[str]) -> bool:
    """Return whether the request carries one allowed exact Origin."""

    values = _header_values(scope, _ORIGIN)
    if len(values) != 1:
        return False
    text = _text(values[0])
    if text is None:
        return False
    normalized = normalize_origin(text)
    return normalized is not None and normalized in allowed_origins


def validate_browser_request(scope: Scope, allowed_origins: frozenset[str]) -> bool:
    """Return whether a browser request passes every evidence check.

    A failure means an absent, duplicated, or unlisted Origin, an absent or
    duplicated client marker, a duplicated ``Authorization`` header, or a
    duplicated refresh-cookie name. The caller must reject that request before
    any token verification, so a rejected request can never rotate a credential
    or revoke a family.
    """

    if not allowed_origins:
        return False
    if not _exact_origin_allowed(scope, allowed_origins):
        return False
    markers = _header_values(scope, _CLIENT_MARKER)
    if len(markers) != 1:
        return False
    marker = _text(markers[0])
    if marker is None or marker.strip().lower() != BROWSER_CLIENT_VALUE:
        return False
    if len(_header_values(scope, _AUTHORIZATION)) > 1:
        return False
    values = _refresh_cookie_values(scope)
    return values is not None and len(values) <= 1


def refresh_credential_from_scope(scope: Scope, allowed_origins: frozenset[str]) -> str | None:
    """Return the refresh cookie credential of a validated browser request.

    The result is ``None`` when the browser evidence fails, when the cookie is
    absent or duplicated, or when the value is not a well-formed opaque
    credential. The caller maps that result to a generic HTTP 401.
    """

    if not validate_browser_request(scope, allowed_origins):
        return None
    values = _refresh_cookie_values(scope)
    if not values or len(values) != 1 or not _cookie_value_is_safe(values[0]):
        return None
    return values[0]


def refresh_cookie_header(token: str, max_age: int) -> str:
    """Return the ``Set-Cookie`` value that installs the refresh cookie."""

    age = max(0, min(int(max_age), MAX_REFRESH_COOKIE_AGE_SECONDS))
    return (
        f"{REFRESH_COOKIE_NAME}={token}; Path={REFRESH_COOKIE_PATH}; "
        f"Max-Age={age}; HttpOnly; Secure; SameSite=Strict"
    )


def refresh_cookie_deletion_header() -> str:
    """Return the ``Set-Cookie`` value that expires the refresh cookie."""

    return (
        f"{REFRESH_COOKIE_NAME}=; Path={REFRESH_COOKIE_PATH}; "
        "Max-Age=0; HttpOnly; Secure; SameSite=Strict"
    )


def set_refresh_cookie(response: Response, token: str, max_age: int) -> None:
    """Install the refresh cookie on one response."""

    response.headers.append("set-cookie", refresh_cookie_header(token, max_age))


def clear_refresh_cookie(response: Response) -> None:
    """Expire the refresh cookie on one response."""

    response.headers.append("set-cookie", refresh_cookie_deletion_header())


__all__ = [
    "BROWSER_CLIENT_HEADER",
    "BROWSER_CLIENT_VALUE",
    "MAX_REFRESH_COOKIE_AGE_SECONDS",
    "REFRESH_COOKIE_NAME",
    "REFRESH_COOKIE_PATH",
    "browser_transport",
    "clear_refresh_cookie",
    "is_loopback_host",
    "normalize_origin",
    "refresh_cookie_deletion_header",
    "refresh_cookie_header",
    "refresh_credential_from_scope",
    "set_refresh_cookie",
    "validate_browser_request",
]
