"""Firecrawl provider adapter built on the official ``firecrawl`` async SDK.

The adapter wraps every SDK call in the shared :class:`ResilientRunner` and
resolves the API key only through the process-wide provider secret resolver.
Absent credentials fail closed as a ``configuration_error`` rather than
falling back to ambient ``FIRECRAWL_API_KEY`` or keyless mode. The trusted
resolver ``api_key`` constructor is sufficient - the SDK manages its own
transport - so no borrowed auth client is needed and the shared client is
never mutated. SDK failures and structurally malformed responses are
normalized to redaction-safe :class:`ProviderOperationError` values.

The SDK returns typed pydantic models (``SearchData`` with a ``web`` list,
``Document`` with ``markdown``); legacy/fake callers may still hand back v1
dicts. Both surfaces are accepted, but only ``web`` results are ever used for
search, and usage evidence is read only from raw mapping payloads.
"""

import math
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import httpx
from firecrawl import AsyncFirecrawl  # type: ignore[import-untyped]

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

__all__ = ["FirecrawlAdapter"]

_NAME = "firecrawl"
# Retryable set mirrors the shared runner's HTTP policy; SDK errors outside it
# are surfaced as non-retryable.
_RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})


def _parse_published_at(value: Any) -> datetime | None:
    """Parse Firecrawl's ISO-8601 ``date``; unparseable values are None."""
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _item_value(item: Any, key: str, default: Any = None) -> Any:
    """Read a field from either a raw dict or a pydantic SDK model."""
    if isinstance(item, dict):
        return item.get(key, default)
    return getattr(item, key, default)


