"""Tavily on ``api.tavily.com``: ``POST /search``, ``POST /extract``, ``GET /usage``.

The reference plugin.

Recorded (2026-11-17, ``tests/contract/recordings/tavily``): search and
extract success bodies, the 422 schema errors, the 400 depth error, the 401s
(missing, wrong key, keyless ``/usage``), the keyed ``/usage`` body (free
Researcher plan: ``plan_limit`` 1000, ``paygo_usage`` 0, ``paygo_limit``
null, ``key.limit`` null), and the keyless daily-cap 429 with its
``error.code = daily_cap_reached`` envelope and a ``Retry-After`` of 824
seconds, the time left until the window frees.

Documented (docs.tavily.com api-credits, rate-limits, endpoint pages):

- Authentication is ``Authorization: Bearer <key>``. A bearer key always
  wins. Without one, ``X-Tavily-Access-Mode: keyless`` selects the keyless
  rail on search and extract; ``/usage`` has no keyless mode. A missing,
  unknown, or revoked key gets 401 ``{"detail": {"error": ...}}``.
- Errors use ``{"detail": {"error": message}}``; schema errors are FastAPI
  422 arrays.
- The free Researcher plan grants 1,000 credits a month, reset on the 1st
  (the store's monthly grant, ``reset_day`` 1). Search costs 1 credit
  (ultra-fast, fast, basic) or 2 (advanced). Extract costs 1 credit per 5
  successful URLs (2 for advanced): the account carries the fraction and a
  response reports only whole credits, so one basic URL reports 0, as live.
  Failed URLs are free. ``/usage`` is free.
- Pay-as-you-go ($0.008 a credit) starts once the plan's credits are spent
  and is billed after use, up to a user-set monthly limit. The mock models it
  as the store's ``postpaid`` funding: ``paygo_usage``/``paygo_limit`` in
  ``/usage`` are the account's ``overage_used``/``overage_limit``. A prepaid
  account (the default) reports 0 and null, as recorded.
- 432 is the plan limit (store scope ``account``) or a key's own monthly
  limit (scope ``key``, set with ``KeySeed(credit_limit=...)`` or
  ``keys create --limit``); 433 is the pay-as-you-go limit (scope
  ``overage``, or a ``paygo`` fault scope). A ``quota_exhausted`` fault can
  force the 402 compatibility status.
- Rate limits are per account and shared by all its keys: 100 requests a
  minute on Researcher (1,000 on PAYGO/Project and above; set the account
  attribute ``requests_per_minute``) and 10 ``/usage`` calls per 10 minutes
  (attribute ``usage_per_10_minutes``). Over the limit is 429 with
  ``Retry-After``.
- Keyless search and extract are free and rate-limited.

Guessed: the account windows are fixed and start at the first request
(Tavily does not say whether they roll); ``/usage`` does not count toward the
RPM limit; the keyless budget of 500 calls a day is invented (Tavily
publishes no number). The store counts it per UTC calendar day and the 429
carries the seconds until that day ends; the live window freed 824 s after a
01:27 UTC capture, so Tavily's real window is not the UTC day.

Synthetic extract targets: a host whose first label is ``blocked`` fails
with a 403 message, and a ``.invalid`` host fails to fetch.
"""

import json
from collections.abc import Sequence
from datetime import timedelta
from decimal import Decimal
from email.utils import format_datetime
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
from polyweb_provider_mock.windows import WindowSpec

__all__ = ["PLUGIN", "TavilyPlugin"]

_SEARCH_DEPTHS: Final = ("ultra-fast", "fast", "basic", "advanced")
_TOPICS: Final = ("general", "news", "finance")
_EXTRACT_DEPTHS: Final = ("basic", "advanced")
_FORMATS: Final = ("markdown", "text")
_MAX_RESULTS: Final = 20
_MAX_EXTRACT_URLS: Final = 20
_DEFAULT_RESULTS: Final = 5
#: Researcher plan limits; account attributes override them (PAYGO: 1,000 RPM).
_REQUESTS_PER_MINUTE: Final = 100
_USAGE_PER_WINDOW: Final = 10
_USAGE_WINDOW_SECONDS: Final = 600
_MISSING: Final[Any] = object()
_CSP: Final = (
    "default-src 'none'; script-src 'self'; connect-src 'self'; img-src 'self'; "
    "style-src 'self';base-uri 'self';form-action 'self'; require-trusted-types-for 'script'; "
    "upgrade-insecure-requests;"
)
_RESPONSE_TIMES: Final = {
    "ultra-fast": (0.1, 0.4),
    "fast": (0.3, 0.9),
    "basic": (0.6, 1.8),
    "advanced": (2.5, 6.0),
}

