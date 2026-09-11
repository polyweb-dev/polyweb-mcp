"""You.com (YDC Index) provider adapter built on the shared HTTPX client."""

from datetime import UTC, datetime
from typing import Any

import httpx

from freesearch.adapters._youcom_support import (
    _BALANCE_URL,
    _FETCH_UNIT_PRICE,
    _SEARCH_UNIT_PRICE,
    _BorrowedTransport,
    _estimated_quota,
    _fetch_request,
    _match_page,
    _page_metadata,
    _parse_published_at,
    _safe_metadata,
    _search_request,
)
from freesearch.adapters._youcom_support import _same_url as _same_url
from freesearch.adapters.base import ProviderAdapter
from freesearch.configuration.provider_config import get_provider_secret_resolver
from freesearch.infrastructure.resilience import ProviderOperationError, ResilientRunner
from freesearch.infrastructure.secrets import ProviderName
from freesearch.models.contracts import (
    CostEstimate,
    FetchedDocument,
    FetchRequest,
    FetchResponse,
    ProviderCapabilities,
    ProviderError,
    QuotaSnapshot,
    SearchRequest,
    SearchResponse,
    SearchResult,
    UsageOperation,
)

__all__ = ["YoucomAdapter"]

_NAME = "you"
_RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})


class YoucomAdapter(ProviderAdapter):
    def __init__(self, client: httpx.AsyncClient, *, runner: ResilientRunner | None = None) -> None:
        self._runner = runner or ResilientRunner(client)
        self._owned_http = self._build_client(client)

    def _build_client(self, client: httpx.AsyncClient) -> httpx.AsyncClient:
        resolved = get_provider_secret_resolver().get(ProviderName.YOU)
        if resolved is None:
            raise self._error("configuration_error", "no You.com API key configured")
        forwarded = {
            key: value for key, value in client.headers.items() if key.lower() == "user-agent"
        }
        forwarded["X-API-Key"] = resolved.get_secret_value()
        return httpx.AsyncClient(
            follow_redirects=False,
            headers=forwarded,
            max_redirects=client.max_redirects,
            timeout=client.timeout,
            transport=_BorrowedTransport(client),
        )

    async def aclose(self) -> None:
        await self._owned_http.aclose()

    @property
    def name(self) -> str:
        return _NAME

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(search=True, fetch=True, cost_estimate=True, quota=True)

    async def search(self, request: SearchRequest) -> SearchResponse:
        try:
            response = await self._runner.run(
                self.name, lambda: _search_request(self._owned_http, request)
            )
            items = self._search_items(self._payload(response, "search"))
            normalized = [self._normalize_result(item) for item in items][: request.limit]
        except ProviderOperationError as exc:
            raise self._remap_error(exc) from None
        except Exception:
            raise self._error("invalid_response", "malformed search response") from None
        return SearchResponse(
            query=request.query,
            provider=self.name,
            results=normalized,
            total_results=len(normalized),
            usage_gap={
                "reason": "metering-unavailable",
                "estimated": True,
                "units": _SEARCH_UNIT_PRICE,
                "currency": "USD",
            },
        )

    def _search_items(self, payload: Any) -> list[Any]:
        if not isinstance(payload, dict):
            raise self._error("invalid_response", "malformed search response")
        results = payload.get("results")
        if results is None:
            return []
        if not isinstance(results, dict):
            raise self._error("invalid_response", "malformed search response")
        return [
            item
            for section in ("web", "news")
            if isinstance(results.get(section), list)
            for item in results[section]
        ]

    def _normalize_result(self, item: Any) -> SearchResult:
        return SearchResult(
            title=item.get("title") or "",
            url=item["url"],
            snippet=self._snippet(item),
            published_at=self._published_at(item),
            score=None,
            metadata=_safe_metadata(item),
        )

    @staticmethod
    def _published_at(item: Any) -> datetime | None:
        for key in ("publish_date", "published_date", "page_age"):
            parsed = _parse_published_at(item.get(key))
            if parsed is not None:
                return parsed
        return None

    @staticmethod
    def _snippet(item: Any) -> str:
        snippets = item.get("snippets")
        if isinstance(snippets, list) and snippets and isinstance(snippets[0], str):
            return snippets[0]
        description = item.get("description")
        return description if isinstance(description, str) else ""

    async def fetch(self, request: FetchRequest) -> FetchResponse:
        try:
            response = await self._runner.run(
                self.name, lambda: _fetch_request(self._owned_http, request)
            )
            pages = self._payload(response, "fetch")
            if not isinstance(pages, list):
                raise self._error("invalid_response", "malformed fetch response")
            match = _match_page(pages, str(request.url))
            if match is None:
                raise self._error("fetch_failed", "no successful extraction result") from None
            document = self._document(match, request)
        except ProviderOperationError as exc:
            raise self._remap_error(exc) from None
        except Exception:
            raise self._error("invalid_response", "malformed fetch response") from None
        return FetchResponse(
            provider=self.name,
            document=document,
            usage_gap={
                "reason": "metering-unavailable",
                "estimated": True,
                "units": _FETCH_UNIT_PRICE,
                "currency": "USD",
            },
        )

    def _document(self, match: dict[str, Any], request: FetchRequest) -> FetchedDocument:
        content = match.get("markdown")
        if not isinstance(content, str):
            raise self._error("invalid_response", "malformed fetch response")
        truncated = request.max_chars is not None and len(content) > request.max_chars
        if truncated:
            content = content[: request.max_chars]
        title = match.get("title")
        return FetchedDocument(
            url=request.url,
            content=content,
            title=title if isinstance(title, str) else None,
            content_type="text/markdown",
            fetched_at=datetime.now(UTC),
            metadata=_page_metadata(match, truncated),
        )

    def _payload(self, response: httpx.Response, operation: str) -> Any:
        if response.is_error:
            raise self._status_error(response.status_code)
        try:
            return response.json()
        except ValueError:
            raise self._error("invalid_response", f"malformed {operation} response") from None

    def _status_error(self, status: int) -> ProviderOperationError:
        mapping = {
            401: ("invalid_api_key", False),
            402: ("insufficient_credits", False),
            403: ("forbidden", False),
            400: ("bad_request", False),
            422: ("bad_request", False),
        }
        code, retryable = mapping.get(status, ("http_error", status in _RETRYABLE_STATUS_CODES))
        return self._error(code, f"HTTP {status}", retryable=retryable, status=status)

    def _remap_error(self, exc: ProviderOperationError) -> ProviderOperationError:
        if exc.error.status_code == 429 and exc.error.code == "http_error":
            return self._error("rate_limited", "rate limit exceeded", retryable=True, status=429)
        return exc

    async def estimate_cost(self, request: SearchRequest | FetchRequest) -> CostEstimate:
        if isinstance(request, SearchRequest):
            return CostEstimate(
                provider=self.name,
                operation=UsageOperation.SEARCH,
                units=_SEARCH_UNIT_PRICE,
                currency="USD",
                notes="estimated per You.com standard search pricing",
            )
        return CostEstimate(
            provider=self.name,
            operation=UsageOperation.FETCH,
            units=_FETCH_UNIT_PRICE,
            currency="USD",
            notes="estimated per You.com contents fetch pricing",
        )

    async def quota(self) -> QuotaSnapshot:
        try:
            response = await self._runner.run(self.name, lambda: self._quota_request())
            snapshot = _estimated_quota(self._payload(response, "quota"), self.name)
        except ProviderOperationError as exc:
            raise self._remap_error(exc) from None
        except Exception:
            raise self._error("invalid_response", "malformed quota response") from None
        return snapshot

    async def _quota_request(self) -> httpx.Response:
        """GET the account balance on the owned resolver-auth scoped client."""
        return await self._owned_http.get(_BALANCE_URL)

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
