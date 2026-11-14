"""You.com (YDC Index) provider adapter built on the shared HTTPX client."""

from datetime import UTC, datetime
from typing import Any, cast

import httpx
from pydantic import SecretStr, ValidationError

from polyweb.adapters._youcom_support import (
    _BALANCE_URL,
    _FETCH_UNIT_PRICE,
    _SEARCH_UNIT_PRICE,
    _estimated_quota,
    _fetch_request,
    _match_page,
    _page_metadata,
    _parse_published_at,
    _safe_metadata,
    _search_request,
)
from polyweb.adapters._youcom_support import _same_url as _same_url
from polyweb.adapters.base import ProviderAdapter, parse_error_record
from polyweb.infrastructure.borrowed_transport import BorrowedTransport
from polyweb.infrastructure.resilience import (
    RETRYABLE_STATUS_CODES,
    ProviderOperationError,
    ResilientRunner,
)
from polyweb.models.contracts import (
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
    UnitKind,
    UsageOperation,
)
from polyweb.models.provider_limits import (
    AuthMode,
    Confidence,
    NativeUsageSnapshot,
    UsageSyncRequest,
    native_pool_id,
)

__all__ = ["YoucomAdapter"]

_NAME = "you"


class YoucomAdapter(ProviderAdapter):
    def __init__(
        self,
        client: httpx.AsyncClient,
        *,
        runner: ResilientRunner | None = None,
        api_key: SecretStr | None = None,
    ) -> None:
        self._runner = runner or ResilientRunner(client)
        self._owned_http = self._build_client(client, api_key)

    def _build_client(
        self, client: httpx.AsyncClient, api_key: SecretStr | None = None
    ) -> httpx.AsyncClient:
        resolved = api_key
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
            transport=BorrowedTransport(client, reassert_timeout=True),
        )

    async def aclose(self) -> None:
        await self._owned_http.aclose()

    @property
    def name(self) -> str:
        return _NAME

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(search=True, fetch=True, cost_estimate=True, quota=True)

    @property
    def limit_auth_mode(self) -> AuthMode:
        """Return the keyed rail this adapter instance uses for limit records."""

        return AuthMode.KEYED

    async def usage_snapshot(self, request: UsageSyncRequest) -> NativeUsageSnapshot | None:
        """Return the vendor balance poll as the native USD observation.

        The account-balance endpoint reports the remaining USD credit balance
        in cents, validated by the shared quota-balance check; the vendor
        exposes no plan limit or reset, so the allowance stays unknown. The
        observation reuses the existing quota mapping, so confidence stays
        estimated and no rate observation is fabricated.
        """

        quota = await self.quota()
        return NativeUsageSnapshot(
            pool_id=native_pool_id(self.name, AuthMode.KEYED, UnitKind.USD),
            provider=self.name,
            auth_mode=AuthMode.KEYED,
            native_unit=UnitKind.USD,
            observed_at=request.observed_at,
            source="vendor_api",
            confidence=Confidence.ESTIMATED,
            remaining=quota.remaining,
            allowance=quota.limit,
            reset_at=quota.reset_at,
            credential_generation=request.credential_generation,
            plan_name="Signup $100 credit + 100 Polyweb MCPes/day",
            usage_url="https://you.com/platform/analytics",
            rate_observations=[],
        )

    async def search(self, request: SearchRequest) -> SearchResponse:
        try:
            response = await self._runner.run(
                self.name, lambda: _search_request(self._owned_http, request)
            )
            payload = self._payload(response, "search")
            items = self._search_items(payload)
            results: list[SearchResult] = []
            parse_errors: list[dict[str, object]] = []
            for index, item in enumerate(items):
                try:
                    results.append(self._normalize_result(item))
                except ValidationError:
                    parse_errors.append(parse_error_record(index))
                except ProviderOperationError as exc:
                    if exc.error.code != "invalid_response":
                        raise
                    parse_errors.append(parse_error_record(index))
            results = results[: request.limit]
        except ProviderOperationError as exc:
            raise self._remap_error(exc) from None
        except Exception:
            raise self._error("invalid_response", "malformed search response") from None
        gap: dict[str, Any] = {
            "reason": "metering-unavailable",
            "estimated": True,
            "units": _SEARCH_UNIT_PRICE,
            "currency": "USD",
        }
        if parse_errors:
            gap["parse_errors"] = parse_errors
        provider_metadata = payload.get("metadata") if isinstance(payload, dict) else None
        return SearchResponse(
            query=request.query,
            provider=self.name,
            results=results,
            total_results=len(results),
            usage_gap=gap,
            provider_metadata=provider_metadata if isinstance(provider_metadata, dict) else None,
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
        if not isinstance(item, dict):
            raise self._error("invalid_response", "malformed search result item")
        url = item.get("url")
        if not isinstance(url, str) or not url:
            raise self._error("invalid_response", "malformed search result item")
        metadata = _safe_metadata(item)
        contents = item.get("contents")
        if isinstance(contents, dict):
            metadata["contents"] = contents
        return SearchResult(
            title=item.get("title") or "",
            url=cast(Any, url),
            snippet=self._snippet(item),
            published_at=self._published_at(item),
            score=None,
            metadata=metadata,
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
        if isinstance(content, str):
            content_type = "text/markdown"
        else:
            content = match.get("html")
            if not isinstance(content, str):
                raise self._error("invalid_response", "malformed fetch response")
            content_type = "text/html"
        truncated = request.max_chars is not None and len(content) > request.max_chars
        if truncated:
            content = content[: request.max_chars]
        title = match.get("title")
        return FetchedDocument(
            url=request.url,
            content=content,
            title=title if isinstance(title, str) else None,
            content_type=content_type,
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
        code, retryable = mapping.get(status, ("http_error", status in RETRYABLE_STATUS_CODES))
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
