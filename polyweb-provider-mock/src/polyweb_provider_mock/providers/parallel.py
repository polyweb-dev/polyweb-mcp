"""Parallel on ``api.parallel.ai`` and ``platform.parallel.ai``.

Product API (``api.parallel.ai``): ``POST /v1/search`` and ``POST /v1/extract``
with ``x-api-key``. Formats follow the live recordings of 2026-11-17
(``tests/contract/recordings/parallel``) and the official v1 references:

- A missing or wrong key gets the gateway's 401 ``{"code": 16, "message":
  "No API key provided (C.0)" | "Invalid API key (C.1)"}`` without a request ID.
  A revoked key answers like a wrong key (no live revoke was recorded).
- Authentication runs before validation. Schema errors are 422 in the v1
  envelope ``{"type": "error", "error": {"ref_id", "message", "detail":
  {"errors": [...]}}}`` with ``ref_id`` equal to ``x-request-id`` (32 hex).
- 402 (out of credit), 403, 429, and 5xx use the same envelope. They are
  documented in general but unrecorded for these endpoints; 429 carries a
  ``Retry-After`` that the real gateway may not send.
- Success bodies carry ``search_id`` / ``extract_id`` and ``session_id`` from
  the same 32 hex request ID (an echoed ``session_id`` wins), ``usage`` SKUs
  (``sku_search``, ``sku_extract_excerpts``), ``warnings`` and ``metadata: null``.
- Prices are USD: the account ``credit_limit`` is the prepaid balance in
  dollars. Search costs $0.001 (``turbo``/``fast``) or $0.005 (``basic`` and the
  default ``advanced``) plus $0.001 per result beyond 10; extract costs $0.001
  per successfully extracted URL. Failed URLs are free.

There is no keyless REST mode (the free hosted MCP is a different product).

Account API (OAuth device flow, balance, apps, key minting) lives in
:mod:`polyweb_provider_mock.providers._parallel_account`.

Synthetic extract targets: a host whose first label is ``blocked`` fails with
an upstream 403, a ``.invalid`` host fails to resolve, and a non-HTTP URL is
an invalid URL; each becomes an ``errors`` entry of an HTTP 200 response.
"""

import json
import secrets
from collections.abc import Awaitable, Callable, Sequence
from datetime import UTC, datetime
from decimal import Decimal
from http import HTTPStatus
from typing import Any, ClassVar, Final
from urllib.parse import urlsplit

from fastapi import APIRouter
from starlette.requests import Request

from polyweb_provider_mock import content
from polyweb_provider_mock.models import AccountSeed, KeyFormat, KeySeed, PriceRule, ProviderSeed
from polyweb_provider_mock.providers import _parallel_account as account_api
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

__all__ = ["PLUGIN", "ParallelPlugin"]

API_HOST: Final = "api.parallel.ai"
PLATFORM_HOST: Final = "platform.parallel.ai"
DEFAULT_ACCOUNT: Final = "parallel-org"

_MODES: Final = ("turbo", "fast", "basic", "advanced")
_DEFAULT_RESULTS: Final = 10
_INCLUDED_RESULTS: Final = 10
_MAX_RESULTS: Final = 40
_MAX_EXTRACT_URLS: Final = 20
_DEFAULT_EXCERPT_CHARS: Final = 6000
_MISSING: Final[Any] = object()
_QUERIES_MESSAGE: Final = (
    "Field required. Pass a list of 2-3 concise keyword queries, 3-6 words each, and put the "
    "full question in objective."
)
_NO_FOCUS_WARNING: Final = (
    "Neither objective nor search_queries were provided, provide at least one to increase the "
    "relevance of excerpts."
)
_SEARCH_FIELDS: Final = frozenset(
    {
        "objective",
        "search_queries",
        "mode",
        "max_chars_total",
        "session_id",
        "client_model",
        "advanced_settings",
    }
)
_SEARCH_SETTINGS: Final = frozenset(
    {"source_policy", "fetch_policy", "excerpt_settings", "location", "max_results"}
)
_EXTRACT_FIELDS: Final = frozenset(
    {
        "urls",
        "objective",
        "search_queries",
        "max_chars_total",
        "session_id",
        "client_model",
        "advanced_settings",
    }
)
_EXTRACT_SETTINGS: Final = frozenset({"fetch_policy", "excerpt_settings", "full_content", "links"})