class FirecrawlAdapter(ProviderAdapter):
    """Search and fetch operations against the Firecrawl API."""

    def __init__(
        self,
        client: httpx.AsyncClient,
        *,
        runner: ResilientRunner | None = None,
        sdk_client: AsyncFirecrawl | None = None,
    ) -> None:
        """Wrap the caller-owned ``client`` in the shared resilience runner.

        ``sdk_client`` is a test-only seam replacing the real SDK client; the
        caller owns the shared HTTPX client and is responsible for closing it.
        The real SDK manages its own transport, so it needs no explicit close.
        """
        self._runner = runner or ResilientRunner(client)
        self._sdk = sdk_client or self._build_sdk()
        # Only the adapter-created SDK owns a transport this adapter must close;
        # an injected SDK is caller-owned and must never be closed here.
        self._owns_sdk = sdk_client is None

    def _build_sdk(self) -> AsyncFirecrawl:
        """Build the SDK with the resolver key only.

        The key comes only from the shared resolver; absent credentials fail
        closed rather than letting the SDK fall back to ambient
        ``FIRECRAWL_API_KEY`` or keyless mode.
        """
        resolved = get_provider_secret_resolver().get(ProviderName.FIRECRAWL)
        if resolved is None:
            raise self._error("configuration_error", "no Firecrawl API key configured")
        return AsyncFirecrawl(api_key=resolved.get_secret_value())

    async def aclose(self) -> None:
        """Close the adapter-created SDK's transport, never the caller's client.

        The installed ``AsyncFirecrawl`` owns its closeable transport only at
        the nested ``v2.async_http_client`` surface; older SDKs may still
        expose a top-level ``async_http_client``. Both are duck-typed so SDKs
        without such a resource stay a no-op; injected SDKs are caller-owned
        and left untouched.
        """
        if not self._owns_sdk:
            return
        transport = getattr(self._sdk, "v2", None)
        close = getattr(getattr(transport, "async_http_client", None), "close", None)
        if close is None:
            close = getattr(getattr(self._sdk, "async_http_client", None), "close", None)
        if close is not None:
            await close()

    @property
    def name(self) -> str:
        return _NAME

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(search=True, fetch=True, cost_estimate=True)

    async def search(self, request: SearchRequest) -> SearchResponse:
        response = await self._runner.run(self.name, lambda: self._search_sdk(request))
        try:
            results = [self._normalize_result(item) for item in self._search_data(response)]
            usage = self._usage_event(response, UsageOperation.SEARCH)
        except ProviderOperationError:
            raise
        except Exception:
            # A structurally malformed payload must not escape as a raw
            # AttributeError/KeyError/ValidationError after the call succeeded.
            raise self._error("invalid_response", "malformed search response") from None
        return SearchResponse(
            query=request.query,
            provider=self.name,
            results=results,
            total_results=len(results),
            usage=usage,
        )

    async def _search_sdk(self, request: SearchRequest) -> Any:
        try:
            return await self._sdk.search(query=request.query, limit=request.limit)
        except httpx.TransportError:
            raise  # the shared ResilientRunner normalizes transport failures
        except Exception as exc:
            raise self._normalize_error(exc) from None

    def _search_data(self, response: Any) -> list[Any]:
        """Return the web search results from a raw dict or SDK model.

        Only the ``web`` source is consumed; news/images are never used to
        invent results.
        """
        if isinstance(response, dict):
            data = response.get("data")
            if not isinstance(data, list):
                raise self._error("invalid_response", "malformed search response") from None
            return data
        if hasattr(response, "web"):
            web = response.web
            if web is None or isinstance(web, list):
                return web or []
        raise self._error("invalid_response", "malformed search response") from None

    def _normalize_result(self, item: Any) -> SearchResult:
        return SearchResult(
            title=_item_value(item, "title") or "",
            url=_item_value(item, "url"),
            snippet=_item_value(item, "description") or "",
            published_at=_parse_published_at(
                _item_value(item, "date") or _item_value(item, "published_date")
            ),
        )

    async def fetch(self, request: FetchRequest) -> FetchResponse:
        response = await self._runner.run(self.name, lambda: self._fetch_sdk(request))
        try:
            content = self._document_data(response)
            truncated = False
            if request.max_chars is not None and len(content) > request.max_chars:
                content = content[: request.max_chars]
                truncated = True
            return FetchResponse(
                provider=self.name,
                document=FetchedDocument(
                    url=request.url,
                    content=content,
                    fetched_at=datetime.now(UTC),
                    metadata={"truncated": True} if truncated else {},
                ),
                usage=self._usage_event(response, UsageOperation.FETCH),
            )
        except ProviderOperationError:
            raise
        except Exception:
            # A structurally malformed payload must not escape as a raw
            # AttributeError/KeyError/TypeError after the call succeeded.
            raise self._error("invalid_response", "malformed fetch response") from None

    async def _fetch_sdk(self, request: FetchRequest) -> Any:
        try:
            return await self._sdk.scrape(url=str(request.url), formats=["markdown"])
        except httpx.TransportError:
            raise  # the shared ResilientRunner normalizes transport failures
        except Exception as exc:
            raise self._normalize_error(exc) from None

    def _document_data(self, response: Any) -> str:
        """Return the markdown from a raw dict or an SDK ``Document`` model."""
        if isinstance(response, dict):
            data = response.get("data")
            if not isinstance(data, dict):
                raise self._error("invalid_response", "malformed fetch response") from None
            markdown = data.get("markdown")
        else:
            markdown = getattr(response, "markdown", None)
        if not isinstance(markdown, str):
            raise self._error("invalid_response", "malformed fetch response") from None
        return markdown

    async def estimate_cost(self, request: SearchRequest | FetchRequest) -> CostEstimate:
        operation = (
            UsageOperation.SEARCH if isinstance(request, SearchRequest) else UsageOperation.FETCH
        )
        # Firecrawl does not publish a per-request unit price, so unknown
        # pricing is reported as zero units rather than invented credits.
        return CostEstimate(
            provider=self.name,
            operation=operation,
            units=Decimal("0"),
            currency="credits",
            notes="Firecrawl does not publish a per-request unit price",
        )

    def _usage_event(self, response: Any, operation: UsageOperation) -> UsageEvent | None:
        """Return an event only when a raw mapping reported credit usage."""
        if not isinstance(response, dict):
            return None
        usage = response.get("usage")
        if not isinstance(usage, dict):
            return None
        credits = usage.get("credits")
        if credits is None:
            return None
        if (
            isinstance(credits, bool)
            or not isinstance(credits, (int, float))
            or credits < 0
            or not math.isfinite(credits)
        ):
            raise self._error("invalid_response", "malformed usage in response") from None
        return UsageEvent(
            provider=self.name,
            operation=operation,
            units=Decimal(str(credits)),
            observed_at=datetime.now(UTC),
            request_id=response.get("request_id"),
        )

    def _normalize_error(self, exc: Exception) -> ProviderOperationError:
        status = self._status_code(exc)
        if status is not None:
            return self._error(
                "http_error",
                f"HTTP {status}",
                retryable=status in _RETRYABLE_STATUS_CODES,
                status=status,
            )
        # The class name carries no payload or secret; raw exceptions are never
        # exposed.
        return self._error("firecrawl_error", type(exc).__name__)

    def _status_code(self, exc: Exception) -> int | None:
        """Extract a real HTTP status from httpx or status-bearing SDK errors.

        The SDK raises ``FirecrawlError`` subclasses carrying ``status_code``;
        those map exactly like httpx ``HTTPStatusError`` so retries follow the
        shared HTTP policy and no raw body/message ever leaks out.
        """
        if isinstance(exc, httpx.HTTPStatusError):
            return exc.response.status_code
        status = getattr(exc, "status_code", None)
        if isinstance(status, bool) or not isinstance(status, int):
            return None
        return status

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
