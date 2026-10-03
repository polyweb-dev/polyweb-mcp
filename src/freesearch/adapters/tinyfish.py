"""Tinyfish provider adapter: search and fetch over HTTPX.

Wraps the caller-owned shared HTTPX client in the shared ResilientRunner,
enforcing fail-closed authentication (X-API-Key). Executes search queries via
GET https://api.search.tinyfish.ai and markdown document extraction via
POST https://api.fetch.tinyfish.ai.
"""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, NoReturn, cast

import httpx
from pydantic import SecretStr

from freesearch.adapters.base import ProviderAdapter
from freesearch.infrastructure.dates import parse_iso_datetime
from freesearch.infrastructure.resilience import (
    RETRYABLE_STATUS_CODES,
    ProviderOperationError,
    ResilientRunner,
)
from freesearch.models.contracts import (
    CostEstimate,
    FetchedDocument,
    FetchRequest,
    FetchResponse,
    HealthStatus,
    ProviderCapabilities,
    ProviderError,
    ProviderHealth,
    SearchRequest,
    SearchResponse,
    SearchResult,
    UnitKind,
    UsageEvent,
    UsageOperation,
)

__all__ = ["TinyfishAdapter"]

_NAME = "tinyfish"
_SEARCH_URL = "https://api.search.tinyfish.ai"
_FETCH_URL = "https://api.fetch.tinyfish.ai"
_API_KEY_HEADER = "X-API-Key"
_CREDENTIAL_HEADERS = frozenset({_API_KEY_HEADER, "Authorization", "X-Subscription-Token"})


