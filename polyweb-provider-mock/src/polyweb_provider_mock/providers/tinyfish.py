"""Tinyfish Search on ``api.search.tinyfish.ai`` and Fetch on ``api.fetch.tinyfish.ai``.

Both products serve their main operation on the root path, so the plugin
claims both hosts and scopes each operation to its host (another host
answers 404 ``UNKNOWN_ROUTE``):

- ``GET /`` on the search host: query parameters ``query`` (required),
  ``page`` (0..10), domain filters, location/language, date and
  academic-year filters, ``domain_type`` (``web``, ``news``,
  ``research_paper``). Ten results per page.
- ``POST /`` on the fetch host: JSON ``{"urls": [...1..10], "format": ...}``
  plus link, cache, conditional, selector, and highlights options. Per-URL
  failures are entries in ``errors[]`` of an HTTP 200, as documented.
- ``GET /usage`` on either host: the documented usage history, built from
  this mock's request log. Polyweb does not call it.

The only recordings are the four 401 responses (missing and bogus key on both
hosts). Success shapes and every other error come from the public docs and
from what Polyweb's adapter parses; no authenticated capture confirms them.

Authentication is ``X-API-Key`` only. A missing key is 401
``MISSING_API_KEY``; an unknown or revoked key is 401 ``INVALID_API_KEY``
(the docs give revoked keys the same answer). Every error is
``{"error": {"code", "message", "details"?}, "request_id"}`` with the same
``X-Request-ID`` header.

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

Invalid requests are rejected before any rate slot is spent; the documented
60-per-minute limit on invalid requests and usage reads is not modelled.

Synthetic fetch targets (first host label): ``blocked`` ``bot_blocked``,
``login`` ``login_required``, ``empty`` ``empty_content``, ``timeout``
``timeout``, ``proxy`` ``proxy_error``, ``missing`` ``page_not_found`` 404,
``gone`` 410, ``status-503`` ``target_http_error`` 503 (any status), a
``.invalid`` host ``target_unreachable``, private or loopback hosts
``invalid_url``, a ``/404`` path ``page_not_found``. The JSON ``format``
document tree is a plausible shape; the docs do not define it.
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
    "missing": {"error": "page_not_found", "status": 404},
    "gone": {"error": "page_not_found", "status": 410},
}


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
    out = {
        **_cdn_headers(error=True),
        "cache-control": "no-store",
        **(headers or {}),
        "x-request-id": request_id,
    }
    if status == 401:
        out["www-authenticate"] = "ApiKey"
    return MockResponse(status=status, body={"error": error, "request_id": request_id}, headers=out)


def _issue(path: Sequence[str | int], code: str, message: str, **extra: Any) -> dict[str, Any]:
    return {**extra, "code": code, "path": list(path), "message": message}


def _input_error(*issues: dict[str, Any], status: int = 400) -> _Rejected:
    first = issues[0]
    field = ".".join(str(part) for part in first["path"])
    message = f'Field "{field}": {first["message"]}' if field else first["message"]
    return _Rejected(_error(status, "INVALID_INPUT", message, details=list(issues)))


def _custom(path: Sequence[str | int], message: str) -> _Rejected:
    return _input_error(_issue(path, "custom", message))


def _int_param(params: Mapping[str, str], name: str, low: int, high: int) -> int | None:
    """Parse an integer query parameter in ``low..high``; raise on a bad value."""

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
            )
        ) from None
    if value < low:
        raise _input_error(
            _issue([name], "too_small", f"Too small: expected number to be >={low}", minimum=low)
        )
    if value > high:
        raise _input_error(
            _issue([name], "too_big", f"Too big: expected number to be <={high}", maximum=high)
        )
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
        raise _custom([name], "Invalid date, expected YYYY-MM-DD") from None


def _domains(raw: str | None) -> list[str]:
    return [item.strip().lower() for item in (raw or "").split(",") if item.strip()]


def _search_request(params: Mapping[str, str]) -> dict[str, Any]:
    """Validate search query parameters as the Search reference documents."""

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
        raise _input_error(
            _issue(["query"], "too_small", "Too small: expected string to have >=1 characters")
        )
    page = _int_param(params, "page", 0, 10) or 0
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
    purpose = params.get("purpose")
    if purpose is not None and (not purpose.strip() or len(purpose) > 2000):
        raise _custom(["purpose"], "purpose must be 1 to 2000 non-blank characters")
    _search_filters(params, domain_type)
    return {
        "query": query,
        "page": page,
        "domain_type": domain_type,
        "include": _domains(params.get("include_domains")),
        "exclude": _domains(params.get("exclude_domains")),
    }


def _search_filters(params: Mapping[str, str], domain_type: str) -> None:
    """Check the date, recency, and academic-year rules."""

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
        raise _custom(["after_date"], "after_date must be less than or equal to before_date")
    if domain_type == "research_paper" and (dated or recency is not None):
        raise _custom(
            ["domain_type"],
            "after_date, before_date and recency_minutes are not supported for research_paper; "
            "use pub_year_min / pub_year_max",
        )
    if (year_min is not None or year_max is not None) and domain_type != "research_paper":
        raise _custom(
            ["pub_year_min"], "pub_year_min and pub_year_max require domain_type=research_paper"
        )
    if year_min is not None and year_max is not None and year_min > year_max:
        raise _custom(["pub_year_min"], "pub_year_min must be less than or equal to pub_year_max")


def _json_object(raw: bytes) -> dict[str, Any]:
    try:
        body = json.loads(raw or b"null")
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise _Rejected(_error(400, "INVALID_INPUT", "Invalid JSON body")) from None
    if not isinstance(body, dict):
        raise _input_error(
            _issue([], "invalid_type", "Invalid input: expected object", expected="object")
        )
    return body


def _fetch_urls(body: Mapping[str, Any]) -> list[str]:
    urls = body.get("urls")
    if not isinstance(urls, list):
        received = "undefined" if urls is None else type(urls).__name__
        raise _input_error(
            _issue(
                ["urls"],
                "invalid_type",
                f"Invalid input: expected array, received {received}",
                expected="array",
            )
        )
    if not urls:
        raise _input_error(
            _issue(["urls"], "too_small", "Too small: expected array to have >=1 items")
        )
    if len(urls) > 10:
        raise _input_error(
            _issue(["urls"], "too_big", "Too big: expected array to have <=10 items")
        )
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
        raise _input_error(
            _issue([name], "invalid_type", f"Invalid input: expected {expected}", expected=expected)
        )
    number = int(body[name]) if numeric else 0
    if numeric and low is not None and number < low:
        raise _input_error(_issue([name], "too_small", f"Too small: expected number to be >={low}"))
    if numeric and high is not None and number > high:
        raise _input_error(_issue([name], "too_big", f"Too big: expected number to be <={high}"))


def _selectors(body: Mapping[str, Any], name: str) -> list[str]:
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
    for selector in value:
        balanced = selector.count("[") == selector.count("]") and selector.count(
            "("
        ) == selector.count(")")
        if not balanced or "{" in selector or selector.strip()[0] in "0123456789>+~,":
            raise _input_error(
                _issue([name], "custom", f'Invalid CSS selector "{selector}"'), status=422
            )
    return list(value)


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
        raise _custom(["highlights"], 'highlights requires format "markdown"')
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
    if _private(host):
        return {"url": url, "error": "invalid_url"}
    if host.endswith(".invalid"):
        return {"url": url, "error": "target_unreachable"}
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
    sections: list[dict[str, Any]] = []
    for block in page.markdown.split("\n\n")[1:]:
        if block.startswith("## "):
            sections.append({"heading": block[3:], "paragraphs": []})
        elif sections:
            sections[-1]["paragraphs"].append(block)
        else:
            sections.append({"heading": None, "paragraphs": [block]})
    return {"title": page.title, "sections": sections}


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
        return _error(404, "UNKNOWN_ROUTE", f"Route {request.method} {request.url.path} not found")

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
                "Highlights are not enabled for this account. Contact support for access."
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
            return self._exhausted(product, scope, None, None)
        refused, windows = context.admit(specs, units)
        if refused is not None:
            return self._rate_limited(ErrorContext(operation=product), window=refused, now=now)
        minute = windows[0]
        headers = {
            **_cdn_headers(error=False),
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

    @staticmethod
    def _ok(body: Any, headers: Mapping[str, str]) -> MockResponse:
        return MockResponse(
            status=200, body=body, headers={**headers, "x-request-id": str(uuid.uuid4())}
        )

    # --------------------------------------------------------------- search

    async def _search(self, context: OperationContext) -> MockResponse:
        try:
            request = _search_request(context.request.query_params)
        except _Rejected as rejected:
            return rejected.response
        gate = self._gate(context, "search", 1)
        if isinstance(gate, MockResponse):
            return gate
        headers, daily = gate
        context.match_key = content.normalize_query(request["query"])
        fixture = context.fixture(context.match_key)
        if fixture is not None and fixture.status != 200:
            return MockResponse(status=fixture.status, body=fixture.body, headers=headers)
        context.charge("search")
        context.store.count_window(daily, 1)
        if fixture is not None and isinstance(fixture.body, dict):
            return self._ok(fixture.body, headers)
        results = self._results(request)
        body = {
            "query": request["query"],
            "results": results,
            "total_results": len(results),
            "page": request["page"],
        }
        return self._ok(body, headers)

    @staticmethod
    def _results(request: Mapping[str, Any]) -> list[dict[str, Any]]:
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
            stamp = hit.published.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
            if kind == "news":
                item.update({"date": stamp, "publisher": site.split(".")[0].title()})
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
                if site == "arxiv.org":
                    item["pdf_url"] = hit.url.replace("arxiv.org/", "arxiv.org/pdf/", 1)
            elif index % 3 == 0:
                item["date"] = stamp
            results.append(item)
        return results

    # ---------------------------------------------------------------- fetch

    async def _fetch(self, context: OperationContext) -> MockResponse:
        try:
            request = _fetch_request(context.raw_body)
        except _Rejected as rejected:
            return rejected.response
        account = self._account(context)
        if (
            request["highlights"] is not None
            and account.attributes.get("highlights_beta") is not True
        ):
            return self.error(ErrorKind.FORBIDDEN, ErrorContext(operation="fetch"))
        gate = self._gate(context, "fetch", len(request["urls"]))
        if isinstance(gate, MockResponse):
            return gate
        headers, daily = gate
        results: list[dict[str, Any]] = []
        errors: list[dict[str, Any]] = []
        for url in request["urls"]:
            context.match_key = content.normalize_url(url)
            item = self._fetched(context, url, request)
            (errors if "error" in item and "text" not in item else results).append(item)
        if results:
            context.charge("fetch", units=len(results))
            context.store.count_window(daily, len(results))
        return self._ok({"results": results, "errors": errors}, headers)

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
        item: dict[str, Any] = {
            "url": url,
            "final_url": _final_url(url),
            "title": page.title,
            "description": None if reserved else page.text.split("\n")[2][:160],
            "language": "en",
            "author": None,
            "published_date": None if reserved else page.published.date().isoformat(),
            "text": text,
            "latency_ms": 150 + rng.randrange(2400),
            "format": fmt,
        }
        if request.get("links") is True:
            item["links"] = [] if reserved else [f"https://{host}/about", f"https://{host}/contact"]
        if request.get("image_links") is True:
            item["image_links"] = list(page.images)
        if request.get("iframe_links") is True:
            item["iframe_links"] = []
        if request.get("include_etag_and_last_modified") is True:
            item["etag"] = f'"{content.hex_id(16, url)}"'
            item["last_modified"] = format_datetime(page.published, usegmt=True)
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
            return rejected.response
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
        return self._ok(body, _cdn_headers(error=False))

    @staticmethod
    def _parsed(entry: LogEntry) -> Any:
        try:
            return json.loads(entry.response_body or "null")
        except json.JSONDecodeError:
            return None

    def _search_items(self, entry: LogEntry) -> list[dict[str, Any]]:
        body = self._parsed(entry)
        results = body.get("results") if isinstance(body, dict) else None
        ok = entry.status == 200
        return [
            {
                "id": entry.id,
                "request_id": content.stable_uuid("tinyfish", "log", entry.id),
                "query": str(entry.request_summary.get("query", {}).get("query", "")),
                "status_code": entry.status,
                "result_count": len(results) if isinstance(results, list) else 0,
                "results": results if isinstance(results, list) else None,
                "cached": False,
                "response_size_bytes": len((entry.response_body or "").encode()) or None,
                "created_at": entry.ts.astimezone(UTC).isoformat().replace("+00:00", "Z"),
                "_status": "completed" if ok else "failed",
            }
        ]

    def _fetch_items(self, entry: LogEntry) -> list[dict[str, Any]]:
        body = self._parsed(entry)
        if not isinstance(body, dict):
            return []
        created = entry.ts.astimezone(UTC).isoformat().replace("+00:00", "Z")
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
