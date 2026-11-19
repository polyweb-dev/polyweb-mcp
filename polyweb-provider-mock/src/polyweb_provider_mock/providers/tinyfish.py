"""Tinyfish Search on ``api.search.tinyfish.ai`` and Fetch on ``api.fetch.tinyfish.ai``.

Both products serve their main operation on the root path, so the plugin
claims both hosts and scopes each operation to its host (the other host
answers 405, as a wrong method does):

- ``GET /`` on the search host: query parameters ``query`` (required),
  ``page`` (0..10), domain filters, location/language, date and
  academic-year filters, ``domain_type`` (``web``, ``news``,
  ``research_paper``). Ten results per page.
- ``POST /`` on the fetch host: JSON ``{"urls": [...1..10], "format": ...}``
  plus link, cache, conditional, selector, and highlights options. Per-URL
  failures are entries in ``errors[]`` of an HTTP 200, as documented.
- ``GET /usage`` on either host: the documented usage history, built from
  this mock's request log. Polyweb does not call it.

Recorded: the four 401 responses (2026-11-17) and an authenticated capture
(2026-11-19, ``tests/contract/recordings/tinyfish``): search on every domain
type, fetch in all three formats with options and per-URL failures, every
validation error below, ``/usage`` on both hosts, and the 404/405 routes.
Unrecorded, from the docs: 402, 429, 5xx, ``iframe_links``, conditional
fetches, ``etag``/``last_modified`` (example.com sent none), and highlights
on an account that has them (the recorded account got 403).

Authentication is ``X-API-Key`` only. A missing key is 401
``MISSING_API_KEY``; an unknown or revoked key is 401 ``INVALID_API_KEY``
(the docs give revoked keys the same answer). Every error is
``{"error": {"code", "message", "details"?}, "request_id"}`` with the same
``X-Request-ID`` header. Only the 401s, which an edge layer answers, carry
``Cache-Control: no-store`` and ``WWW-Authenticate``; everything past
authentication carries the application's headers instead, among them
``X-TF-User-ID`` (a fake Clerk-style id per account) and
``X-Middleware-Rewrite``. Validation errors follow Zod's issue format except
the CSS-selector check, a 422 with a Pydantic-style message and no
``details``. A wrong method on ``/`` is 405 with an empty body (without
the real ``X-TF-User-ID``: the mock routes before it authenticates); an
unknown path is the site's HTML 404.

Limits follow Polyweb's catalog and the public pricing page, per account
(person): Search 30 requests per minute and 500 per hour, Fetch 150 URLs per
minute (429 ``RATE_LIMIT_EXCEEDED`` with ``details``, ``Retry-After``, and
``X-RateLimit-*`` headers; the reset header is Unix seconds). The daily free
allowance resets at 00:00 UTC: 12,000 Search requests and 1,000 successful
Fetch URLs. Beyond it, an account whose ``wallet_balance`` attribute is not
positive gets 402 ``INSUFFICIENT_CREDITS`` (``FREE_ALLOWANCE_EXHAUSTED`` for
plan ``beta``). The docs publish no overage price, so nothing draws the
wallet. Account attributes override any limit (``search_per_minute``,
``search_per_hour``, ``search_daily_free``, ``fetch_per_minute``,
``fetch_daily_free``). ``credits set tinyfish 0`` also forces the 402.

As recorded, every search request spends a minute slot, an invalid one too
(its 400 carries the ``X-RateLimit-*`` headers). Fetch spends one slot per
URL, failed URLs included, but a request that fails schema validation (400)
or asks for highlights without access (403) spends none; the selector 422
comes after the slots are spent. The documented 60-per-minute limit on
invalid requests and usage reads is not modelled.

Search results list their fields in alphabetical order. Web results carry
``date`` on some hits in mixed forms (ISO 8601, ``Oct 18, 2020``,
``4 days ago``); news dates are RFC 2822 (``Wed, 11 Nov 2026 23:13:16 GMT``).
A fetch response that has ``errors`` also carries ``request_id``.

Synthetic fetch targets (first host label): ``blocked`` ``bot_blocked``,
``login`` ``login_required``, ``empty`` ``empty_content``, ``timeout``
``timeout``, ``proxy`` ``proxy_error``, ``unreachable``
``target_unreachable``, ``missing`` ``page_not_found`` 404, ``gone`` 410,
``status-503`` ``target_http_error`` 503 (any status), a ``.invalid`` host or
a private or loopback host ``invalid_url`` (as recorded for an unresolvable
host), a ``/404`` path ``page_not_found``. The JSON ``format`` document is
``{"type": "document", "children": [...]}``; only ``paragraph`` nodes were
recorded, so the ``heading`` and ``list`` nodes are a guess.
"""

import base64
import ipaddress
import json
import re
import secrets
import uuid
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from email.utils import format_datetime
from typing import Any, ClassVar, Final
from urllib.parse import urlsplit

from starlette.requests import Request

from polyweb_provider_mock import content
from polyweb_provider_mock.models import (
    Account,
    AccountSeed,
    KeyFormat,
    KeySeed,
    LogEntry,
    PriceRule,
    ProviderSeed,
)
from polyweb_provider_mock.providers.base import (
    Credentials,
    ErrorContext,
    ErrorKind,
    MockResponse,
    Operation,
    OperationContext,
    ProviderPlugin,
    header_value,
)
from polyweb_provider_mock.store import MockStore
from polyweb_provider_mock.windows import Window, WindowSpec

__all__ = ["PLUGIN", "TinyfishPlugin"]

