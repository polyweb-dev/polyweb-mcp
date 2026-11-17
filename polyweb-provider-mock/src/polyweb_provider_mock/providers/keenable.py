"""Keenable on ``api.keenable.ai``: keyed and keyless search and fetch.

Four routes, as Polyweb calls them (research of 2026-11-17, eight keyless
recordings in ``tests/contract/recordings/keenable``, keyed paths from the
public docs):

- ``POST /v1/search`` and ``GET /v1/fetch`` need ``X-API-Key: keen_...``
  (``Authorization: Bearer`` also works; ``X-API-Key`` wins).
- ``POST /v1/search/public`` and ``GET /v1/fetch/public`` are the keyless
  rail. They need ``X-Keenable-Title`` (or ``?keenable_title=``); without it
  the answer is 400 ``missing_app_title`` and no rate slot is spent.

Every error is Keenable's flat envelope (``error``, ``message``, ``type``,
``code``, ``fix``, ``docs_url``, ``retryable``, ``request_id`` = the
``X-Request-Id`` header). A missing key is 401 ``missing_api_key``, an
unknown key 401 ``invalid_api_key`` (``Malformed API key`` without the
``keen_`` prefix), a revoked key 403 ``credentials_forbidden``, exhausted
credits 402 ``insufficient_credits``. Retryable errors carry
``retry_after_seconds`` and ``Retry-After``: 500 ``internal_error`` (2 s),
fetch 502 ``target_unreachable`` (2 s), 503 ``auth_unavailable`` (5 s), fetch
504 ``target_timeout`` (5 s), and search 529 ``search_overloaded`` (1 s). An
``http_error`` fault with status 529 renders that last one; current Polyweb
does not retry 529 although Keenable marks it retryable.

Rate limits:

- Keyless: 1000 requests per hour and 10 per second *per endpoint* (the
  recordings show independent search and fetch counters with different
  reset instants). The hourly window starts at the first request after the
  previous one ended. Success and post-title 400 responses carry
  ``X-RateLimit-Limit/Remaining`` and an ISO-8601 ``X-RateLimit-Reset``.
  Over the limit: 429 ``public_rate_limit_hourly`` /
  ``public_rate_limit_per_second`` with a ``limit`` object (scope ``ip``).
  The core keyless ``per_day`` / ``per_minute`` budget (CLI ``keyless set``)
  applies on top, shared by both endpoints.
- Keyed: 10 requests per second per organization (account), shared by all
  its keys, 429 ``rate_limit_per_second``. The keyed success responses carry
  the same three headers for that window; no keyed capture confirms them.

Credits: every successful keyed call costs 1 credit (``search.pro``,
``search.realtime``, ``fetch``, ``fetch.live``, USD 0.004) and reports a
``usage`` object; failed calls are free. The seeded organization has the
100,000-request monthly free allowance as its credit limit; ``credits add``
models purchased credits, and ``usage.paid`` turns true once the free
allowance is spent. Keyless calls are free and have no ``usage``.

Accuracy gaps: the allowance resets on the UTC calendar month unless the
account's ``reset_day`` attribute anchors it to the organization's creation
day (``polyweb-mock account set keenable reset_day=17``); consumed purchased
credits come back at the monthly reset (real purchased credits never expire
but are not refunded); ``billing_url`` is inferred from the docs' "Billing
page of the console".

Synthetic fetch targets (first host label): ``blocked`` 403
``target_blocked``, ``paywall``/``login`` 422 ``target_paywalled``,
``empty`` 422 ``content_not_extracted``, ``missing`` (or a ``/404`` path) 404
``page_not_found``, ``slow`` 504 ``target_timeout``, a ``.invalid`` host 502
``target_unreachable``, and private or loopback hosts 403
``private_url_not_allowed``.
"""

import base64
import hashlib
import ipaddress
import json
import secrets
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, ClassVar, Final
from urllib.parse import urlsplit

from starlette.requests import Request

from polyweb_provider_mock import content
from polyweb_provider_mock.models import (
    AccountSeed,
    KeyFormat,
    KeylessSeed,
    KeySeed,
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
    bearer_token,
    header_value,
)
from polyweb_provider_mock.store import Charge, MockStore
from polyweb_provider_mock.windows import Window, WindowSpec

