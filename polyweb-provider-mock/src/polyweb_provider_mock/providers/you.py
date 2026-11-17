"""You.com: Search and Contents on ``ydc-index.io``, the account balance on ``api.you.com``.

Formats follow the live recordings of 2026-11-17 (``tests/contract/recordings/you``)
and the official API reference:

- Authentication is the raw key in ``X-API-Key`` (no ``Bearer``). There is no
  keyless mode. The two hosts answer authentication failures differently:
  the ``ydc-index.io`` AWS API gateway sends 403 ``{"message": "Forbidden"}``
  for a wrong key and 402 ``payment_required`` for a missing key; the
  ``api.you.com`` balance API sends 401 ``{"detail": ...}`` for both. A path on
  the wrong host gets the gateway's 403 ``Missing Authentication Token``.
- The account is a shared USD wallet kept in **cents** (``balance`` is cents,
  fractional cents allowed). Search costs 0.5 cents ($5 per 1,000) and Contents
  0.1 cents per returned page ($1 per 1,000); full-page extraction with
  ``extraction_source`` ``fetch`` (every page) or ``blend`` (the pages that
  miss the cache) adds 0.1 cents per live page. The balance poll is free.
  The default wallet is the one-time $100 signup credit, which never resets.
- An empty wallet is 402 ``payment_required``. A key's own spend cap (the key
  credit limit) is 429 ``spend_cap_exceeded``; backoff does not clear it.
- Validation errors: Search answers 422 ``{"error": "invalid request
  parameter(s)"}``; Contents answers FastAPI 422 ``detail`` arrays.

Unverified (no live sample): revoked keys (rendered like a wrong key on each
host), the rate-limit and spend-cap 429 bodies, the authenticated
exhausted-wallet body (rendered as the recorded ``payment_required`` envelope),
and 5xx bodies (rendered as AWS API gateway and FastAPI defaults). Successes
carry no ``X-RateLimit-*`` headers, as in every recording; a 429 carries them.

Synthetic Contents targets: a host whose first label is ``blocked`` and a
``.invalid`` host are left out of the result array, as a failed page is.
"""

import json
import random
import time
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from email.utils import format_datetime
from html import escape
from http import HTTPStatus
from typing import Any, ClassVar, Final
from urllib.parse import urlsplit

from starlette.requests import Request

from polyweb_provider_mock import content
from polyweb_provider_mock.models import (
    AccountSeed,
    KeyFormat,
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
    header_value,
)

__all__ = ["PLUGIN", "YouPlugin"]

_GATEWAY_HOSTS: Final = frozenset({"ydc-index.io", "api.ydc-index.io"})
_API_HOSTS: Final = frozenset({"api.you.com"})
_GATEWAY_OPERATIONS: Final = frozenset({"search", "contents"})
_MISSING: Final[Any] = object()

_INVALID_PARAMS: Final = "invalid request parameter(s)"
_PAYMENT_REQUIRED: Final = {
    "error": "payment_required",
    "message": (
        "Your prepaid credit balance has been depleted. Please add credits to continue "
        "using the API."
    ),
    "upgrade_url": "https://you.com/platform",
}
_SPEND_CAP: Final = {
    "error": "spend_cap_exceeded",
    "message": (
        "This API key has reached its spending cap for the current billing period. Raise or "
        "remove the cap on the API Keys page."
    ),
    "upgrade_url": "https://you.com/platform/api-keys",
}
#: The per-endpoint default of self-serve accounts: 10 requests per second.
_RATE_LIMIT: Final = 10
#: ``balance`` for an account without a limit; You.com has no unlimited wallet.
_UNLIMITED_BALANCE_CENTS: Final = 100_000_000.0

_SAFESEARCH: Final = frozenset({"off", "moderate", "strict"})
_LIVECRAWL: Final = frozenset({"web", "news", "all"})
_PAGE_FORMATS: Final = frozenset({"markdown", "html"})
_CONTENT_FORMATS: Final = ("html", "markdown", "metadata")
_SOURCES: Final = frozenset({"blend", "cache", "fetch"})
_EXTRACTION_KEYS: Final = frozenset(
    {"extraction_mode", "extraction_source", "full_page", "highlights"}
)
_DEFAULT_COUNT: Final = 10
_MAX_HIGHLIGHT_RESULTS: Final = 50
_APIGW_ALPHABET: Final = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-"