_SEARCH_HOST: Final = "api.search.tinyfish.ai"
_FETCH_HOST: Final = "api.fetch.tinyfish.ai"
_WALLET_URL: Final = "https://agent.tinyfish.ai/wallet"
_PAGE_SIZE: Final = 10
_DOMAIN_TYPES: Final = ("web", "news", "research_paper")
_FORMATS: Final = ("markdown", "html", "json")
_DATE: Final = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_STATUS_HOST: Final = re.compile(r"^status-(\d{3})$")
_ACADEMIC: Final = ("arxiv.org", "www.nature.com", "dl.acm.org", "openreview.net")
_VENUES: Final = ("NeurIPS", "ICML", "Nature", "ACM Computing Surveys", "ICLR", "arXiv")
_AUTHORS: Final = ("A. Rivera", "J. Chen", "M. Okafor", "S. Novak", "L. Haddad", "K. Tanaka")
_KNOWN_SELECTORS: Final = frozenset(
    {"main", "article", "body", "section", "h1", "h2", "p", "#content", ".content"}
)
_DEFAULT_LIMITS: Final = {
    "search_per_minute": 30,
    "search_per_hour": 500,
    "search_daily_free": 12_000,
    "fetch_per_minute": 150,
    "fetch_daily_free": 1_000,
}
_FAILURES: Final[dict[str, dict[str, Any]]] = {
    "blocked": {"error": "bot_blocked"},
    "login": {"error": "login_required"},
    "empty": {"error": "empty_content"},
    "timeout": {"error": "timeout"},
    "proxy": {"error": "proxy_error"},
    "unreachable": {"error": "target_unreachable"},
    "missing": {"error": "page_not_found", "status": 404},
    "gone": {"error": "page_not_found", "status": 410},
}
#: Headers the application sends on every response past authentication (recorded).
_APP_HEADERS: Final = {
    "strict-transport-security": "max-age=63072000; includeSubDomains",
    "x-frame-options": "DENY",
    "x-content-type-options": "nosniff",
    "referrer-policy": "no-referrer",
    "access-control-allow-headers": (
        "Content-Type, X-API-Key, Authorization, X-TF-Request-Origin, X-TF-Client-Name, "
        "X-TF-Client-Version, X-TF-API-Source, X-TF-API-Example, X-TF-Setup-Attempt-Id, "
        "X-TF-Connect-Source, X-TF-Connect-Client, X-TF-Connect-Attempt-Id, Payment-Authorization"
    ),
    "access-control-allow-methods": "GET, POST, PUT, DELETE, OPTIONS",
    "access-control-allow-origin": "*",
    "access-control-expose-headers": (
        "Retry-After, X-RateLimit-Limit, X-RateLimit-Remaining, X-RateLimit-Reset, X-Request-ID, "
        "X-TF-Notice, X-TF-Notice-Level, X-TF-Notice-Latest, X-TF-Notice-Package, "
        "WWW-Authenticate, Payment-Receipt"
    ),
    "x-clerk-auth-reason": "session-token-and-uat-missing",
    "x-clerk-auth-status": "signed-out",
    "vary": "rsc, next-router-state-tree, next-router-prefetch, next-router-segment-prefetch",
}
_BASE62: Final = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
_NOT_FOUND_PAGE: Final = (
    b'<!DOCTYPE html><html lang="en"><head><meta charSet="utf-8"/>'
    b"<title>404: This page could not be found.</title></head><body>"
    b"<h1>404</h1><h2>This page could not be found.</h2></body></html>"
)


class _Rejected(Exception):
    """A request that fails validation; carries the provider response."""

    def __init__(self, response: MockResponse) -> None:
        super().__init__(response.status)
        self.response = response


def _request_host(request: Request) -> str:
    return (request.headers.get("host") or "").split(":")[0].lower().rstrip(".")


def _cdn_headers(*, error: bool) -> dict[str, str]:
    edge = uuid.uuid4()
    return {
        "x-cache": "Error from cloudfront" if error else "Miss from cloudfront",
        "via": f"1.1 {edge.hex}.cloudfront.net (CloudFront)",
        "x-amz-cf-pop": "DFW57-P8",
        "server": "uvicorn",
        "x-amz-cf-id": base64.urlsafe_b64encode(secrets.token_bytes(40)).decode(),
    }


def _error(
    status: int,
    code: str,
    message: str,
    *,
    details: Any = None,
    headers: Mapping[str, str] | None = None,
) -> MockResponse:
    """Return Tinyfish's ``{"error": {...}, "request_id"}`` envelope."""

    request_id = str(uuid.uuid4())
    error: dict[str, Any] = {"code": code, "message": message}
    if details is not None:
        error["details"] = details
    # The edge answers 401s; everything else comes from the application.
    edge = {"cache-control": "no-store", "www-authenticate": "ApiKey"}
    out = {
        **(edge if status == 401 else _APP_HEADERS),
        **_cdn_headers(error=True),
        **(headers or {}),
        "x-request-id": request_id,
    }
    return MockResponse(status=status, body={"error": error, "request_id": request_id}, headers=out)


def _user_id(account_id: str) -> str:
    """Return a stable Clerk-style ``user_`` id (27 base-62 characters) for an account."""

    rng = content.rng("tinyfish-user", account_id)
    return "user_3" + "".join(rng.choice(_BASE62) for _ in range(26))


def _issue(path: Sequence[str | int], code: str, message: str, **extra: Any) -> dict[str, Any]:
    return {**extra, "code": code, "path": list(path), "message": message}


def _bound(
    path: Sequence[str | int],
    origin: str,
    *,
    low: int | None = None,
    high: int | None = None,
    message: str,
) -> dict[str, Any]:
    """Return Zod's ``too_small``/``too_big`` issue, as recorded."""

    if high is not None:
        return _issue(path, "too_big", message, origin=origin, maximum=high, inclusive=True)
    return _issue(path, "too_small", message, origin=origin, minimum=low, inclusive=True)


def _input_error(*issues: dict[str, Any], status: int = 400) -> _Rejected:
    first = issues[0]
    field = ".".join(str(part) for part in first["path"])
    message = f'Field "{field}": {first["message"]}' if field else first["message"]
    return _Rejected(_error(status, "INVALID_INPUT", message, details=list(issues)))


def _custom(path: Sequence[str | int], message: str) -> _Rejected:
    return _input_error(_issue(path, "custom", message))