__all__ = ["PLUGIN", "KeenablePlugin"]

_JSON: Final = "application/json; charset=utf-8"
_KEY_PREFIX: Final = "keen_"
_DOCS: Final = "https://docs.keenable.ai/errors#"
_API_KEYS_URL: Final = "https://app.keenable.ai/console/api-keys"
_BILLING_URL: Final = "https://app.keenable.ai/console/billing"
_AUTO_TOP_UP_URL: Final = "https://docs.keenable.ai/auto-top-up.md"
_KEYLESS_HINT: Final = (
    "/v1/search/public and /v1/fetch/public work without a key, rate-limited per IP. Name your "
    "app in the X-Keenable-Title header (or the keenable_title query parameter); public requests "
    "without it get a 400."
)
_EXPOSED: Final = (
    "Content-Type,Authorization,X-Request-Id,Server-Timing,PAYMENT-REQUIRED,PAYMENT-RESPONSE,"
    "Retry-After,X-RateLimit-Limit,X-RateLimit-Remaining,X-RateLimit-Reset"
)
_PUBLIC_HOURLY: Final = 1000
_PUBLIC_PER_SECOND: Final = 10
_KEYED_PER_SECOND: Final = 10
_FREE_ALLOWANCE: Final = Decimal(100_000)
_DEFAULT_RESULTS: Final = 10
_DEFAULT_MAX_CHARS: Final = 50_000
_SEARCH_PARAMS: Final = frozenset(
    {
        "query",
        "mode",
        "max_results",
        "site",
        "exclude_domains",
        "published_after",
        "published_before",
        "acquired_after",
        "acquired_before",
        "query_time",
        "snippet_max_length",
        "disable_cards",
        "safety_mode",
        "session_id",
    }
)
_DATE_PARAMS: Final = (
    "published_after",
    "published_before",
    "acquired_after",
    "acquired_before",
    "query_time",
)
_FETCH_PARAMS: Final = frozenset({"url", "max_chars", "live", "prompt", "session_id"})


@dataclass(frozen=True)
class _Code:
    status: int
    error: str
    type: str
    fix: str
    retry_after: int | None = None


