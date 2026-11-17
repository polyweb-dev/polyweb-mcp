"""Firecrawl v2 on ``api.firecrawl.dev``: search, scrape, and team credit usage.

Formats follow the live recordings of 2026-11-17 (``firecrawl-py`` 4.41.0,
``tests/contract/recordings/firecrawl``) and the official API reference:

- Authentication is ``Authorization: Bearer fc-...``. A wrong or revoked key
  gets 401 ``{"success": false, "error": "Unauthorized: Invalid token"}``
  with a ``WWW-Authenticate`` header. Without a key, search and scrape use
  the keyless free tier (a per-day budget); ``/v2/team/credit-usage`` has
  no keyless mode and answers 401 with a ``signup_url``.
- Every error is ``{"success": false, "error": ...}``; validation errors add
  ``code: "BAD_REQUEST"`` and zod ``details``. Credit exhaustion is 402,
  rate limits are 429 with ``Retry-After``.
- Search costs 2 credits per 10 requested results (rounded up) plus the
  scrape cost of each result when ``scrapeOptions.formats`` asks for
  content; the envelope reports ``creditsUsed`` and a search ``id``. Scrape
  costs 1 credit per page plus per-page modifiers (JSON and LLM formats +4,
  PDF +1 per page, ZDR +1, PII redaction +4, lockdown +4), reported in
  ``data.metadata.creditsUsed``. A target-site 403/404 still returns a
  document and is billed; a scrape with no document is free.
- Scrape auto-resume: a host whose first label is ``processing`` answers
  the first two identical scrapes with 408 ``SCRAPE_TIMEOUT`` and
  ``details.state = "processing_continues"``; the SDK re-sends the same
  POST and the third answer is the finished document, billed once. An
  ``http_error`` fault with status 408 and scope ``processing_continues``
  produces the same signal on any URL.

Synthetic scrape targets: a ``blocked`` first label returns a document with
``metadata.statusCode`` 403, ``notfound`` returns 404, and a ``.invalid``
host fails DNS resolution (400, no document, free). A ``.pdf`` path is
parsed as a PDF with ``numPages``.

Accuracy gaps (no live evidence): 402, 429, 5xx, keyless-cap, and DNS
failure messages are inferred from the docs and the open-source API; the
keyless per-day cap (50) is unpublished; ``branding``, ``product``,
``menu``, and ``attributes`` formats are accepted but return no content.
"""

import base64
import json
import math
import random
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from http import HTTPStatus
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
from polyweb_provider_mock.providers._exa_firecrawl_common import charge_all, iso_ms, schema_value
from polyweb_provider_mock.providers.base import (
    Credentials,
    ErrorContext,
    ErrorKind,
    MockResponse,
    Operation,
    OperationContext,
    ProviderPlugin,
    bearer_token,
)

__all__ = ["PLUGIN", "FirecrawlPlugin"]

_HOST: Final = "api.firecrawl.dev"
_JSON: Final = "application/json; charset=utf-8"
_MISSING: Final[Any] = object()
_WWW_AUTHENTICATE: Final = (
    'Bearer resource_metadata="https://www.firecrawl.dev/.well-known/oauth-protected-resource"'
)
_SIGNUP_URL: Final = "https://firecrawl.dev/k/mock-signup"
_PROCESSING_RESUMES: Final = 2
_RESUME_SECONDS: Final = 5
_DEFAULT_LIMIT: Final = 5
_MAX_LIMIT: Final = 100
_RATE_LIMIT_PER_MINUTE: Final = 10
_UNLIMITED_CREDITS: Final = 1_000_000_000
_USD_PER_CREDIT: Final = Decimal("0.0038")
_CHANNELS: Final = ("web", "news", "images")