def _int_param(
    params: Mapping[str, str],
    name: str,
    low: int,
    high: int,
    *,
    messages: tuple[str, str] | None = None,
) -> int | None:
    """Parse an integer query parameter in ``low..high``; raise on a bad value.

    ``messages`` replaces Zod's default too-small and too-big wording, as the
    search ``page`` parameter does (``page must be <= 10``).
    """

    raw = params.get(name)
    if raw is None:
        return None
    try:
        value = int(raw)
    except ValueError:
        raise _input_error(
            _issue(
                [name],
                "invalid_type",
                "Invalid input: expected number, received NaN",
                expected="number",
                received="NaN",
            )
        ) from None
    small, big = messages or (
        f"Too small: expected number to be >={low}",
        f"Too big: expected number to be <={high}",
    )
    if value < low:
        raise _input_error(_bound([name], "number", low=low, message=small))
    if value > high:
        raise _input_error(_bound([name], "number", high=high, message=big))
    return value


def _date_param(params: Mapping[str, str], name: str) -> date | None:
    raw = params.get(name)
    if raw is None:
        return None
    try:
        if not _DATE.match(raw):
            raise ValueError(raw)
        return date.fromisoformat(raw)
    except ValueError:
        raise _custom([name], f"{name} must be YYYY-MM-DD") from None


def _domains(raw: str | None) -> list[str]:
    return [item.strip().lower() for item in (raw or "").split(",") if item.strip()]


def _search_request(params: Mapping[str, str]) -> dict[str, Any]:
    """Validate search query parameters with the recorded messages."""

    query = params.get("query")
    if query is None:
        raise _input_error(
            _issue(
                ["query"],
                "invalid_type",
                "Invalid input: expected string, received undefined",
                expected="string",
            )
        )
    if not query.strip():
        raise _input_error(_bound(["query"], "string", low=1, message="query is required"))
    page = _int_param(params, "page", 0, 10, messages=("page must be >= 0", "page must be <= 10"))
    domain_type = params.get("domain_type") or "web"
    if domain_type not in _DOMAIN_TYPES:
        raise _input_error(
            _issue(
                ["domain_type"],
                "invalid_value",
                'Invalid option: expected one of "web"|"news"|"research_paper"',
                values=list(_DOMAIN_TYPES),
            )
        )
    # A blank purpose is accepted (recorded); only the documented length is checked.
    purpose = params.get("purpose")
    if purpose is not None and len(purpose) > 2000:
        raise _custom(["purpose"], "purpose must be at most 2000 characters")
    _search_filters(params, domain_type)
    return {
        "query": query,
        "page": page or 0,
        "domain_type": domain_type,
        "include": _domains(params.get("include_domains")),
        "exclude": _domains(params.get("exclude_domains")),
        # Recorded: with a recency or date filter every web result is dated.
        "dated": any(params.get(name) for name in ("recency_minutes", "after_date", "before_date")),
    }


def _search_filters(params: Mapping[str, str], domain_type: str) -> None:
    """Check the date, recency, and academic-year rules (recorded wording and paths)."""

    recency = _int_param(params, "recency_minutes", 1, 5_256_000)
    after, before = _date_param(params, "after_date"), _date_param(params, "before_date")
    year_min = _int_param(params, "pub_year_min", 0, 9999)
    year_max = _int_param(params, "pub_year_max", 0, 9999)
    dated = after is not None or before is not None
    if recency is not None and dated:
        raise _custom(
            ["recency_minutes"], "recency_minutes cannot be combined with after_date or before_date"
        )
    if after is not None and before is not None and after > before:
        raise _custom(["before_date"], "after_date must be on or before before_date")
    if domain_type == "research_paper" and (dated or recency is not None):
        raise _custom(
            ["domain_type"],
            "date and recency filters are not supported for domain_type=research_paper",
        )
    if (year_min is not None or year_max is not None) and domain_type != "research_paper":
        raise _custom(
            ["domain_type"],
            "pub_year_min and pub_year_max are only supported for domain_type=research_paper",
        )
    if year_min is not None and year_max is not None and year_min > year_max:
        # Unrecorded; worded like the recorded date-order check.
        raise _custom(["pub_year_max"], "pub_year_min must be on or before pub_year_max")


def _json_type(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, list):
        return "array"
    return "string" if isinstance(value, str) else "object"


def _json_object(raw: bytes) -> dict[str, Any]:
    try:
        body = json.loads(raw or b"null")
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise _Rejected(_error(400, "INVALID_INPUT", "Invalid JSON in request body")) from None
    if not isinstance(body, dict):
        message = f"Invalid input: expected object, received {_json_type(body)}"
        raise _input_error(_issue([], "invalid_type", message, expected="object"))
    return body


def _fetch_urls(body: Mapping[str, Any]) -> list[str]:
    urls = body.get("urls")
    if not isinstance(urls, list):
        received = "undefined" if "urls" not in body else _json_type(urls)
        raise _input_error(
            _issue(
                ["urls"],
                "invalid_type",
                f"Invalid input: expected array, received {received}",
                expected="array",
            )
        )
    if not urls:
        message = "Too small: expected array to have >=1 items"
        raise _input_error(_bound(["urls"], "array", low=1, message=message))
    if len(urls) > 10:
        message = "Too big: expected array to have <=10 items"
        raise _input_error(_bound(["urls"], "array", high=10, message=message))
    for index, url in enumerate(urls):
        parts = urlsplit(url) if isinstance(url, str) else None
        if parts is None or parts.scheme not in ("http", "https") or not parts.hostname:
            raise _input_error(
                _issue(["urls", index], "invalid_format", "Invalid URL", format="url")
            )
    return list(urls)