_MESSAGES: Final = {
    ErrorKind.AUTH_INVALID: "Unauthorized: missing or invalid API key.",
    ErrorKind.AUTH_REVOKED: "Unauthorized: missing or invalid API key.",
    ErrorKind.FORBIDDEN: "Forbidden",
    ErrorKind.BAD_REQUEST: "Bad Request",
    ErrorKind.RATE_LIMITED: (
        "Your request has been blocked due to excessive requests. "
        "Please reduce the rate of requests."
    ),
    ErrorKind.SERVER_ERROR: "Internal Server Error",
    ErrorKind.SERVICE_UNAVAILABLE: "Service Unavailable",
}
_QUOTA_MESSAGES: Final = {
    432: (
        "This request exceeds your plan's set usage limit. Please upgrade your plan or "
        "contact support@tavily.com"
    ),
    433: (
        "This request exceeds the pay-as-you-go limit. You can increase your limit on the "
        "Tavily dashboard."
    ),
    402: "Your account is out of credits. Please upgrade your plan or add credits.",
}
_DEFAULT_STATUS: Final = {
    ErrorKind.AUTH_INVALID: 401,
    ErrorKind.AUTH_REVOKED: 401,
    ErrorKind.FORBIDDEN: 403,
    ErrorKind.BAD_REQUEST: 400,
    ErrorKind.RATE_LIMITED: 429,
    ErrorKind.QUOTA_EXHAUSTED: 432,
    ErrorKind.SERVER_ERROR: 500,
    ErrorKind.SERVICE_UNAVAILABLE: 503,
}
_KEYLESS_MESSAGE: Final = (
    "You reached the daily keyless Tavily limit. To continue immediately, pay via x402 agentic "
    "payment (https://docs.tavily.com/documentation/machine-payments/x402) or sign up at "
    "https://tavily.com for a Tavily API key. Otherwise, retry after the time given in the "
    "Retry-After response header."
)
_KEYLESS_ACTIONS: Final = (
    {
        "type": "agentic_payment",
        "resource": "https://docs.tavily.com/documentation/machine-payments/x402",
        "instruction": (
            "Pay for this request using the x402 agentic payment protocol to continue immediately."
        ),
    },
    {
        "type": "signup",
        "resource": "https://tavily.com",
        "instruction": (
            "Ask the user to sign up at tavily.com and retry with the API key in the "
            "Authorization header as: Bearer <TAVILY_API_KEY>"
        ),
    },
)


def _number(value: Decimal) -> int | float:
    """Render credits as JSON integers when whole, as Tavily does."""

    return int(value) if value == value.to_integral_value() else float(value)


def _message(kind: ErrorKind, status: int) -> str:
    """Return the documented message, or the status phrase for a forced status."""

    if status == _DEFAULT_STATUS[kind]:
        return _MESSAGES[kind]
    try:
        return HTTPStatus(status).phrase
    except ValueError:
        return _MESSAGES[kind]


def _seconds_to_midnight(context: ErrorContext) -> int:
    """Return the seconds until the keyless UTC day ends (the window frees)."""

    if context.store is None:
        return 86400
    now = context.store.now()
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
    return max(1, int((midnight - now).total_seconds()))


def _validation(kind: str, loc: Sequence[str | int], message: str, value: Any) -> MockResponse:
    """Return the FastAPI 422 body that Tavily sends for a schema error."""

    item = {"type": kind, "loc": ["body", *loc], "msg": message, "input": value}
    return MockResponse(status=422, body={"detail": [item]})