_CODES: Final[dict[str, _Code]] = {
    "missing_app_title": _Code(
        400,
        "Missing app identifier",
        "invalid_request_error",
        "Name your app in the X-Keenable-Title header (or the keenable_title query parameter) "
        "and retry. With an API key, call /v1/search or /v1/fetch instead, which do not need it.",
    ),
    "missing_parameter": _Code(
        400,
        "Missing required parameter",
        "invalid_request_error",
        'Send the parameter named in "param"; it is required. Then retry.',
    ),
    "invalid_parameter": _Code(
        400,
        "Invalid parameter",
        "invalid_request_error",
        'Correct the parameter named in "param" and retry; the API reference lists the values '
        "it accepts.",
    ),
    "unknown_parameter": _Code(
        400,
        "Bad request",
        "invalid_request_error",
        'Remove the unknown parameter, or rename it to one of the parameters listed in "allowed", '
        "and retry.",
    ),
    "invalid_json": _Code(
        400,
        "Invalid JSON",
        "invalid_request_error",
        "The request body could not be parsed as JSON. Send a valid JSON object with "
        "Content-Type: application/json (check quoting and trailing commas), or send the "
        "parameters in the query string, and retry.",
    ),
    "invalid_request": _Code(
        400,
        "Invalid request",
        "invalid_request_error",
        'Read "message" for what to change, and "details", when present, for each field that '
        "failed; correct the request and retry.",
    ),
    "not_found": _Code(
        404,
        "Not found",
        "invalid_request_error",
        'Nothing was found for this request: read "message", correct it and retry.',
    ),
    "missing_api_key": _Code(
        401,
        "Missing authentication",
        "authentication_error",
        'Send your Keenable API key in the X-API-Key header (or as "Authorization: Bearer <key>") '
        "and retry. Create a key at https://app.keenable.ai/console/api-keys.",
    ),
    "invalid_api_key": _Code(
        401,
        "Authentication failed",
        "authentication_error",
        "The API key was not accepted. Copy the full key from "
        "https://app.keenable.ai/console/api-keys, or create a new one there, and retry with it "
        "in the X-API-Key header.",
    ),
    "credentials_forbidden": _Code(
        403,
        "Forbidden",
        "permission_error",
        "The credentials were recognized but are not allowed, usually because the key was "
        "revoked. Retrying with them will not help: create a new key at "
        "https://app.keenable.ai/console/api-keys, or ask a human with console access to create "
        "one for you.",
    ),
    "forbidden": _Code(
        403,
        "Forbidden",
        "permission_error",
        'This request is not allowed: read "message" for the reason. Retrying the same request '
        "returns the same 403.",
    ),
    "insufficient_credits": _Code(
        402,
        "Insufficient credits",
        "billing_error",
        "Retrying returns the same 402 until credits are added. Ask a human with console access "
        "to buy credits at the URL in this response's billing_url field (the Billing page of the "
        "Keenable console), and to turn on auto top-up there so the balance refills itself "
        "(https://docs.keenable.ai/auto-top-up.md).",
    ),
    "public_rate_limit_hourly": _Code(
        429,
        "Rate limit exceeded",
        "rate_limit_error",
        "Wait for Retry-After (up to an hour) before retrying; a retry sooner returns 429 again. "
        "To continue now instead, create a free API key at "
        "https://app.keenable.ai/console/api-keys and call /v1/search or /v1/fetch with it in the "
        "X-API-Key header: keyed requests have no hourly cap.",
        1,
    ),
    "public_rate_limit_per_second": _Code(
        429,
        "Rate limit exceeded",
        "rate_limit_error",
        "Wait for Retry-After and retry, or send an API key (free at "
        "https://app.keenable.ai/console/api-keys) to /v1/search or /v1/fetch for your "
        "organization's own limit.",
        1,
    ),
    "rate_limit_per_second": _Code(
        429,
        "Rate limit exceeded",
        "rate_limit_error",
        "Your organization is limited to 10 requests per second, shared by all its keys. Wait "
        "for Retry-After, retry, and keep under 10 per second.",
        1,
    ),
    "internal_error": _Code(
        500,
        "Internal server error",
        "api_error",
        "Something failed on our side; the request itself may be fine. Wait a few seconds and "
        "retry up to 3 times, then report it with the request_id.",
        2,
    ),
    "auth_unavailable": _Code(
        503,
        "Authentication temporarily unavailable",
        "api_error",
        "Keenable could not check your credentials just now; the key itself may be fine. Wait "
        "for Retry-After and retry the same request.",
        5,
    ),
    "search_overloaded": _Code(
        529,
        "Overloaded",
        "api_error",
        "Search is briefly overloaded. Wait for Retry-After and retry, backing off if it repeats.",
        1,
    ),
    "target_unreachable": _Code(
        502,
        "Bad gateway",
        "target_error",
        "The fetcher could not reach the page: a connection, DNS or TLS failure, or a server "
        "error on the site. This is often transient: wait a few seconds and retry up to 3 times, "
        "then try another URL.",
        2,
    ),
    "target_timeout": _Code(
        504,
        "Gateway timeout",
        "target_error",
        "The page took too long to respond. Retrying can help: wait a few seconds and retry up "
        "to 3 times, then try another URL.",
        5,
    ),
    "target_blocked": _Code(
        403,
        "Upstream forbidden",
        "target_error",
        "The site refused the fetcher, for example with a bot check or an access rule. This is "
        "not about your API key, and retrying the same URL will not help: fetch another source "
        "for the same content.",
    ),
    "private_url_not_allowed": _Code(
        403,
        "Forbidden",
        "permission_error",
        "The fetcher only reaches public http and https pages. Use a public URL; retrying this "
        "one returns the same 403.",
    ),
    "page_not_found": _Code(
        404,
        "Not found",
        "target_error",
        "The site says the page does not exist. Retrying the same URL returns the same 404: "
        "check the URL, or use another search result.",
    ),
    "content_not_extracted": _Code(
        422,
        "Unprocessable entity",
        "target_error",
        "The page was reached but has no readable text to extract. Retrying will not help: "
        "fetch another source.",
    ),
    "target_paywalled": _Code(
        422,
        "Unprocessable entity",
        "target_error",
        "The page needs a login or a subscription, so there is no content to return. Retrying "
        "will not help: fetch another source.",
    ),
}