def _check_type(
    body: Mapping[str, Any], name: str, kind: type, low: int | None = None, high: int | None = None
) -> None:
    value: Any = body.get(name)
    if value is None:
        return
    numeric = kind is int
    if not isinstance(value, kind) or (numeric and isinstance(value, bool)):
        expected = "number" if numeric else kind.__name__.replace("bool", "boolean")
        message = f"Invalid input: expected {expected}, received {_json_type(value)}"
        raise _input_error(_issue([name], "invalid_type", message, expected=expected))
    number = int(body[name]) if numeric else 0
    if numeric and low is not None and number < low:
        message = f"Too small: expected number to be >={low}"
        raise _input_error(_bound([name], "number", low=low, message=message))
    if numeric and high is not None and number > high:
        message = f"Too big: expected number to be <={high}"
        raise _input_error(_bound([name], "number", high=high, message=message))


def _selectors(body: Mapping[str, Any], name: str) -> list[str]:
    """Check the selector list's documented size limits (the 400 part)."""

    value = body.get(name)
    if value is None:
        return []
    valid = (
        isinstance(value, list)
        and 1 <= len(value) <= 20
        and all(isinstance(item, str) and item.strip() and len(item) <= 1000 for item in value)
    )
    if not valid:
        raise _custom(
            [name], f"{name} must be 1 to 20 non-blank selectors of at most 1000 characters"
        )
    return list(value)


def _selector_problem(selector: str) -> tuple[str, int] | None:
    """Return ``(reason, position)`` for a selector the CSS parser rejects.

    The recorded reasons are ``Invalid character '{' position 0``,
    ``Malformed attribute selector at position 0`` and ``Malformed
    pseudo-class selector at position 1``; other malformed selectors reuse them.
    """

    for index, char in enumerate(selector):
        if char in "{}":
            return f"Invalid character '{char}' position {index}", index
    bracket = selector.find("[")
    if selector.count("[") != selector.count("]") and bracket >= 0:
        return f"Malformed attribute selector at position {bracket}", bracket
    if selector.count("(") != selector.count(")"):
        colon = selector.rfind(":", 0, max(0, selector.find("(")) or len(selector))
        at = max(colon, 0)
        return f"Malformed pseudo-class selector at position {at}", at
    first = selector.strip()[0]
    if first in "0123456789>+~,":
        index = selector.index(first)
        return f"Invalid character '{first}' position {index}", index
    return None


def _selector_error(request: Mapping[str, Any]) -> MockResponse | None:
    """Return the recorded 422 for the first selector the CSS parser rejects."""

    for name in ("include_selectors", "exclude_selectors"):
        for selector in request[name]:
            problem = _selector_problem(selector)
            if problem is None:
                continue
            reason, at = problem
            message = (
                f"body.{name}: Value error, {name} contains an unsupported CSS selector "
                f"('{selector}'): {reason}\n  line 1:\n{selector}\n{' ' * at}^"
            )
            return _error(422, "INVALID_INPUT", message)
    return None


def _highlights(body: Mapping[str, Any], fmt: str) -> dict[str, Any] | None:
    value = body.get("highlights")
    if value is None:
        return None
    if (
        not isinstance(value, dict)
        or not isinstance(value.get("query"), str)
        or not value["query"].strip()
    ):
        raise _custom(["highlights", "query"], "highlights.query must be a non-empty string")
    _check_type(value, "max_snippets", int, 1, 20)
    _check_type(value, "max_characters", int, 100, 20_000)
    _check_type(value, "include_full_page_text", bool)
    if fmt != "markdown":
        raise _custom(["highlights"], "highlights is only valid when format is 'markdown'")
    return value


def _fetch_request(raw: bytes) -> dict[str, Any]:
    """Validate a fetch body as the Fetch reference documents."""

    body = _json_object(raw)
    urls = _fetch_urls(body)
    fmt = body.get("format") or "markdown"
    if fmt not in _FORMATS:
        raise _input_error(
            _issue(
                ["format"],
                "invalid_value",
                'Invalid option: expected one of "markdown"|"html"|"json"',
                values=list(_FORMATS),
            )
        )
    purpose = body.get("purpose")
    if purpose is not None and (
        not isinstance(purpose, str) or not purpose.strip() or len(purpose) > 2000
    ):
        raise _custom(["purpose"], "purpose must be 1 to 2000 non-blank characters")
    for name in ("links", "image_links", "iframe_links", "include_etag_and_last_modified"):
        _check_type(body, name, bool)
    _check_type(body, "ttl", int, 0)
    _check_type(body, "per_url_timeout_ms", int, 1, 110_000)
    conditional = body.get("if_none_match") is not None or body.get("if_modified_since") is not None
    if conditional and len(urls) > 1:
        raise _custom(["urls"], "if_none_match and if_modified_since accept a single URL only")
    return {
        **body,
        "urls": urls,
        "format": fmt,
        "include_selectors": _selectors(body, "include_selectors"),
        "exclude_selectors": _selectors(body, "exclude_selectors"),
        "highlights": _highlights(body, fmt),
    }


def _private(host: str) -> bool:
    if host == "localhost" or host.endswith((".local", ".internal", ".localhost")):
        return True
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    return address.is_private or address.is_loopback or address.is_link_local


def _failure(url: str, request: Mapping[str, Any]) -> dict[str, Any] | None:
    """Return the synthetic ``errors[]`` entry for a URL whose host asks for one."""

    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    first = host.split(".")[0]
    status = _STATUS_HOST.match(first)
    if _private(host) or host.endswith(".invalid"):
        return {"url": url, "error": "invalid_url"}
    if status is not None:
        return {"url": url, "error": "target_http_error", "status": int(status.group(1))}
    if first in _FAILURES:
        return {"url": url, **_FAILURES[first]}
    if "/404" in parts.path:
        return {"url": url, "error": "page_not_found", "status": 404}
    if request["include_selectors"] and parts.path.lower().endswith((".pdf", ".csv")):
        return {"url": url, "error": "selector_unsupported"}
    return None


def _matches(selector: str) -> bool:
    tokens = re.split(r"[\s,>+~]+", selector.strip())
    return any(token in _KNOWN_SELECTORS for token in tokens)