def _object_body(context: OperationContext) -> dict[str, Any] | MockResponse:
    try:
        body = context.json()
    except json.JSONDecodeError as exc:
        return MockResponse(
            status=422,
            body={
                "detail": [
                    {
                        "type": "json_invalid",
                        "loc": ["body", exc.pos],
                        "msg": "JSON decode error",
                        "input": {},
                        "ctx": {"error": exc.msg},
                    }
                ]
            },
        )
    if body is None:
        return _validation("missing", (), "Field required", None)
    if not isinstance(body, dict):
        return _validation(
            "model_attributes_type",
            (),
            "Input should be a valid dictionary or object to extract fields from",
            body,
        )
    return body


def _wants(value: Any, *accepted: str) -> str | None:
    """Return the selected mode of a boolean-or-mode option, or ``None`` when off."""

    if value is True:
        return accepted[0]
    if isinstance(value, str) and value in accepted:
        return value
    return None


def _valid_url(url: str) -> bool:
    parts = urlsplit(url)
    return parts.scheme in {"http", "https"} and bool(parts.hostname) and "." in parts.netloc


def _response_time(depth: str, *seed: object) -> float:
    low, high = _RESPONSE_TIMES.get(depth, (0.01, 0.05))
    return round(low + content.rng("response_time", *seed).random() * (high - low), 2)


def _finish(
    context: OperationContext, body: dict[str, Any], request: dict[str, Any], credits: Decimal
) -> MockResponse:
    """Append ``usage`` (when requested) and a fresh ``request_id`` to a success body."""

    body.pop("usage", None)
    body.pop("request_id", None)
    if request.get("include_usage") is True:
        body["usage"] = {"credits": _number(credits)}
    body["request_id"] = context.request_id()
    return MockResponse(status=200, body=body)