# ---------------------------------------------------------------- headers


def _hex(generator: random.Random, size: int) -> str:
    return "".join(generator.choice("0123456789abcdef") for _ in range(size))


def _uuid(generator: random.Random) -> str:
    return str(uuid.UUID(int=generator.getrandbits(128), version=4))


def _gateway(
    response: MockResponse,
    generator: random.Random,
    *,
    backend: bool = True,
    errortype: str | None = None,
) -> MockResponse:
    """Add the AWS API gateway headers; ``backend`` adds the remapped uvicorn headers."""

    now = datetime.now(UTC)
    headers = {"x-amzn-requestid": _uuid(generator)}
    if backend:
        headers["x-amzn-remapped-content-length"] = str(len(response.content()))
    if errortype is not None:
        headers["x-amzn-errortype"] = errortype
    apigw = "".join(generator.choice(_APIGW_ALPHABET) for _ in range(15))
    headers["x-amz-apigw-id"] = f"{apigw}="
    if backend:
        headers["x-amzn-remapped-server"] = "uvicorn"
    headers["x-amzn-trace-id"] = f"Root=1-{int(now.timestamp()):08x}-{_hex(generator, 24)}"
    if backend:
        headers["x-amzn-remapped-date"] = format_datetime(now, usegmt=True)
    response.headers = {**headers, **response.headers}
    return response


def _edge(response: MockResponse, generator: random.Random) -> MockResponse:
    """Add the Cloudflare edge headers of ``api.you.com``."""

    now = datetime.now(UTC)
    response.headers = {
        "x-request-id": _uuid(generator),
        "x-correlation-id": _uuid(generator),
        "x-trace-id": f"{_uuid(generator)}|{now.isoformat()}",
        "cf-cache-status": "DYNAMIC",
        "cf-ray": f"{_hex(generator, 16)}-IAD",
        "alt-svc": 'h3=":443"; ma=86400',
        **response.headers,
    }
    return response


def _rate_headers(retry_after: int | None, *, header: bool) -> dict[str, str]:
    seconds = retry_after if retry_after is not None else 1
    headers = {
        "X-RateLimit-Limit": str(_RATE_LIMIT),
        "X-RateLimit-Remaining": "0",
        "X-RateLimit-Reset": str(int(time.time()) + max(1, seconds)),
    }
    if header:
        headers["Retry-After"] = str(seconds)
    return headers


def _phrase(status: int, default: str) -> str:
    try:
        return HTTPStatus(status).phrase
    except ValueError:
        return default


# ------------------------------------------------------------------ bodies


def _detail(kind: str, loc: Sequence[str | int], msg: str, value: Any, **ctx: Any) -> MockResponse:
    """Return the FastAPI 422 body that the Contents backend sends."""

    item: dict[str, Any] = {"type": kind, "loc": ["body", *loc], "msg": msg, "input": value}
    if ctx:
        item["ctx"] = ctx
    return MockResponse(status=422, body={"detail": [item]})


def _int_in(value: Any, low: int, high: int | None = None) -> bool:
    if isinstance(value, bool) or not isinstance(value, int):
        return False
    return value >= low and (high is None or value <= high)


def _strings(value: Any) -> bool:
    return isinstance(value, list) and all(isinstance(item, str) for item in value)


def _favicon(domain: str) -> str:
    return f"https://you.com/favicon?domain={domain}&size=128"


def _site_name(host: str) -> str:
    labels = host.removeprefix("www.").split(".")
    if labels[0] in {"example", "localhost"}:
        return ""
    return (labels[-2] if len(labels) > 1 else labels[0]).capitalize()


def _paragraphs(page: content.Page) -> list[str]:
    lines = [line for line in page.text.split("\n")[1:] if len(line) > 60]
    return lines or page.text.split("\n")[1:] or [page.title]