class _Rejected(Exception):
    """A request that fails validation; carries the provider response."""

    def __init__(self, response: MockResponse) -> None:
        super().__init__(response.status)
        self.response = response


def _uuid7(now: datetime | None = None) -> str:
    """Return a UUIDv7 string, as Keenable's ``X-Request-Id`` values are."""

    millis = int((now or datetime.now(UTC)).timestamp() * 1000) & ((1 << 48) - 1)
    rand = secrets.randbits(74)
    value = (millis << 80) | (0x7 << 76) | ((rand >> 62) << 64) | (0b10 << 62)
    return str(uuid.UUID(int=value | (rand & ((1 << 62) - 1))))


def _iso_ms(moment: datetime) -> str:
    return moment.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _iso_s(moment: datetime) -> str:
    return moment.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _number(value: Decimal) -> int | float:
    return int(value) if value == value.to_integral_value() else float(value)


def _json(status: int, body: Any, headers: Mapping[str, str] | None = None) -> MockResponse:
    """Return a JSON response with Keenable's content type and a weak ETag."""

    response = MockResponse(status=status, body=body, headers=dict(headers or {}), media_type=_JSON)
    data = response.content()
    digest = base64.b64encode(hashlib.sha1(data, usedforsecurity=False).digest()).decode()
    response.headers.setdefault("etag", f'W/"{len(data):x}-{digest[:27]}"')
    return response


def _envelope(
    code: str,
    message: str | None = None,
    *,
    status: int | None = None,
    fix: str | None = None,
    retry_after: int | None = None,
    retry_after_header: bool = True,
    headers: Mapping[str, str] | None = None,
    extra: Mapping[str, Any] | None = None,
) -> MockResponse:
    """Return Keenable's flat error envelope for ``code``."""

    spec = _CODES[code]
    request_id = _uuid7()
    body: dict[str, Any] = {"error": spec.error}
    if message is not None:
        body["message"] = message
    body.update({"type": spec.type, "code": code, "fix": fix or spec.fix})
    body.update(extra or {})
    body["docs_url"] = _DOCS + code.replace("_", "-")
    delay = retry_after if retry_after is not None else spec.retry_after
    body["retryable"] = delay is not None
    out = {**(headers or {}), "x-request-id": request_id}
    if delay is not None:
        body["retry_after_seconds"] = delay
        if retry_after_header:
            out["Retry-After"] = str(delay)
    body["request_id"] = request_id
    return _json(status or spec.status, body, out)


def _missing(param: str) -> _Rejected:
    return _Rejected(
        _envelope(
            "missing_parameter",
            f'"{param}" is required',
            fix=f'Send the "{param}" parameter; it is required. Then retry.',
            extra={"param": param},
        )
    )


def _invalid(param: str, rule: str, message: str | None = None) -> _Rejected:
    return _Rejected(
        _envelope(
            "invalid_parameter",
            message or f'"{param}": {rule}',
            fix=f'Correct the "{param}" parameter ({rule}) and retry.',
            extra={"param": param},
        )
    )


def _reject_unknown(names: Sequence[str], allowed: frozenset[str]) -> None:
    unknown = sorted({name for name in names if name not in allowed})
    if unknown:
        raise _Rejected(
            _envelope(
                "unknown_parameter",
                f"Unknown parameter(s): {', '.join(unknown)}",
                extra={"param": unknown[0], "allowed": sorted(allowed)},
            )
        )


def _int_in(value: Any, low: int, high: int) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and low <= value <= high


def _title(request: Request) -> str | None:
    return (
        header_value(request, "x-keenable-title")
        or (request.query_params.get("keenable_title") or "").strip()[:256]
        or None
    )


def _with_headers(response: MockResponse, headers: Mapping[str, str]) -> MockResponse:
    response.headers = {**headers, **response.headers}
    return response


