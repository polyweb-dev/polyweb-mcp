"""Exa on ``api.exa.ai`` (``POST /search``, ``POST /contents``) and ``admin-api.exa.ai``.

Formats follow the live recordings of 2026-11-17 (``exa-py`` 2.18.1,
``tests/contract/recordings/exa``) and the official API reference:

- Authentication is ``x-api-key: <key>`` (what the SDK sends) or
  ``Authorization: Bearer <key>``. A request without any key gets the
  x402 ``402 X402_PAYMENT_REQUIRED`` payment challenge, with the
  ``payment-required`` and MPP ``www-authenticate`` headers. A wrong or
  revoked key gets ``401 INVALID_API_KEY``.
- Errors use ``{"requestId", "error", "tag"}`` and carry ``x-request-id``.
  Credit exhaustion is 402 ``NO_MORE_CREDITS``; a key budget is
  ``API_KEY_BUDGET_EXCEEDED`` and a team budget (fault scope ``team``) is
  ``TEAM_BUDGET_EXCEEDED``. Rate limits are 429 ``RATE_LIMIT_EXCEEDED``
  with ``Retry-After``; overload is 503 ``SERVICE_OVERLOADED``.
- Billing is in US dollars: the account balance and every price are USD.
  Search costs a base price by ``type`` (up to 10 results), $0.001 per
  extra result, and $0.001 per page summary, reported as
  ``costDollars.search`` and ``costDollars.summary``. Contents costs
  $0.001 per returned page per content type (text, highlights, summary),
  reported per type in ``costDollars.contents``. Failed URLs are free.
- ``GET admin-api.exa.ai/team-management/api-keys/{id}/usage`` needs a
  service key (scope ``team_management``) of the same team. Regular,
  wrong, and missing keys all get ``401 {"error": "Unauthorized"}``. The
  report is built from the usage ledger of the target key.

Free tier and limits:

- Recorded: per-response ``costDollars`` (an estimate); nothing in any
  response reports the remaining balance.
- Documented (exa.ai billing, pricing, rate-limit and error-code pages):
  the team gets $10 of credit every month, reset to $10 on the first day
  of each calendar month with no carry-over (the account's monthly grant,
  ``reset_day`` 1), plus a one-time $10 onboarding bonus that never
  expires (the account's prepaid balance). The prices per 1,000 above.
  Team-wide rate limits: ``/search`` 10 QPS, deep search types 5 QPS,
  ``/contents`` 100 QPS. A key's own budget (``API_KEY_BUDGET_EXCEEDED``)
  and the team budget (``TEAM_BUDGET_EXCEEDED``) apply per billing period,
  so a key budget resets with the month. The seeded ``budgeted`` key has a
  $0.05 budget so that path is reachable without faults.
- Guessed: the spend order. The grant is spent before the bonus (it
  expires; the bonus does not). Rate limits use one-second windows per
  team, are checked after the body validates, and a deep search spends a
  slot in both the ``/search`` and the deep window; ``Retry-After`` is the
  rest of the window.

Synthetic contents targets: a host whose first label is ``blocked`` fails
with ``CRAWL_HTTP_403``, ``timeout`` fails with ``CRAWL_LIVECRAWL_TIMEOUT``,
and a ``notfound`` label or a ``.invalid`` host fails with
``CRAWL_NOT_FOUND``; each failure is a ``statuses`` entry in a 200.

Accuracy gaps (no live evidence): 429, 5xx, budget 402, and revoked-key
bodies follow the documented tags with inferred messages. The ``search``
cost key is ``neural`` as recorded for ``auto``; other types use their own
name. Company ``entities`` (recorded on every result that returns
content) are synthetic.
"""

import base64
import json
import secrets
import uuid
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from functools import cache
from http import HTTPStatus
from importlib import resources
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
from polyweb_provider_mock.providers._exa_firecrawl_common import iso_ms, schema_value
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
from polyweb_provider_mock.store import MockStore
from polyweb_provider_mock.windows import WindowSpec

__all__ = ["PLUGIN", "ExaPlugin"]

_API_HOST: Final = "api.exa.ai"
_ADMIN_HOST: Final = "admin-api.exa.ai"
_API_ONLY: Final = frozenset({_API_HOST})
_SERVICE_SCOPE: Final = "team_management"
_JSON: Final = "application/json; charset=utf-8"
_MISSING: Final[Any] = object()
_MAX_RESULTS: Final = 100
_INCLUDED_RESULTS: Final = 10
_USAGE_LOOKBACK: Final = timedelta(days=180)
_USAGE_DEFAULT: Final = timedelta(days=30)
_MONTHLY_GRANT: Final = Decimal(10)
_ONBOARDING_BONUS: Final = Decimal(10)
_KEY_BUDGET: Final = Decimal("0.05")
#: Team-wide requests per second.
_SEARCH_QPS: Final = 10
_DEEP_QPS: Final = 5
_CONTENTS_QPS: Final = 100