#: Every scrape format, in the order of the API's zod union.
_FORMATS: Final = (
    "markdown",
    "html",
    "rawHtml",
    "rawBase64",
    "links",
    "images",
    "summary",
    "json",
    "deterministicJson",
    "changeTracking",
    "screenshot",
    "attributes",
    "branding",
    "product",
    "menu",
    "question",
    "highlights",
    "query",
    "audio",
    "video",
)
#: Object formats that need one more field: ``type -> (field, JSON type)``.
_FORMAT_FIELDS: Final = {
    "attributes": ("selectors", "array"),
    "question": ("question", "string"),
    "highlights": ("query", "string"),
    "query": ("prompt", "string"),
}
_FORMAT_PRICES: Final = {
    "json": "scrape.json",
    "deterministicJson": "scrape.json",
    "question": "scrape.question",
    "query": "scrape.query",
    "highlights": "scrape.highlights",
    "audio": "scrape.audio",
    "video": "scrape.video",
}
_OPTION_PRICES: Final = (
    ("zeroDataRetention", "scrape.zero_data_retention"),
    ("redactPII", "scrape.redact_pii"),
    ("lockdown", "scrape.lockdown"),
    ("checkPromptInjection", "scrape.prompt_injection_check"),
)
_PRICES: Final = (
    ("search", 2, "10 results"),
    ("scrape", 1, "page"),
    ("scrape.json", 4, "page"),
    ("scrape.question", 4, "page"),
    ("scrape.query", 4, "page"),
    ("scrape.highlights", 4, "page"),
    ("scrape.audio", 4, "page"),
    ("scrape.video", 4, "page"),
    ("scrape.pdf_page", 1, "pdf page"),
    ("scrape.zero_data_retention", 1, "page"),
    ("scrape.redact_pii", 4, "page"),
    ("scrape.lockdown", 4, "page"),
    ("scrape.prompt_injection_check", 4, "page"),
)
_DEFAULT_STATUS: Final = {
    ErrorKind.AUTH_INVALID: 401,
    ErrorKind.AUTH_REVOKED: 401,
    ErrorKind.FORBIDDEN: 403,
    ErrorKind.BAD_REQUEST: 400,
    ErrorKind.RATE_LIMITED: 429,
    ErrorKind.QUOTA_EXHAUSTED: 402,
    ErrorKind.SERVER_ERROR: 500,
    ErrorKind.SERVICE_UNAVAILABLE: 503,
}
_INVALID_TOKEN: Final = "Unauthorized: Invalid token"
_KEYLESS_ENDPOINT: Final = (
    f"This endpoint is not supported by the keyless free tier. Sign up for a free API key at "
    f"{_SIGNUP_URL} for more endpoints, more usage, and higher rate limits.\n\n"
    "Then authenticate with:\nAuthorization: Bearer YOUR_API_KEY"
)
_KEYLESS_CAP: Final = (
    f"You have reached the daily limit of the keyless free tier. Sign up for a free API key at "
    f"{_SIGNUP_URL} for 1,000 credits and higher rate limits.\n\n"
    "Then authenticate with:\nAuthorization: Bearer YOUR_API_KEY"
)
_INSUFFICIENT_CREDITS: Final = (
    "Payment Required: Insufficient credits to perform this request. For more credits, you can "
    "upgrade your plan at https://firecrawl.dev/pricing or turn on pay-as-you-go."
)
_TIMEOUT_MESSAGE: Final = "Request timed out"
_DAYS: Final = ("Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat")


def _number(value: Decimal) -> int | float:
    return int(value) if value == value.to_integral_value() else float(value)


def _response_time(*seed: object) -> dict[str, str]:
    generator = content.rng("firecrawl-time", *seed) if seed else random.Random()
    return {"x-response-time": f"{0.2 + generator.random() * 2500:.3f}ms"}


def _js_date(value: datetime) -> str:
    """Render a date like JavaScript's ``Date.prototype.toString`` in UTC."""

    value = value.astimezone(UTC)
    return (
        f"{_DAYS[(value.weekday() + 1) % 7]} {value:%b %d %Y %H:%M:%S} "
        "GMT+0000 (Coordinated Universal Time)"
    )


def _js_type(value: Any) -> str:
    if value is _MISSING:
        return "undefined"
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, str):
        return "string"
    return "array" if isinstance(value, list) else "object"