def _html(page: content.Page) -> str:
    parts = [f"<html><head><title>{page.title}</title></head><body>"]
    for block in page.markdown.split("\n\n"):
        if block.startswith("## "):
            parts.append(f"<h2>{block[3:]}</h2>")
        elif block.startswith("# "):
            parts.append(f"<h1>{block[2:]}</h1>")
        elif block.startswith("- "):
            parts.append(f"<ul><li>{block[2:]}</li></ul>")
        else:
            parts.append(f"<p>{block}</p>")
    parts.append("</body></html>")
    return "".join(parts)


def _tree(page: content.Page) -> dict[str, Any]:
    """Return the JSON ``format`` document: typed nodes under ``children``.

    Recorded: ``{"type": "document", "children": [{"type": "paragraph",
    "text": ...}]}``, without the page title. Heading and list nodes are a guess.
    """

    children: list[dict[str, Any]] = []
    for block in page.markdown.split("\n\n")[1:]:
        if block.startswith("#"):
            level = len(block) - len(block.lstrip("#"))
            children.append({"type": "heading", "level": level, "text": block[level:].strip()})
        elif block.startswith("- "):
            items = [line[2:] for line in block.split("\n") if line.startswith("- ")]
            children.append({"type": "list", "items": items})
        else:
            children.append({"type": "paragraph", "text": block})
    return {"type": "document", "children": children}


def _web_date(published: datetime, now: datetime, turn: int) -> str:
    """Return a web result's ``date`` in one of the recorded forms, by turn."""

    age = (now - published).days
    if turn % 3 == 1:
        return f"{published:%b} {published.day}, {published.year}"
    if turn % 3 == 2 and 1 < age < 30:
        return f"{age} days ago"
    return published.strftime("%Y-%m-%dT%H:%M:%SZ")


def _usage_time(moment: datetime) -> str:
    """Return a usage ``created_at``: UTC ``YYYY-MM-DD HH:MM:SS`` (recorded)."""

    return moment.astimezone(UTC).strftime("%Y-%m-%d %H:%M:%S")


def _final_url(url: str) -> str:
    parts = urlsplit(url)
    return parts._replace(path=parts.path or "/").geturl()