def _html(page: content.Page) -> str:
    parts = []
    for line in page.text.split("\n")[1:]:
        tag = "h2" if len(line) <= 40 else "p"
        parts.append(f"<{tag}>{escape(line)}</{tag}>")
    title = escape(page.title)
    return (
        f'<!DOCTYPE html><html lang="en"><head><title>{title}</title></head>'
        f"<body><h1>{title}</h1>{''.join(parts)}</body></html>"
    )


def _page_age(hit: content.SearchHit) -> str:
    seconds = content.rng("you-age", hit.url).randrange(86_400)
    return (hit.published + timedelta(seconds=seconds)).strftime("%Y-%m-%dT%H:%M:%S")


@dataclass(frozen=True)
class _Extraction:
    mode: str | None = None
    source: str | None = None
    formats: tuple[str, ...] = ()
    tokens: int = 2048


@dataclass(frozen=True)
class _Search:
    """A validated Search request."""

    query: str
    count: int
    offset: int
    include: tuple[str, ...]
    exclude: tuple[str, ...]
    extraction: _Extraction
    livecrawl_formats: tuple[str, ...]


def _extraction(value: Any, count: int, crawl_timeout: Any) -> _Extraction | None:
    """Validate the ``extraction`` object; ``None`` means invalid."""

    if value is None:
        return _Extraction()
    if not isinstance(value, dict) or set(value) - _EXTRACTION_KEYS:
        return None
    mode, source = value.get("extraction_mode"), value.get("extraction_source")
    full_page, highlights = value.get("full_page"), value.get("highlights")
    if source is not None and source not in _SOURCES:
        return None
    if mode == "full_page":
        options = {} if full_page is None else full_page
        if highlights is not None or not isinstance(options, dict):
            return None
        formats = options.get("extraction_formats", ["markdown"])
        if set(options) - {"extraction_formats"} or not _strings(formats) or not formats:
            return None
        if set(formats) - _PAGE_FORMATS:
            return None
        return _Extraction(mode=mode, source=source or "blend", formats=tuple(formats))
    if mode == "highlights":
        options = {} if highlights is None else highlights
        if full_page is not None or source is not None or crawl_timeout is not None:
            return None
        if count > _MAX_HIGHLIGHT_RESULTS or not isinstance(options, dict):
            return None
        tokens = options.get("total_max_tokens", 2048)
        if set(options) - {"total_max_tokens"} or not _int_in(tokens, 1024, 8192):
            return None
        return _Extraction(mode=mode, tokens=tokens)
    return None


def _search_request(body: Any) -> _Search | None:
    """Validate a Search body; ``None`` means 422 ``invalid request parameter(s)``."""

    if not isinstance(body, dict):
        return None
    query, count = body.get("query"), body.get("count", _DEFAULT_COUNT)
    offset = body.get("offset", 0)
    if not isinstance(query, str) or not query.strip():
        return None
    if not _int_in(count, 1, 100) or not _int_in(offset, 0, 9):
        return None
    domains = {key: body.get(key) or [] for key in ("include_domains", "exclude_domains")}
    boost = body.get("boost_domains") or []
    if not all(_strings(value) for value in (*domains.values(), boost)):
        return None
    if domains["include_domains"] and (domains["exclude_domains"] or boost):
        return None
    if not _valid_options(body):
        return None
    extraction = _extraction(body.get("extraction"), count, body.get("crawl_timeout"))
    if extraction is None:
        return None
    livecrawl_formats = body.get("livecrawl_formats") or ["markdown"]
    return _Search(
        query=query,
        count=count,
        offset=offset,
        include=tuple(domains["include_domains"]),
        exclude=tuple(domains["exclude_domains"]),
        extraction=extraction,
        livecrawl_formats=tuple(livecrawl_formats) if body.get("livecrawl") else (),
    )


