"""Brave Search on ``api.search.brave.com``: ``GET /res/v1/web/search`` and ``/res/v1/llm/context``.

Formats follow the live recordings of 2026-11-17 (``tests/contract/recordings/brave``)
and the official API reference:

- Authentication is the raw key in ``X-Subscription-Token``. Brave sells
  separate plans with separate keys: a **Search** key (scope ``search``) serves
  both endpoints; an **Answers** key (scope ``answers``) gets 400
  ``OPTION_NOT_IN_PLAN``. A wrong key is 422 ``SUBSCRIPTION_TOKEN_INVALID`` and a
  missing key is 422 ``VALIDATION`` on the header, both from the edge layer
  (no ``error.id`` or ``time``). There is no keyless mode.
- Every success carries ``X-RateLimit-Limit``, ``-Policy``, ``-Remaining``, and
  ``-Reset`` as ``<per second>, <per month>`` pairs, derived from the mock state:
  the burst limit is the account attribute ``rate_per_second`` (Search 50) and
  the burst remaining counts the account's billed calls of the last second
  (a sliding window shared by all keys of the plan). The monthly element is
  the account credit limit in requests, where **0 means unlimited** (then the
  monthly remaining is 0 too, as live). The resets are seconds from now, not
  timestamps; the policy window is 2592000 seconds.
- Each success costs 1 credit (one request, $0.005). The seeded plans have no
  monthly cap, as the recorded account; ``credits set brave <n>`` gives one.
  A spent monthly cap is 429 ``QUOTA_LIMITED``; more than ``rate_per_second``
  calls in one second is 429 ``RATE_LIMITED`` with ``Retry-After: 1``.
- Validation errors are 422 ``VALIDATION`` with pydantic items in
  ``error.meta.errors``.

Unverified (no live sample): the revoked-key answer (rendered as a wrong
key), every 429 and 402 body (``meta`` is a guess), the prepaid-exhaustion
status (a ``quota_exhausted`` fault with status 402 or scope ``credits`` gives
402 ``CREDIT_EXHAUSTED``; scope ``spend_cap`` gives 429 ``USAGE_LIMIT_EXCEEDED``),
and outage bodies (502/503/504 use the AWS load balancer HTML page). An
Answers key on Web Search is assumed to fail like it does on LLM Context.
"""

import base64
import hashlib
import random
import re
import uuid
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, ClassVar, Final
from urllib.parse import urlsplit

from starlette.datastructures import QueryParams
from starlette.requests import Request