class TinyfishPlugin(ProviderPlugin):
    """Tinyfish Search and Fetch."""

    name: ClassVar[str] = "tinyfish"
    hosts: ClassVar[frozenset[str]] = frozenset({_SEARCH_HOST, _FETCH_HOST})
    # The real key format is unpublished; mock keys are plain alphanumerics.
    key_format: ClassVar[KeyFormat] = KeyFormat(prefix="", body_length=40)

    def operations(self) -> Sequence[Operation]:
        return (
            Operation("search", "GET", "/", self._search, hosts=frozenset({_SEARCH_HOST})),
            Operation("fetch", "POST", "/", self._fetch, hosts=frozenset({_FETCH_HOST})),
            Operation("usage", "GET", "/usage", self._usage, billable=False),
        )

    def credentials(self, request: Request, store: MockStore) -> Credentials:
        return Credentials(key=header_value(request, "x-api-key"))

    def default_seed(self) -> ProviderSeed:
        return ProviderSeed(
            accounts=(
                AccountSeed(
                    id="tinyfish-personal",
                    plan="personal",
                    credit_limit=None,
                    reset_rule="daily",
                    attributes={"wallet_balance": "0.00", "highlights_beta": True},
                ),
            ),
            keys=(
                KeySeed(
                    label="default",
                    account_id="tinyfish-personal",
                    env_var="POLYWEB_TINYFISH_API_KEY",
                ),
                KeySeed(label="secondary", account_id="tinyfish-personal"),
            ),
        )

    def default_pricing(self) -> Sequence[PriceRule]:
        return (
            PriceRule(
                provider=self.name,
                operation="search",
                credits_per_unit=Decimal(1),
                usd_per_unit=Decimal(0),
            ),
            PriceRule(
                provider=self.name,
                operation="fetch",
                credits_per_unit=Decimal(1),
                usd_per_unit=Decimal(0),
                unit="url",
            ),
        )

    def not_found(self, request: Request, status: int) -> MockResponse:
        """A wrong method is an empty 405; an unknown path is the site's HTML 404 (recorded)."""

        if status == 405:
            headers = {
                **_APP_HEADERS,
                **_cdn_headers(error=True),
                "x-request-id": str(uuid.uuid4()),
            }
            return MockResponse(status=405, body=b"", headers=headers, media_type=None)
        return MockResponse(
            status=404,
            body=_NOT_FOUND_PAGE,
            headers={
                "cache-control": "private, no-cache, no-store, max-age=0, must-revalidate",
                **_cdn_headers(error=True),
            },
            media_type="text/html; charset=utf-8",
        )

    # --------------------------------------------------------------- errors

    def error(self, kind: ErrorKind, context: ErrorContext) -> MockResponse:
        status = context.status
        product = "Fetch" if context.operation == "fetch" else "Search"
        if kind is ErrorKind.AUTH_INVALID and context.missing_key:
            return _error(
                status or 401, "MISSING_API_KEY", context.message or "X-API-Key header is required"
            )
        if kind in (ErrorKind.AUTH_INVALID, ErrorKind.AUTH_REVOKED):
            return _error(
                status or 401, "INVALID_API_KEY", context.message or "Invalid or expired API key"
            )
        if kind is ErrorKind.RATE_LIMITED:
            return self._rate_limited(context)
        if kind is ErrorKind.QUOTA_EXHAUSTED:
            return self._exhausted(context.operation, context.scope, status, context.message)
        if kind is ErrorKind.FORBIDDEN:
            message = (
                "highlights is not enabled for this account"
                if product == "Fetch"
                else "Search request forbidden by the upstream service"
            )
            return _error(status or 403, "FORBIDDEN", context.message or message)
        if kind is ErrorKind.BAD_REQUEST:
            if status == 404:
                return _error(
                    404, "UNKNOWN_ROUTE", context.message or f"{product} API is not available"
                )
            return _error(status or 400, "INVALID_INPUT", context.message or "Invalid request")
        if kind is ErrorKind.SERVICE_UNAVAILABLE:
            if context.scope == "store":
                return _error(
                    status or 503, "SERVICE_BUSY", context.message or "Service temporarily busy"
                )
            message = f"{product} service unavailable"
            return _error(status or 503, "BACKEND_UNAVAILABLE", context.message or message)
        if status in (502, 504):
            message = (
                "Backend service timed out." if status == 504 else "Backend service unreachable."
            )
            return _error(status, "BACKEND_UNAVAILABLE", context.message or message)
        return _error(
            status or 500, "INTERNAL_ERROR", context.message or "An unexpected error occurred"
        )

    @staticmethod
    def _exhausted(
        operation: str, scope: str | None, status: int | None, message: str | None
    ) -> MockResponse:
        product = "Fetch" if operation == "fetch" else "Search"
        if scope in ("free_allowance", "beta"):
            text = f"Daily free {product} allowance used; it resets at 00:00 UTC."
            return _error(status or 402, "FREE_ALLOWANCE_EXHAUSTED", message or text)
        campaign = product.lower()
        text = (
            f"Daily free {product} allowance used and your wallet balance is empty. Add funds at "
            f"{_WALLET_URL}?utm_source=api&utm_medium=insufficient_funds&utm_campaign={campaign}"
        )
        return _error(status or 402, "INSUFFICIENT_CREDITS", message or text)

    def _rate_limited(
        self, context: ErrorContext, *, window: Window | None = None, now: datetime | None = None
    ) -> MockResponse:
        fetch = context.operation == "fetch"
        unit = "urls" if fetch else "requests"
        limit = window.spec.limit if window is not None else (150 if fetch else 30)
        seconds_window = int(window.spec.seconds) if window is not None else 60
        moment = now or datetime.now(UTC)
        retry = (
            window.retry_after(moment)
            if window is not None
            else (context.retry_after if context.retry_after is not None else 60)
        )
        reset = window.reset if window is not None else moment + timedelta(seconds=retry)
        campaign = "fetch" if fetch else "search"
        upgrade = (
            f"{_WALLET_URL}?utm_source=api&utm_medium=rate_limit_error&utm_campaign={campaign}"
        )
        per = {60: "minute", 3600: "hour", 86400: "day"}.get(
            seconds_window, f"{seconds_window} seconds"
        )
        noun = "URLs" if fetch else "requests"
        headers = {
            "x-ratelimit-limit": str(limit),
            "x-ratelimit-remaining": "0",
            "x-ratelimit-reset": str(int(reset.timestamp())),
        }
        if context.retry_after_header:
            headers["Retry-After"] = str(retry)
        return _error(
            429,
            "RATE_LIMIT_EXCEEDED",
            context.message
            or f"Rate limit exceeded. Limit: {limit} {noun} per {per}. "
            f"Request a higher limit at {upgrade}",
            details={
                "limit": limit,
                "unit": unit,
                "window_seconds": seconds_window,
                "upgrade_url": upgrade,
            },
            headers=headers,
        )

    # ------------------------------------------------------------ helpers

    @staticmethod
    def _account(context: OperationContext) -> Account:
        account = context.principal.account
        assert account is not None
        return account

    def _limit(self, account: Account, name: str) -> int:
        return int(account.attributes.get(name, _DEFAULT_LIMITS[name]))

    def _gate(
        self, context: OperationContext, product: str, units: int
    ) -> tuple[dict[str, str], WindowSpec] | MockResponse:
        """Spend the per-minute (and per-hour) slots, then check the daily allowance."""

        account = self._account(context)
        prefix = f"tinyfish:{account.id}:{product}"
        specs = [
            WindowSpec(
                f"{prefix}:minute", self._limit(account, f"{product}_per_minute"), 60, aligned=True
            )
        ]
        if product == "search" and self._limit(account, "search_per_hour") > 0:
            specs.append(
                WindowSpec(
                    f"{prefix}:hour", self._limit(account, "search_per_hour"), 3600, aligned=True
                )
            )
        daily = WindowSpec(
            f"{prefix}:day", self._limit(account, f"{product}_daily_free"), 86400, aligned=True
        )
        now = context.store.now()
        if context.store.peek_window(daily).remaining <= 0 and not self._wallet_funded(account):
            scope = "beta" if account.plan == "beta" else None
            exhausted = self._exhausted(product, scope, None, None)
            return self._rejected(exhausted, self._app_headers(context))
        refused, windows = context.admit(specs, units)
        if refused is not None:
            limited = self._rate_limited(ErrorContext(operation=product), window=refused, now=now)
            return self._rejected(limited, self._app_headers(context))
        minute = windows[0]
        headers = {
            **self._app_headers(context),
            "x-ratelimit-limit": str(minute.spec.limit),
            "x-ratelimit-remaining": str(minute.remaining),
            "x-ratelimit-reset": str(int(minute.reset.timestamp())),
        }
        return headers, daily

    @staticmethod
    def _wallet_funded(account: Account) -> bool:
        try:
            return Decimal(str(account.attributes.get("wallet_balance", "0"))) > 0
        except ArithmeticError:
            return False

    def _app_headers(self, context: OperationContext) -> dict[str, str]:
        """Return the application headers, with this account's id and the internal path."""

        product = "search" if _request_host(context.request) == _SEARCH_HOST else "fetch"
        path = context.request.url.path.rstrip("/")
        query = context.request.url.query
        rewrite = f"/v1/{product}{path}" + (f"?{query}" if query else "")
        return {
            **_APP_HEADERS,
            "x-middleware-rewrite": rewrite,
            "x-tf-user-id": _user_id(self._account(context).id),
        }

    @staticmethod
    def _rejected(response: MockResponse, headers: Mapping[str, str]) -> MockResponse:
        """Add the application (and any rate-limit) headers to an error response."""

        response.headers.update({k: v for k, v in headers.items() if k not in response.headers})
        return response

    @staticmethod
    def _ok(
        body: Any, headers: Mapping[str, str], *, echo_request_id: bool = False
    ) -> MockResponse:
        request_id = str(uuid.uuid4())
        if echo_request_id:
            body = {**body, "request_id": request_id}
        return MockResponse(
            status=200,
            body=body,
            headers={**headers, **_cdn_headers(error=False), "x-request-id": request_id},
        )

    # --------------------------------------------------------------- search

    async def _search(self, context: OperationContext) -> MockResponse:
        # Recorded: an invalid search spends a minute slot too.
        gate = self._gate(context, "search", 1)
        if isinstance(gate, MockResponse):
            return gate
        headers, daily = gate
        try:
            request = _search_request(context.request.query_params)
        except _Rejected as rejected:
            return self._rejected(rejected.response, headers)
        context.match_key = content.normalize_query(request["query"])
        fixture = context.fixture(context.match_key)
        if fixture is not None and fixture.status != 200:
            return MockResponse(
                status=fixture.status,
                body=fixture.body,
                headers={**headers, **_cdn_headers(error=True)},
            )
        context.charge("search")
        context.store.count_window(daily, 1)
        if fixture is not None and isinstance(fixture.body, dict):
            return self._ok(fixture.body, headers)
        results = self._results(request, context.store.now())
        body = {
            "query": request["query"],
            "results": results,
            "total_results": len(results),
            "page": request["page"],
        }
        return self._ok(body, headers)

    @staticmethod
    def _results(request: Mapping[str, Any], now: datetime) -> list[dict[str, Any]]:
        page, kind = request["page"], request["domain_type"]
        include = request["include"] or (list(_ACADEMIC) if kind == "research_paper" else [])
        hits = content.search_hits(
            request["query"],
            _PAGE_SIZE * (page + 1),
            include_domains=include,
            exclude_domains=request["exclude"],
        )[page * _PAGE_SIZE :]
        results: list[dict[str, Any]] = []
        for index, hit in enumerate(hits):
            site = hit.domain.removeprefix("www.")
            item: dict[str, Any] = {
                "position": page * _PAGE_SIZE + index + 1,
                "site_name": site,
                "title": hit.title,
                "snippet": hit.snippet,
                "url": hit.url,
            }
            published = hit.published.astimezone(UTC)
            if kind == "news":
                news_date = format_datetime(published, usegmt=True)
                item.update({"date": news_date, "publisher": site.split(".")[0].title()})
            elif kind == "research_paper":
                rng = content.rng("tinyfish-paper", hit.url)
                item.update(
                    {
                        "authors": rng.sample(_AUTHORS, k=1 + rng.randrange(3)),
                        "venue": rng.choice(_VENUES),
                        "year": hit.published.year,
                        "cited_by_count": rng.randrange(0, 900),
                    }
                )
                # Recorded: every research result had a ``pdf_url``.
                item["pdf_url"] = (
                    hit.url.replace("arxiv.org/", "arxiv.org/pdf/", 1)
                    if site == "arxiv.org"
                    else f"{hit.url.rstrip('/')}.pdf"
                )
            elif request["dated"] or index % 3 == 0:
                item["date"] = _web_date(published, now, index)
            results.append(dict(sorted(item.items())))
        return results

    # ---------------------------------------------------------------- fetch

    async def _fetch(self, context: OperationContext) -> MockResponse:
        # Recorded order: schema 400 and highlights 403 spend no slot; the
        # selector 422 comes after the URLs are counted.
        app = self._app_headers(context)
        try:
            request = _fetch_request(context.raw_body)
        except _Rejected as rejected:
            return self._rejected(rejected.response, app)
        account = self._account(context)
        if (
            request["highlights"] is not None
            and account.attributes.get("highlights_beta") is not True
        ):
            forbidden = self.error(ErrorKind.FORBIDDEN, ErrorContext(operation="fetch"))
            return self._rejected(forbidden, app)
        gate = self._gate(context, "fetch", len(request["urls"]))
        if isinstance(gate, MockResponse):
            return gate
        headers, daily = gate
        invalid = _selector_error(request)
        if invalid is not None:
            return self._rejected(invalid, headers)
        results: list[dict[str, Any]] = []
        errors: list[dict[str, Any]] = []
        for url in request["urls"]:
            context.match_key = content.normalize_url(url)
            item = self._fetched(context, url, request)
            (errors if "error" in item and "text" not in item else results).append(item)
        if results:
            context.charge("fetch", units=len(results))
            context.store.count_window(daily, len(results))
        body = {"results": results, "errors": errors}
        return self._ok(body, headers, echo_request_id=bool(errors))

    def _fetched(
        self, context: OperationContext, url: str, request: Mapping[str, Any]
    ) -> dict[str, Any]:
        """Return one result, or one ``errors[]`` entry, for a URL."""

        fixture = context.fixture(content.normalize_url(url))
        if fixture is not None and isinstance(fixture.body, dict):
            saved = fixture.body
            if isinstance(saved.get("results"), list) or isinstance(saved.get("errors"), list):
                found = [*saved.get("results", []), *saved.get("errors", [])]
                match = next(
                    (item for item in found if isinstance(item, dict) and item.get("url") == url),
                    None,
                )
                if match is not None:
                    return dict(match)
            else:
                return {**saved, "url": url}
        failure = _failure(url, request)
        if failure is not None:
            return failure
        include = request["include_selectors"]
        unmatched = [selector for selector in include if not _matches(selector)]
        if include and len(unmatched) == len(include):
            return {
                "url": url,
                "error": "selector_not_matched",
                "unmatched_selectors": unmatched,
                "candidate_selectors": ["main", "article", "#content"],
            }
        item = self._document(url, request)
        if unmatched:
            item["unmatched_selectors"] = unmatched
        return item

    @staticmethod
    def _document(url: str, request: Mapping[str, Any]) -> dict[str, Any]:
        page = content.page(url)
        fmt = request["format"]
        text: Any = (
            page.markdown if fmt == "markdown" else _html(page) if fmt == "html" else _tree(page)
        )
        host = (urlsplit(url).hostname or "").lower()
        reserved = page.images == ()
        rng = content.rng("tinyfish-fetch", content.normalize_url(url))
        # Field order as recorded: the option fields sit between the page
        # fields and ``latency_ms``; ``unmatched_selectors`` comes last.
        item: dict[str, Any] = {
            "url": url,
            "final_url": _final_url(url),
            "title": page.title,
            "description": None if reserved else page.text.split("\n")[2][:160],
            "language": "en",
            "text": text,
            "author": None,
            "published_date": None if reserved else page.published.date().isoformat(),
        }
        if request.get("links") is True:
            item["links"] = [] if reserved else [f"https://{host}/about", f"https://{host}/contact"]
        if request.get("image_links") is True:
            item["image_links"] = list(page.images)
        if request.get("iframe_links") is True:
            item["iframe_links"] = []
        # The recorded reserved page (example.com) sent no validators.
        if request.get("include_etag_and_last_modified") is True and not reserved:
            item["etag"] = f'"{content.hex_id(16, url)}"'
            item["last_modified"] = format_datetime(page.published, usegmt=True)
        item["latency_ms"] = round(30 + rng.random() * 2400, 6)
        item["format"] = fmt
        highlights = request["highlights"]
        if highlights is not None:
            paragraphs = [
                block for block in page.markdown.split("\n\n") if not block.startswith(("#", "-"))
            ]
            count = int(highlights.get("max_snippets") or 5)
            item["highlights"] = [
                {"text": text, "rank": rank} for rank, text in enumerate(paragraphs[:count], 1)
            ]
            if highlights.get("include_full_page_text") is not True:
                item["text"] = None
        return item

    # ---------------------------------------------------------------- usage

    async def _usage(self, context: OperationContext) -> MockResponse:
        params = context.request.query_params
        try:
            limit = _int_param(params, "limit", 1, 1000) or 100
            page = _int_param(params, "page", 1, 1_000_000) or 1
            status = params.get("status")
            if status is not None and status not in ("completed", "failed"):
                raise _input_error(
                    _issue(
                        ["status"],
                        "invalid_value",
                        'Invalid option: expected one of "completed"|"failed"',
                        values=["completed", "failed"],
                    )
                )
        except _Rejected as rejected:
            return self._rejected(rejected.response, self._app_headers(context))
        account = self._account(context)
        labels = {
            key.label for key in context.store.keys(self.name) if key.account_id == account.id
        }
        search = _request_host(context.request) == _SEARCH_HOST
        entries = [
            entry
            for entry in reversed(context.store.log_tail(self.name, limit=10_000, with_bodies=True))
            if entry.operation == ("search" if search else "fetch")
            and entry.key_label in labels
            and entry.status is not None
        ]
        items = [
            item
            for entry in entries
            for item in (self._search_items(entry) if search else self._fetch_items(entry))
        ]
        if status is not None:
            items = [item for item in items if item["_status"] == status]
        total = len(items)
        chunk = [
            {k: v for k, v in item.items() if k != "_status"}
            for item in items[(page - 1) * limit : page * limit]
        ]
        body = {
            "items": chunk,
            "total": total,
            "limit": limit,
            "page": page,
            "total_pages": max(1, -(-total // limit)),
            "has_more": page * limit < total,
        }
        return self._ok(body, self._app_headers(context))

    @staticmethod
    def _parsed(entry: LogEntry) -> Any:
        try:
            return json.loads(entry.response_body or "null")
        except json.JSONDecodeError:
            return None

    def _search_items(self, entry: LogEntry) -> list[dict[str, Any]]:
        body = self._parsed(entry)
        results = body.get("results") if isinstance(body, dict) else None
        ok = entry.status == 200 and isinstance(results, list)
        # Recorded: a failed search has no count or size and an empty list;
        # ``cached`` was null on every recorded item.
        return [
            {
                "id": content.stable_uuid("tinyfish", "search", entry.id),
                "request_id": content.stable_uuid("tinyfish", "log", entry.id),
                "query": str(entry.request_summary.get("query", {}).get("query", "")),
                "status_code": entry.status,
                "result_count": len(results) if ok and results is not None else None,
                "results": results if ok and results is not None else [],
                "cached": None,
                "response_size_bytes": len((entry.response_body or "").encode()) if ok else None,
                "created_at": _usage_time(entry.ts),
                "_status": "completed" if ok else "failed",
            }
        ]

    def _fetch_items(self, entry: LogEntry) -> list[dict[str, Any]]:
        body = self._parsed(entry)
        if not isinstance(body, dict):
            return []
        created = _usage_time(entry.ts)
        items: list[dict[str, Any]] = []
        for index, item in enumerate([*body.get("results", []), *body.get("errors", [])]):
            if not isinstance(item, dict):
                continue
            failed = "error" in item and "text" not in item
            text = item.get("text")
            items.append(
                {
                    "id": content.stable_uuid("tinyfish", "fetch", entry.id, index),
                    "url": item.get("url"),
                    "final_url": item.get("final_url") or item.get("url"),
                    "title": item.get("title"),
                    "description": item.get("description"),
                    "language": item.get("language"),
                    "author": item.get("author"),
                    "published_date": item.get("published_date"),
                    "format": item.get("format") or "markdown",
                    "status": "failed" if failed else "completed",
                    "request_origin": "api",
                    "request_id": content.stable_uuid("tinyfish", "log", entry.id),
                    "text_length": len(text) if isinstance(text, str) else None,
                    "links_count": len(item.get("links") or []),
                    "image_links_count": len(item.get("image_links") or []),
                    "latency_ms": item.get("latency_ms"),
                    "created_at": created,
                    "error": item.get("error") if failed else None,
                    "_status": "failed" if failed else "completed",
                }
            )
        return items


PLUGIN = TinyfishPlugin()
