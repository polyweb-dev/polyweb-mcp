"""Brave Search API adapter using the shared HTTP and resilience contracts."""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import httpx
from pydantic import SecretStr

from freesearch.adapters.base import ProviderAdapter
from freesearch.contracts import (
    CostEstimate,
    FetchRequest,
    FetchResponse,
    ProviderCapabilities,
    ProviderError,
    SearchRequest,
    SearchResponse,
    SearchResult,
    UsageEvent,
    UsageOperation,
)
from freesearch.provider_config import get_provider_secret_resolver
from freesearch.resilience import ProviderOperationError, ResilientRunner
from freesearch.secrets import ProviderName

_NAME = "brave"
_SEARCH_URL = "https://api.search.brave.com/res/v1/web/search"
_MAX_SEARCH_RESULTS = 20
_RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})


class BraveAdapter(ProviderAdapter):
    """Normalize Brave web search responses without owning client lifecycle."""

    def __init__(self, client: httpx.AsyncClient, *, runner: ResilientRunner | None = None) -> None:
        resolved = get_provider_secret_resolver().get(ProviderName.BRAVE)
        if resolved is None:
            raise self._error("configuration_error", "no Brave API key configured")
        self._client = client
        self._runner = runner or ResilientRunner(client)
        self._api_key: SecretStr = resolved

    @property
    def name(self) -> str:
        return _NAME

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(search=True, fetch=False, cost_estimate=True)

    async def search(self, request: SearchRequest) -> SearchResponse:
        try:
            response = await self._runner.run(self.name, lambda: self._search_request(request))
        except ProviderOperationError:
            raise
        except httpx.TransportError:
            raise self._error("transport_error", "transport error", retryable=True) from None
        try:
            if response.is_error:
                raise self._http_error(response.status_code)
            return self._search_response(request, response)
        except ProviderOperationError:
            raise
        except Exception:
            raise self._error("invalid_response", "malformed search response") from None

    async def fetch(self, request: FetchRequest) -> FetchResponse:
        del request
        raise self._error("unsupported_operation", "Brave does not support fetch")

    async def estimate_cost(self, request: SearchRequest | FetchRequest) -> CostEstimate:
        if isinstance(request, SearchRequest):
            return CostEstimate(
                provider=self.name,
                operation=UsageOperation.SEARCH,
                units=Decimal("1"),
                currency="queries",
                notes="Brave bills one search query per request",
            )
        return CostEstimate(
            provider=self.name,
            operation=UsageOperation.FETCH,
            units=Decimal("0"),
            currency="queries",
            notes="fetch is not supported by Brave Search",
        )

    async def _search_request(self, request: SearchRequest) -> httpx.Response:
        headers = {"X-Subscription-Token": self._api_key.get_secret_value()}
        user_agent = self._client.headers.get("User-Agent")
        if user_agent is not None:
            headers["User-Agent"] = user_agent
        wire_request = httpx.Request(
            "GET",
            _SEARCH_URL,
            params=self._params(request),
            headers=headers,
        )
        return await self._client.send(wire_request, auth=None, follow_redirects=False)

    def _params(self, request: SearchRequest) -> dict[str, str | int]:
        params: dict[str, str | int] = {
            "q": request.query,
            "count": min(request.limit, _MAX_SEARCH_RESULTS),
        }
        if request.country_code is not None:
            params["country"] = request.country_code.upper()
        if request.language is not None:
            params["search_lang"] = request.language
        return params

    def _search_response(self, request: SearchRequest, response: httpx.Response) -> SearchResponse:
        payload = response.json()
        web = payload["web"]
        results = web["results"]
        if not isinstance(web, dict) or not isinstance(results, list):
            raise TypeError("missing web results")
        normalized = [self._normalize_result(result) for result in results]
        return SearchResponse(
            query=request.query,
            provider=self.name,
            results=normalized,
            total_results=len(normalized),
            usage=self._usage_event(response),
        )

    @staticmethod
    def _normalize_result(result: Any) -> SearchResult:
        if not isinstance(result, dict):
            raise TypeError("result is not a mapping")
        metadata = {
            key: result[key] for key in ("language", "subtype") if isinstance(result.get(key), str)
        }
        return SearchResult(
            title=result.get("title") or "",
            url=result["url"],
            snippet=result.get("description") or "",
            published_at=result.get("page_age"),
            metadata=metadata,
        )

    def _usage_event(self, response: httpx.Response) -> UsageEvent:
        metadata: dict[str, int] = {}
        remaining = self._rate_limit_remaining(response.headers.get("X-RateLimit-Remaining"))
        if remaining is not None:
            metadata["rate_limit_remaining"] = remaining
        return UsageEvent(
            provider=self.name,
            operation=UsageOperation.SEARCH,
            units=Decimal("1"),
            observed_at=datetime.now(UTC),
            metadata=metadata,
        )

    @staticmethod
    def _rate_limit_remaining(value: str | None) -> int | None:
        try:
            remaining = int(value) if value is not None else None
        except ValueError:
            return None
        return remaining if remaining is not None and remaining >= 0 else None

    def _http_error(self, status: int) -> ProviderOperationError:
        return self._error(
            "http_error",
            f"HTTP {status}",
            retryable=status in _RETRYABLE_STATUS_CODES,
            status=status,
        )

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