class TinyfishAdapter(ProviderAdapter):
    """Search, fetch, and cost-estimate operations against the Tinyfish API."""

    def __init__(
        self,
        client: httpx.AsyncClient,
        *,
        runner: ResilientRunner | None = None,
        api_key: SecretStr | None = None,
    ) -> None:
        if api_key is None or not api_key.get_secret_value().strip():
            raise self._error(
                "configuration_error",
                "no Tinyfish API key configured",
                retryable=False,
            )
        self._client = client
        self._runner = runner or ResilientRunner(client)
        self._api_key = api_key

    @property
    def name(self) -> str:
        return _NAME

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            search=True,
            fetch=True,
            cost_estimate=True,
            quota=False,
        )

    def _auth(self) -> dict[str, str]:
        if self._api_key is None or not self._api_key.get_secret_value().strip():
            raise self._error(
                "configuration_error",
                "no Tinyfish API key configured",
                retryable=False,
            )
        return {_API_KEY_HEADER: self._api_key.get_secret_value()}

    async def _send_request(
        self,
        method: str,
        url: str,
        headers: dict[str, str],
        *,
        json: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> httpx.Response:
        request = self._client.build_request(method, url, json=json, params=params, headers=headers)
        for name in _CREDENTIAL_HEADERS:
            if name in request.headers:
                del request.headers[name]
        request.headers.update(headers)
        return await self._client.send(request, auth=None)

    async def search(self, request: SearchRequest) -> SearchResponse:
        try:
            response = await self._runner.run(self.name, lambda: self._search_request(request))
        except ProviderOperationError as exc:
            raise self._remap_error(exc) from None

        try:
            if response.is_error:
                raise self._http_error(response) from None
            payload = response.json()
            if not isinstance(payload, dict) or not isinstance(payload.get("results"), list):
                raise self._error("invalid_response", "malformed search response")
            results = [self._normalize_result(item) for item in payload["results"]][: request.limit]
            total_results = payload.get("total_results")
            if not isinstance(total_results, int) or total_results < 0:
                total_results = len(results)
            return SearchResponse(
                query=request.query,
                provider=self.name,
                results=results,
                total_results=total_results,
                usage=self._usage_event(UsageOperation.SEARCH),
            )
        except ProviderOperationError:
            raise
        except Exception:
            raise self._error("invalid_response", "malformed search response") from None

    def _search_params(self, request: SearchRequest) -> dict[str, str | int]:
        params: dict[str, str | int] = {
            "query": request.query,
            "page": 0,
        }
        if request.domains:
            include = [d for d in request.domains if not d.startswith("-")]
            exclude = [d.lstrip("-") for d in request.domains if d.startswith("-")]
            if include:
                params["include_domains"] = ",".join(include)
            if exclude:
                params["exclude_domains"] = ",".join(exclude)
        if request.country_code is not None:
            params["location"] = request.country_code.upper()
        if request.language is not None:
            params["language"] = request.language
        recency = getattr(request, "recency_minutes", None)
        if recency is not None:
            params["recency_minutes"] = recency
        return params

    async def _search_request(self, request: SearchRequest) -> httpx.Response:
        return await self._send_request(
            "GET",
            _SEARCH_URL,
            self._auth(),
            params=self._search_params(request),
        )

    def _normalize_result(self, item: Any) -> SearchResult:
        if not isinstance(item, dict):
            raise self._error("invalid_response", "malformed search result item")
        url = item.get("url")
        if not isinstance(url, str) or not url:
            raise self._error("invalid_response", "missing or invalid url in search result")
        metadata: dict[str, Any] = {}
        for key in ("site_name", "position"):
            if item.get(key) is not None:
                metadata[key] = item[key]
        published_raw = item.get("date") or item.get("published_date") or item.get("published_at")
        published_at = parse_iso_datetime(published_raw) if published_raw else None
        return SearchResult(
            title=item.get("title") or "",
            url=cast(Any, url),
            snippet=item.get("snippet") or item.get("description") or "",
            published_at=published_at,
            metadata=metadata,
        )

    def _handle_fetch_errors(self, errors: Any) -> NoReturn:
        if isinstance(errors, list) and errors:
            first_err = errors[0] if isinstance(errors[0], dict) else {}
            err_type = str(first_err.get("error", ""))
            status_raw = first_err.get("status")
            parsed_status = (
                int(status_raw) if status_raw is not None and str(status_raw).isdigit() else 404
            )
            status_code = (
                403
                if parsed_status == 999 or err_type == "bot_blocked"
                else min(599, max(100, parsed_status))
            )
            if err_type == "timeout":
                raise self._error("timeout", "fetch timed out", retryable=True, status=504)
            if err_type == "bot_blocked":
                raise self._error(
                    "bot_blocked",
                    "fetch failed: target site blocked automated bot access",
                    retryable=False,
                    status=403,
                )
            raise self._error(
                "not_found",
                f"fetch failed: {err_type or 'not found'}",
                retryable=False,
                status=status_code,
            )
        raise self._error("invalid_response", "no extraction results returned")

    def _parse_fetch_document(self, item: Any, request: FetchRequest) -> FetchedDocument:
        if not isinstance(item, dict):
            raise self._error("invalid_response", "malformed fetch document item")
        raw_content = item.get("text") if item.get("text") is not None else item.get("content")
        if not isinstance(raw_content, str):
            raise self._error("invalid_response", "missing or non-string text in fetch response")

        content = raw_content
        truncated = False
        if request.max_chars is not None and len(content) > request.max_chars:
            content = content[: max(0, request.max_chars)]
            truncated = True

        title = item.get("title") if isinstance(item.get("title"), str) else None
        metadata: dict[str, Any] = {}
        if truncated:
            metadata["truncated"] = True
        for key in (
            "final_url",
            "description",
            "language",
            "author",
            "published_date",
            "latency_ms",
            "format",
        ):
            if item.get(key) is not None:
                metadata[key] = item[key]

        format_val = str(item.get("format") or "").strip().lower()
        if format_val == "html":
            content_type = "text/html"
        elif format_val in ("plain", "text"):
            content_type = "text/plain"
        else:
            content_type = "text/markdown"

        return FetchedDocument(
            url=request.url,
            content=content,
            title=title,
            content_type=content_type,
            fetched_at=datetime.now(UTC),
            metadata=metadata,
        )

    async def fetch(self, request: FetchRequest) -> FetchResponse:
        try:
            response = await self._runner.run(self.name, lambda: self._fetch_request(request))
        except ProviderOperationError as exc:
            raise self._remap_error(exc) from None

        try:
            if response.is_error:
                raise self._http_error(response) from None
            payload = response.json()
            if not isinstance(payload, dict):
                raise self._error("invalid_response", "malformed fetch response")
            results = payload.get("results")
            if not isinstance(results, list) or len(results) == 0:
                self._handle_fetch_errors(payload.get("errors"))

            document = self._parse_fetch_document(results[0], request)
            return FetchResponse(
                provider=self.name,
                document=document,
                usage=self._usage_event(UsageOperation.FETCH),
            )
        except ProviderOperationError:
            raise
        except Exception:
            raise self._error("invalid_response", "malformed fetch response") from None

    async def _fetch_request(self, request: FetchRequest) -> httpx.Response:
        headers = self._auth()
        headers["Content-Type"] = "application/json"
        payload = {
            "urls": [str(request.url)],
            "format": "markdown",
        }
        return await self._send_request(
            "POST",
            _FETCH_URL,
            headers,
            json=payload,
        )

    async def estimate_cost(self, request: SearchRequest | FetchRequest) -> CostEstimate:
        operation = (
            UsageOperation.SEARCH if isinstance(request, SearchRequest) else UsageOperation.FETCH
        )
        return CostEstimate(
            provider=self.name,
            operation=operation,
            units=Decimal("0"),
            currency="USD",
            notes="free tier",
        )

    def _usage_event(self, operation: UsageOperation) -> UsageEvent:
        return UsageEvent(
            provider=self.name,
            operation=operation,
            units=Decimal("1"),
            unit_kind=UnitKind.REQUEST,
            display_unit="requests",
            observed_at=datetime.now(UTC),
            metadata={"cost_usd": Decimal("0")},
        )

    async def health(self) -> ProviderHealth:
        return ProviderHealth(
            provider=self.name,
            status=HealthStatus.UNKNOWN,
            checked_at=datetime.now(UTC),
        )

    async def aclose(self) -> None:
        pass

    def _http_error(self, response: httpx.Response) -> ProviderOperationError:
        status = response.status_code
        if status == 401:
            return self._error("invalid_api_key", "invalid API key", retryable=False, status=401)
        if status == 429:
            return self._error("rate_limited", "rate limit exceeded", retryable=True, status=429)
        return self._error(
            "http_error",
            f"HTTP {status}",
            retryable=status in RETRYABLE_STATUS_CODES,
            status=status,
        )

    def _remap_error(self, exc: ProviderOperationError) -> ProviderOperationError:
        if exc.error.status_code == 429 and exc.error.code == "http_error":
            return self._error("rate_limited", "rate limit exceeded", retryable=True, status=429)
        return exc

    def _error(
        self,
        code: str,
        message: str,
        *,
        retryable: bool = False,
        status: int | None = None,
    ) -> ProviderOperationError:
        return ProviderOperationError(
            ProviderError(
                provider=self.name,
                code=code,
                message=message,
                retryable=retryable,
                status_code=status,
            )
        )