def _issue(path: Sequence[str | int], expected: str, value: Any) -> dict[str, Any]:
    received = _js_type(value)
    return {
        "expected": expected,
        "code": "invalid_type",
        "path": list(path),
        "message": f"Invalid input: expected {expected}, received {received}",
    }


def _bad_request(context: OperationContext, details: list[dict[str, Any]]) -> MockResponse:
    return context.error(ErrorKind.BAD_REQUEST, details={"details": details})


def _format_union_error(index: int) -> list[dict[str, Any]]:
    """Return the zod ``invalid_union`` details for one unknown format."""

    branches: list[list[dict[str, Any]]] = []
    for name in _FORMATS:
        branch: list[dict[str, Any]] = [
            {
                "code": "invalid_value",
                "values": [name],
                "path": ["type"],
                "message": f'Invalid input: expected "{name}"',
            }
        ]
        if name in _FORMAT_FIELDS:
            field, kind = _FORMAT_FIELDS[name]
            branch.append(_issue([field], kind, _MISSING))
        branches.append(branch)
    return [
        {
            "code": "invalid_union",
            "errors": branches,
            "path": ["formats", index],
            "message": "Invalid input",
        }
    ]


def _object_body(context: OperationContext) -> dict[str, Any] | MockResponse:
    try:
        body = context.json()
    except (json.JSONDecodeError, UnicodeDecodeError):
        return context.error(ErrorKind.BAD_REQUEST, message="Invalid JSON in request body")
    if not isinstance(body, dict):
        return _bad_request(context, [_issue([], "object", body)])
    return body


def _valid_url(url: str) -> bool:
    parts = urlsplit(url)
    return parts.scheme in {"http", "https"} and bool(parts.hostname)


def _reserved(host: str) -> bool:
    return host.removeprefix("www.").split(".")[0] in {"example", "localhost"}


def _parse_formats(value: Any) -> list[dict[str, Any] | None]:
    """Return normalized ``{"type": ...}`` formats; a ``None`` entry marks a bad index."""

    formats: list[dict[str, Any] | None] = []
    for item in value:
        fmt = (
            {"type": item}
            if isinstance(item, str)
            else dict(item)
            if isinstance(item, dict)
            else {}
        )
        name = fmt.get("type")
        if name not in _FORMATS:
            formats.append(None)
            continue
        if name in _FORMAT_FIELDS:
            field, kind = _FORMAT_FIELDS[name]
            expected = list if kind == "array" else str
            if not isinstance(fmt.get(field), expected):
                formats.append(None)
                continue
        formats.append(fmt)
    return formats