from polyweb_provider_mock import content
from polyweb_provider_mock.models import (
    Account,
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
from polyweb_provider_mock.store import MockStore, QuotaExhausted

__all__ = ["PLUGIN", "BravePlugin"]

_SEARCH_SCOPE: Final = frozenset({"search"})
_MONTH_WINDOW: Final = 2_592_000
_DEFAULT_RATE: Final = 50
#: Private ``ErrorContext.details`` key that carries ledger-derived headers.
_HEADERS: Final = "_headers"

_SUCCESS_HEADERS: Final = {
    "vary": "Accept-Encoding, Sec-Fetch-Dest, Sec-Fetch-Mode, Sec-Fetch-Site, Sec-Fetch-User",
    "x-content-type-options": "nosniff",
    "referrer-policy": "strict-origin-when-cross-origin",
    "strict-transport-security": "max-age=31536000; includeSubDomains; preload",
    "x-download-options": "noopen",
    "x-frame-options": "SAMEORIGIN",
    "x-xss-protection": "1; mode=block",
}
_ELB_PAGES: Final = {
    502: "502 Bad Gateway",
    503: "503 Service Temporarily Unavailable",
    504: "504 Gateway Time-out",
}

_TRUE: Final = frozenset({"1", "on", "t", "true", "y", "yes"})
_FALSE: Final = frozenset({"0", "off", "f", "false", "n", "no"})
_VERTICALS: Final = ("discussions", "faq", "infobox", "videos", "web")

#: Parameter rules: ``(kind, rule)`` with kind ``query``, ``str``, ``int``,
#: ``bool``, or ``enum``; ``rule`` is an inclusive range or the enum values.
_Spec = tuple[str, Any]
_COMMON: Final[dict[str, _Spec]] = {
    "q": ("query", None),
    "country": ("str", None),
    "search_lang": ("str", None),
}
_WEB_PARAMS: Final[dict[str, _Spec]] = {
    **_COMMON,
    "ui_lang": ("str", None),
    "count": ("int", (1, 20)),
    "offset": ("int", (0, 9)),
    "safesearch": ("enum", ("off", "moderate", "strict")),
    "spellcheck": ("bool", None),
    "freshness": ("str", None),
    "text_decorations": ("bool", None),
    "result_filter": ("str", None),
    "units": ("enum", ("metric", "imperial")),
    "goggles_id": ("str", None),
    "goggles": ("str", None),
    "extra_snippets": ("bool", None),
    "summary": ("bool", None),
    "enable_rich_callback": ("bool", None),
    "include_fetch_metadata": ("bool", None),
    "operators": ("bool", None),
    "operators_fallback": ("bool", None),
}
_CONTEXT_PARAMS: Final[dict[str, _Spec]] = {
    **_COMMON,
    "count": ("int", (1, 50)),
    "safesearch": ("enum", ("off", "moderate", "strict")),
    "spellcheck": ("bool", None),
    "operators": ("bool", None),
    "operators_fallback": ("bool", None),
    "maximum_number_of_urls": ("int", (1, 50)),
    "maximum_number_of_tokens": ("int", (1024, 32768)),
    "maximum_number_of_snippets": ("int", (1, 256)),
    "maximum_number_of_tokens_per_url": ("int", (512, 8192)),
    "maximum_number_of_snippets_per_url": ("int", (1, 100)),
    "context_threshold_mode": ("enum", ("disabled", "strict", "lenient", "balanced")),
    "goggles": ("str", None),
    "freshness": ("str", None),
    "enable_local": ("bool", None),
    "enable_source_metadata": ("bool", None),
}
#: The parsed defaults that a 422 for a missing ``q`` echoes as its ``input``.
_WEB_DEFAULTS: Final[dict[str, Any]] = {
    "country": "US",
    "search_lang": "en",
    "ui_lang": "en-US",
    "count": 20,
    "offset": 0,
    "safesearch": "moderate",
    "spellcheck": True,
    "freshness": "",
    "text_decorations": True,
    "snippet_answer": True,
    "poi_cluster": True,
    "extract_icons": False,
    "disable_top_stories": False,
    "enable_rich_callback": False,
    "include_fetch_metadata": False,
    "operators": True,
    "operators_fallback": False,
    "enable_ads": False,
}
_CONTEXT_DEFAULTS: Final[dict[str, Any]] = {
    "country": "US",
    "search_lang": "en",
    "count": 20,
    "spellcheck": True,
    "operators": True,
    "operators_fallback": True,
    "maximum_number_of_tokens": 8192,
    "freshness": "",
    "enable_source_metadata": False,
}


# ----------------------------------------------------------------- params


def _range_error(name: str, raw: str, value: int, low: int, high: int) -> dict[str, Any] | None:
    loc = ["query", name]
    if value < low:
        return {
            "type": "greater_than_equal",
            "loc": loc,
            "msg": f"Input should be greater than or equal to {low}",
            "input": raw,
            "ctx": {"ge": low},
        }
    if value > high:
        return {
            "type": "less_than_equal",
            "loc": loc,
            "msg": f"Input should be less than or equal to {high}",
            "input": raw,
            "ctx": {"le": high},
        }
    return None


def _convert(name: str, kind: str, rule: Any, raw: str) -> tuple[Any, dict[str, Any] | None]:
    """Parse one query value as Brave's pydantic models do; return value and error."""

    loc = ["query", name]
    if kind == "int":
        try:
            value = int(raw.strip())
        except ValueError:
            message = "Input should be a valid integer, unable to parse string as an integer"
            return None, {"type": "int_parsing", "loc": loc, "msg": message, "input": raw}
        return value, _range_error(name, raw, value, *rule)
    if kind == "bool":
        lowered = raw.strip().lower()
        if lowered in _TRUE | _FALSE:
            return lowered in _TRUE, None
        message = "Input should be a valid boolean, unable to interpret input"
        return None, {"type": "bool_parsing", "loc": loc, "msg": message, "input": raw}
    if kind == "enum" and raw not in rule:
        quoted = [f"'{item}'" for item in rule]
        expected = f"{', '.join(quoted[:-1])} or {quoted[-1]}"
        error = {
            "type": "enum",
            "loc": loc,
            "msg": f"Input should be {expected}",
            "input": raw,
            "ctx": {"expected": expected},
        }
        return None, error
    if kind == "query" and not raw.strip():
        error = {
            "type": "string_too_short",
            "loc": loc,
            "msg": "String should have at least 1 character",
            "input": raw,
            "ctx": {"min_length": 1},
        }
        return None, error
    if kind == "query" and len(raw) > 600:
        error = {
            "type": "string_too_long",
            "loc": loc,
            "msg": "String should have at most 600 characters",
            "input": raw,
            "ctx": {"max_length": 600},
        }
        return None, error
    return raw, None


def _parse(
    params: QueryParams, specs: Mapping[str, _Spec], defaults: Mapping[str, Any]
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    values: dict[str, Any] = {}
    errors: list[dict[str, Any]] = []
    if "q" not in params:
        given = {name: params[name] for name in specs if name in params}
        errors.append(
            {
                "type": "missing",
                "loc": ["query", "q"],
                "msg": "Field required",
                "input": {**defaults, **given},
            }
        )
    for name, (kind, rule) in specs.items():
        if name not in params:
            continue
        value, error = _convert(name, kind, rule, params[name])
        if error is not None:
            errors.append(error)
        else:
            values[name] = value
    if "goggles" in params:
        values["goggles"] = params.getlist("goggles")
    return values, errors


# ---------------------------------------------------------------- content


def _proxied(url: str, fit: str) -> str:
    """Return the ``imgs.search.brave.com`` proxy URL of an image."""

    signature = base64.urlsafe_b64encode(hashlib.sha256(url.encode()).digest()).decode()
    encoded = base64.urlsafe_b64encode(url.encode()).decode().rstrip("=")
    path = "/".join(encoded[index : index + 16] for index in range(0, len(encoded), 16))
    return f"https://imgs.search.brave.com/{signature.rstrip('=')}/rs:{fit}/g:ce/{path}"


def _favicon(host: str) -> str:
    digest = hashlib.sha256(host.encode()).hexdigest()
    return _proxied(f"http://favicons.search.brave.com/icons/{digest}/{host}/", "fit:32:32:1:0")


def _meta_url(url: str) -> dict[str, str]:
    parts = urlsplit(url)
    host = parts.hostname or ""
    segments = [segment for segment in parts.path.split("/") if segment]
    return {
        "scheme": parts.scheme,
        "netloc": host.removeprefix("www."),
        "hostname": host,
        "favicon": _favicon(host),
        "path": "  ".join(f"\u203a {segment}" for segment in segments),
    }


def _site_name(host: str) -> str:
    labels = host.removeprefix("www.").split(".")
    return (labels[-2] if len(labels) > 1 else labels[0]).capitalize()


def _age(published: datetime, now: datetime) -> str:
    delta = now - published
    if delta < timedelta(days=1):
        return f"{max(1, int(delta.total_seconds() // 3600))} hours ago"
    if delta < timedelta(days=7):
        return f"{delta.days} days ago"
    return f"{published:%B} {published.day}, {published.year}"


def _published(url: str) -> datetime:
    page = content.page(url)
    return page.published + timedelta(seconds=content.rng("brave-age", url).randrange(86_400))


def _fetched(url: str, now: datetime) -> int:
    return int(now.timestamp()) - content.rng("brave-fetched", url).randrange(3_600, 400_000)


def _decorate(text: str, query: str, enabled: bool) -> str:
    """Wrap the query terms in ``<strong>``, as ``text_decorations`` does."""

    if not enabled:
        return text
    for word in sorted({w for w in re.findall(r"[\w'-]+", query) if len(w) > 2}, key=len)[::-1]:
        text = re.sub(rf"(?i)\b({re.escape(word)})\b", r"<strong>\1</strong>", text, count=1)
    return text


def _paragraphs(page: content.Page) -> list[str]:
    lines = [line for line in page.text.split("\n")[1:] if len(line) > 60]
    return lines or [page.text]


class BravePlugin(ProviderPlugin):
    """Brave Web Search and LLM Context."""

    name: ClassVar[str] = "brave"
    hosts: ClassVar[frozenset[str]] = frozenset({"api.search.brave.com"})
    key_format: ClassVar[KeyFormat] = KeyFormat(prefix="BSA", body_length=28)

    def operations(self) -> Sequence[Operation]:
        return (
            Operation("web_search", "GET", "/res/v1/web/search", self._web, scopes=_SEARCH_SCOPE),
            Operation(
                "llm_context", "GET", "/res/v1/llm/context", self._context, scopes=_SEARCH_SCOPE
            ),
        )

    def credentials(self, request: Request) -> Credentials:
        return Credentials(key=header_value(request, "x-subscription-token"))

    def default_seed(self) -> ProviderSeed:
        return ProviderSeed(
            accounts=(
                AccountSeed(
                    id="brave-search",
                    plan="Search",
                    credit_limit=None,
                    attributes={"rate_per_second": _DEFAULT_RATE, "free_credits_usd": 5},
                ),
                AccountSeed(
                    id="brave-answers",
                    plan="Answers",
                    credit_limit=None,
                    attributes={"rate_per_second": 2, "free_credits_usd": 5},
                ),
            ),
            keys=(
                KeySeed(
                    label="search",
                    account_id="brave-search",
                    env_var="POLYWEB_BRAVE_SEARCH_API_KEY",
                    scopes=("search",),
                ),
                KeySeed(
                    label="answers",
                    account_id="brave-answers",
                    env_var="POLYWEB_BRAVE_ANSWERS_API_KEY",
                    scopes=("answers",),
                ),
            ),
        )

    def default_pricing(self) -> Sequence[PriceRule]:
        return tuple(
            PriceRule(
                provider=self.name,
                operation=operation,
                credits_per_unit=Decimal(1),
                usd_per_unit=Decimal("0.005"),
            )
            for operation in ("web_search", "llm_context")
        )

    # --------------------------------------------------------------- errors

    def error(self, kind: ErrorKind, context: ErrorContext) -> MockResponse:
        status = context.status
        headers = dict(context.details.get(_HEADERS, {}))
        if kind in {ErrorKind.AUTH_INVALID, ErrorKind.AUTH_REVOKED}:
            return self._edge_auth(context)
        if kind is ErrorKind.FORBIDDEN:
            status = status or 400
            code = "OPTION_NOT_IN_PLAN" if status == 400 else "RESOURCE_NOT_ALLOWED"
            detail = context.message or "The option is not included in the plan."
            return self._app_error(status, code, detail, {"component": "authentication"})
        if kind is ErrorKind.BAD_REQUEST:
            errors = list(context.details.get("errors", []))
            detail = context.message or "Unable to validate request parameter(s)"
            return self._app_error(status or 422, "VALIDATION", detail, {"errors": errors})
        if kind is ErrorKind.RATE_LIMITED:
            if context.retry_after_header:
                headers["Retry-After"] = str(context.retry_after or 1)
            detail = context.message or "Request rate limit exceeded for plan."
            meta = {"component": "rate_limiter"}
            return self._app_error(status or 429, "RATE_LIMITED", detail, meta, headers)
        if kind is ErrorKind.QUOTA_EXHAUSTED:
            return self._quota_error(context, headers)
        status = status or (503 if kind is ErrorKind.SERVICE_UNAVAILABLE else 500)
        if status in _ELB_PAGES:
            title = _ELB_PAGES[status]
            page = (
                f"<html>\r\n<head><title>{title}</title></head>\r\n<body>\r\n"
                f"<center><h1>{title}</h1></center>\r\n</body>\r\n</html>\r\n"
            )
            return MockResponse(status, page.encode(), media_type="text/html")
        detail = context.message or "An internal error occurred. Please try again later."
        return self._app_error(status, "INTERNAL", detail, None)

    def _quota_error(self, context: ErrorContext, headers: dict[str, str]) -> MockResponse:
        if context.status == 402 or context.scope in {"credits", "prepaid"}:
            detail = "Your prepaid credits are exhausted. Add funds to continue."
            meta = {"component": "billing"}
            return self._app_error(context.status or 402, "CREDIT_EXHAUSTED", detail, meta, headers)
        if context.scope in {"spend_cap", "usage"}:
            detail = "The monthly spending limit of your plan has been reached."
            meta = {"component": "billing"}
            return self._app_error(
                context.status or 429, "USAGE_LIMIT_EXCEEDED", detail, meta, headers
            )
        detail = context.message or "The monthly request quota of your plan has been exceeded."
        meta = {"component": "rate_limiter"}
        return self._app_error(context.status or 429, "QUOTA_LIMITED", detail, meta, headers)

    @staticmethod
    def _edge_auth(context: ErrorContext) -> MockResponse:
        """Return the edge layer's 422 for a missing or unknown subscription token."""

        status = context.status or 422
        if context.missing_key:
            meta: dict[str, Any] = {
                "errors": [
                    {
                        "input": None,
                        "loc": ["header", "x-subscription-token"],
                        "msg": "Field required",
                        "type": "missing",
                    }
                ]
            }
            error = {
                "code": "VALIDATION",
                "detail": "Unable to validate request parameter(s)",
                "meta": meta,
                "status": status,
            }
        else:
            error = {
                "code": "SUBSCRIPTION_TOKEN_INVALID",
                "detail": context.message or "The provided subscription token is invalid.",
                "meta": {"component": "authentication"},
                "status": status,
            }
        return MockResponse(status, {"error": error, "type": "ErrorResponse"})

    @staticmethod
    def _app_error(
        status: int,
        code: str,
        detail: str,
        meta: dict[str, Any] | None,
        headers: dict[str, str] | None = None,
    ) -> MockResponse:
        """Return the application ``ErrorResponse`` envelope with its id and time."""

        body = {
            "type": "ErrorResponse",
            "error": {
                "id": str(uuid.uuid4()),
                "status": status,
                "detail": detail,
                "meta": meta,
                "code": code,
            },
            "time": int(datetime.now(UTC).timestamp()),
        }
        dur = random.uniform(2.0, 15.0)
        return MockResponse(
            status,
            body,
            {
                **(headers or {}),
                "server-timing": f"search-roundtrip;dur={dur:.3f}",
                "vary": "Accept-Encoding",
            },
        )

    def drop_required_field(self, operation: str, body: Any) -> Any:
        victim = "grounding" if operation == "llm_context" else "web"
        if isinstance(body, dict) and victim in body:
            return {key: value for key, value in body.items() if key != victim}
        return super().drop_required_field(operation, body)

    # ---------------------------------------------------------- rate state

    @staticmethod
    def _burst_used(store: MockStore, account: Account, now: datetime) -> int:
        """Return the account's billed calls in the sliding one-second window."""

        rate = int(account.attributes.get("rate_per_second", _DEFAULT_RATE))
        since = now - timedelta(seconds=1)
        entries = store.ledger("brave", limit=max(4 * rate, 64))
        return sum(1 for entry in entries if entry.account_id == account.id and entry.ts > since)

    def _rate_headers(self, store: MockStore, account_id: str) -> dict[str, str]:
        """Return the four ``X-RateLimit-*`` pairs from the account and its ledger."""

        account = store.account(self.name, account_id)
        now = store.now()
        rate = int(account.attributes.get("rate_per_second", _DEFAULT_RATE))
        burst_left = max(0, rate - self._burst_used(store, account, now))
        monthly = 0 if account.credit_limit is None else int(account.credit_limit)
        left = 0 if account.remaining is None else int(account.remaining)
        reset = account.period_reset
        monthly_reset = 0 if reset is None else max(0, int((reset - now).total_seconds()))
        return {
            "X-RateLimit-Limit": f"{rate}, {monthly}",
            "X-RateLimit-Policy": f"{rate};w=1, {monthly};w={_MONTH_WINDOW}",
            "X-RateLimit-Remaining": f"{burst_left}, {left}",
            "X-RateLimit-Reset": f"1, {monthly_reset}",
        }

    def _billed(self, context: OperationContext) -> MockResponse | dict[str, str]:
        """Check the burst window and debit the call; return the rate headers or an error."""

        account = context.principal.account
        if account is None:
            return context.error(ErrorKind.AUTH_INVALID, missing_key=True)
        store = context.store
        rate = int(account.attributes.get("rate_per_second", _DEFAULT_RATE))
        if self._burst_used(store, account, store.now()) >= rate:
            headers = self._rate_headers(store, account.id)
            return context.error(ErrorKind.RATE_LIMITED, retry_after=1, details={_HEADERS: headers})
        try:
            context.charge(context.operation.name)
        except QuotaExhausted as exc:
            headers = self._rate_headers(store, account.id)
            return context.error(
                ErrorKind.QUOTA_EXHAUSTED, scope=exc.scope, details={_HEADERS: headers}
            )
        return self._rate_headers(store, account.id)

    def _validated(
        self,
        context: OperationContext,
        specs: Mapping[str, _Spec],
        defaults: Mapping[str, Any],
    ) -> dict[str, Any] | MockResponse:
        values, errors = _parse(context.request.query_params, specs, defaults)
        if errors:
            return context.error(ErrorKind.BAD_REQUEST, details={"errors": errors})
        return values

    def _success(self, body: Any, headers: dict[str, str], query: str) -> MockResponse:
        dur = 60.0 + content.rng("brave-roundtrip", query).random() * 800.0
        return MockResponse(
            200,
            body,
            {**headers, "server-timing": f"search-roundtrip;dur={dur:.3f}", **_SUCCESS_HEADERS},
        )

    async def _serve(
        self,
        context: OperationContext,
        specs: Mapping[str, _Spec],
        defaults: Mapping[str, Any],
    ) -> tuple[dict[str, Any], dict[str, str], Any] | MockResponse:
        """Validate, apply a fixture, and bill; return params, headers, and a fixture body."""

        values = self._validated(context, specs, defaults)
        if isinstance(values, MockResponse):
            return values
        context.match_key = content.normalize_query(values["q"])
        fixture = context.fixture(context.match_key)
        if fixture is not None and fixture.status != 200:
            return MockResponse(fixture.status, fixture.body)
        billed = self._billed(context)
        if isinstance(billed, MockResponse):
            return billed
        return values, billed, None if fixture is None else fixture.body

    # ---------------------------------------------------------- web search

    async def _web(self, context: OperationContext) -> MockResponse:
        served = await self._serve(context, _WEB_PARAMS, _WEB_DEFAULTS)
        if isinstance(served, MockResponse):
            return served
        params, headers, saved = served
        query = params["q"]
        body = saved if isinstance(saved, dict) else self._web_body(context, params)
        return self._success(body, headers, query)

    def _web_body(self, context: OperationContext, params: dict[str, Any]) -> dict[str, Any]:
        query: str = params["q"]
        count: int = params.get("count", 20)
        offset: int = params.get("offset", 0)
        now = context.store.now()
        decorate = params.get("text_decorations", True)
        fetch_meta = params.get("include_fetch_metadata", False)
        hits = content.search_hits(query, count * (offset + 1))[count * offset :]
        wanted = set(_VERTICALS)
        if params.get("result_filter"):
            wanted &= {item.strip() for item in str(params["result_filter"]).split(",")}
        verticals: dict[str, Any] = {}
        if "discussions" in wanted:
            verticals["discussions"] = self._discussions(query, now, decorate, fetch_meta)
        if "faq" in wanted:
            verticals["faq"] = self._faq(query, decorate)
        if "infobox" in wanted:
            verticals["infobox"] = self._infobox(query)
        results = [self._web_result(hit, query, now, params, decorate, fetch_meta) for hit in hits]
        body: dict[str, Any] = {
            "type": "search",
            "query": self._query_block(query, params, context.request, more=len(hits) == count),
            **{
                key: verticals[key] for key in ("discussions", "faq", "infobox") if key in verticals
            },
            "mixed": self._mixed(len(results) if "web" in wanted else 0, verticals, wanted),
        }
        if "videos" in wanted:
            body["videos"] = self._videos(query, now, fetch_meta)
        if "web" in wanted:
            body["web"] = {"type": "search", "results": results, "family_friendly": True}
        if params.get("summary") is True:
            body["summarizer"] = {
                "type": "summarizer",
                "key": base64.urlsafe_b64encode(
                    f'{{"query": "{query}", "country": "us", "language": "en"}}'.encode()
                ).decode(),
            }
        return body

    @staticmethod
    def _query_block(
        query: str, params: dict[str, Any], request: Request, *, more: bool
    ) -> dict[str, Any]:
        stem = " ".join(query.lower().split())
        suffixes = ("examples", "meaning", "definition", "vs alternatives", "tutorial", "list")
        return {
            "original": query,
            "show_strict_warning": False,
            "is_navigational": False,
            "is_news_breaking": False,
            "spellcheck_off": not params.get("spellcheck", True),
            "country": str(params.get("country", "us")).lower(),
            "bad_results": False,
            "should_fallback": False,
            "postal_code": request.headers.get("x-loc-postal-code", ""),
            "city": request.headers.get("x-loc-city", ""),
            "header_country": request.headers.get("x-loc-country", ""),
            "more_results_available": more,
            "state": request.headers.get("x-loc-state", ""),
            "related_queries": [f"{stem} {suffix}" for suffix in suffixes],
        }

    @staticmethod
    def _mixed(web: int, verticals: dict[str, Any], wanted: set[str]) -> dict[str, Any]:
        main: list[dict[str, Any]] = [{"type": "web", "index": i, "all": False} for i in range(web)]
        if "infobox" in verticals:
            main.insert(min(1, len(main)), {"type": "infobox", "index": 0, "all": False})
        position = min(3, len(main))
        for name in ("discussions", "faq", "videos"):
            if name in verticals or (name == "videos" and name in wanted):
                main.insert(position, {"type": name, "all": True})
                position += 1
        return {"type": "mixed", "main": main, "top": [], "side": []}

    @staticmethod
    def _web_result(
        hit: content.SearchHit,
        query: str,
        now: datetime,
        params: dict[str, Any],
        decorate: bool,
        fetch_meta: bool,
    ) -> dict[str, Any]:
        host = hit.domain
        published = _published(hit.url)
        result: dict[str, Any] = {
            "title": hit.title,
            "url": hit.url,
            "is_source_local": False,
            "is_source_both": False,
            "description": _decorate(hit.snippet, query, decorate),
            "page_age": published.strftime("%Y-%m-%dT%H:%M:%S"),
        }
        if fetch_meta:
            result["fetched_content_timestamp"] = _fetched(hit.url, now)
        result.update(
            {
                "profile": {
                    "name": _site_name(host),
                    "url": hit.url,
                    "long_name": host.removeprefix("www."),
                    "img": _favicon(host),
                },
                "language": "en",
                "family_friendly": True,
                "type": "search_result",
                "subtype": "generic",
                "is_live": False,
                "meta_url": _meta_url(hit.url),
                "age": _age(published, now),
            }
        )
        if params.get("extra_snippets") is True:
            result["extra_snippets"] = _paragraphs(content.page(hit.url, hit.title))[:5]
        return result

    @staticmethod
    def _discussions(query: str, now: datetime, decorate: bool, fetch_meta: bool) -> dict[str, Any]:
        results = []
        for index, forum in enumerate(("webdev", "programming", "learnprogramming")):
            topic = content.answer(f"{query} {forum}")
            title = f"{query} - what do you all use?"
            slug = re.sub(r"[^a-z0-9]+", "_", query.lower()).strip("_") or "thread"
            thread = content.hex_id(6, query, index)
            url = f"https://www.reddit.com/r/{forum}/comments/{thread}/{slug}/"
            published = _published(url)
            item: dict[str, Any] = {
                "title": title,
                "url": url,
                "is_source_local": False,
                "is_source_both": False,
                "description": _decorate(topic, query, decorate),
            }
            if fetch_meta:
                item["fetched_content_timestamp"] = _fetched(url, now)
            generator = content.rng("brave-discussion", url)
            item.update(
                {
                    "language": "en",
                    "family_friendly": True,
                    "type": "discussion",
                    "subtype": "generic",
                    "is_live": False,
                    "meta_url": _meta_url(url),
                    "age": _age(published, now),
                    "data": {
                        "forum_name": f"r/{forum}",
                        "num_answers": generator.randrange(3, 120),
                        "score": str(generator.randrange(5, 900)),
                        "title": title,
                        "question": f"<p>{topic}</p>",
                        "top_comment": content.answer(f"{query} comment {index}"),
                    },
                }
            )
            results.append(item)
        return {"type": "search", "results": results, "mutated_by_goggles": False}

    @staticmethod
    def _faq(query: str, decorate: bool) -> dict[str, Any]:
        results = []
        for index, lead in enumerate(("What is", "How does one use", "Why does")):
            hit = content.search_hits(f"{query} faq", 3)[index]
            results.append(
                {
                    "question": f"{lead} {query}?",
                    "answer": _decorate(content.answer(f"{query} {lead}"), query, decorate),
                    "title": hit.title,
                    "url": hit.url,
                    "meta_url": _meta_url(hit.url),
                }
            )
        return {"type": "faq", "results": results}

    @staticmethod
    def _infobox(query: str) -> dict[str, Any]:
        title = " ".join(word.capitalize() for word in query.split()) or "Search"
        slug = re.sub(r"\s+", "_", title)
        url = f"https://en.wikipedia.org/wiki/{slug}"
        image = (
            f"https://upload.wikimedia.org/wikipedia/commons/{content.hex_id(1, query)}/{slug}.png"
        )
        generator = content.rng("brave-infobox", query)
        return {
            "type": "graph",
            "results": [
                {
                    "title": title,
                    "url": url,
                    "is_source_local": False,
                    "is_source_both": False,
                    "description": content.answer(query).split(".")[0].lower(),
                    "family_friendly": True,
                    "type": "infobox",
                    "position": 1 + generator.randrange(3),
                    "long_desc": content.answer(f"{query} long description"),
                    "attributes": [
                        ["Type", "Topic"],
                        ["Available in", "English"],
                        ["First described", str(1990 + generator.randrange(30))],
                    ],
                    "profiles": [
                        {
                            "name": "Wikipedia",
                            "url": url,
                            "long_name": "en.wikipedia.org",
                            "img": _favicon("en.wikipedia.org"),
                        }
                    ],
                    "website_url": content.search_hits(query, 1)[0].url,
                    "ratings": [],
                    "providers": [
                        {
                            "type": "external",
                            "name": "Wikipedia",
                            "url": url,
                            "img": _favicon("en.wikipedia.org"),
                        }
                    ],
                    "images": [
                        {
                            "src": _proxied(image, "fit:500:0:0:0"),
                            "alt": f"{title} - Wikipedia",
                            "original": image,
                            "logo": False,
                        }
                    ],
                    "subtype": "generic",
                    "found_in_urls": [url],
                }
            ],
        }

    @staticmethod
    def _videos(query: str, now: datetime, fetch_meta: bool) -> dict[str, Any]:
        results = []
        for index in range(3):
            video_id = content.hex_id(11, query, "video", index)
            url = f"https://www.youtube.com/watch?v={video_id}"
            published = _published(url)
            generator = content.rng("brave-video", url)
            thumbnail = f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg"
            item: dict[str, Any] = {
                "type": "video_result",
                "url": url,
                "title": f"{query.title()} explained in {3 + index * 4} minutes",
                "description": content.answer(f"{query} video {index}"),
                "age": _age(published, now),
                "page_age": published.strftime("%Y-%m-%dT%H:%M:%S"),
            }
            if fetch_meta:
                item["fetched_content_timestamp"] = _fetched(url, now)
            item["video"] = {
                "duration": f"{3 + index * 4:02d}:{generator.randrange(60):02d}",
                "publisher": "YouTube",
            }
            item["meta_url"] = _meta_url(url)
            item["thumbnail"] = {
                "src": _proxied(thumbnail, "fit:200:200:1:0"),
                "original": thumbnail,
            }
            results.append(item)
        return {"type": "videos", "results": results, "mutated_by_goggles": False}

    # --------------------------------------------------------- llm context

    async def _context(self, context: OperationContext) -> MockResponse:
        served = await self._serve(context, _CONTEXT_PARAMS, _CONTEXT_DEFAULTS)
        if isinstance(served, MockResponse):
            return served
        params, headers, saved = served
        body = saved if isinstance(saved, dict) else self._context_body(context, params)
        return self._success(body, headers, params["q"])

    def _context_body(self, context: OperationContext, params: dict[str, Any]) -> dict[str, Any]:
        query: str = params["q"]
        now = context.store.now()
        urls = min(params.get("count", 20), params.get("maximum_number_of_urls", 20))
        tokens_left = params.get("maximum_number_of_tokens", 8192)
        per_url = params.get("maximum_number_of_tokens_per_url", 4096)
        snippets_cap = params.get("maximum_number_of_snippets_per_url", 100)
        metadata = params.get("enable_source_metadata", False)
        generic: list[dict[str, Any]] = []
        sources: dict[str, Any] = {}
        for hit in content.search_hits(query, urls):
            page = content.page(hit.url, hit.title)
            snippets, used = self._snippets(page, min(per_url, tokens_left), snippets_cap)
            if not snippets:
                break
            tokens_left -= used
            generic.append({"url": hit.url, "title": hit.title, "snippets": snippets})
            sources[hit.url] = self._source(hit.url, hit.title, hit.snippet, now, metadata)
        grounding: dict[str, Any] = {"generic": generic}
        if params.get("enable_local") is True:
            places = self._places(query)
            grounding["poi"] = places[0]
            grounding["map"] = places[1:]
            for place in places:
                sources[place["url"]] = self._source(
                    place["url"], place["title"], place["snippets"][0], now, metadata
                )
        else:
            grounding["map"] = []
        return {"grounding": grounding, "sources": sources}

    @staticmethod
    def _snippets(page: content.Page, budget: int, cap: int) -> tuple[list[str], int]:
        """Return Markdown snippets of a page within a token budget and a count cap."""

        sections = page.markdown.split("\n\n## ")[1:] or [page.markdown]
        snippets: list[str] = []
        used = 0
        for section in sections[:cap]:
            heading, _, text = section.partition("\n\n")
            snippet = f"## {heading}\n{text}" if text else section
            cost = len(snippet.split()) * 4 // 3
            if snippets and used + cost > budget:
                break
            snippets.append(snippet)
            used += cost
        return snippets, used

    @staticmethod
    def _source(
        url: str, title: str, snippet: str, now: datetime, metadata: bool
    ) -> dict[str, Any]:
        host = urlsplit(url).hostname or ""
        published = _published(url)
        source: dict[str, Any] = {
            "title": title,
            "hostname": host,
            "age": [
                f"{published:%A}, {published:%B} {published.day}, {published.year}",
                published.strftime("%Y-%m-%d"),
                f"{max(0, (now - published).days)} days ago",
                published.strftime("%Y-%m-%dT%H:%M:%SZ"),
            ],
        }
        if metadata:
            image = f"https://{host}/images/{content.hex_id(12, url)}.webp"
            source.update(
                {
                    "site_name": _site_name(host),
                    "favicon": _favicon(host),
                    "thumbnail": {"src": _proxied(image, "fit:860:0:0:0"), "original": image},
                    "snippet": snippet,
                    "description": content.answer(url).split(". ")[0] + ".",
                    "fetched_content_timestamp": _fetched(url, now),
                }
            )
        return source

    @staticmethod
    def _places(query: str) -> list[dict[str, Any]]:
        places = []
        for index in range(3):
            name = f"{query.title()} {('Center', 'Studio', 'Hall')[index]}"
            slug = re.sub(r"[^a-z0-9]+", "", name.lower())
            url = f"https://www.{slug}.com/"
            places.append(
                {
                    "name": name,
                    "url": url,
                    "title": f"{name} - Official Site",
                    "snippets": [content.answer(f"{query} place {index}")],
                }
            )
        return places


PLUGIN = BravePlugin()
