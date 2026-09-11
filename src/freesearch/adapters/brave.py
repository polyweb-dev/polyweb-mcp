"""Brave Search API adapter using the shared HTTP and resilience contracts."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import httpx
from pydantic import SecretStr

from freesearch.adapters.base import ProviderAdapter
from freesearch.configuration.provider_config import get_provider_secret_resolver
from freesearch.infrastructure.resilience import ProviderOperationError, ResilientRunner
from freesearch.infrastructure.secrets import ProviderName
from freesearch.models.contracts import (
    CostEstimate,
    FetchRequest,
    FetchResponse,
    ProviderCapabilities,
    ProviderError,
    QuotaSnapshot,
    QuotaSource,
    SearchRequest,
    SearchResponse,
    SearchResult,
    UnitKind,
    UsageEvent,
    UsageOperation,
)

_NAME = "brave"
_SEARCH_URL = "https://api.search.brave.com/res/v1/web/search"
_MAX_SEARCH_RESULTS = 20
_RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})

__all__ = [
    "BRAVE_EXHAUSTION_BODY_CODES",
    "COST_USD_PER_REQUEST",
    "FREE_CREDITS_USD",
    "BraveAdapter",
    "brave_cost_metadata",
    "brave_spend_usd",
    "monthly_header_value",
    "parse_monthly_element",
]

# Manual USD price from the Brave dashboard ($5.00 per 1000 requests).
# No dashboard scraping is performed; this constant is only used for
# spend-projection metadata alongside the observed throttle snapshot.
COST_USD_PER_REQUEST = Decimal("0.005")
# Free monthly credit allowance shown on the Brave dashboard.
FREE_CREDITS_USD = Decimal("5.00")
# Vendor exhaustion markers observed in Brave error bodies. A non-429
# response carrying one of these codes is a quota-exhausted signal.
BRAVE_EXHAUSTION_BODY_CODES = frozenset(
    {"CREDIT_EXHAUSTED", "QUOTA_LIMITED", "USAGE_LIMIT_EXCEEDED"}
)


def _string_has_exhaustion_code(value: str) -> bool:
    """Return True when raw text carries a known exhaustion marker."""
    return any(code in value for code in BRAVE_EXHAUSTION_BODY_CODES)


def brave_spend_usd(success_count: int | Decimal) -> Decimal:
    """Return derived USD spend for a count of Brave REQUEST successes."""
    if isinstance(success_count, bool):
        raise TypeError("success count must be an int or Decimal, not bool")
    if isinstance(success_count, int):
        if success_count < 0:
            raise ValueError("success count must be non-negative")
        count = Decimal(success_count)
    elif isinstance(success_count, Decimal):
        if not success_count.is_finite():
            raise ValueError("success count must be finite")
        if success_count < 0:
            raise ValueError("success count must be non-negative")
        if success_count != success_count.to_integral_value():
            raise ValueError("success count must be integral")
        count = success_count
    else:
        raise TypeError("success count must be an int or Decimal")
    return COST_USD_PER_REQUEST * count


def brave_cost_metadata(
    success_count: int | Decimal | None = None,
) -> dict[str, Decimal]:
    """Return Brave spend metadata without touching throttle fields."""
    metadata: dict[str, Decimal] = {
        "cost_per_req": COST_USD_PER_REQUEST,
        "allowance_usd": FREE_CREDITS_USD,
    }
    if success_count is not None:
        metadata["spend_usd"] = brave_spend_usd(success_count)
    return metadata


def monthly_header_value(value: str | None) -> int | None:
    """Return the non-negative monthly element from a Brave comma pair."""

    if value is None:
        return None
    parts = value.split(",")
    if len(parts) < 2:
        return None
    raw = parts[1].strip()
    if not raw:
        return None
    try:
        parsed = int(raw)
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


parse_monthly_element = monthly_header_value


class BraveAdapter(ProviderAdapter):
    """Normalize Brave web search responses without owning client lifecycle."""

    def __init__(self, client: httpx.AsyncClient, *, runner: ResilientRunner | None = None) -> None:
        resolved = get_provider_secret_resolver().get(ProviderName.BRAVE)
        if resolved is None:
            raise self._error("configuration_error", "no Brave API key configured")
        self._client = client
        self._runner = runner or ResilientRunner(client)
        self._api_key: SecretStr = resolved
        self._last_quota = self._empty_quota()

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
                raise self._http_error(response)
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
        snapshot = self._quota_snapshot(response)
        self._last_quota = snapshot
        return SearchResponse(
            query=request.query,
            provider=self.name,
            results=normalized,
            total_results=len(normalized),
            usage=self._usage_event(response),
            quota_snapshot=snapshot,
        )

    def quota_after_success(self, response: SearchResponse) -> QuotaSnapshot:
        """Project monthly rate-limit headers observed on a successful search."""

        return response.quota_snapshot or self._last_quota

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
            unit_kind=UnitKind.REQUEST,
            display_unit="requests",
            observed_at=datetime.now(UTC),
            metadata=metadata,
        )

    def _base_metadata(self) -> dict[str, Any]:
        metadata: dict[str, Any] = {"window": "monthly"}
        metadata.update(brave_cost_metadata())
        return metadata

    def _quota_snapshot(self, response: httpx.Response) -> QuotaSnapshot:
        observed_at = datetime.now(UTC)
        remaining = monthly_header_value(response.headers.get("X-RateLimit-Remaining"))
        limit = monthly_header_value(response.headers.get("X-RateLimit-Limit"))
        reset = monthly_header_value(response.headers.get("X-RateLimit-Reset"))
        if limit == Decimal("0"):
            return QuotaSnapshot(
                provider=self.name,
                source=QuotaSource.OBSERVED,
                remaining=None,
                limit=None,
                reset_at=None,
                observed_at=observed_at,
                unit_kind=UnitKind.REQUEST,
                display_unit="requests",
                metadata=self._base_metadata(),
            )
        return QuotaSnapshot(
            provider=self.name,
            source=QuotaSource.OBSERVED,
            remaining=Decimal(remaining) if remaining is not None else None,
            limit=Decimal(limit) if limit is not None else None,
            reset_at=observed_at + timedelta(seconds=reset) if reset is not None else None,
            observed_at=observed_at,
            unit_kind=UnitKind.REQUEST,
            display_unit="requests",
            metadata=self._base_metadata(),
        )

    def _empty_quota(self) -> QuotaSnapshot:
        return QuotaSnapshot(
            provider=self.name,
            source=QuotaSource.OBSERVED,
            remaining=None,
            limit=None,
            reset_at=None,
            observed_at=datetime.now(UTC),
            unit_kind=UnitKind.REQUEST,
            display_unit="requests",
            metadata=self._base_metadata(),
        )

    @staticmethod
    def _rate_limit_remaining(value: str | None) -> int | None:
        if value is None:
            return None
        # Brave may expose either a bare value (legacy responses) or the
        # documented ``per-second, monthly`` pair.  Usage telemetry records
        # the per-second headroom; the quota snapshot separately records the
        # monthly element via ``monthly_header_value``.
        raw = value.split(",", 1)[0].strip()
        if not raw:
            return None
        try:
            remaining = int(raw)
        except (TypeError, ValueError):
            return None
        return remaining if remaining >= 0 else None

    async def quota_after_error(self, status: int | None) -> QuotaSnapshot | None:
        """Persist a 402 exhaustion observation without inventing a limit."""
        if status != 402:
            return None
        previous = self._last_quota
        limit = previous.limit if previous is not None else None
        if limit is not None and limit <= 0:
            limit = None
        metadata = self._base_metadata()
        metadata["exhaustion"] = True
        metadata["exhaustion_status"] = status
        snapshot = QuotaSnapshot(
            provider=self.name,
            source=QuotaSource.OBSERVED,
            remaining=Decimal("0"),
            limit=limit,
            reset_at=None,
            observed_at=datetime.now(UTC),
            unit_kind=UnitKind.REQUEST,
            display_unit="requests",
            metadata=metadata,
        )
        self._last_quota = snapshot
        return snapshot

    def _http_error(self, response: httpx.Response) -> ProviderOperationError:
        status = response.status_code
        if status != 429 and self._is_quota_exhaustion(response):
            return self._error(
                "quota_exhausted",
                f"HTTP {status}",
                retryable=False,
                status=status,
            )
        if status == 402:
            return self._error(
                "quota_exhausted",
                f"HTTP {status}",
                retryable=False,
                status=status,
            )
        return self._error(
            "http_error",
            f"HTTP {status}",
            retryable=status in _RETRYABLE_STATUS_CODES,
            status=status,
        )

    def _is_quota_exhaustion(self, response: httpx.Response) -> bool:
        """Return True when the body carries a known exhaustion marker."""
        try:
            payload: Any = response.json()
        except Exception:
            payload = None
        if payload is not None and self._payload_has_exhaustion_code(payload):
            return True
        try:
            text = response.text
        except Exception:
            return False
        return _string_has_exhaustion_code(text)

    @staticmethod
    def _payload_has_exhaustion_code(payload: Any) -> bool:
        stack: list[Any] = [payload]
        while stack:
            current = stack.pop()
            if isinstance(current, str):
                if _string_has_exhaustion_code(current):
                    return True
            elif isinstance(current, dict):
                stack.extend(current.values())
            elif isinstance(current, list):
                stack.extend(current)
        return False

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