#: Search ``type`` -> priced operation. ``neural``/``keyword`` are legacy names.
_SEARCH_TYPES: Final = {
    "instant": "search.instant",
    "lite": "search.instant",
    "fast": "search.fast",
    "auto": "search.auto",
    "neural": "search.auto",
    "keyword": "search.fast",
    "deep-lite": "search.deep-lite",
    "deep": "search.deep",
    "deep-reasoning": "search.deep-reasoning",
}
_SEARCH_TIMES: Final = {
    "instant": (25.0, 180.0),
    "lite": (25.0, 180.0),
    "fast": (60.0, 450.0),
    "deep-lite": (2500.0, 9000.0),
    "deep": (4000.0, 15000.0),
    "deep-reasoning": (8000.0, 30000.0),
}
_CONTENT_TYPES: Final = ("text", "highlights", "summary")
_PRICES: Final = (
    ("search.instant", "0.004", "request", "Instant Search"),
    ("search.fast", "0.007", "request", "Fast Search"),
    ("search.auto", "0.007", "request", "Neural Search"),
    ("search.deep-lite", "0.012", "request", "Deep Lite Search"),
    ("search.deep", "0.012", "request", "Deep Search"),
    ("search.deep-reasoning", "0.015", "request", "Deep Reasoning Search"),
    ("search.extra_result", "0.001", "result", "Additional Search Results"),
    ("search.summary", "0.001", "page", "AI Page Summary"),
    ("contents.text", "0.001", "page", "Content Retrieval (text)"),
    ("contents.highlights", "0.001", "page", "Content Retrieval (highlights)"),
    ("contents.summary", "0.001", "page", "Content Retrieval (summary)"),
)
_PRICE_NAMES: Final = {operation: name for operation, _, _, name in _PRICES}

_INVALID_KEY: Final = (
    "Invalid API key. Provide a valid key using 'Authorization: Bearer <key>' or "
    "'x-api-key: <key>'. Create a key at https://dashboard.exa.ai/api-keys"
)
_TAGS: Final = {
    ErrorKind.AUTH_INVALID: (401, "INVALID_API_KEY", _INVALID_KEY),
    ErrorKind.AUTH_REVOKED: (401, "INVALID_API_KEY", _INVALID_KEY),
    ErrorKind.FORBIDDEN: (
        403,
        "FEATURE_DISABLED",
        "The requested endpoint, search type, or option is not enabled for your plan.",
    ),
    ErrorKind.BAD_REQUEST: (400, "INVALID_REQUEST_BODY", "Invalid request body"),
    ErrorKind.RATE_LIMITED: (
        429,
        "RATE_LIMIT_EXCEEDED",
        "You have exceeded your rate limit. Please reduce your request rate and retry.",
    ),
    ErrorKind.QUOTA_EXHAUSTED: (
        402,
        "NO_MORE_CREDITS",
        "You have run out of credits. Top up at https://dashboard.exa.ai/home to continue.",
    ),
    ErrorKind.SERVER_ERROR: (500, "INTERNAL_SERVER_ERROR", "Internal server error"),
    ErrorKind.SERVICE_UNAVAILABLE: (
        503,
        "SERVICE_OVERLOADED",
        "Exa is temporarily over capacity. Please retry with exponential backoff.",
    ),
}
_QUOTA_TAGS: Final = {
    "key": (
        "API_KEY_BUDGET_EXCEEDED",
        "This API key has exceeded its spending budget for the current billing period. "
        "Contact your team administrator.",
    ),
    "team": (
        "TEAM_BUDGET_EXCEEDED",
        "Your team has exceeded its spending budget for the current billing period.",
    ),
}
_ADMIN_MESSAGES: Final = {
    ErrorKind.BAD_REQUEST: "Invalid API key ID format.",
    ErrorKind.RATE_LIMITED: "Too many requests",
    ErrorKind.QUOTA_EXHAUSTED: "Payment Required",
    ErrorKind.SERVER_ERROR: "Failed to fetch usage data. Please try again later.",
    ErrorKind.SERVICE_UNAVAILABLE: "Service Unavailable",
}
_EXPOSED: Final = (
    "PAYMENT-REQUIRED,PAYMENT-RESPONSE,payment-required,payment-response,WWW-Authenticate,"
    "Payment-Receipt,x-request-id,x-exa-queued,x-exa-queue-ms,x-exa-region,"
    "x-exa-processing-region,Deprecation,Sunset,Retry-After,X-RateLimit-Scope"
)
_API_HEADERS: Final = {
    "content-security-policy": "frame-ancestors 'self'",
    "cross-origin-opener-policy": "same-origin",
    "cross-origin-resource-policy": "same-origin",
    "origin-agent-cluster": "?1",
    "referrer-policy": "no-referrer",
    "strict-transport-security": "max-age=31536000; includeSubDomains; preload",
    "x-content-type-options": "nosniff",
    "x-dns-prefetch-control": "off",
    "x-download-options": "noopen",
    "x-frame-options": "DENY",
    "x-permitted-cross-domain-policies": "none",
    "x-xss-protection": "0",
    "x-exa-region": "us-west-2",
    "x-exa-processing-region": "us",
    "vary": "Origin",
    "access-control-allow-credentials": "true",
    "access-control-expose-headers": _EXPOSED,
}
_QUEUE_HEADERS: Final = {"x-exa-queued": "false", "x-exa-queue-ms": "0"}
#: x402 challenge defaults: the price of the SDK's default request.
_CHALLENGE: Final = {
    "search": ("/search", "search", Decimal("0.007")),
    "contents": ("/contents", "text", Decimal("0.001")),
}
_MPP_CURRENCY: Final = "0x20C000000000000000000000b9537d11c60E8b50"
_MPP_RECIPIENT: Final = "0x6d6f636b0000000000000000000000000000e7a2"
_CRAWL_FAILURES: Final = {
    "blocked": ("CRAWL_HTTP_403", 403),
    "timeout": ("CRAWL_LIVECRAWL_TIMEOUT", 408),
    "notfound": ("CRAWL_NOT_FOUND", 404),
}
_FIRST_NAMES: Final = ("Alex", "Maria", "Chen", "Priya", "Jonas", "Amara", "Diego", "Sofia")
_LAST_NAMES: Final = ("Novak", "Okafor", "Lindqvist", "Tanaka", "Moreau", "Haddad", "Ruiz")
_CITIES: Final = (
    ("San Francisco", "United States"),
    ("London", "United Kingdom"),
    ("Berlin", "Germany"),
    ("Toronto", "Canada"),
    ("Singapore", "Singapore"),
)


