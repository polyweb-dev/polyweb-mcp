"""Keenable provider adapter: keyless or API-key search/fetch over HTTPX.

The adapter sends per-request headers through the caller-owned shared HTTPX
client (never mutating or closing it), running every call through the shared
:class:`ResilientRunner`. The key is resolved lazily per request: absent or
blank keys select keyless ``/public`` endpoints with ``X-Keenable-Title``; a
key selects private endpoints with ``X-API-Key`` only. Keenable's free tier is
zero cost, so usage and cost events always report zero units.
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

__all__ = ["KeenableAdapter"]

_NAME = "keenable"
_BASE_URL = "https://api.keenable.ai"
_MAX_SEARCH_RESULTS = 50
_RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})
_KEYLESS = "keyless"
_KEYED = "keyed"
_TITLE_HEADER = "X-Keenable-Title"
_API_KEY_HEADER = "X-API-Key"
# Credential headers a caller client may set as defaults; stripped after
# merging so exactly the adapter-selected header is sent.
_CREDENTIAL_HEADERS = frozenset({_TITLE_HEADER, _API_KEY_HEADER, "Authorization"})
_PATHS = {
    _KEYLESS: ("/v1/search/public", "/v1/fetch/public"),
    _KEYED: ("/v1/search", "/v1/fetch"),
}


def _parse_published_at(value: Any) -> datetime | None:
    """Parse an ISO-8601 timestamp; unparseable values are None."""
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


class KeenableAdapter(ProviderAdapter):
    """Search, fetch, and cost-estimate operations against the Keenable API."""

    def __init__(
        self,
        client: httpx.AsyncClient,
        *,
        runner: ResilientRunner | None = None,
    ) -> None:
        """Wrap the caller-owned ``client`` in the shared resilience runner."""
        self._client = client
        self._runner = runner or ResilientRunner(client)

    @property
    def name(self) -> str:
        return _NAME

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(search=True, fetch=True, cost_estimate=True, quota=False)

    def _auth(self) -> tuple[str, dict[str, str]]:
        """Resolve the API key lazily; absent or blank keys select keyless mode."""
        resolved = get_provider_secret_resolver().get(ProviderName.KEENABLE)
        if resolved is None or not resolved.get_secret_value():
            return _KEYLESS, {_TITLE_HEADER: "freesearch"}
        return _KEYED, {_API_KEY_HEADER: resolved.get_secret_value()}

    def _endpoint(self, mode: str, operation: str) -> str:
        search_path, fetch_path = _PATHS[mode]
        return f"{_BASE_URL}{search_path if operation == 'search' else fetch_path}"

    async def _send_request(
        self,
        method: str,
        url: str,
        headers: dict[str, str],
        *,
        json: dict[str, Any] | None = None,
        params: dict[str, str] | None = None,
    ) -> httpx.Response:
        """Send with client defaults merged, then exactly our auth header."""
        request = self._client.build_request(method, url, json=json, params=params, headers=headers)
        for name in _CREDENTIAL_HEADERS:
            if name in request.headers:
                del request.headers[name]
        request.headers.update(headers)
        # auth=None so a caller client's default auth cannot add Authorization.
        return await self._client.send(request, auth=None)

    async def search(self, request: SearchRequest) -> SearchResponse:
        response = await self._runner.run(self.name, lambda: self._search_request(request))
        try:
            if response.is_error:
                raise self._http_error(response) from None
            payload = response.json()
            results = [self._normalize_result(item) for item in payload["results"]]
            return SearchResponse(
                query=request.query,
                provider=self.name,
                results=results,
                total_results=len(results),
                usage=self._usage_event(UsageOperation.SEARCH),
            )
        except ProviderOperationError:
            raise
        except Exception:
            # A structurally malformed payload must not escape as a raw
            # AttributeError/KeyError/ValidationError/JSONDecodeError.
            raise self._error("invalid_response", "malformed search response") from None

    async def _search_request(self, request: SearchRequest) -> httpx.Response:
        mode, headers = self._auth()
        return await self._send_request(
            "POST",
            self._endpoint(mode, "search"),
            headers,
            json={
                "query": request.query,
                "max_results": min(request.limit, _MAX_SEARCH_RESULTS),
            },
        )

    def _normalize_result(self, item: Any) -> SearchResult:
        metadata: dict[str, Any] = {}
        for key in ("description", "acquired_at"):
            if item.get(key) is not None:
                metadata[key] = item[key]
        return SearchResult(
            title=item.get("title") or "",
            url=item["url"],
            snippet=item.get("snippet") or "",
            published_at=_parse_published_at(item.get("published_at")),
            metadata=metadata,
        )

    async def fetch(self, request: FetchRequest) -> FetchResponse:
        response = await self._runner.run(self.name, lambda: self._fetch_request(request))
        try:
            if response.is_error:
                raise self._http_error(response) from None
            payload = response.json()
            content = payload["content"]
            if not isinstance(content, str):
                raise self._error("invalid_response", "malformed fetch response") from None
            title = payload.get("title") if isinstance(payload.get("title"), str) else None
            truncated = request.max_chars is not None and len(content) > request.max_chars
            if truncated:
                content = content[: request.max_chars]
            return FetchResponse(
                provider=self.name,
                document=FetchedDocument(
                    url=request.url,
                    content=content,
                    title=title,
                    fetched_at=datetime.now(UTC),
                    metadata={"truncated": True} if truncated else {},
                ),
                usage=self._usage_event(UsageOperation.FETCH),
            )
        except ProviderOperationError:
            raise
        except Exception:
            # A structurally malformed payload must not escape as a raw
            # AttributeError/KeyError/TypeError/JSONDecodeError.
            raise self._error("invalid_response", "malformed fetch response") from None

    async def _fetch_request(self, request: FetchRequest) -> httpx.Response:
        mode, headers = self._auth()
        params: dict[str, str] = {"url": str(request.url)}
        if request.max_chars is not None:
            params["max_chars"] = str(request.max_chars)
        return await self._send_request(
            "GET", self._endpoint(mode, "fetch"), headers, params=params
        )

    async def estimate_cost(self, request: SearchRequest | FetchRequest) -> CostEstimate:
        operation = (
            UsageOperation.SEARCH if isinstance(request, SearchRequest) else UsageOperation.FETCH
        )
        return CostEstimate(
            provider=self.name,
            operation=operation,
            units=Decimal("0"),
            notes="Keenable free tier is zero cost",
        )

    def _usage_event(self, operation: UsageOperation) -> UsageEvent:
        return UsageEvent(
            provider=self.name,
            operation=operation,
            units=Decimal("0"),
            observed_at=datetime.now(UTC),
        )

    def _http_error(self, response: httpx.Response) -> ProviderOperationError:
        status = response.status_code
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