class FirecrawlPlugin(ProviderPlugin):
    """Firecrawl search, scrape (with auto-resume), and team credit usage."""

    name: ClassVar[str] = "firecrawl"
    hosts: ClassVar[frozenset[str]] = frozenset({_HOST})
    key_format: ClassVar[KeyFormat] = KeyFormat(
        prefix="fc-", body_length=32, alphabet="0123456789abcdef"
    )

    def operations(self) -> Sequence[Operation]:
        return (
            Operation("search", "POST", "/v2/search", self._search, keyless=True),
            Operation("scrape", "POST", "/v2/scrape", self._scrape, keyless=True),
            Operation(
                "credit_usage", "GET", "/v2/team/credit-usage", self._credit_usage, billable=False
            ),
        )

    def credentials(self, request: Request) -> Credentials:
        key = bearer_token(request)
        return Credentials(key=key, keyless=key is None)

    def default_seed(self) -> ProviderSeed:
        return ProviderSeed(
            accounts=(
                AccountSeed(
                    id="firecrawl-team",
                    plan="Free",
                    credit_limit=Decimal(1000),
                    # planCredits excludes coupon and pay-as-you-go credits, so
                    # `credits add` raises remainingCredits above it, as live.
                    attributes={"plan_credits": 1000},
                ),
            ),
            keys=(
                KeySeed(
                    label="default",
                    account_id="firecrawl-team",
                    env_var="POLYWEB_FIRECRAWL_API_KEY",
                ),
                KeySeed(label="secondary", account_id="firecrawl-team"),
            ),
            keyless=KeylessSeed(enabled=True, per_day=50),
        )

    def default_pricing(self) -> Sequence[PriceRule]:
        return tuple(
            PriceRule(
                provider=self.name,
                operation=operation,
                credits_per_unit=Decimal(credits),
                usd_per_unit=Decimal(credits) * _USD_PER_CREDIT,
                unit=unit,
            )
            for operation, credits, unit in _PRICES
        )

    def response_headers(self) -> dict[str, str]:
        return {"access-control-allow-origin": "*"}

    def not_found(self, request: Request, status: int) -> MockResponse:
        phrase = HTTPStatus(status).phrase
        return MockResponse(
            status=status,
            body={"success": False, "error": phrase},
            headers=_response_time(),
            media_type=_JSON,
        )

    def drop_required_field(self, operation: str, body: Any) -> Any:
        victim = "data" if operation == "credit_usage" else "success"
        if isinstance(body, dict):
            return {key: value for key, value in body.items() if key != victim}
        return super().drop_required_field(operation, body)

    # --------------------------------------------------------------- errors

    def error(self, kind: ErrorKind, context: ErrorContext) -> MockResponse:
        status = context.status or _DEFAULT_STATUS[kind]
        headers = _response_time()
        body: dict[str, Any] = {"success": False}
        if status == 408:
            body |= self._timeout_body(context)
        elif kind is ErrorKind.AUTH_INVALID and context.missing_key and context.status is None:
            body |= {"error": context.message or _KEYLESS_ENDPOINT, "signup_url": _SIGNUP_URL}
            headers["www-authenticate"] = _WWW_AUTHENTICATE
        elif kind in {ErrorKind.AUTH_INVALID, ErrorKind.AUTH_REVOKED}:
            body["error"] = context.message or _INVALID_TOKEN
            headers["www-authenticate"] = _WWW_AUTHENTICATE
        elif kind is ErrorKind.RATE_LIMITED:
            body |= self._rate_limit_body(context)
            if context.retry_after_header:
                headers["Retry-After"] = str(self._retry_after(context))
        elif kind is ErrorKind.QUOTA_EXHAUSTED:
            body["error"] = context.message or _INSUFFICIENT_CREDITS
        elif kind is ErrorKind.BAD_REQUEST:
            body["code"] = str(context.details.get("code", "BAD_REQUEST"))
            body["error"] = context.message or self._phrase(status)
            if "details" in context.details:
                body["details"] = context.details["details"]
        elif kind is ErrorKind.SERVER_ERROR and status == 500:
            body["error"] = context.message or (
                "An unexpected error occurred. Please contact help@firecrawl.com for help. "
                f"Your exception ID is {random.getrandbits(128):032x}"
            )
        else:
            body["error"] = context.message or self._phrase(status)
        return MockResponse(status=status, body=body, headers=headers, media_type=_JSON)

    @staticmethod
    def _phrase(status: int) -> str:
        try:
            return HTTPStatus(status).phrase
        except ValueError:
            return "Error"

    @staticmethod
    def _retry_after(context: ErrorContext) -> int:
        return 60 if context.retry_after is None else context.retry_after

    @staticmethod
    def _timeout_body(context: ErrorContext) -> dict[str, Any]:
        body: dict[str, Any] = {
            "code": "SCRAPE_TIMEOUT",
            "error": context.message or _TIMEOUT_MESSAGE,
        }
        if context.scope == "processing_continues":
            seconds = context.retry_after if context.retry_after is not None else _RESUME_SECONDS
            body["details"] = {"state": "processing_continues", "retryAfterSeconds": seconds}
        return body

    def _rate_limit_body(self, context: ErrorContext) -> dict[str, Any]:
        if context.message:
            return {"error": context.message}
        if context.keyless:
            return {"error": _KEYLESS_CAP, "signup_url": _SIGNUP_URL}
        if context.scope == "concurrency":
            return {"error": "Concurrency limit reached"}
        seconds = self._retry_after(context)
        resets = _js_date(datetime.now(UTC) + timedelta(seconds=seconds))
        return {
            "error": (
                f"Rate limit exceeded. Consumed (req/min): {_RATE_LIMIT_PER_MINUTE + 1}, "
                "Remaining (req/min): 0. Upgrade your plan at https://firecrawl.dev/pricing "
                f"for increased rate limits or please retry after {seconds}s, resets at {resets}"
            )
        }

    # -------------------------------------------------------------- helpers

    @staticmethod
    def _success(context: OperationContext, body: dict[str, Any]) -> MockResponse:
        return MockResponse(
            status=200,
            body=body,
            headers=_response_time(context.sequence),
            media_type=_JSON,
        )

    @staticmethod
    def _scrape_parts(
        formats: Sequence[Mapping[str, Any]], options: Mapping[str, Any], pdf_pages: int
    ) -> list[tuple[str, int]]:
        """Return the priced parts of scraping one page."""

        parts = [("scrape", 1)]
        parts += [(_FORMAT_PRICES[f["type"]], 1) for f in formats if f["type"] in _FORMAT_PRICES]
        parts.append(("scrape.pdf_page", pdf_pages))
        prompt_check = any(f.get("checkPromptInjection") is True for f in formats)
        for option, operation in _OPTION_PRICES:
            if options.get(option) is True or (option == "checkPromptInjection" and prompt_check):
                parts.append((operation, 1))
        return parts

    @staticmethod
    def _pdf_pages(url: str, options: Mapping[str, Any]) -> int:
        if not urlsplit(url).path.lower().endswith(".pdf"):
            return 0
        pages = 2 + content.rng("firecrawl-pdf", url).randrange(11)
        parsers = options.get("parsers")
        if isinstance(parsers, list):
            pdf = [
                p for p in parsers if p == "pdf" or (isinstance(p, dict) and p.get("type") == "pdf")
            ]
            if not pdf:
                return 0
            cap = pdf[0].get("maxPages") if isinstance(pdf[0], dict) else None
            if isinstance(cap, int) and not isinstance(cap, bool) and cap > 0:
                pages = min(pages, cap)
        return pages

    def _document(
        self,
        context: OperationContext,
        url: str,
        formats: Sequence[Mapping[str, Any]],
        options: Mapping[str, Any],
        *,
        title: str | None = None,
        pdf_pages: int = 0,
    ) -> dict[str, Any]:
        """Return a v2 document with only the requested formats, plus metadata."""

        page = content.page(url, title)
        host = (urlsplit(url).hostname or "example.com").lower()
        label = host.split(".")[0]
        status = {"blocked": 403, "notfound": 404}.get(label, 200)
        markdown = page.markdown
        if status != 200:
            markdown = f"# {self._phrase(status)}\n\nThe server returned HTTP {status} for {url}."
        document: dict[str, Any] = {}
        for fmt in formats:
            document.update(self._format_output(url, page, markdown, fmt))
        document["metadata"] = self._metadata(context, url, page, options, status, pdf_pages)
        return document

    @staticmethod
    def _format_output(
        url: str, page: content.Page, markdown: str, fmt: Mapping[str, Any]
    ) -> dict[str, Any]:
        name = fmt["type"]
        host = (urlsplit(url).hostname or "example.com").lower()
        reserved = _reserved(host)
        paragraphs = "".join(f"<p>{line}</p>" for line in page.text.split("\n")[1:])
        html = (
            f'<!DOCTYPE html><html lang="en"><body><h1>{page.title}</h1>{paragraphs}</body></html>'
        )
        if name == "markdown":
            return {"markdown": markdown}
        if name == "html":
            return {"html": html}
        if name in {"rawHtml", "rawBase64"}:
            raw = html.replace(
                "<body>",
                f'<head><meta charset="utf-8"><title>{page.title}</title></head><body>',
            )
            if name == "rawHtml":
                return {"rawHtml": raw}
            return {"rawBase64": base64.b64encode(raw.encode()).decode("ascii")}
        if name == "links":
            if reserved:
                return {"links": ["https://iana.org/help/example-domains"]}
            return {
                "links": [f"https://{host}/{content.hex_id(8, url, 'link', i)}" for i in range(5)]
            }
        if name == "images":
            return {"images": list(page.images)}
        if name == "changeTracking":
            return {
                "changeTracking": {
                    "previousScrapeAt": None,
                    "changeStatus": "new",
                    "visibility": "visible",
                }
            }
        return FirecrawlPlugin._generated_output(url, page, fmt)

    @staticmethod
    def _generated_output(url: str, page: content.Page, fmt: Mapping[str, Any]) -> dict[str, Any]:
        """Return the output of a format that an LLM or a media pipeline produces."""

        name = fmt["type"]
        if name == "summary":
            return {"summary": content.answer(page.title)}
        if name in {"json", "deterministicJson"}:
            schema = fmt.get("schema")
            if isinstance(schema, dict):
                return {"json": schema_value(schema, page.title)}
            prompt = str(fmt.get("prompt") or page.title)
            return {"json": {"title": page.title, "summary": content.answer(prompt)}}
        if name == "screenshot":
            shot = content.stable_uuid("firecrawl", "screenshot", url)
            media = "https://service.firecrawl.dev/storage/v1/object/public/media"
            return {"screenshot": f"{media}/screenshot-{shot}.png"}
        if name in {"question", "query"}:
            return {"answer": content.answer(str(fmt.get("question") or fmt.get("prompt")))}
        if name == "highlights":
            return {"highlights": content.answer(f"{page.title} {fmt.get('query')}")}
        if name in {"audio", "video"}:
            media = content.hex_id(16, url, name)
            extension = "mp3" if name == "audio" else "mp4"
            return {name: f"https://storage.googleapis.com/firecrawl-media/{media}.{extension}"}
        return {}

    @staticmethod
    def _metadata(
        context: OperationContext,
        url: str,
        page: content.Page,
        options: Mapping[str, Any],
        status: int,
        pdf_pages: int,
    ) -> dict[str, Any]:
        parts = urlsplit(url)
        host = (parts.hostname or "example.com").lower()
        reserved = _reserved(host)
        metadata: dict[str, Any] = {
            "viewport": "width=device-width,initial-scale=1",
            "language": "en",
            "title": page.title,
            "favicon": "data:," if reserved or page.favicon is None else page.favicon,
        }
        if not reserved:
            description = page.text.split("\n")[2] if page.text.count("\n") >= 2 else page.title
            metadata |= {
                "description": description,
                "ogTitle": page.title,
                "ogDescription": description,
                "ogUrl": url,
                "ogImage": page.images[0] if page.images else None,
                "publishedTime": iso_ms(page.published),
            }
        proxy = options.get("proxy")
        max_age = options.get("maxAge", 172_800_000)
        cached = isinstance(max_age, int) and max_age > 0 and status == 200
        metadata |= {
            "scrapeId": context.request_id(),
            "sourceURL": url,
            "url": url if parts.path else f"{url}/",
            "statusCode": status,
            "contentType": "application/pdf" if pdf_pages else "text/html; charset=utf-8",
            "proxyUsed": "enhanced" if proxy in {"enhanced", "stealth"} else "basic",
            "cacheState": "hit" if cached else "miss",
        }
        if cached:
            age = content.rng("firecrawl-cache", url).random() * min(int(max_age), 3_600_000)
            metadata["cachedAt"] = iso_ms(context.store.now() - timedelta(milliseconds=age))
        if pdf_pages:
            metadata["numPages"] = pdf_pages
        if status != 200:
            metadata["error"] = HTTPStatus(status).phrase
        return metadata

    # --------------------------------------------------------------- search

    def _search_request(
        self, context: OperationContext, request: dict[str, Any]
    ) -> tuple[str, int, list[str]] | MockResponse:
        query = request.get("query", _MISSING)
        if not isinstance(query, str) or not query.strip():
            if isinstance(query, str):
                return _bad_request(
                    context,
                    [
                        {
                            "origin": "string",
                            "code": "too_small",
                            "minimum": 1,
                            "inclusive": True,
                            "path": ["query"],
                            "message": "Too small: expected string to have >=1 characters",
                        }
                    ],
                )
            return _bad_request(context, [_issue(["query"], "string", query)])
        limit = request.get("limit", _DEFAULT_LIMIT)
        if isinstance(limit, bool) or not isinstance(limit, int):
            return _bad_request(context, [_issue(["limit"], "number", limit)])
        if not 1 <= limit <= _MAX_LIMIT:
            bound, word, sign = (1, "small", ">=") if limit < 1 else (_MAX_LIMIT, "big", "<=")
            return _bad_request(
                context,
                [
                    {
                        "origin": "number",
                        "code": f"too_{word}",
                        "minimum" if limit < 1 else "maximum": bound,
                        "inclusive": True,
                        "path": ["limit"],
                        "message": f"Too {word}: expected number to be {sign}{bound}",
                    }
                ],
            )
        sources = request.get("sources") or [{"type": "web"}]
        channels: list[str] = []
        for index, source in enumerate(sources if isinstance(sources, list) else [sources]):
            kind = source if isinstance(source, str) else _option(source, "type")
            if kind not in _CHANNELS:
                return _bad_request(context, [_issue(["sources", index, "type"], "string", kind)])
            if kind not in channels:
                channels.append(str(kind))
        return query, limit, channels

    async def _search(self, context: OperationContext) -> MockResponse:
        request = _object_body(context)
        if isinstance(request, MockResponse):
            return request
        checked = self._search_request(context, request)
        if isinstance(checked, MockResponse):
            return checked
        query, limit, channels = checked
        context.match_key = content.normalize_query(query)
        fixture = context.fixture(context.match_key)
        if fixture is not None and fixture.status != 200:
            return MockResponse(status=fixture.status, body=fixture.body, media_type=_JSON)
        scrape_options = request.get("scrapeOptions")
        scrape = scrape_options if isinstance(scrape_options, dict) else {}
        formats = [f for f in _parse_formats(scrape.get("formats") or []) if f is not None]
        parts = [("search", math.ceil(limit / 10))]
        if fixture is not None and isinstance(fixture.body, dict):
            saved = fixture.body.get("data", fixture.body)
            data = dict(saved) if isinstance(saved, dict) else {"web": saved}
        else:
            data = self._search_data(context, query, limit, channels, request, formats)
            if formats:
                parts += self._scrape_parts(formats, scrape, 0) * len(data.get("web", []))
        charges = charge_all(context, parts)
        credits = sum((charge.credits for charge in charges), Decimal(0))
        body = {
            "success": True,
            "data": data,
            "creditsUsed": _number(credits),
            "id": context.request_id(),
        }
        return self._success(context, body)

    def _search_data(
        self,
        context: OperationContext,
        query: str,
        limit: int,
        channels: Sequence[str],
        request: Mapping[str, Any],
        formats: Sequence[Mapping[str, Any]],
    ) -> dict[str, list[dict[str, Any]]]:
        hits = content.search_hits(
            query,
            limit,
            include_domains=[str(d) for d in request.get("includeDomains") or []],
            exclude_domains=[str(d) for d in request.get("excludeDomains") or []],
        )
        data: dict[str, list[dict[str, Any]]] = {}
        generator = content.rng("firecrawl-search", query)
        for channel in channels:
            items: list[dict[str, Any]] = []
            for position, hit in enumerate(hits, start=1):
                image = content.image_urls(hit.domain, 1, "firecrawl", hit.url)[0]
                if channel == "web":
                    item: dict[str, Any] = {
                        "url": hit.url,
                        "title": hit.title,
                        "description": hit.snippet,
                        "position": position,
                    }
                    if formats:
                        item |= self._document(context, hit.url, formats, {}, title=hit.title)
                elif channel == "news":
                    days = generator.randrange(1, 40)
                    age = f"{days} days ago" if days < 14 else f"{days // 7} weeks ago"
                    item = {
                        "title": hit.title,
                        "url": hit.url,
                        "snippet": hit.snippet,
                        "date": age,
                        "imageUrl": image,
                        "position": position,
                    }
                else:
                    item = {
                        "title": hit.title,
                        "imageUrl": image,
                        "imageWidth": 320 + generator.randrange(1800),
                        "imageHeight": 180 + generator.randrange(1000),
                        "url": hit.url,
                        "position": position,
                    }
                items.append(item)
            data[channel] = items
        return data

    # --------------------------------------------------------------- scrape

    async def _scrape(self, context: OperationContext) -> MockResponse:
        request = _object_body(context)
        if isinstance(request, MockResponse):
            return request
        url = request.get("url", _MISSING)
        if not isinstance(url, str):
            return _bad_request(context, [_issue(["url"], "string", url)])
        url = url.strip()
        if not _valid_url(url):
            issue = {
                "code": "invalid_format",
                "format": "url",
                "path": ["url"],
                "message": "Invalid URL",
            }
            return _bad_request(context, [issue])
        raw_formats = request.get("formats", ["markdown"])
        if not isinstance(raw_formats, list):
            return _bad_request(context, [_issue(["formats"], "array", raw_formats)])
        parsed = _parse_formats(raw_formats)
        if None in parsed:
            return _bad_request(context, _format_union_error(parsed.index(None)))
        formats = [f for f in parsed if f is not None]
        context.match_key = content.normalize_url(url)
        host = (urlsplit(url).hostname or "").lower()
        if host.split(".")[0] == "processing" and self._still_processing(context, request):
            return context.error(ErrorKind.BAD_REQUEST, status=408, scope="processing_continues")
        fixture = context.fixture(context.match_key)
        if fixture is not None and fixture.status != 200:
            return MockResponse(status=fixture.status, body=fixture.body, media_type=_JSON)
        if host.endswith(".invalid"):
            return context.error(
                ErrorKind.BAD_REQUEST,
                message=(
                    f"DNS resolution failed for hostname: {host}. Please check if the domain "
                    "is valid and accessible."
                ),
                details={"code": "SCRAPE_DNS_RESOLUTION_ERROR"},
            )
        pdf_pages = self._pdf_pages(url, request)
        if fixture is not None and isinstance(fixture.body, dict):
            saved = fixture.body.get("data", fixture.body)
            document = dict(saved) if isinstance(saved, dict) else {}
            metadata = dict(document.get("metadata") or {})
        else:
            document = self._document(context, url, formats, request, pdf_pages=pdf_pages)
            metadata = document["metadata"]
        charges = charge_all(context, self._scrape_parts(formats, request, pdf_pages))
        metadata["creditsUsed"] = _number(sum((c.credits for c in charges), Decimal(0)))
        metadata["concurrencyLimited"] = False
        document["metadata"] = metadata
        return self._success(context, {"success": True, "data": document})

    @staticmethod
    def _still_processing(context: OperationContext, request: Mapping[str, Any]) -> bool:
        """Count identical scrapes of a ``processing`` host; the first two still run."""

        fingerprint = content.hex_id(16, json.dumps(request, sort_keys=True, default=str))
        attempt = context.store.next_sequence(
            f"firecrawl:resume:{context.principal.label}:{fingerprint}"
        )
        return attempt <= _PROCESSING_RESUMES

    # -------------------------------------------------------- credit usage

    async def _credit_usage(self, context: OperationContext) -> MockResponse:
        account = context.principal.account
        if account is None:
            return context.error(ErrorKind.AUTH_INVALID, missing_key=True)
        remaining = account.remaining
        plan = account.attributes.get("plan_credits", account.credit_limit)
        data = {
            "remainingCredits": _UNLIMITED_CREDITS if remaining is None else _number(remaining),
            "planCredits": _number(Decimal(str(plan))) if plan is not None else None,
            "billingPeriodStart": iso_ms(account.period_start),
            "billingPeriodEnd": None
            if account.period_reset is None
            else iso_ms(account.period_reset),
        }
        return self._success(context, {"success": True, "data": data})


def _option(value: Any, name: str) -> Any:
    return value.get(name) if isinstance(value, dict) else None


PLUGIN = FirecrawlPlugin()