class _ExaKeyFormat(KeyFormat):
    """Exa keys are UUIDs; mock keys start with ``6d6f636b`` (ASCII ``mock``)."""

    def generate(self, seed: str | None = None) -> str:
        tail = secrets.token_hex(12) if seed is None else content.hex_id(24, "exa-key", seed)
        return str(uuid.UUID(hex=f"6d6f636b{tail}"))


@cache
def _x402_template() -> dict[str, Any]:
    folder = resources.files("polyweb_provider_mock.providers")
    data: dict[str, Any] = json.loads(folder.joinpath("exa_x402.json").read_text("utf-8"))
    return data


def _usd(value: Decimal) -> float:
    return float(round(value, 6))


def _js_type(value: Any) -> str:
    """Name a JSON value the way the provider's zod messages do."""

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


def _compact(value: Any) -> bytes:
    return json.dumps(value, separators=(",", ":")).encode("utf-8")


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _phrase(status: int, default: str) -> str:
    try:
        return HTTPStatus(status).phrase
    except ValueError:
        return default


def _public_id(key: str) -> str:
    return f"key_{content.hex_id(12, 'exa-public-id', key)}"


def _reserved(url: str) -> bool:
    host = (urlsplit(url).hostname or "").lower().removeprefix("www.")
    return host.split(".")[0] in {"example", "localhost"}


def _admin_error(status: int, message: str) -> MockResponse:
    return MockResponse(status=status, body={"error": message}, media_type=_JSON)


def _api_error(
    status: int,
    tag: str,
    message: str,
    *,
    headers: Mapping[str, str] | None = None,
    extra: Mapping[str, Any] | None = None,
) -> MockResponse:
    request_id = uuid.uuid4().hex
    merged = {**_API_HEADERS, "x-request-id": request_id, **(headers or {})}
    if status == 400:
        merged.update(_QUEUE_HEADERS)
    body = {"requestId": request_id, "error": message, "tag": tag, **(extra or {})}
    return MockResponse(status=status, body=body, headers=merged, media_type=_JSON)


def _invalid_body(
    context: OperationContext, detail: str, tag: str = "INVALID_REQUEST_BODY"
) -> MockResponse:
    message = detail
    if tag == "INVALID_REQUEST_BODY":
        message = f"Invalid request body | Validation error: {detail}"
    return context.error(ErrorKind.BAD_REQUEST, message=message, details={"tag": tag})


def _object_body(context: OperationContext) -> dict[str, Any] | MockResponse:
    try:
        body = context.json()
    except (json.JSONDecodeError, UnicodeDecodeError):
        return _invalid_body(context, "Invalid JSON in request body")
    if not isinstance(body, dict):
        return _invalid_body(context, f"Invalid input: expected object, received {_js_type(body)}")
    return body


def _selected(value: Any) -> bool:
    """Return whether a ``text``/``highlights``/``summary`` selector asks for content."""

    return value is True or isinstance(value, dict)


def _option(value: Any, name: str, default: Any = None) -> Any:
    return value.get(name, default) if isinstance(value, dict) else default


def _positive(value: Any, default: int) -> int:
    return (
        value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else default
    )