_MESSAGES: Final = {
    ErrorKind.FORBIDDEN: "Forbidden.",
    ErrorKind.BAD_REQUEST: "Bad request.",
    ErrorKind.RATE_LIMITED: "Rate limit exceeded. Please retry after some time.",
    ErrorKind.QUOTA_EXHAUSTED: (
        "Insufficient credit in account. Add credits at https://platform.parallel.ai."
    ),
    ErrorKind.SERVER_ERROR: "Internal server error.",
    ErrorKind.SERVICE_UNAVAILABLE: "Service temporarily unavailable.",
}
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
_OAUTH_ERRORS: Final = {
    ErrorKind.AUTH_INVALID: "invalid_client",
    ErrorKind.AUTH_REVOKED: "invalid_client",
    ErrorKind.FORBIDDEN: "access_denied",
    ErrorKind.BAD_REQUEST: "invalid_request",
    ErrorKind.RATE_LIMITED: "too_many_requests",
    ErrorKind.QUOTA_EXHAUSTED: "server_error",
    ErrorKind.SERVER_ERROR: "server_error",
    ErrorKind.SERVICE_UNAVAILABLE: "temporarily_unavailable",
}
#: OAuth error codes a fault ``message`` may name to force that exact error.
_OAUTH_CODES: Final = frozenset(
    {
        "invalid_request",
        "invalid_client",
        "invalid_grant",
        "invalid_scope",
        "unauthorized_client",
        "unsupported_grant_type",
        "authorization_pending",
        "slow_down",
        "access_denied",
        "expired_token",
        "server_error",
        "temporarily_unavailable",
    }
)
_REQUIRED_FIELD: Final = {
    "search": "results",
    "extract": "results",
    "register": "client_id",
    "device_code": "device_code",
    "token": "access_token",
    "balance": "org_id",
    "apps": "apps",
    "create_key": "raw_api_key",
}


def _phrase(status: int, fallback: str) -> str:
    try:
        return HTTPStatus(status).phrase
    except ValueError:
        return fallback


def _request_id() -> str:
    return secrets.token_hex(16)


def _invalid(errors: list[dict[str, Any]], request_id: str | None = None) -> MockResponse:
    """Return the recorded 422 envelope for schema errors."""

    ref = request_id or _request_id()
    body = {
        "type": "error",
        "error": {
            "ref_id": ref,
            "message": "Request validation error.",
            "detail": {"errors": errors},
        },
    }
    return MockResponse(status=422, body=body, headers={"x-request-id": ref})


def _item(kind: str, loc: Sequence[str | int], message: str, value: Any) -> dict[str, Any]:
    return {"type": kind, "loc": ["body", *loc], "msg": message, "input": value}


def _object_body(context: OperationContext) -> dict[str, Any] | MockResponse:
    try:
        body = context.json()
    except json.JSONDecodeError as exc:
        return _invalid(
            [
                {
                    **_item("json_invalid", [exc.pos], "JSON decode error", {}),
                    "ctx": {"error": exc.msg},
                }
            ]
        )
    if not isinstance(body, dict):
        message = "Input should be a valid dictionary or object to extract fields from"
        return _invalid([_item("model_attributes_type", [], message, body)])
    return body


def _extra_fields(
    body: dict[str, Any], allowed: frozenset[str], loc: Sequence[str] = ()
) -> list[dict[str, Any]]:
    return [
        _item("extra_forbidden", [*loc, name], "Extra inputs are not permitted", value)
        for name, value in body.items()
        if name not in allowed
    ]


def _strings(value: Any, loc: Sequence[str]) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return [_item("list_type", loc, "Input should be a valid list", value)]
    return [
        _item("string_type", [*loc, index], "Input should be a valid string", item)
        for index, item in enumerate(value)
        if not isinstance(item, str)
    ]


def _positive(value: Any, loc: Sequence[str]) -> list[dict[str, Any]]:
    if value is None:
        return []
    if isinstance(value, bool) or not isinstance(value, int):
        return [_item("int_type", loc, "Input should be a valid integer", value)]
    if value < 1:
        return [
            _item("greater_than_equal", loc, "Input should be greater than or equal to 1", value)
        ]
    return []


def _settings(body: dict[str, Any], allowed: frozenset[str]) -> tuple[dict[str, Any], list[Any]]:
    settings = body.get("advanced_settings")
    if settings is None:
        return {}, []
    if not isinstance(settings, dict):
        message = "Input should be a valid dictionary or object to extract fields from"
        return {}, [_item("model_attributes_type", ["advanced_settings"], message, settings)]
    return settings, _extra_fields(settings, allowed, ("advanced_settings",))