def _search_request(raw: bytes) -> dict[str, Any]:
    """Validate a search body in Keenable's order; raise :class:`_Rejected`."""

    try:
        body = json.loads(raw or b"null")
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise _Rejected(_envelope("invalid_json", "The request body is not valid JSON")) from None
    if not isinstance(body, dict):
        raise _Rejected(_envelope("invalid_request", "The request body must be a JSON object"))
    _reject_unknown(list(body), _SEARCH_PARAMS)
    query = body.get("query")
    if query is None or query == "":
        raise _missing("query")
    if not isinstance(query, str):
        raise _invalid("query", "must be a string")
    mode = body.get("mode") if body.get("mode") is not None else "pro"
    if mode not in ("pro", "realtime"):
        raise _invalid("mode", 'is not a supported search mode; use "pro" or "realtime"')
    count = body.get("max_results", _DEFAULT_RESULTS)
    if not _int_in(count, 1, 50):
        raise _invalid("max_results", "must be an integer between 1 and 50")
    snippet = body.get("snippet_max_length")
    if snippet is not None and not _int_in(snippet, 180, 10_000):
        raise _invalid("snippet_max_length", "must be an integer between 180 and 10000")
    site = body.get("site")
    if site is not None and (not isinstance(site, str) or not site.strip()):
        raise _invalid("site", "must be a non-empty string")
    for name in _DATE_PARAMS:
        value = body.get(name)
        if value is not None and (
            not isinstance(value, str) or not value or value.split() != [value]
        ):
            raise _invalid(
                name,
                "must be a date, a timestamp or a relative delta such as 7d",
                f'Invalid {name} value "{value}": value must not contain whitespace',
            )
    exclude = body.get("exclude_domains") or []
    if not isinstance(exclude, list) or not all(isinstance(item, str) for item in exclude):
        raise _invalid("exclude_domains", "must be an array of host names")
    return {
        "query": query,
        "mode": mode,
        "count": count,
        "snippet": snippet,
        "site": site,
        "exclude": exclude,
    }


def _fetch_request(request: Request) -> tuple[str, int, bool, str | None]:
    """Validate fetch query parameters; return url, max_chars, live, prompt."""

    params = request.query_params
    _reject_unknown([name for name in params if name != "keenable_title"], _FETCH_PARAMS)
    url = (params.get("url") or "").strip()
    if not url:
        raise _missing("url")
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise _invalid("url", "must be an absolute http or https URL")
    raw_chars = params.get("max_chars")
    if raw_chars is not None and (not raw_chars.isdigit() or int(raw_chars) < 1):
        raise _invalid("max_chars", "must be a positive integer")
    live = params.get("live")
    if live is not None and live not in ("true", "false"):
        raise _invalid("live", "must be true or false")
    prompt = params.get("prompt")
    if prompt is not None and len(prompt) > 2000:
        raise _invalid("prompt", "must be 2000 characters or less")
    max_chars = int(raw_chars) if raw_chars is not None else _DEFAULT_MAX_CHARS
    return url, max_chars, live == "true", prompt


def _private(host: str) -> bool:
    if host in {"localhost", "metadata.google.internal"} or host.endswith((".local", ".internal")):
        return True
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    return address.is_private or address.is_loopback or address.is_link_local


def _target_error(url: str) -> MockResponse | None:
    """Return the synthetic target failure of a fetch URL, if its host asks for one."""

    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    first = host.split(".")[0]
    if _private(host):
        return _envelope(
            "private_url_not_allowed", "The URL points to a private or non-routable address."
        )
    failures = {
        "blocked": ("target_blocked", "The site refused the fetcher."),
        "paywall": ("target_paywalled", "The page needs a login or a subscription."),
        "login": ("target_paywalled", "The page needs a login or a subscription."),
        "empty": ("content_not_extracted", "The page has no readable text to extract."),
        "missing": ("page_not_found", "The page does not exist at this URL."),
        "slow": ("target_timeout", "The page took too long to respond."),
    }
    if host.endswith(".invalid"):
        return _envelope("target_unreachable", "The fetcher could not reach the page.")
    if first in failures:
        return _envelope(*failures[first])
    if "/404" in parts.path:
        return _envelope("page_not_found", "The page does not exist at this URL.")
    return None


def _final_url(url: str) -> str:
    parts = urlsplit(url)
    return parts._replace(path=parts.path or "/").geturl()


def _cap(text: str, max_chars: int) -> tuple[str, bool]:
    if len(text) <= max_chars:
        return text, False
    if max_chars <= 3:
        return text[:max_chars], True
    return text[: max_chars - 3] + "...", True


