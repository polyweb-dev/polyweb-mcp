"""Tinyfish provider adapter: search and fetch over HTTPX.

Wraps the caller-owned shared HTTPX client in the shared ResilientRunner,
enforcing fail-closed authentication (X-API-Key). Executes search queries via
GET https://api.search.tinyfish.ai and markdown document extraction via
POST https://api.fetch.tinyfish.ai.
"""

import json
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, NoReturn, cast

import httpx
from pydantic import SecretStr, ValidationError

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
from freesearch.models.provider_limits import NativeUsageSnapshot, UsageSyncRequest

__all__ = ["TinyfishAdapter"]

_NAME = "tinyfish"
_SEARCH_URL = "https://api.search.tinyfish.ai"
_FETCH_URL = "https://api.fetch.tinyfish.ai"
_API_KEY_HEADER = "X-API-Key"


def _parse_error_record(index: int) -> dict[str, object]:
    """Return the safe record for one rejected search result item.

    The record holds no raw payload, URL, key, query, or validation text, so a
    rejected item can never leak response content into usage metadata.
    """

    return {
        "index": index,
        "code": "invalid_response",
        "message": "malformed search result item",
    }


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
        # Forward only the shared client user-agent, never its credentials or cookies.
        user_agent = self._client.headers.get("User-Agent")
        if user_agent is not None:
            headers["User-Agent"] = user_agent
        request = httpx.Request(method, url, json=json, params=params, headers=headers)
        return await self._client.send(request, auth=None, follow_redirects=False)

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
            results: list[SearchResult] = []
            parse_errors: list[dict[str, object]] = []
            for index, item in enumerate(payload["results"]):
                try:
                    results.append(self._normalize_result(item))
                except ValidationError:
                    parse_errors.append(_parse_error_record(index))
                except ProviderOperationError as exc:
                    if exc.error.code != "invalid_response":
                        raise
                    parse_errors.append(_parse_error_record(index))
            results = results[: request.limit]
            total_results = payload.get("total_results")
            if not isinstance(total_results, int) or total_results < 0:
                total_results = len(results)
            usage = self._usage_event(UsageOperation.SEARCH)
            if parse_errors:
                usage.metadata["parse_errors"] = parse_errors
            return SearchResponse(
                query=request.query,
                provider=self.name,
                results=results,
                total_results=total_results,
                usage=usage,
            )
        except ProviderOperationError:
            raise
        except Exception:
            raise self._error("invalid_response", "malformed search response") from None

    def _search_params(self, request: SearchRequest) -> dict[str, str | int]:
        options = (
            request.provider_options.tinyfish if request.provider_options is not None else None
        )
        params: dict[str, str | int] = {
            "query": request.query,
            "page": options.page if options is not None and options.page is not None else 0,
        }

        include = [domain for domain in request.domains if not domain.startswith("-")]
        exclude = [domain.lstrip("-") for domain in request.domains if domain.startswith("-")]
        if options is not None and options.include_domains is not None:
            include = list(options.include_domains)
        if options is not None and options.exclude_domains is not None:
            exclude = list(options.exclude_domains)
        if include:
            params["include_domains"] = ",".join(include)
        if exclude:
            params["exclude_domains"] = ",".join(exclude)

        location = options.location if options is not None else None
        if location is None:
            location = request.country_code.upper() if request.country_code is not None else None
        if location is not None:
            params["location"] = location

        language = options.language if options is not None else None
        if language is None:
            language = request.language
        if language is not None:
            params["language"] = language

        if options is not None:
            for key in (
                "purpose",
                "recency_minutes",
                "after_date",
                "before_date",
                "domain_type",
                "pub_year_min",
                "pub_year_max",
            ):
                value = getattr(options, key)
                if value is not None:
                    params[key] = value
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
        for key in (
            "site_name",
            "position",
            "date",
            "publisher",
            "authors",
            "venue",
            "year",
            "cited_by_count",
            "pdf_url",
        ):
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
            fallback_status = 502 if err_type in ("target_unreachable", "proxy_error") else 404
            parsed_status = (
                int(status_raw)
                if status_raw is not None and str(status_raw).isdigit()
                else fallback_status
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
            if err_type in ("target_unreachable", "proxy_error"):
                raise self._error(
                    "transport_error",
                    "fetch failed: target page unavailable",
                    retryable=True,
                    status=status_code,
                )
            if err_type == "target_http_error" or status_code in RETRYABLE_STATUS_CODES:
                raise self._error(
                    "http_error",
                    f"fetch failed: target returned HTTP {status_code}",
                    retryable=status_code in RETRYABLE_STATUS_CODES,
                    status=status_code,
                )
            raise self._error(
                "not_found",
                "fetch failed: target page not found",
                retryable=False,
                status=status_code,
            )
        raise self._error("invalid_response", "no extraction results returned")

    def _parse_fetch_document(self, item: Any, request: FetchRequest) -> FetchedDocument:
        if not isinstance(item, dict):
            raise self._error("invalid_response", "malformed fetch document item")
        raw_content = item.get("text") if item.get("text") is not None else item.get("content")
        if isinstance(raw_content, str):
            content = raw_content
        elif isinstance(raw_content, (dict, list)):
            content = json.dumps(raw_content, ensure_ascii=False)
        elif raw_content is None and isinstance(item.get("highlights"), list):
            content = "\n\n".join(
                highlight["text"]
                for highlight in item["highlights"]
                if isinstance(highlight, dict) and isinstance(highlight.get("text"), str)
            )
        else:
            raise self._error("invalid_response", "missing or non-string text in fetch response")

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
            "links",
            "image_links",
            "iframe_links",
            "not_modified",
            "etag",
            "last_modified",
            "unmatched_selectors",
            "highlights",
        ):
            if item.get(key) is not None:
                metadata[key] = item[key]

        format_val = str(item.get("format") or "").strip().lower()
        if format_val == "html":
            content_type = "text/html"
        elif format_val == "json" or isinstance(raw_content, (dict, list)):
            content_type = "application/json"
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
        options = (
            request.provider_options.tinyfish if request.provider_options is not None else None
        )
        payload: dict[str, Any] = {
            "urls": [str(request.url)],
            "format": options.format
            if options is not None and options.format is not None
            else "markdown",
        }
        if options is not None:
            for key in (
                "purpose",
                "links",
                "image_links",
                "iframe_links",
                "ttl",
                "per_url_timeout_ms",
                "if_none_match",
                "if_modified_since",
                "include_etag_and_last_modified",
            ):
                value = getattr(options, key)
                if value is not None:
                    payload[key] = value
            for key in ("include_selectors", "exclude_selectors"):
                value = getattr(options, key)
                if value is not None:
                    payload[key] = list(value)
            if options.highlights is not None:
                payload["highlights"] = options.highlights.model_dump(exclude_none=True)
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

    async def usage_snapshot(self, request: UsageSyncRequest) -> NativeUsageSnapshot | None:
        """Return no native observation: search and fetch have no wallet.

        Tinyfish search and fetch draw no wallet budget. The adapter ignores
        its Agent and Browser wallet endpoints for these operations. Its rate
        counters are not funds, so no snapshot exists.
        """

        return None

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