def _focus_errors(body: dict[str, Any]) -> list[dict[str, Any]]:
    errors: list[dict[str, Any]] = []
    objective = body.get("objective")
    if objective is not None and not isinstance(objective, str):
        errors.append(
            _item("string_type", ["objective"], "Input should be a valid string", objective)
        )
    session = body.get("session_id")
    if session is not None and (not isinstance(session, str) or len(session) > 1000):
        message = "String should have at most 1000 characters"
        errors.append(_item("string_too_long", ["session_id"], message, session))
    errors.extend(_positive(body.get("max_chars_total"), ["max_chars_total"]))
    return errors


def _search_errors(body: dict[str, Any]) -> list[dict[str, Any]]:
    errors = _extra_fields(body, _SEARCH_FIELDS)
    queries = body.get("search_queries", _MISSING)
    if queries is _MISSING:
        errors.append(_item("missing", ["search_queries"], _QUERIES_MESSAGE, body))
    else:
        errors.extend(_strings(queries, ["search_queries"]))
    mode = body.get("mode")
    if mode is not None and mode not in _MODES:
        message = "Input should be 'turbo', 'fast', 'basic' or 'advanced'"
        errors.append(_item("literal_error", ["mode"], message, mode))
    errors.extend(_focus_errors(body))
    settings, problems = _settings(body, _SEARCH_SETTINGS)
    errors.extend(problems)
    errors.extend(_positive(settings.get("max_results"), ["advanced_settings", "max_results"]))
    return errors


def _extract_errors(body: dict[str, Any]) -> list[dict[str, Any]]:
    errors = _extra_fields(body, _EXTRACT_FIELDS)
    urls = body.get("urls", _MISSING)
    if urls is _MISSING:
        errors.append(_item("missing", ["urls"], "Field required", body))
    else:
        errors.extend(_strings(urls, ["urls"]))
        if isinstance(urls, list) and len(urls) > _MAX_EXTRACT_URLS:
            message = f"List should have at most 20 items after validation, not {len(urls)}"
            errors.append(_item("too_long", ["urls"], message, urls))
    queries = body.get("search_queries")
    if queries is not None:
        errors.extend(_strings(queries, ["search_queries"]))
    errors.extend(_focus_errors(body))
    _, problems = _settings(body, _EXTRACT_SETTINGS)
    errors.extend(problems)
    return errors


def _limit(text: str, chars: int | None) -> str:
    return text if chars is None or len(text) <= chars else text[:chars]


def _excerpt_chars(settings: dict[str, Any]) -> int | None:
    excerpt = settings.get("excerpt_settings")
    value = excerpt.get("max_chars_per_result") if isinstance(excerpt, dict) else None
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _publish_date(url: str, published: datetime) -> str | None:
    if content.rng("publish", url).random() < 0.35:
        return None
    return published.date().isoformat()


def _acquired_at(now: datetime) -> str:
    return now.astimezone(UTC).strftime("%Y-%m-%dT00:00:00Z")


def _url_failure(url: str) -> dict[str, Any] | None:
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    if parts.scheme not in {"http", "https"} or not host:
        return {"url": url, "error_type": "invalid_url", "http_status_code": None, "content": None}
    if host.split(".")[0] == "blocked":
        return {
            "url": url,
            "error_type": "fetch_error",
            "http_status_code": 403,
            "content": f"Error fetching content from {url}",
        }
    if host.endswith(".invalid"):
        return {
            "url": url,
            "error_type": "fetch_error",
            "http_status_code": None,
            "content": f"Error fetching content from {url}",
        }
    return None