class KeenablePlugin(ProviderPlugin):
    """Keenable search and fetch, keyed and keyless."""

    name: ClassVar[str] = "keenable"
    hosts: ClassVar[frozenset[str]] = frozenset({"api.keenable.ai"})
    key_format: ClassVar[KeyFormat] = KeyFormat(prefix=_KEY_PREFIX, body_length=32)

    def operations(self) -> Sequence[Operation]:
        return (
            Operation("search", "POST", "/v1/search", self._search),
            Operation(
                "search", "POST", "/v1/search/public", self._search, billable=False, keyless=True
            ),
            Operation("fetch", "GET", "/v1/fetch", self._fetch),
            Operation(
                "fetch", "GET", "/v1/fetch/public", self._fetch, billable=False, keyless=True
            ),
        )

    def credentials(self, request: Request, store: MockStore) -> Credentials:
        if request.url.path.rstrip("/").endswith("/public"):
            return Credentials(key=None, keyless=True)
        return Credentials(key=header_value(request, "x-api-key") or bearer_token(request))

    def default_seed(self) -> ProviderSeed:
        return ProviderSeed(
            accounts=(
                AccountSeed(
                    id="keenable-org",
                    plan="Free",
                    credit_limit=_FREE_ALLOWANCE,
                    reset_rule="monthly",
                    attributes={"free_allowance": int(_FREE_ALLOWANCE)},
                ),
            ),
            keys=(
                KeySeed(
                    label="default", account_id="keenable-org", env_var="POLYWEB_KEENABLE_API_KEY"
                ),
                KeySeed(label="secondary", account_id="keenable-org"),
            ),
            keyless=KeylessSeed(enabled=True),
        )

    def default_pricing(self) -> Sequence[PriceRule]:
        return tuple(
            PriceRule(
                provider=self.name,
                operation=sku,
                credits_per_unit=Decimal(1),
                usd_per_unit=Decimal("0.004"),
            )
            for sku in ("search.pro", "search.realtime", "fetch", "fetch.live")
        )

    def response_headers(self) -> dict[str, str]:
        return {
            "vary": "Origin, Accept-Encoding",
            "access-control-allow-credentials": "true",
            "access-control-expose-headers": _EXPOSED,
            "via": "1.1 google",
            "alt-svc": 'h3=":443"; ma=2592000,h3-29=":443"; ma=2592000',
        }

    def not_found(self, request: Request, status: int) -> MockResponse:
        message = "Method not allowed" if status == 405 else f"No route for {request.url.path}"
        return _envelope("not_found", message, status=status)

    def drop_required_field(self, operation: str, body: Any) -> Any:
        if operation == "fetch" and isinstance(body, dict):
            return {key: value for key, value in body.items() if key != "content"}
        return super().drop_required_field(operation, body)

    # --------------------------------------------------------------- errors

    def error(self, kind: ErrorKind, context: ErrorContext) -> MockResponse:
        keyed = not context.keyless
        hint = {"keyless": _KEYLESS_HINT} if keyed else {}
        if kind is ErrorKind.AUTH_INVALID and context.missing_key:
            return _envelope(
                "missing_api_key",
                context.message
                or "Either X-API-Key header or Authorization Bearer token is required",
                status=context.status,
                extra={**hint, "api_keys_url": _API_KEYS_URL},
            )
        if kind is ErrorKind.AUTH_INVALID:
            presented = context.presented_key
            malformed = presented is not None and not presented.startswith(_KEY_PREFIX)
            message = "Malformed API key" if malformed else "Invalid API key"
            return _envelope(
                "invalid_api_key",
                context.message or message,
                status=context.status,
                extra={**hint, "api_keys_url": _API_KEYS_URL},
            )
        if kind is ErrorKind.AUTH_REVOKED:
            return _envelope(
                "credentials_forbidden",
                context.message or "Key revoked",
                status=context.status,
                extra={**hint, "api_keys_url": _API_KEYS_URL},
            )
        if kind is ErrorKind.RATE_LIMITED:
            return self._rate_limited(context)
        if kind is ErrorKind.QUOTA_EXHAUSTED:
            return _envelope(
                "insufficient_credits",
                context.message
                or "This month's free requests and the purchased credits are used up.",
                status=context.status,
                extra={"billing_url": _BILLING_URL, "auto_top_up_url": _AUTO_TOP_UP_URL},
            )
        code = self._code(kind, context)
        return _envelope(code, context.message or _CODES[code].error, status=context.status)

    @staticmethod
    def _code(kind: ErrorKind, context: ErrorContext) -> str:
        status = context.status or 0
        fetch = context.operation == "fetch"
        if kind is ErrorKind.FORBIDDEN:
            return "forbidden"
        if kind is ErrorKind.BAD_REQUEST:
            if status == 404:
                return "page_not_found" if fetch else "not_found"
            return "content_not_extracted" if status == 422 else "invalid_request"
        if kind is ErrorKind.SERVICE_UNAVAILABLE or status == 503:
            return "auth_unavailable"
        if status == 529 and not fetch:
            return "search_overloaded"
        if fetch and status in (502, 504):
            return "target_unreachable" if status == 502 else "target_timeout"
        return "internal_error"

    def _rate_limited(
        self,
        context: ErrorContext,
        *,
        window: Window | None = None,
        now: datetime | None = None,
    ) -> MockResponse:
        """Render a 429 from a fault, the core keyless budget, or a refused window."""

        moment = now or datetime.now(UTC)
        scope = context.scope or ("hour" if context.keyless else "second")
        hourly = scope in ("hour", "day")
        if context.keyless:
            code = "public_rate_limit_hourly" if hourly else "public_rate_limit_per_second"
            maximum = _PUBLIC_HOURLY if hourly else _PUBLIC_PER_SECOND
            message = (
                f"Too many requests — the keyless limit of {maximum} requests per hour for this "
                "IP address was reached."
                if hourly
                else f"Too many requests — keyless requests are limited to {maximum} per second "
                "per IP address."
            )
        else:
            code, maximum = "rate_limit_per_second", _KEYED_PER_SECOND
            message = f"Too many requests — your organization has a {maximum} RPS limit."
        seconds = context.retry_after if context.retry_after is not None else 1
        resets = moment + timedelta(seconds=seconds)
        if window is not None:
            maximum, resets = window.spec.limit, window.reset
            seconds = window.retry_after(moment)
        limit = {
            "scope": "ip" if context.keyless else "organization",
            "window": "hour" if hourly else scope if scope == "minute" else "second",
            "max": maximum,
            "resets_at": _iso_ms(resets),
        }
        return _envelope(
            code,
            context.message or message,
            retry_after=seconds,
            retry_after_header=context.retry_after_header,
            headers={
                "x-ratelimit-limit": str(maximum),
                "x-ratelimit-remaining": "0",
                "x-ratelimit-reset": _iso_ms(resets),
            },
            extra={"retryAfter": seconds, "limit": limit},
        )

    # ---------------------------------------------------------- rate gates

    def _admit(self, context: OperationContext, endpoint: str) -> dict[str, str] | MockResponse:
        """Spend one rate slot; return the rate headers, or the 429 response."""

        principal = context.principal
        if principal.keyless:
            specs = [
                WindowSpec(f"keenable:public:{endpoint}:hour", _PUBLIC_HOURLY, 3600),
                WindowSpec(f"keenable:public:{endpoint}:second", _PUBLIC_PER_SECOND, 1),
            ]
        else:
            account = principal.account.id if principal.account is not None else "unknown"
            specs = [WindowSpec(f"keenable:org:{account}:second", _KEYED_PER_SECOND, 1)]
        refused, windows = context.admit(specs)
        if refused is not None:
            scope = "hour" if refused.spec.seconds >= 3600 else "second"
            return self._rate_limited(
                ErrorContext(operation=endpoint, keyless=principal.keyless, scope=scope),
                window=refused,
                now=context.store.now(),
            )
        shown = windows[0]
        return {
            "x-ratelimit-limit": str(shown.spec.limit),
            "x-ratelimit-remaining": str(shown.remaining),
            "x-ratelimit-reset": _iso_ms(shown.reset),
        }

    def _gate(self, context: OperationContext, endpoint: str) -> dict[str, str] | MockResponse:
        """Check the public title (free), then spend a rate slot."""

        if context.principal.keyless and _title(context.request) is None:
            return _envelope(
                "missing_app_title",
                "X-Keenable-Title header is required for token-less requests",
                extra={"param": "X-Keenable-Title"},
            )
        return self._admit(context, endpoint)

    # ------------------------------------------------------------- billing

    def _charge(self, context: OperationContext, sku: str) -> Charge:
        """Bill a keyed call; record a free ledger row for a keyless one."""

        if context.principal.keyless:
            return context.charge(f"public.{sku}")
        return context.charge(sku)

    def _usage(self, context: OperationContext, charge: Charge, sku: str) -> dict[str, Any]:
        principal = context.principal
        assert principal.account is not None
        account = context.store.account(self.name, principal.account.id)
        free = Decimal(str(account.attributes.get("free_allowance", _FREE_ALLOWANCE)))
        usage: dict[str, Any] = {
            "sku": sku,
            "amount": int(charge.units),
            "credits": _number(charge.credits),
            "paid": account.credits_used - charge.credits >= free,
        }
        if account.remaining is not None:
            usage["credits_remaining"] = _number(account.remaining)
        return usage

    def _success(
        self, context: OperationContext, body: dict[str, Any], sku: str, headers: dict[str, str]
    ) -> MockResponse:
        charge = self._charge(context, sku)
        body.pop("usage", None)
        if not context.principal.keyless:
            body["usage"] = self._usage(context, charge, sku)
        return _json(200, body, {**headers, "x-request-id": _uuid7(context.store.now())})

    # --------------------------------------------------------------- search

    async def _search(self, context: OperationContext) -> MockResponse:
        gate = self._gate(context, "search")
        if isinstance(gate, MockResponse):
            return gate
        try:
            request = _search_request(context.raw_body)
        except _Rejected as rejected:
            return _with_headers(rejected.response, gate)
        query, mode = request["query"], request["mode"]
        context.match_key = content.normalize_query(query)
        fixture = context.fixture(context.match_key)
        if fixture is not None and fixture.status != 200:
            return _json(fixture.status, fixture.body, gate)
        if fixture is not None and isinstance(fixture.body, dict):
            saved = {k: v for k, v in fixture.body.items() if k not in ("query", "mode")}
            body = {"query": query, "mode": mode, **saved}
        else:
            body = {"query": query, "mode": mode, "results": self._results(request)}
        return self._success(context, body, f"search.{mode}", gate)

    @staticmethod
    def _results(request: dict[str, Any]) -> list[dict[str, Any]]:
        site = request["site"]
        hits = content.search_hits(
            request["query"],
            request["count"],
            include_domains=[site.lower().removeprefix("www.")] if site else None,
            exclude_domains=list(request["exclude"]),
        )
        cap = request["snippet"]
        results: list[dict[str, Any]] = []
        for index, hit in enumerate(hits):
            page = content.page(hit.url, hit.title)
            snippet = page.markdown.split("\n\n", 1)[-1]
            acquired = hit.published + timedelta(days=3 + index, seconds=index * 3607)
            results.append(
                {
                    "title": hit.title,
                    "url": hit.url,
                    "description": "",
                    "snippet": snippet[:cap] if cap else snippet,
                    "acquired_at": _iso_s(acquired),
                }
            )
        return results

    # ---------------------------------------------------------------- fetch

    async def _fetch(self, context: OperationContext) -> MockResponse:
        gate = self._gate(context, "fetch")
        if isinstance(gate, MockResponse):
            return gate
        try:
            url, max_chars, live, prompt = _fetch_request(context.request)
        except _Rejected as rejected:
            return _with_headers(rejected.response, gate)
        context.match_key = content.normalize_url(url)
        fixture = context.fixture(context.match_key)
        if fixture is not None and fixture.status != 200:
            return _json(fixture.status, fixture.body, gate)
        sku = "fetch.live" if live else "fetch"
        if fixture is not None and isinstance(fixture.body, dict):
            return self._success(context, dict(fixture.body), sku, gate)
        failure = _target_error(url)
        if failure is not None:
            return _with_headers(failure, gate)
        page = content.page(url)
        text = page.markdown
        if live:
            text = f"{text}\n\n{content.answer(url + ' live')}"
        if prompt is not None:
            text = content.answer(f"{prompt} {url}")
        capped, truncated = _cap(text, max_chars)
        body = {
            "url": _final_url(url),
            "title": page.title,
            "content": capped,
            "description": "",
            "truncated": truncated,
            "total_chars": len(text),
        }
        return self._success(context, body, sku, gate)


PLUGIN = KeenablePlugin()