class TavilyPlugin(ProviderPlugin):
    """Tavily search, extract, and usage."""

    name: ClassVar[str] = "tavily"
    hosts: ClassVar[frozenset[str]] = frozenset({"api.tavily.com"})
    key_format: ClassVar[KeyFormat] = KeyFormat(prefix="tvly-dev-", body_length=32)

    def operations(self) -> Sequence[Operation]:
        return (
            Operation("search", "POST", "/search", self._search, keyless=True),
            Operation("extract", "POST", "/extract", self._extract, keyless=True),
            Operation("usage", "GET", "/usage", self._usage, billable=False),
        )

    def credentials(self, request: Request, store: MockStore) -> Credentials:
        mode = (header_value(request, "x-tavily-access-mode") or "").lower()
        return Credentials(key=bearer_token(request), keyless=mode == "keyless")

    def default_seed(self) -> ProviderSeed:
        return ProviderSeed(
            accounts=(
                AccountSeed(
                    id="tavily-researcher",
                    plan="Researcher",
                    credit_limit=Decimal(1000),
                    attributes={"paygo_usage": 0, "paygo_limit": None},
                ),
            ),
            keys=(
                KeySeed(
                    label="default",
                    account_id="tavily-researcher",
                    env_var="POLYWEB_TAVILY_API_KEY",
                ),
                KeySeed(label="secondary", account_id="tavily-researcher"),
            ),
            # Invented: Tavily publishes no keyless numbers.
            keyless=KeylessSeed(enabled=True, per_day=500),
        )

    def default_pricing(self) -> Sequence[PriceRule]:
        def price(operation: str, credits: str, unit: str, rule: str) -> PriceRule:
            amount = Decimal(credits)
            return PriceRule.model_validate(
                {
                    "provider": self.name,
                    "operation": operation,
                    "credits_per_unit": amount,
                    "usd_per_unit": amount * Decimal("0.008"),
                    "unit": unit,
                    "rule": rule,
                }
            )

        return (
            price("search.ultra-fast", "1", "request", "per_unit"),
            price("search.fast", "1", "request", "per_unit"),
            price("search.basic", "1", "request", "per_unit"),
            price("search.advanced", "2", "request", "per_unit"),
            price("extract.basic", "0.2", "url", "accumulate"),
            price("extract.advanced", "0.4", "url", "accumulate"),
        )

    def response_headers(self) -> dict[str, str]:
        return {"content-security-policy": _CSP}

    # --------------------------------------------------------------- errors

    def error(self, kind: ErrorKind, context: ErrorContext) -> MockResponse:
        if kind is ErrorKind.RATE_LIMITED and context.keyless:
            return self._keyless_limit(context)
        status = context.status or _DEFAULT_STATUS[kind]
        if kind is ErrorKind.QUOTA_EXHAUSTED:
            if context.status is None and context.scope in {"paygo", "overage"}:
                status = 433
            message = context.message or _QUOTA_MESSAGES.get(status, _QUOTA_MESSAGES[432])
        else:
            message = context.message or _message(kind, status)
        headers: dict[str, str] = {}
        if kind is ErrorKind.RATE_LIMITED and context.retry_after_header:
            headers["Retry-After"] = str(
                context.retry_after if context.retry_after is not None else 60
            )
        return MockResponse(
            status=status, body={"detail": {"error": message, **context.details}}, headers=headers
        )

    @staticmethod
    def _keyless_limit(context: ErrorContext) -> MockResponse:
        window = context.scope if context.scope in {"day", "minute"} else "day"
        seconds = context.retry_after
        if seconds is None:
            seconds = 60 if window == "minute" else _seconds_to_midnight(context)
        envelope = {
            "error": {
                "code": "daily_cap_reached" if window == "day" else "rate_limit_exceeded",
                "message": context.message or _KEYLESS_MESSAGE,
                "next_actions": [dict(action) for action in _KEYLESS_ACTIONS],
                "window": window,
                "retry_after_seconds": seconds,
            }
        }
        headers = {"Retry-After": str(seconds)} if context.retry_after_header else {}
        return MockResponse(status=context.status or 429, body=envelope, headers=headers)

    def _throttle(self, context: OperationContext) -> MockResponse | None:
        """Spend the account's shared rate window; return the 429 when it is full."""

        account = context.principal.account
        if account is None:
            return None
        attributes = account.attributes
        if context.operation.name == "usage":
            spec = WindowSpec(
                f"tavily:{account.id}:usage",
                int(attributes.get("usage_per_10_minutes", _USAGE_PER_WINDOW)),
                _USAGE_WINDOW_SECONDS,
            )
        else:
            spec = WindowSpec(
                f"tavily:{account.id}:minute",
                int(attributes.get("requests_per_minute", _REQUESTS_PER_MINUTE)),
                60,
            )
        now = context.store.now()
        refused, _ = context.admit([spec])
        if refused is None:
            return None
        return context.error(ErrorKind.RATE_LIMITED, retry_after=refused.retry_after(now))

    def drop_required_field(self, operation: str, body: Any) -> Any:
        if operation == "usage" and isinstance(body, dict):
            return {key: value for key, value in body.items() if key != "account"}
        return super().drop_required_field(operation, body)

    # --------------------------------------------------------------- search

    async def _search(self, context: OperationContext) -> MockResponse:
        limited = self._throttle(context)
        if limited is not None:
            return limited
        request = _object_body(context)
        if isinstance(request, MockResponse):
            return request
        query = request.get("query", _MISSING)
        if query is _MISSING:
            return _validation("missing", ("query",), "Field required", request)
        if not isinstance(query, str):
            return _validation("string_type", ("query",), "Input should be a valid string", query)
        depth = request.get("search_depth") or "basic"
        if depth not in _SEARCH_DEPTHS:
            return context.error(
                ErrorKind.BAD_REQUEST,
                message=(
                    "Invalid search depth. Must be 'ultra-fast', 'fast', 'basic' or 'advanced'."
                ),
            )
        topic = request.get("topic") or "general"
        if topic not in _TOPICS:
            return context.error(
                ErrorKind.BAD_REQUEST,
                message="Invalid topic. Must be 'general', 'news' or 'finance'.",
            )
        count = request.get("max_results", _DEFAULT_RESULTS)
        if isinstance(count, bool) or not isinstance(count, int) or not 0 <= count <= _MAX_RESULTS:
            return context.error(
                ErrorKind.BAD_REQUEST, message="max_results must be between 0 and 20."
            )
        context.match_key = content.normalize_query(query)
        fixture = context.fixture(context.match_key)
        if fixture is not None and fixture.status != 200:
            return MockResponse(status=fixture.status, body=fixture.body)
        charge = context.charge(f"search.{depth}")
        if fixture is not None and isinstance(fixture.body, dict):
            body = dict(fixture.body)
        else:
            body = self._search_body(query, str(depth), str(topic), count, request)
        return _finish(context, body, request, charge.credits)

    def _search_body(
        self, query: str, depth: str, topic: str, count: int, request: dict[str, Any]
    ) -> dict[str, Any]:
        hits = content.search_hits(
            query,
            count,
            include_domains=list(request.get("include_domains") or []),
            exclude_domains=list(request.get("exclude_domains") or []),
        )
        answer_mode = _wants(request.get("include_answer"), "basic", "advanced")
        answer = None
        if answer_mode is not None:
            answer = content.answer(query)
            if answer_mode == "advanced":
                answer = f"{answer} {content.answer(query + ' details')}"
        body: dict[str, Any] = {
            "query": query,
            "follow_up_questions": None,
            "answer": answer,
            "images": self._top_images(hits, request),
            "results": [
                self._result(query, index, hit, topic, request) for index, hit in enumerate(hits)
            ],
            "response_time": _response_time(depth, query),
        }
        if request.get("auto_parameters") is True:
            body["auto_parameters"] = {"topic": topic, "search_depth": depth}
        return body

    @staticmethod
    def _top_images(hits: list[content.SearchHit], request: dict[str, Any]) -> list[Any]:
        if request.get("include_images") is not True:
            return []
        images: list[Any] = []
        for hit in hits[:5]:
            url = content.image_urls(hit.domain, 1, "top", hit.url)[0]
            if request.get("include_image_descriptions") is True:
                images.append({"url": url, "title": hit.title, "description": hit.snippet})
            else:
                images.append(url)
        return images

    @staticmethod
    def _result(
        query: str, index: int, hit: content.SearchHit, topic: str, request: dict[str, Any]
    ) -> dict[str, Any]:
        page = content.page(hit.url, hit.title)
        snippet = hit.snippet
        chunks = request.get("chunks_per_source")
        if request.get("search_depth") == "advanced" and isinstance(chunks, int) and chunks > 1:
            snippet = " [...] ".join([snippet, *page.text.split("\n")[2 : 2 + chunks - 1]])
        item: dict[str, Any] = {
            "url": hit.url,
            "title": hit.title,
            "content": snippet,
            "score": hit.score,
        }
        if topic == "news" or request.get("include_published_date") is True:
            item["published_date"] = format_datetime(hit.published, usegmt=True)
        raw_mode = _wants(request.get("include_raw_content"), "markdown", "text")
        item["raw_content"] = None
        if raw_mode is not None:
            item["raw_content"] = page.markdown if raw_mode == "markdown" else page.text
        if request.get("include_images") is True:
            item["images"] = [
                {"url": url, "description": None, "description_source": "og:image", "score": 10}
                for url in page.images[:1]
            ]
        if request.get("include_favicon") is True:
            item["favicon"] = page.favicon
        item["id"] = f"{content.hex_id(6, query, hit.url)}-{index:02d}"
        return item

    # -------------------------------------------------------------- extract

    async def _extract(self, context: OperationContext) -> MockResponse:
        limited = self._throttle(context)
        if limited is not None:
            return limited
        request = _object_body(context)
        if isinstance(request, MockResponse):
            return request
        checked = self._extract_request(context, request)
        if isinstance(checked, MockResponse):
            return checked
        urls, depth, fmt = checked
        failed = [
            {"url": url, "error": "Validation Error: Invalid URL format"}
            for url in urls
            if not _valid_url(url)
        ]
        valid = [url for url in urls if _valid_url(url)]
        if not valid:
            return context.error(
                ErrorKind.BAD_REQUEST,
                message="All URLs failed validation.",
                details={"failed_results": failed},
            )
        results: list[dict[str, Any]] = []
        for url in valid:
            context.match_key = content.normalize_url(url)
            item = self._extracted(context, url, fmt, request)
            if "error" in item:
                failed.append(item)
            else:
                results.append(item)
        credits = Decimal(0)
        if results:
            charge: Charge = context.charge(f"extract.{depth}", units=len(results))
            credits = charge.credits
        body: dict[str, Any] = {
            "results": results,
            "failed_results": failed,
            "response_time": _response_time(f"extract-{depth}", *valid),
        }
        return _finish(context, body, request, credits)

    @staticmethod
    def _extract_request(
        context: OperationContext, request: dict[str, Any]
    ) -> tuple[list[str], str, str] | MockResponse:
        urls = request.get("urls", _MISSING)
        if urls is _MISSING:
            return _validation("missing", ("urls",), "Field required", request)
        if isinstance(urls, str):
            urls = [urls]
        if not isinstance(urls, list) or not all(isinstance(url, str) for url in urls):
            return _validation("list_type", ("urls",), "Input should be a valid list", urls)
        if not urls:
            return context.error(ErrorKind.BAD_REQUEST, message="No URLs provided.")
        if len(urls) > _MAX_EXTRACT_URLS:
            return context.error(ErrorKind.BAD_REQUEST, message="Max 20 URLs are allowed.")
        depth = request.get("extract_depth") or "basic"
        if depth not in _EXTRACT_DEPTHS:
            return context.error(
                ErrorKind.BAD_REQUEST,
                message="Invalid extract depth. Must be 'basic' or 'advanced'.",
            )
        fmt = request.get("format") or "markdown"
        if fmt not in _FORMATS:
            return context.error(
                ErrorKind.BAD_REQUEST, message="Invalid format. Must be 'markdown' or 'text'."
            )
        return list(urls), str(depth), str(fmt)

    @staticmethod
    def _extracted(
        context: OperationContext, url: str, fmt: str, request: dict[str, Any]
    ) -> dict[str, Any]:
        """Return one success item or one ``{"url", "error"}`` failure."""

        fixture = context.fixture(content.normalize_url(url))
        if fixture is not None and isinstance(fixture.body, dict):
            saved = fixture.body
            if isinstance(saved.get("results"), list):
                match = next((r for r in saved["results"] if r.get("url") == url), None)
                if match is not None:
                    return dict(match)
            elif "raw_content" in saved or "error" in saved:
                return {**saved, "url": url}
        host = (urlsplit(url).hostname or "").lower()
        if host.split(".")[0] == "blocked":
            return {"url": url, "error": "Failed to fetch url: 403 Forbidden"}
        if host.endswith(".invalid"):
            return {"url": url, "error": "Failed to fetch url"}
        page = content.page(url)
        item: dict[str, Any] = {
            "url": url,
            "title": page.title,
            "raw_content": page.markdown if fmt == "markdown" else page.text,
            "images": list(page.images) if request.get("include_images") is True else [],
        }
        if request.get("include_favicon") is True:
            item["favicon"] = page.favicon
        return item

    # ---------------------------------------------------------------- usage

    async def _usage(self, context: OperationContext) -> MockResponse:
        principal = context.principal
        account, key = principal.account, principal.key
        if account is None or key is None:
            return context.error(ErrorKind.AUTH_INVALID, missing_key=True)
        limited = self._throttle(context)
        if limited is not None:
            return limited
        store = context.store
        since = account.period_start
        per_account = store.usage_by_operation(self.name, account_id=account.id, since=since)
        per_key = store.usage_by_operation(
            self.name, account_id=account.id, key_label=key.label, since=since
        )

        def kinds(totals: dict[str, Decimal]) -> dict[str, int | float]:
            sums = {kind: Decimal(0) for kind in ("search", "crawl", "extract", "map", "research")}
            for operation, credits in totals.items():
                prefix = operation.split(".")[0]
                if prefix in sums:
                    sums[prefix] += credits
            return {f"{kind}_usage": _number(value) for kind, value in sums.items()}

        key_limit = key.credit_limit
        plan_limit = account.credit_limit
        if account.funding == "postpaid":
            cap = account.overage_limit
            paygo_usage: Any = _number(account.overage_used)
            paygo_limit: Any = None if cap is None else _number(cap)
        else:
            paygo_usage = account.attributes.get("paygo_usage", 0)
            paygo_limit = account.attributes.get("paygo_limit")
        body = {
            "key": {
                "usage": _number(key.credits_used),
                "limit": None if key_limit is None else _number(key_limit),
                **kinds(per_key),
            },
            "account": {
                "current_plan": account.plan,
                "plan_usage": _number(account.credits_used),
                "plan_limit": None if plan_limit is None else _number(plan_limit),
                **kinds(per_account),
                "paygo_usage": paygo_usage,
                "paygo_limit": paygo_limit,
            },
        }
        return MockResponse(status=200, body=body)


PLUGIN = TavilyPlugin()
