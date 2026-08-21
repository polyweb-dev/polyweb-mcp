"""Parallel provider adapter: direct HTTPX against ``api.parallel.ai``, no SDK.

Wire calls go through the shared :class:`ResilientRunner`; the API key is
resolved once via the process-wide provider secret resolver (absent
credentials fail closed) and travels as a per-request ``x-api-key`` header.
Responses normalize to the shared contracts: ``search_id`` / ``extract_id``
map to the usage request id; any final non-2xx status is a typed error and
malformed payloads are the redaction-safe, non-retryable ``invalid_response``.
"""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import httpx

from freesearch.adapters.base import ProviderAdapter
from freesearch.contracts import (
    CostEstimate,
    FetchedDocument,
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

__all__ = ["ParallelAdapter"]

_NAME = "parallel"
_SEARCH_URL = "https://api.parallel.ai/v1/search"
_EXTRACT_URL = "https://api.parallel.ai/v1/extract"
_RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})
_STATUS_ERROR_CODES = {
    400: "bad_request",
    401: "invalid_api_key",
    403: "forbidden",
    422: "invalid_response",
}


class _BorrowedTransport(httpx.AsyncBaseTransport):
    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        return await self._client._transport_for_url(request.url).handle_async_request(request)


def _parse_published_at(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


class ParallelAdapter(ProviderAdapter):
    """Search, fetch, and cost-estimate operations against the Parallel API."""

    def __init__(
        self,
        client: httpx.AsyncClient,
        *,
        runner: ResilientRunner | None = None,
    ) -> None:
        """Wrap the caller-owned ``client`` in the shared resilience runner."""
        resolved = get_provider_secret_resolver().get(ProviderName.PARALLEL)
        if resolved is None:
            raise self._error("configuration_error", "no Parallel API key configured")
        self._api_key = resolved.get_secret_value()
        self._http = httpx.AsyncClient(
            transport=_BorrowedTransport(client),
            timeout=client.timeout,
            follow_redirects=client.follow_redirects,
            max_redirects=client.max_redirects,
        )
        self._runner = runner or ResilientRunner(client)

    async def aclose(self) -> None:
        await self._http.aclose()

    @property
    def name(self) -> str:
        return _NAME

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(search=True, fetch=True, cost_estimate=True)

    async def search(self, request: SearchRequest) -> SearchResponse:
        response = await self._runner.run(
            self.name, lambda: self._request(_SEARCH_URL, self._search_body(request))
        )
        try:
            return self._search_response(request, self._normalize_response(response))
        except ProviderOperationError:
            raise
        except Exception:
            raise self._error("invalid_response", "malformed search response") from None

    def _search_body(self, request: SearchRequest) -> dict[str, Any]:
        settings: dict[str, Any] = {"max_results": min(request.limit, 20)}
        if request.domains:
            settings["source_policy"] = {"include_domains": list(request.domains)}
        if request.country_code is not None:
            settings["location"] = request.country_code.lower()
        return {
            "objective": request.query,
            "search_queries": [request.query],
            "advanced_settings": settings,
        }

    async def _request(self, url: str, body: dict[str, Any]) -> httpx.Response:
        return await self._http.post(url, headers={"x-api-key": self._api_key}, json=body)

    def _search_response(self, request: SearchRequest, payload: dict[str, Any]) -> SearchResponse:
        request_id = self._require(payload, "search_id", str)
        results = [
            self._normalize_search_result(item) for item in self._require(payload, "results", list)
        ]
        return SearchResponse(
            query=request.query,
            provider=self.name,
            results=results,
            total_results=len(results),
            usage=self._usage_event(payload, UsageOperation.SEARCH, request_id),
        )

    def _normalize_search_result(self, item: Any) -> SearchResult:
        if not isinstance(item.get("url"), str):
            raise self._error("invalid_response", "malformed search response")
        excerpts = item.get("excerpts")
        if not isinstance(excerpts, list):
            raise self._error("invalid_response", "malformed search response")
        return SearchResult(
            title=item.get("title") or "",
            url=item.get("url"),
            snippet="\n\n".join(excerpts),
            published_at=_parse_published_at(item.get("publish_date")),
        )

    async def fetch(self, request: FetchRequest) -> FetchResponse:
        body = {"urls": [str(request.url)], "advanced_settings": {"full_content": True}}
        response = await self._runner.run(self.name, lambda: self._request(_EXTRACT_URL, body))
        try:
            return self._fetch_response(request, self._normalize_response(response))
        except ProviderOperationError:
            raise
        except Exception:
            raise self._error("invalid_response", "malformed fetch response") from None

    def _fetch_response(self, request: FetchRequest, payload: dict[str, Any]) -> FetchResponse:
        request_id = self._require(payload, "extract_id", str)
        match = self._matching_result(self._require(payload, "results", list), str(request.url))
        content = match.get("full_content")
        if not isinstance(content, str):
            raise self._error("invalid_response", "malformed fetch response")
        truncated = request.max_chars is not None and len(content) > request.max_chars
        if truncated:
            content = content[: request.max_chars]
        return FetchResponse(
            provider=self.name,
            document=FetchedDocument(
                url=request.url,
                content=content,
                fetched_at=datetime.now(UTC),
                metadata={"truncated": True} if truncated else {},
            ),
            usage=self._usage_event(payload, UsageOperation.FETCH, request_id),
        )

    def _matching_result(self, results: list[Any], target: str) -> dict[str, Any]:
        for item in results:
            if isinstance(item, dict) and str(item.get("url") or "") == target:
                return item
        raise self._error("fetch_failed", "no successful extraction result") from None

    async def estimate_cost(self, request: SearchRequest | FetchRequest) -> CostEstimate:
        operation = (
            UsageOperation.SEARCH if isinstance(request, SearchRequest) else UsageOperation.FETCH
        )
        return CostEstimate(
            provider=self.name,
            operation=operation,
            units=Decimal("1"),
            currency="credits",
            notes="one credit per request on the Parallel free tier",
        )

    def _normalize_response(self, response: httpx.Response) -> dict[str, Any]:
        if not 200 <= response.status_code < 300:
            status = response.status_code
            raise self._error(
                _STATUS_ERROR_CODES.get(status, "http_error"),
                f"HTTP {status}",
                retryable=status in _RETRYABLE_STATUS_CODES,
                status=status,
            ) from None
        payload = response.json()
        if not isinstance(payload, dict):
            raise self._error("invalid_response", "malformed response payload")
        return payload

    def _require(self, payload: dict[str, Any], key: str, expected: type) -> Any:
        value = payload.get(key)
        if not isinstance(value, expected):
            raise self._error("invalid_response", "malformed response payload")
        return value

    def _usage_event(
        self, payload: dict[str, Any], operation: UsageOperation, request_id: str | None
    ) -> UsageEvent | None:
        """Sum documented ``usage`` SKU counts; malformed usage is invalid_response."""
        usage = payload.get("usage")
        if usage is None:
            return None
        if not isinstance(usage, list) or any(not isinstance(e, dict) for e in usage):
            raise self._error("invalid_response", "malformed usage in response")
        units = Decimal(0)
        for entry in usage:
            count = entry.get("count")
            if isinstance(count, bool) or not isinstance(count, (int, float)):
                raise self._error("invalid_response", "malformed usage in response")
            units += Decimal(str(count))
        return UsageEvent(
            provider=self.name,
            operation=operation,
            units=units,
            observed_at=datetime.now(UTC),
            request_id=request_id,
        )

    def _error(
        self, code: str, message: str, *, retryable: bool = False, status: int | None = None
    ) -> ProviderOperationError:
        error = ProviderError(
            provider=self.name, code=code, message=message, retryable=retryable, status_code=status
        )
        return ProviderOperationError(error)