def _valid_options(body: dict[str, Any]) -> bool:
    for key, allowed in (
        ("safesearch", _SAFESEARCH),
        ("knowledge", {"core"}),
        ("livecrawl", _LIVECRAWL),
    ):
        value = body.get(key)
        if value is not None and value not in allowed:
            return False
    if any(
        body.get(key) is not None and not isinstance(body[key], str)
        for key in ("country", "language", "freshness")
    ):
        return False
    if body.get("strict_operators") is not None and not isinstance(body["strict_operators"], bool):
        return False
    crawl_timeout = body.get("crawl_timeout")
    if crawl_timeout is not None and not _int_in(crawl_timeout, 1, 60):
        return False
    formats = body.get("livecrawl_formats")
    return formats is None or (_strings(formats) and not set(formats) - _PAGE_FORMATS)


class YouPlugin(ProviderPlugin):
    """You.com Search, Contents, and account balance."""

    name: ClassVar[str] = "you"
    hosts: ClassVar[frozenset[str]] = _GATEWAY_HOSTS | _API_HOSTS
    key_format: ClassVar[KeyFormat] = KeyFormat(prefix="ydc-sk-", body_length=58)

    def operations(self) -> Sequence[Operation]:
        return (
            Operation("search", "POST", "/v1/search", self._search),
            Operation("contents", "POST", "/v1/contents", self._contents),
            Operation(
                "balance", "GET", "/v1/billing/account_balance", self._balance, billable=False
            ),
        )

    def credentials(self, request: Request) -> Credentials:
        return Credentials(key=header_value(request, "x-api-key"))

    def default_seed(self) -> ProviderSeed:
        return ProviderSeed(
            accounts=(
                AccountSeed(
                    id="you-signup",
                    plan="Signup credit",
                    credit_limit=Decimal(10_000),
                    reset_rule="none",
                    attributes={"unit": "usd_cents"},
                ),
            ),
            keys=(
                KeySeed(label="default", account_id="you-signup", env_var="POLYWEB_YOU_API_KEY"),
                KeySeed(label="secondary", account_id="you-signup"),
            ),
        )

    def default_pricing(self) -> Sequence[PriceRule]:
        def price(operation: str, cents: str, unit: str) -> PriceRule:
            amount = Decimal(cents)
            return PriceRule(
                provider=self.name,
                operation=operation,
                credits_per_unit=amount,
                usd_per_unit=amount / 100,
                unit=unit,
            )

        return (
            price("search", "0.5", "request"),
            price("search.live_page", "0.1", "page"),
            price("contents", "0.1", "page"),
        )

    # --------------------------------------------------------------- errors

    def error(self, kind: ErrorKind, context: ErrorContext) -> MockResponse:
        generator = random.Random()
        if context.operation in _GATEWAY_OPERATIONS:
            response, backend, errortype = self._gateway_error(kind, context)
            return _gateway(response, generator, backend=backend, errortype=errortype)
        return _edge(self._api_error(kind, context), generator)

    @staticmethod
    def _gateway_error(
        kind: ErrorKind, context: ErrorContext
    ) -> tuple[MockResponse, bool, str | None]:
        """Return the gateway or backend response, whether the backend sent it, and its type."""

        status = context.status
        if kind in {ErrorKind.AUTH_INVALID, ErrorKind.AUTH_REVOKED}:
            if context.missing_key and status in {None, 402}:
                return MockResponse(402, dict(_PAYMENT_REQUIRED)), False, "AccessDeniedException"
            if status == 401:
                return MockResponse(401, {"detail": "Invalid or expired API key"}), True, None
            forbidden = MockResponse(status or 403, {"message": "Forbidden"})
            return forbidden, False, "ForbiddenException"
        if kind is ErrorKind.FORBIDDEN:
            body = {"detail": context.message or "Missing required scopes"}
            return MockResponse(status or 403, body), True, None
        if kind is ErrorKind.BAD_REQUEST:
            status = status or 422
            message = context.message or _INVALID_PARAMS
            if status in {400, 422}:
                return MockResponse(status, {"error": message, **context.details}), True, None
            return MockResponse(status, {"detail": _phrase(status, message)}), True, None
        if kind is ErrorKind.QUOTA_EXHAUSTED:
            if context.scope == "key" or status == 429:
                return MockResponse(429, dict(_SPEND_CAP)), True, None
            payment = MockResponse(status or 402, dict(_PAYMENT_REQUIRED))
            return payment, False, "AccessDeniedException"
        if kind is ErrorKind.RATE_LIMITED:
            if context.scope in {"key", "spend_cap"}:
                return MockResponse(429, dict(_SPEND_CAP)), True, None
            headers = _rate_headers(context.retry_after, header=context.retry_after_header)
            limited = MockResponse(status or 429, {"message": "Too Many Requests"}, headers)
            return limited, False, "TooManyRequestsException"
        if kind is ErrorKind.SERVICE_UNAVAILABLE:
            return MockResponse(status or 503, {"message": "Service Unavailable"}), False, None
        status = status or 500
        if status == 500:
            body = {"detail": context.message or "Internal Server Error"}
            return MockResponse(500, body), True, None
        messages = {502: "Internal server error", 504: "Endpoint request timed out"}
        body = {"message": context.message or messages.get(status) or _phrase(status, "Error")}
        return MockResponse(status, body), False, None

    @staticmethod
    def _api_error(kind: ErrorKind, context: ErrorContext) -> MockResponse:
        status = context.status
        if kind in {ErrorKind.AUTH_INVALID, ErrorKind.AUTH_REVOKED}:
            detail = "API key is required" if context.missing_key else "Invalid or expired API key"
            return MockResponse(status or 401, {"detail": context.message or detail})
        if kind is ErrorKind.FORBIDDEN:
            return MockResponse(
                status or 403, {"detail": context.message or "Missing required scopes"}
            )
        if kind is ErrorKind.RATE_LIMITED:
            headers = _rate_headers(context.retry_after, header=context.retry_after_header)
            return MockResponse(status or 429, {"detail": "Too Many Requests"}, headers)
        if kind is ErrorKind.QUOTA_EXHAUSTED:
            return MockResponse(status or 402, {"detail": "Insufficient credits"})
        defaults = {
            ErrorKind.BAD_REQUEST: 400,
            ErrorKind.SERVICE_UNAVAILABLE: 503,
            ErrorKind.SERVER_ERROR: 500,
        }
        status = status or defaults[kind]
        return MockResponse(status, {"detail": context.message or _phrase(status, "Error")})

    def not_found(self, request: Request, status: int) -> MockResponse:
        generator = random.Random()
        if (request.url.hostname or "").lower() in _GATEWAY_HOSTS:
            body = {"message": "Missing Authentication Token"}
            response = MockResponse(403, body)
            return _gateway(
                response, generator, backend=False, errortype="MissingAuthenticationTokenException"
            )
        detail = "Method Not Allowed" if status == 405 else "Not Found"
        return _edge(MockResponse(status, {"detail": detail}), generator)

    def _misrouted(self, context: OperationContext) -> MockResponse | None:
        """Answer a path that exists on the other You.com host as the real hosts do."""

        on_gateway = (context.request.url.hostname or "").lower() in _GATEWAY_HOSTS
        if on_gateway == (context.operation.name in _GATEWAY_OPERATIONS):
            return None
        return self.not_found(context.request, 404)

    def drop_required_field(self, operation: str, body: Any) -> Any:
        if (
            operation == "search"
            and isinstance(body, dict)
            and isinstance(body.get("results"), dict)
        ):
            sections = {
                name: [
                    {key: value for key, value in item.items() if key != "url"}
                    for item in items
                    if isinstance(item, dict)
                ]
                if isinstance(items, list)
                else items
                for name, items in body["results"].items()
            }
            return {**body, "results": sections}
        if operation == "contents" and isinstance(body, list):
            return [
                {key: value for key, value in page.items() if key not in {"markdown", "html"}}
                for page in body
                if isinstance(page, dict)
            ]
        if operation == "balance" and isinstance(body, dict) and isinstance(body.get("data"), dict):
            data = {key: value for key, value in body["data"].items() if key != "attributes"}
            return {**body, "data": data}
        return super().drop_required_field(operation, body)

    # --------------------------------------------------------------- search

    async def _search(self, context: OperationContext) -> MockResponse:
        misrouted = self._misrouted(context)
        if misrouted is not None:
            return misrouted
        try:
            body: Any = context.json()
        except json.JSONDecodeError:
            body = None
        request = _search_request(body)
        if request is None:
            return context.error(ErrorKind.BAD_REQUEST)
        context.match_key = content.normalize_query(request.query)
        fixture = context.fixture(context.match_key)
        generator = content.rng(self.name, "headers", context.sequence)
        if fixture is not None and fixture.status != 200:
            return _gateway(MockResponse(fixture.status, fixture.body), generator)
        context.charge("search")
        if fixture is not None and isinstance(fixture.body, dict):
            result = dict(fixture.body)
            if isinstance(result.get("metadata"), dict):
                result["metadata"] = {**result["metadata"], "search_uuid": context.request_id()}
        else:
            items = self._items(request)
            live = self._live_pages(request, items)
            if live:
                context.charge("search.live_page", units=live)
            result = {
                "results": {"web": items},
                "metadata": {
                    "query": request.query,
                    "search_uuid": context.request_id(),
                    "latency": 0.2 + content.rng("you-latency", request.query).random() * 0.4,
                },
            }
        return _gateway(MockResponse(200, result), generator)

    def _items(self, request: _Search) -> list[dict[str, Any]]:
        total = request.count * (request.offset + 1)
        hits = content.search_hits(
            request.query,
            total,
            include_domains=list(request.include),
            exclude_domains=list(request.exclude),
        )[request.count * request.offset :]
        budget = request.extraction.tokens // max(1, len(hits))
        return [self._item(request, hit, budget) for hit in hits]

    @staticmethod
    def _item(request: _Search, hit: content.SearchHit, budget: int) -> dict[str, Any]:
        page = content.page(hit.url, hit.title)
        extraction = request.extraction
        if extraction.mode == "highlights":
            highlights: list[str] = []
            words = 0
            for paragraph in _paragraphs(page)[:3]:
                words += len(paragraph.split())
                if highlights and words * 4 // 3 > budget:
                    break
                highlights.append(paragraph)
            return {
                "url": hit.url,
                "contents": {"highlights": highlights},
                "title": hit.title,
                "description": "",
                "page_age": _page_age(hit),
                "favicon_url": _favicon(hit.domain),
            }
        item: dict[str, Any] = {"url": hit.url, "title": hit.title, "description": hit.snippet}
        if page.images:
            item["thumbnail_url"] = page.images[0]
            item["original_thumbnail_url"] = page.images[0]
        item["page_age"] = _page_age(hit)
        item["favicon_url"] = _favicon(hit.domain)
        item["snippets"] = _paragraphs(page)[:2]
        formats = extraction.formats or request.livecrawl_formats
        if formats:
            item["contents"] = {
                fmt: page.markdown if fmt == "markdown" else _html(page) for fmt in formats
            }
        return item

    @staticmethod
    def _live_pages(request: _Search, items: list[dict[str, Any]]) -> int:
        """Return the pages that a live crawl fetched (billed on top of the search)."""

        if request.livecrawl_formats:
            return len(items)
        source = request.extraction.source
        if request.extraction.mode != "full_page" or source == "cache":
            return 0
        if source == "fetch":
            return len(items)
        return sum(1 for item in items if content.rng("you-cache", item["url"]).random() < 0.5)

    # ------------------------------------------------------------- contents

    async def _contents(self, context: OperationContext) -> MockResponse:
        misrouted = self._misrouted(context)
        if misrouted is not None:
            return misrouted
        generator = content.rng(self.name, "headers", context.sequence)
        checked = self._contents_request(context)
        if isinstance(checked, MockResponse):
            return _gateway(checked, generator)
        urls, formats = checked
        pages: list[dict[str, Any]] = []
        for url in urls:
            context.match_key = content.normalize_url(url)
            page = self._page(context, url, formats)
            if page is not None:
                pages.append(page)
        if pages:
            context.charge("contents", units=len(pages))
        return _gateway(MockResponse(200, pages), generator)

    @staticmethod
    def _contents_request(context: OperationContext) -> tuple[list[str], list[str]] | MockResponse:
        try:
            body = context.json()
        except json.JSONDecodeError as exc:
            return _detail("json_invalid", (exc.pos,), "JSON decode error", {}, error=exc.msg)
        if body is None:
            return _detail("missing", (), "Field required", None)
        if not isinstance(body, dict):
            message = "Input should be a valid dictionary or object to extract fields from"
            return _detail("model_attributes_type", (), message, body)
        urls = body.get("urls", _MISSING)
        if urls is _MISSING:
            return _detail("missing", ("urls",), "Field required", body)
        if not isinstance(urls, list):
            return _detail("list_type", ("urls",), "Input should be a valid list", urls)
        for index, url in enumerate(urls):
            if not isinstance(url, str):
                return _detail(
                    "string_type", ("urls", index), "Input should be a valid string", url
                )
        formats = body.get("formats", ["markdown"])
        if not isinstance(formats, list):
            return _detail("list_type", ("formats",), "Input should be a valid list", formats)
        expected = "'html', 'markdown' or 'metadata'"
        for index, fmt in enumerate(formats):
            if fmt not in _CONTENT_FORMATS:
                message = f"Input should be {expected}"
                return _detail("enum", ("formats", index), message, fmt, expected=expected)
        for name, low, high in (("max_age", 0, None), ("crawl_timeout", 1, 60)):
            value = body.get(name)
            if value is None or _int_in(value, low, high):
                continue
            if isinstance(value, bool) or not isinstance(value, int):
                message = "Input should be a valid integer"
                return _detail("int_type", (name,), message, value)
            if value < low:
                message = f"Input should be greater than or equal to {low}"
                return _detail("greater_than_equal", (name,), message, value, ge=low)
            message = f"Input should be less than or equal to {high}"
            return _detail("less_than_equal", (name,), message, value, le=high)
        return list(urls), list(formats)

    @staticmethod
    def _page(context: OperationContext, url: str, formats: list[str]) -> dict[str, Any] | None:
        """Return one page in the requested formats, or ``None`` for a failed page."""

        fixture = context.fixture(content.normalize_url(url))
        if fixture is not None:
            saved = fixture.body
            if isinstance(saved, list):
                key = content.normalize_url(url)
                saved = next(
                    (
                        page
                        for page in saved
                        if isinstance(page, dict)
                        and content.normalize_url(str(page.get("url", ""))) == key
                    ),
                    None,
                )
            if isinstance(saved, dict):
                return {**saved, "url": url}
            if saved is None:
                return None
        parts = urlsplit(url)
        host = (parts.hostname or "").lower()
        if parts.scheme not in {"http", "https"} or not host:
            return None
        if host.split(".")[0] == "blocked" or host.endswith(".invalid"):
            return None
        page = content.page(url)
        item: dict[str, Any] = {"url": url}
        if "html" in formats:
            item["html"] = _html(page)
        if "metadata" in formats:
            item["metadata"] = {
                "site_name": _site_name(host),
                "favicon_url": f"https://api.ydc-index.io/favicon?domain={host}&size=128",
            }
        if "markdown" in formats:
            item["markdown"] = page.markdown
        item["title"] = page.title
        return item

    # -------------------------------------------------------------- balance

    async def _balance(self, context: OperationContext) -> MockResponse:
        misrouted = self._misrouted(context)
        if misrouted is not None:
            return misrouted
        account = context.principal.account
        if account is None:
            return context.error(ErrorKind.AUTH_INVALID, missing_key=True)
        remaining = account.remaining
        balance = _UNLIMITED_BALANCE_CENTS if remaining is None else float(remaining)
        body = {
            "data": {
                "type": "account",
                "id": content.stable_uuid(self.name, "account", account.id),
                "attributes": {"balance": balance},
            }
        }
        generator = content.rng(self.name, "headers", context.sequence)
        return _edge(MockResponse(200, body), generator)


PLUGIN = YouPlugin()