class ExaPlugin(ProviderPlugin):
    """Exa search, contents, and the team-management key usage report."""

    name: ClassVar[str] = "exa"
    hosts: ClassVar[frozenset[str]] = frozenset({_API_HOST, _ADMIN_HOST})
    key_format: ClassVar[KeyFormat] = _ExaKeyFormat(body_length=36)

    def operations(self) -> Sequence[Operation]:
        return (
            Operation("search", "POST", "/search", self._search, hosts=_API_ONLY),
            Operation("contents", "POST", "/contents", self._contents, hosts=_API_ONLY),
            Operation(
                "usage",
                "GET",
                "/team-management/api-keys/{key_id}/usage",
                self._usage,
                billable=False,
                scopes=frozenset({_SERVICE_SCOPE}),
                hosts=frozenset({_ADMIN_HOST}),
            ),
        )

    def credentials(self, request: Request, store: MockStore) -> Credentials:
        return Credentials(key=header_value(request, "x-api-key") or bearer_token(request))

    def default_seed(self) -> ProviderSeed:
        return ProviderSeed(
            accounts=(
                AccountSeed(
                    id="exa-team",
                    plan="Free $10 monthly grant + $10 onboarding bonus",
                    # USD: $10 refilled on the 1st of each calendar month (default
                    # reset_day 1); the one-time $10 bonus is prepaid and never resets.
                    credit_limit=_MONTHLY_GRANT,
                    prepaid_credits=_ONBOARDING_BONUS,
                    attributes={
                        "currency": "USD",
                        "team_id": content.stable_uuid("exa", "team", "exa-team"),
                    },
                ),
            ),
            keys=(
                KeySeed(label="default", account_id="exa-team", env_var="POLYWEB_EXA_API_KEY"),
                KeySeed(label="secondary", account_id="exa-team"),
                KeySeed(label="service", account_id="exa-team", scopes=(_SERVICE_SCOPE,)),
                KeySeed(label="budgeted", account_id="exa-team", credit_limit=_KEY_BUDGET),
            ),
        )

    def default_pricing(self) -> Sequence[PriceRule]:
        return tuple(
            PriceRule(
                provider=self.name,
                operation=operation,
                credits_per_unit=Decimal(usd),
                usd_per_unit=Decimal(usd),
                unit=unit,
            )
            for operation, usd, unit, _ in _PRICES
        )

    def not_found(self, request: Request, status: int) -> MockResponse:
        phrase = _phrase(status, "Not Found")
        if (request.url.hostname or "") == _ADMIN_HOST:
            return _admin_error(status, phrase)
        return _api_error(status, phrase.upper().replace(" ", "_"), phrase)

    def response_headers(self) -> dict[str, str]:
        return {"server": "cloudflare"}

    def drop_required_field(self, operation: str, body: Any) -> Any:
        if operation == "usage" and isinstance(body, dict):
            return {key: value for key, value in body.items() if key != "total_cost_usd"}
        return super().drop_required_field(operation, body)

    # --------------------------------------------------------------- errors

    def error(self, kind: ErrorKind, context: ErrorContext) -> MockResponse:
        if context.operation == "usage":
            return self._admin_failure(kind, context)
        if kind is ErrorKind.AUTH_INVALID and context.missing_key and context.status is None:
            return self._payment_required(context.operation)
        status, tag, message = _TAGS[kind]
        if kind is ErrorKind.QUOTA_EXHAUSTED and context.scope in _QUOTA_TAGS:
            tag, message = _QUOTA_TAGS[context.scope]
        if context.status is not None and context.status != status:
            status = context.status
            message = _phrase(status, message)
            tag = message.upper().replace(" ", "_").replace("-", "_")
        tag = str(context.details.get("tag", tag))
        headers: dict[str, str] = {}
        if kind is ErrorKind.RATE_LIMITED and context.retry_after_header:
            headers["Retry-After"] = str(60 if context.retry_after is None else context.retry_after)
        return _api_error(status, tag, context.message or message, headers=headers)

    @staticmethod
    def _admin_failure(kind: ErrorKind, context: ErrorContext) -> MockResponse:
        if kind in {ErrorKind.AUTH_INVALID, ErrorKind.AUTH_REVOKED, ErrorKind.FORBIDDEN}:
            return _admin_error(context.status or 401, context.message or "Unauthorized")
        default = {
            ErrorKind.BAD_REQUEST: 400,
            ErrorKind.RATE_LIMITED: 429,
            ErrorKind.QUOTA_EXHAUSTED: 402,
            ErrorKind.SERVER_ERROR: 500,
            ErrorKind.SERVICE_UNAVAILABLE: 503,
        }[kind]
        response = _admin_error(context.status or default, context.message or _ADMIN_MESSAGES[kind])
        if kind is ErrorKind.RATE_LIMITED and context.retry_after_header:
            retry = 60 if context.retry_after is None else context.retry_after
            response.headers["Retry-After"] = str(retry)
        return response

    @staticmethod
    def _payment_required(operation: str) -> MockResponse:
        """Return the x402 challenge Exa sends to a request without a key."""

        path, part, price = _CHALLENGE.get(operation, _CHALLENGE["search"])
        url = f"https://{_API_HOST}{path}"
        description = f"Exa {path} endpoint"
        amount = str(int(price * 1_000_000))
        template = _x402_template()
        accepts = json.loads(json.dumps(template["accepts"]))
        for accept in accepts:
            accept["amount"] = amount
            accept["extra"]["breakdown"] = {part: float(price)}
            accept["extra"]["totalUsd"] = float(price)
        agentkit = json.loads(json.dumps(template["agentkit"]))
        now = datetime.now(UTC)
        agentkit["info"].update(
            {
                "uri": url,
                "nonce": secrets.token_hex(16),
                "issuedAt": iso_ms(now),
                "resources": [url],
            }
        )
        message = "Payment required to access this resource"
        challenge = {
            "x402Version": 2,
            "resource": {"url": url, "description": description, "mimeType": "application/json"},
            "accepts": accepts,
            "extensions": {"bazaar": template["bazaar"][operation], "agentkit": agentkit},
        }
        mpp_request = {
            "amount": amount,
            "currency": _MPP_CURRENCY,
            "methodDetails": {"chainId": 4217, "feePayer": True, "supportedModes": ["pull"]},
            "recipient": _MPP_RECIPIENT,
        }
        www_authenticate = (
            f'Payment id="{_b64url(secrets.token_bytes(32))}", realm="{_API_HOST}", '
            f'method="tempo", intent="charge", request="{_b64url(_compact(mpp_request))}", '
            f'description="{description}", expires="{iso_ms(now + timedelta(minutes=5))}", '
            f'opaque="{_b64url(_compact({"_mppx_scope": f"POST {path}"}))}"'
        )
        header = {**challenge, "error": message}
        headers = {
            "payment-required": base64.b64encode(_compact(header)).decode("ascii"),
            "www-authenticate": www_authenticate,
        }
        return _api_error(402, "X402_PAYMENT_REQUIRED", message, headers=headers, extra=challenge)

    # ---------------------------------------------------------------- shared

    @staticmethod
    def _admit(context: OperationContext, limits: Sequence[tuple[str, int]]) -> MockResponse | None:
        """Spend one slot in each team-wide per-second window; return the 429 if one is full."""

        account = context.principal.account
        if account is None or context.principal.keyless:
            return None
        specs = [WindowSpec(f"exa:{account.id}:{name}:second", qps, 1) for name, qps in limits]
        refused, _ = context.admit(specs)
        if refused is None:
            return None
        return context.error(
            ErrorKind.RATE_LIMITED, retry_after=refused.retry_after(context.store.now())
        )

    @staticmethod
    def _success(context: OperationContext, body: dict[str, Any]) -> MockResponse:
        request_id = context.request_id().replace("-", "")
        body = {"requestId": request_id, **{k: v for k, v in body.items() if k != "requestId"}}
        headers = {**_API_HEADERS, "x-request-id": request_id, **_QUEUE_HEADERS}
        return MockResponse(status=200, body=body, headers=headers, media_type=_JSON)

    def _result(
        self,
        url: str,
        options: Mapping[str, Any],
        *,
        title: str | None = None,
        query: str = "",
        in_search: bool,
    ) -> dict[str, Any]:
        """Return one result with the content fields that ``options`` select."""

        page = content.page(url, title)
        reserved = _reserved(url)
        host = (urlsplit(url).hostname or "example.com").lower()
        item: dict[str, Any] = {"id": url, "title": page.title, "url": url}
        if not reserved:
            item["publishedDate"] = iso_ms(page.published)
        if not reserved or not in_search:
            item["author"] = None if reserved else self._author(host)
        if not reserved:
            item["image"] = page.images[0]
            item["favicon"] = page.favicon
        text = page.markdown.removeprefix("# ")
        selected = {name: options.get(name) for name in _CONTENT_TYPES}
        if _selected(selected["text"]):
            limit = _option(selected["text"], "maxCharacters")
            item["text"] = text[:limit] if isinstance(limit, int) and limit > 0 else text
        if _selected(selected["highlights"]):
            item["highlights"] = self._highlights(page, text, selected["highlights"])
        if _selected(selected["summary"]):
            item["summary"] = self._summary(page.title, query, selected["summary"])
        extras = options.get("extras")
        if isinstance(extras, dict) and extras:
            item["extras"] = self._extras(url, page, reserved, extras)
        # Recorded: every result that returns content carries the site's company entity.
        if any(_selected(value) for value in selected.values()):
            item["entities"] = [self._company(host)]
        return item

    @staticmethod
    def _author(host: str) -> str:
        generator = content.rng("exa-author", host)
        return f"{generator.choice(_FIRST_NAMES)} {generator.choice(_LAST_NAMES)}"

    @staticmethod
    def _highlights(page: content.Page, text: str, selector: Any) -> list[str]:
        count = _positive(_option(selector, "highlightsPerUrl"), 1)
        if text.count("\n\n") <= 1:
            return [text]
        paragraphs = [line for line in page.text.split("\n")[1:] if line.endswith(".")]
        sentences = [f"{part.rstrip('.')}." for line in paragraphs for part in line.split(". ")]
        per = _positive(_option(selector, "numSentences"), 2)
        chunks = [" ".join(sentences[i : i + per]) for i in range(0, len(sentences), per)]
        return [f"{page.title}\n\n{chunks[0]}", *chunks[1:]][:count]

    @staticmethod
    def _summary(title: str, query: str, selector: Any) -> str:
        schema = _option(selector, "schema")
        focus = _option(selector, "query") or query or title
        if isinstance(schema, dict):
            return json.dumps(schema_value(schema, f"{title} {focus}"), ensure_ascii=False)
        return f"The webpage is {title}. {content.answer(str(focus))}"

    @staticmethod
    def _extras(
        url: str, page: content.Page, reserved: bool, extras: Mapping[str, Any]
    ) -> dict[str, Any]:
        host = (urlsplit(url).hostname or "example.com").lower()
        out: dict[str, Any] = {}
        if "links" in extras:
            links = 0 if reserved else _positive(extras.get("links"), 0)
            out["links"] = [
                f"https://{host}/{content.hex_id(8, url, 'link', i)}" for i in range(links)
            ]
        if "imageLinks" in extras:
            images = 0 if reserved else _positive(extras.get("imageLinks"), 0)
            out["imageLinks"] = list(page.images[:images])
        return out

    @staticmethod
    def _company(host: str) -> dict[str, Any]:
        generator = content.rng("exa-company", host)
        label = host.removeprefix("www.").split(".")[0]
        city, country = generator.choice(_CITIES)
        visits = generator.randrange(10_000, 5_000_000)
        months = ("2026-05", "2026-06", "2026-07", "2026-08", "2026-09", "2026-10")
        slug = "".join(generator.choice("abcdefghijklmnopqrstuvwxyz0123456789") for _ in range(11))
        return {
            "id": f"https://exa.ai/library/organization/{slug}",
            "type": "company",
            "version": 1,
            "properties": {
                "name": label.title(),
                "foundedYear": 1990 + generator.randrange(35),
                "description": content.answer(f"{label} company"),
                "workforce": {"total": generator.randrange(5, 20_000)},
                "headquarters": {
                    "address": f"{generator.randrange(1, 999)} Market Street, {city}",
                    "city": city,
                    "postalCode": None,
                    "country": country,
                },
                "financials": {
                    "revenueAnnual": generator.randrange(1, 500) * 1_000_000,
                    "fundingTotal": None,
                    "fundingLatestRound": None,
                },
                "webTraffic": {
                    "visitsMonthly": visits,
                    "countryRank": generator.randrange(1, 20_000),
                    "avgDurationSeconds": generator.randrange(20, 600),
                    "history": [
                        {
                            "value": int(visits * (0.8 + generator.random() * 0.4)),
                            "dateFrom": month,
                            "dateTo": month,
                        }
                        for month in months
                    ],
                },
                "research": None,
            },
        }

    # --------------------------------------------------------------- search

    def _search_request(
        self, context: OperationContext, request: dict[str, Any]
    ) -> tuple[str, int, str, dict[str, Any]] | MockResponse:
        query = request.get("query", _MISSING)
        if not isinstance(query, str):
            received = _js_type(query)
            return _invalid_body(
                context,
                f'Invalid input: expected string, received {received} at "query" or '
                f'Invalid input: expected array, received {received} at "query"',
            )
        contents = request.get("contents", {})
        if not isinstance(contents, dict):
            return _invalid_body(
                context,
                f'Invalid input: expected object, received {_js_type(contents)} at "contents"',
            )
        count = request.get("numResults", _INCLUDED_RESULTS)
        if isinstance(count, bool) or not isinstance(count, int):
            return _invalid_body(
                context,
                f'Invalid input: expected number, received {_js_type(count)} at "numResults"',
            )
        if count < 1:
            return _invalid_body(context, 'Too small: expected number to be >=1 at "numResults"')
        if count > _MAX_RESULTS:
            if _selected(contents.get("highlights")):
                return _invalid_body(
                    context,
                    "numResults must be less than or equal to 100 when highlights are requested.",
                    "INVALID_NUM_RESULTS",
                )
            return _invalid_body(
                context,
                "The requested number of results exceeds the limit for your plan.",
                "NUM_RESULTS_EXCEEDED",
            )
        kind = request.get("type") or "auto"
        if kind not in _SEARCH_TYPES:
            options = "|".join(f'"{name}"' for name in _SEARCH_TYPES)
            return _invalid_body(context, f'Invalid option: expected one of {options} at "type"')
        return query, count, str(kind), contents

    async def _search(self, context: OperationContext) -> MockResponse:
        request = _object_body(context)
        if isinstance(request, MockResponse):
            return request
        checked = self._search_request(context, request)
        if isinstance(checked, MockResponse):
            return checked
        query, count, kind, contents = checked
        limits = [("search", _SEARCH_QPS)]
        if kind.startswith("deep"):
            limits.append(("deep", _DEEP_QPS))
        refused = self._admit(context, limits)
        if refused is not None:
            return refused
        context.match_key = content.normalize_query(query)
        fixture = context.fixture(context.match_key)
        if fixture is not None and fixture.status != 200:
            return MockResponse(status=fixture.status, body=fixture.body, media_type=_JSON)
        if fixture is not None and isinstance(fixture.body, dict):
            body = dict(fixture.body)
        else:
            body = self._search_body(query, count, kind, contents, request)
        found = body.get("results")
        results: list[Any] = found if isinstance(found, list) else []
        summaries = sum(
            1 for item in results if isinstance(item, dict) and bool(item.get("summary"))
        )
        extra = max(0, len(results) - _INCLUDED_RESULTS)
        charges = context.charge_all(
            [
                (_SEARCH_TYPES[kind], 1),
                ("search.extra_result", extra),
                ("search.summary", summaries),
            ],
        )
        spent = {charge.operation: charge.credits for charge in charges}
        search_cost = spent.get(_SEARCH_TYPES[kind], Decimal(0)) + spent.get(
            "search.extra_result", Decimal(0)
        )
        cost: dict[str, Any] = {
            "total": _usd(sum(spent.values(), Decimal(0))),
            "search": {"neural" if kind in {"auto", "neural"} else kind: _usd(search_cost)},
        }
        if summaries:
            cost["summary"] = _usd(spent.get("search.summary", Decimal(0)))
        body["costDollars"] = cost
        return self._success(context, body)

    def _search_body(
        self,
        query: str,
        count: int,
        kind: str,
        contents: dict[str, Any],
        request: dict[str, Any],
    ) -> dict[str, Any]:
        hits = content.search_hits(
            query,
            count,
            include_domains=[str(d) for d in request.get("includeDomains") or []],
            exclude_domains=[str(d) for d in request.get("excludeDomains") or []],
        )
        results = [
            self._result(hit.url, contents, title=hit.title, query=query, in_search=True)
            for hit in hits
        ]
        low, high = _SEARCH_TIMES.get(kind, (80.0, 2500.0))
        elapsed = low + content.rng("exa-search-time", query, kind).random() * (high - low)
        body: dict[str, Any] = {
            "resolvedSearchType": "" if kind == "auto" else kind,
            "results": results,
            "searchTime": round(elapsed, 1),
        }
        schema = request.get("outputSchema")
        if kind.startswith("deep") or isinstance(schema, dict):
            answer: Any = content.answer(query)
            if isinstance(schema, dict) and schema.get("type") == "object":
                answer = schema_value(schema, query)
            body["output"] = {
                "content": answer,
                "grounding": [
                    {
                        "field": "content",
                        "citations": [{"url": hit.url, "title": hit.title} for hit in hits[:3]],
                        "confidence": "high",
                    }
                ],
            }
        return body

    # ------------------------------------------------------------- contents

    async def _contents(self, context: OperationContext) -> MockResponse:
        request = _object_body(context)
        if isinstance(request, MockResponse):
            return request
        urls = request.get("urls", request.get("ids", _MISSING))
        if isinstance(urls, str):
            urls = [urls]
        if urls is _MISSING:
            return _invalid_body(context, 'Must provide either ids or urls at "ids.urls"')
        if not isinstance(urls, list) or not all(isinstance(url, str) for url in urls):
            return _invalid_body(
                context, f'Invalid input: expected array, received {_js_type(urls)} at "urls"'
            )
        refused = self._admit(context, [("contents", _CONTENTS_QPS)])
        if refused is not None:
            return refused
        options = dict(request)
        if not any(name in options for name in _CONTENT_TYPES):
            options["text"] = True
        results: list[dict[str, Any]] = []
        statuses: list[dict[str, Any]] = []
        for url in urls:
            context.match_key = content.normalize_url(url)
            item, status = self._fetched(context, url, options)
            statuses.append(status)
            if item is not None:
                results.append(item)
        selected = [name for name in _CONTENT_TYPES if _selected(options.get(name))]
        per_type = {name: sum(1 for item in results if name in item) for name in selected}
        charges = context.charge_all([(f"contents.{name}", n) for name, n in per_type.items()])
        spent = {charge.operation.removeprefix("contents."): charge.credits for charge in charges}
        body: dict[str, Any] = {"results": results, "statuses": statuses}
        total = sum(spent.values(), Decimal(0))
        if results:
            body["costDollars"] = {
                "total": _usd(total),
                "contents": {name: _usd(value) for name, value in spent.items()},
            }
        elapsed = 1.0 + content.rng("exa-contents-time", *urls).random() * 1500
        body["searchTime"] = round(elapsed, 3)
        return self._success(context, body)

    def _fetched(
        self, context: OperationContext, url: str, options: Mapping[str, Any]
    ) -> tuple[dict[str, Any] | None, dict[str, Any]]:
        """Return one result (or ``None``) and its ``statuses`` entry."""

        fixture = context.fixture(content.normalize_url(url))
        if fixture is not None and isinstance(fixture.body, dict):
            saved = fixture.body
            if isinstance(saved.get("results"), list):
                match = next((r for r in saved["results"] if r.get("url") == url), None)
                if match is not None:
                    return dict(match), {"id": url, "status": "success", "source": "cached"}
            elif "url" in saved:
                return {**saved, "id": url, "url": url}, {
                    "id": url,
                    "status": "success",
                    "source": "cached",
                }
        host = (urlsplit(url).hostname or "").lower()
        label = host.split(".")[0]
        failure = _CRAWL_FAILURES.get(label)
        if failure is None and (host.endswith(".invalid") or not host):
            failure = _CRAWL_FAILURES["notfound"]
        if failure is not None:
            tag, code = failure
            return None, {
                "id": url,
                "status": "error",
                "error": {"tag": tag, "httpStatusCode": code},
            }
        item = self._result(url, options, in_search=False)
        return item, {"id": url, "status": "success", "source": "cached"}

    # ---------------------------------------------------------------- usage

    async def _usage(self, context: OperationContext) -> MockResponse:
        principal = context.principal
        if principal.account is None:
            return context.error(ErrorKind.AUTH_INVALID)
        key_id = str(context.request.path_params.get("key_id", ""))
        if not key_id.startswith("key_") and not self._uuid(key_id):
            return _admin_error(400, "Invalid API key ID format.")
        target = next(
            (
                key
                for key in context.store.keys(self.name)
                if key_id in {key.key, _public_id(key.key)}
                and key.account_id == principal.account.id
            ),
            None,
        )
        if target is None:
            return _admin_error(404, "API key not found")
        period = self._period(context)
        if isinstance(period, MockResponse):
            return period
        start, end = period
        totals: dict[str, list[Decimal]] = {}
        for entry in context.store.ledger(self.name, limit=1_000_000):
            if (
                entry.account_id == target.account_id
                and entry.key_label == target.label
                and start <= entry.ts <= end
            ):
                bucket = totals.setdefault(entry.operation, [Decimal(0), Decimal(0)])
                bucket[0] += entry.units
                bucket[1] += entry.credits
        breakdown = [
            {
                "price_id": "price_" + operation.replace(".", "_").replace("-", "_"),
                "price_name": _PRICE_NAMES.get(operation, operation),
                "quantity": float(units) if units % 1 else int(units),
                "amount_usd": _usd(amount),
            }
            for operation, (units, amount) in sorted(totals.items())
        ]
        body = {
            "id": _public_id(target.key),
            "api_key_id": target.key,
            "api_key_name": target.label,
            "team_id": principal.account.attributes.get("team_id", principal.account.id),
            "period": {"start": iso_ms(start), "end": iso_ms(end)},
            "total_cost_usd": _usd(sum((amount for _, amount in totals.values()), Decimal(0))),
            "cost_breakdown": breakdown,
            "metadata": {"generated_at": iso_ms(context.store.now())},
        }
        return MockResponse(status=200, body=body, media_type=_JSON)

    @staticmethod
    def _uuid(value: str) -> bool:
        try:
            uuid.UUID(value)
        except ValueError:
            return False
        return True

    @staticmethod
    def _period(context: OperationContext) -> tuple[datetime, datetime] | MockResponse:
        params = context.request.query_params
        now = context.store.now()
        group_by = params.get("group_by")
        if group_by is not None and group_by not in {"hour", "day", "month"}:
            return _admin_error(400, "Invalid group_by parameter. Must be one of: hour, day, month")
        bounds: list[datetime] = []
        for name, default in (("start_date", now - _USAGE_DEFAULT), ("end_date", now)):
            raw = params.get(name)
            if raw is None:
                bounds.append(default)
                continue
            try:
                parsed = datetime.fromisoformat(raw)
            except ValueError:
                return _admin_error(
                    400,
                    "Invalid date format. Use ISO 8601 format (YYYY-MM-DD or YYYY-MM-DDTHH:mm:ss)",
                )
            bounds.append(parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC))
        start, end = bounds
        if start > end:
            return _admin_error(400, "start_date must be before end_date")
        if start < now - _USAGE_LOOKBACK:
            return _admin_error(
                400, "Date range too far in the past. start_date must be within the last 6 months."
            )
        return start, end


PLUGIN = ExaPlugin()