class ParallelPlugin(ProviderPlugin):
    """Parallel search and extract, plus the Account API and its OAuth device flow."""

    name: ClassVar[str] = "parallel"
    hosts: ClassVar[frozenset[str]] = frozenset({API_HOST, PLATFORM_HOST})
    # The real key format is unverified; Parallel keys are long opaque strings.
    key_format: ClassVar[KeyFormat] = account_api.KEY_FORMAT

    def operations(self) -> Sequence[Operation]:
        def account(name: str, method: str, path: str, handler: Any, host: str) -> Operation:
            return Operation(
                name, method, path, self._on(host, handler), billable=False, auth="none"
            )

        return (
            Operation("search", "POST", "/v1/search", self._on(API_HOST, self._search)),
            Operation("extract", "POST", "/v1/extract", self._on(API_HOST, self._extract)),
            account(
                "register",
                "POST",
                "/getServiceKeys/register",
                account_api.handle_register,
                PLATFORM_HOST,
            ),
            account(
                "device_code",
                "POST",
                "/getServiceKeys/device/code",
                account_api.handle_device_code,
                PLATFORM_HOST,
            ),
            account(
                "token", "POST", "/getServiceKeys/token", account_api.handle_token, PLATFORM_HOST
            ),
            account(
                "revoke",
                "POST",
                "/getServiceKeys/token/revoke",
                account_api.handle_revoke,
                PLATFORM_HOST,
            ),
            account(
                "balance",
                "GET",
                "/account/service/v1/balance",
                account_api.handle_balance,
                API_HOST,
            ),
            account("apps", "GET", "/account/service/v1/apps", account_api.handle_apps, API_HOST),
            account(
                "create_key",
                "POST",
                "/account/service/v1/apps/{app_id}/keys",
                account_api.handle_create_key,
                API_HOST,
            ),
            account(
                "delete_key",
                "DELETE",
                "/account/service/v1/apps/{app_id}/keys/{api_key_id}",
                account_api.handle_delete_key,
                API_HOST,
            ),
        )

    def _on(
        self, host: str, handler: Callable[[OperationContext], Awaitable[MockResponse]]
    ) -> Callable[[OperationContext], Awaitable[MockResponse]]:
        """Serve a path only on its real host; the other host answers 404."""

        async def guarded(context: OperationContext) -> MockResponse:
            presented = (context.request.headers.get("host") or "").split(":")[0].lower()
            if presented and presented != host:
                return self.not_found(context.request, 404)
            return await handler(context)

        return guarded

    def credentials(self, request: Request) -> Credentials:
        key = header_value(request, "x-api-key")
        if key is not None and key.count(".") == 2:
            # An Account API access token used as a product key (ParallelOAuthAdapter).
            claims = account_api.token_claims(key)
            if claims is not None:
                return Credentials(key=account_api.bridge_key(str(claims.get("org_id"))))
        return Credentials(key=key)

    def default_seed(self) -> ProviderSeed:
        return ProviderSeed(
            accounts=(
                AccountSeed(
                    id=DEFAULT_ACCOUNT,
                    plan="Build",
                    credit_limit=Decimal(5),
                    attributes={
                        "org_id": content.stable_uuid(self.name, "org", DEFAULT_ACCOUNT),
                        "org_name": "Polyweb Mock Org",
                        "user_id": content.stable_uuid(self.name, "user", DEFAULT_ACCOUNT),
                        "user_email": "owner@example.com",
                        "currency": "USD",
                        "pending_debit_cents": 0,
                        "will_invoice": False,
                    },
                ),
            ),
            keys=(
                KeySeed(
                    label="default", account_id=DEFAULT_ACCOUNT, env_var="POLYWEB_PARALLEL_API_KEY"
                ),
                KeySeed(label="secondary", account_id=DEFAULT_ACCOUNT),
                KeySeed(
                    label=account_api.bridge_label(DEFAULT_ACCOUNT),
                    account_id=DEFAULT_ACCOUNT,
                    key=account_api.bridge_key(DEFAULT_ACCOUNT),
                    scopes=(account_api.BRIDGE_SCOPE,),
                ),
            ),
        )

    def default_pricing(self) -> Sequence[PriceRule]:
        def price(operation: str, usd: str, unit: str) -> PriceRule:
            amount = Decimal(usd)
            return PriceRule(
                provider=self.name,
                operation=operation,
                credits_per_unit=amount,
                usd_per_unit=amount,
                unit=unit,
            )

        return (
            price("search.turbo", "0.001", "request"),
            price("search.fast", "0.001", "request"),
            price("search.basic", "0.005", "request"),
            price("search.advanced", "0.005", "request"),
            price("search.extra_result", "0.001", "result"),
            price("extract", "0.001", "url"),
        )

    def response_headers(self) -> dict[str, str]:
        ray = f"{secrets.token_hex(8)}-SJC"
        return {"via": "1.1 google", "cf-cache-status": "DYNAMIC", "cf-ray": ray}

    def admin_routes(self, router: APIRouter, store: MockStore) -> None:
        account_api.register_admin_routes(router, store)

    def cli_commands(self, groups: Any) -> None:
        account_api.register_cli(groups)

    def drop_required_field(self, operation: str, body: Any) -> Any:
        victim = _REQUIRED_FIELD.get(operation)
        if victim is not None and isinstance(body, dict):
            return {key: value for key, value in body.items() if key != victim}
        return super().drop_required_field(operation, body)

    # --------------------------------------------------------------- errors

    def error(self, kind: ErrorKind, context: ErrorContext) -> MockResponse:
        if context.operation in account_api.OAUTH_OPERATIONS:
            return self._oauth_error(kind, context)
        if context.operation in account_api.ACCOUNT_OPERATIONS:
            return self._account_error(kind, context)
        return self._product_error(kind, context)

    @staticmethod
    def _retry_after(kind: ErrorKind, context: ErrorContext) -> dict[str, str]:
        if kind is not ErrorKind.RATE_LIMITED or not context.retry_after_header:
            return {}
        return {"Retry-After": str(context.retry_after if context.retry_after is not None else 60)}

    def _product_error(self, kind: ErrorKind, context: ErrorContext) -> MockResponse:
        if kind in {ErrorKind.AUTH_INVALID, ErrorKind.AUTH_REVOKED} and context.status in {
            None,
            401,
        }:
            message = context.message or (
                "No API key provided (C.0)" if context.missing_key else "Invalid API key (C.1)"
            )
            return MockResponse(
                status=401,
                body={"code": 16, "message": message},
                media_type="application/json; charset=utf-8",
            )
        status = context.status or _DEFAULT_STATUS[kind]
        fallback = _MESSAGES.get(kind, "Unauthorized.")
        message = context.message or (
            fallback if status == _DEFAULT_STATUS[kind] else _phrase(status, fallback)
        )
        ref = _request_id()
        body = {
            "type": "error",
            "error": {"ref_id": ref, "message": message, "detail": dict(context.details) or None},
        }
        headers = {"x-request-id": ref, **self._retry_after(kind, context)}
        return MockResponse(status=status, body=body, headers=headers)

    def _account_error(self, kind: ErrorKind, context: ErrorContext) -> MockResponse:
        if kind in {ErrorKind.AUTH_INVALID, ErrorKind.AUTH_REVOKED} and context.status in {
            None,
            401,
        }:
            return account_api.bearer_failure("missing" if context.missing_key else "invalid")
        status = context.status or _DEFAULT_STATUS[kind]
        message = context.message or _phrase(status, "Error")
        return account_api.account_response(
            status, {"detail": message}, self._retry_after(kind, context)
        )

    def _oauth_error(self, kind: ErrorKind, context: ErrorContext) -> MockResponse:
        status = context.status or _DEFAULT_STATUS[kind]
        if kind is ErrorKind.QUOTA_EXHAUSTED and context.status is None:
            status = 500
        code = _OAUTH_ERRORS[kind]
        description = _phrase(status, "Error")
        if context.message in _OAUTH_CODES:
            code = str(context.message)
        elif context.message:
            description = context.message
        error = account_api.OAuthError(code, description, status).response()
        error.headers.update(self._retry_after(kind, context))
        return error

    # --------------------------------------------------------------- search

    def _token_refused(self, context: OperationContext) -> MockResponse | None:
        """Refuse an expired or orphaned OAuth access token used as a product key."""

        presented = header_value(context.request, "x-api-key")
        if presented is None or account_api.token_claims(presented) is None:
            return None
        if isinstance(account_api.ParallelAccount(context.store).access(presented), str):
            return context.error(ErrorKind.AUTH_INVALID)
        return None

    async def _search(self, context: OperationContext) -> MockResponse:
        refused = self._token_refused(context)
        if refused is not None:
            return refused
        request = _object_body(context)
        if isinstance(request, MockResponse):
            return request
        errors = _search_errors(request)
        if errors:
            return _invalid(errors)
        settings = request.get("advanced_settings") or {}
        mode = request.get("mode") or "advanced"
        count = min(settings.get("max_results") or _DEFAULT_RESULTS, _MAX_RESULTS)
        queries: list[str] = request["search_queries"]
        query = request.get("objective") or " ".join(queries) or "web search"
        context.match_key = content.normalize_query(query)
        fixture = context.fixture(context.match_key)
        if fixture is not None and fixture.status != 200:
            return MockResponse(status=fixture.status, body=fixture.body)
        if fixture is not None and isinstance(fixture.body, dict):
            body = dict(fixture.body)
        else:
            body = {"results": self._search_results(query, count, settings, request)}
        context.charge(f"search.{mode}")
        returned = body.get("results")
        extra = len(returned) - _INCLUDED_RESULTS if isinstance(returned, list) else 0
        if extra > 0:
            context.charge("search.extra_result", extra)
        rid = _request_id()
        return MockResponse(
            body={
                "search_id": f"search_{rid}",
                "results": body.get("results", []),
                "warnings": body.get("warnings"),
                "usage": [{"name": "sku_search", "count": 1}],
                "metadata": body.get("metadata"),
                "session_id": request.get("session_id") or f"session_{rid}",
            },
            headers={"x-request-id": rid},
        )

    @staticmethod
    def _search_results(
        query: str, count: int, settings: dict[str, Any], request: dict[str, Any]
    ) -> list[dict[str, Any]]:
        policy = settings.get("source_policy") or {}
        hits = content.search_hits(
            query,
            count,
            include_domains=list(policy.get("include_domains") or []),
            exclude_domains=list(policy.get("exclude_domains") or []),
        )
        per_result = _excerpt_chars(settings) or _DEFAULT_EXCERPT_CHARS
        total = request.get("max_chars_total")
        if isinstance(total, int) and hits:
            per_result = min(per_result, max(1, total // len(hits)))
        results: list[dict[str, Any]] = []
        for hit in hits:
            page = content.page(hit.url, hit.title)
            sections = page.markdown.split("\n\n")[1:4]
            excerpt = _limit("\n\n".join([hit.snippet, *sections]), per_result)
            results.append(
                {
                    "url": hit.url,
                    "title": hit.title,
                    "publish_date": _publish_date(hit.url, hit.published),
                    "excerpts": [excerpt],
                }
            )
        return results

    # -------------------------------------------------------------- extract

    async def _extract(self, context: OperationContext) -> MockResponse:
        refused = self._token_refused(context)
        if refused is not None:
            return refused
        request = _object_body(context)
        if isinstance(request, MockResponse):
            return request
        errors = _extract_errors(request)
        if errors:
            return _invalid(errors)
        settings = request.get("advanced_settings") or {}
        results: list[dict[str, Any]] = []
        failures: list[dict[str, Any]] = []
        for url in request["urls"]:
            context.match_key = content.normalize_url(url)
            item = self._extracted(context, url, settings)
            (failures if "error_type" in item else results).append(item)
        if results:
            context.charge("extract", len(results))
        focused = request.get("objective") or request.get("search_queries")
        warnings = None
        if not focused:
            warnings = [{"type": "warning", "message": _NO_FOCUS_WARNING, "detail": None}]
        rid = _request_id()
        usage = [{"name": "sku_extract_excerpts", "count": len(results)}] if results else []
        return MockResponse(
            body={
                "extract_id": f"extract_{rid}",
                "results": results,
                "errors": failures,
                "warnings": warnings,
                "usage": usage,
                "metadata": None,
                "session_id": request.get("session_id") or f"session_{rid}",
            },
            headers={"x-request-id": rid},
        )

    @staticmethod
    def _extracted(context: OperationContext, url: str, settings: dict[str, Any]) -> dict[str, Any]:
        """Return one result or one ``errors`` entry for ``url``."""

        fixture = context.fixture(content.normalize_url(url))
        if fixture is not None and isinstance(fixture.body, dict):
            saved = fixture.body
            if isinstance(saved.get("results"), list):
                match = next((r for r in saved["results"] if r.get("url") == url), None)
                if match is not None:
                    return dict(match)
            elif "full_content" in saved or "error_type" in saved:
                return {**saved, "url": url}
        failure = _url_failure(url)
        if failure is not None:
            return failure
        page = content.page(url)
        full = settings.get("full_content", False)
        full_chars = full.get("max_chars_per_result") if isinstance(full, dict) else None
        paragraphs = page.markdown.split("\n\n")
        excerpt = _limit("\n\n".join(paragraphs[1:3] or paragraphs), _excerpt_chars(settings))
        item: dict[str, Any] = {
            "url": url,
            "title": page.title,
            "publish_date": _publish_date(url, page.published),
            "excerpts": [excerpt],
            "full_content": (
                _limit(page.markdown, full_chars if isinstance(full_chars, int) else None)
                if full is True or isinstance(full, dict)
                else None
            ),
            "acquired_at": _acquired_at(context.store.now()),
        }
        if settings.get("links") is True:
            host = urlsplit(url).hostname or "example.com"
            item["links"] = [f"https://{host}/", f"https://{host}/about"]
        return item


PLUGIN = ParallelPlugin()
