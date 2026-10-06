"""Brave Search API adapter using the shared HTTP and resilience contracts."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import httpx
from pydantic import SecretStr

from freesearch.adapters.base import ProviderAdapter
from freesearch.infrastructure.resilience import (
    RETRYABLE_STATUS_CODES,
    ProviderOperationError,
    ResilientRunner,
)
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
from freesearch.models.provider_limits import (
    AuthMode,
    Confidence,
    LimitOperation,
    NativeUsageSnapshot,
    RateObservation,
    RateUnit,
    RateWindowName,
    UsageSyncRequest,
    native_pool_id,
)

_NAME = "brave"
_SEARCH_URL = "https://api.search.brave.com/res/v1/web/search"
_MAX_SEARCH_RESULTS = 20

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
# Implied monthly request allowance derived from the dashboard pricing facts
# ($5.00 free credits at $0.005/request). Used only when the vendor never
# reported a monthly limit; snapshots built on it are ESTIMATED and flagged
# in metadata so they are never mistaken for a vendor balance.
_IMPLIED_MONTHLY_LIMIT = FREE_CREDITS_USD / COST_USD_PER_REQUEST
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


def _month_start(value: datetime) -> datetime:
    return datetime(value.year, value.month, 1, tzinfo=UTC)


def _next_month_start(value: datetime) -> datetime:
    if value.month == 12:
        return datetime(value.year + 1, 1, 1, tzinfo=UTC)
    return datetime(value.year, value.month + 1, 1, tzinfo=UTC)


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

    def __init__(
        self,
        client: httpx.AsyncClient,
        *,
        runner: ResilientRunner | None = None,
        api_key: SecretStr | None = None,
    ) -> None:
        resolved = api_key
        if resolved is None:
            raise self._error("configuration_error", "no Brave API key configured")
        self._client = client
        self._runner = runner or ResilientRunner(client)
        self._api_key: SecretStr = resolved
        self._last_quota = self._empty_quota()
        # Local monthly counter. Header-reported monthly values re-anchor it
        # whenever present; otherwise the counter tracks usage against the
        # last header-seeded limit (or the implied pricing-derived limit).
        # The calendar-month boundary is provisional until the vendor reset
        # day is verified; a header-reported reset always wins for reset_at.
        self._monthly_limit: Decimal | None = None
        self._monthly_limit_implied = True
        self._monthly_used = Decimal("0")
        self._ledger_month = _month_start(datetime.now(UTC))
        self._hydrated_month: datetime | None = None
        # The burst element of the rate-limit comma pair is a one-second rate
        # observation only. It never enters the monthly budget figures.
        self._burst_remaining: int | None = None
        self._burst_observed_at: datetime | None = None
        # True once a monthly header element or a vendor exhaustion arrived, so
        # a projection cannot replace a vendor observation.
        self._monthly_observed = False

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
        response = await self._client.send(wire_request, auth=None, follow_redirects=False)
        # Brave splits its 429 answer: RATE_LIMITED means rate pressure, and
        # QUOTA_LIMITED means a spent budget. The budget answer is final, so it
        # leaves this closure as a normalized non-retryable error and never
        # reaches the shared retry policy. A rate answer keeps its status, its
        # Retry-After header, and the unchanged runner policy.
        if response.status_code == 429 and self._is_quota_exhaustion(response):
            raise self._http_error(response)
        return response

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
        # Count the just-completed request before projecting the snapshot so
        # the monthly ledger includes it (matches Keenable's usage-first order).
        usage = self._usage_event(response)
        snapshot = self._quota_snapshot(response)
        self._last_quota = snapshot
        return SearchResponse(
            query=request.query,
            provider=self.name,
            results=normalized,
            total_results=len(normalized),
            usage=usage,
            quota_snapshot=snapshot,
        )

    def quota_after_success(self, response: SearchResponse) -> QuotaSnapshot:
        """Project monthly rate-limit headers observed on a successful search."""

        return response.quota_snapshot or self._last_quota

    async def hydrate_quota(self, repository: Any) -> QuotaSnapshot | None:
        """Restore the monthly counter after an adapter or process restart."""

        now = datetime.now(UTC)
        month_start = _month_start(now)
        self._rollover_if_needed(now)
        if self._hydrated_month == month_start:
            return None
        latest = await repository.latest_quota(self.name)
        if (
            latest is not None
            and latest.limit is not None
            and latest.limit > 0
            and latest.unit_kind is UnitKind.REQUEST
            and latest.observed_at >= month_start
            and not latest.metadata.get("limit_implied")
        ):
            self._monthly_limit = latest.limit
            self._monthly_limit_implied = False
        events = await repository.list_usage(provider=self.name)
        used = Decimal("0")
        for event in events:
            if (
                event.observed_at >= month_start
                and event.status.value == "success"
                and event.unit_kind is UnitKind.REQUEST
            ):
                used += event.units
        self._monthly_used = used
        self._hydrated_month = month_start
        return self._snapshot_from_counter(now, None)

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

    def _rollover_if_needed(self, now: datetime) -> None:
        month = _month_start(now)
        if month == self._ledger_month:
            return
        self._ledger_month = month
        self._monthly_used = Decimal("0")
        self._hydrated_month = None
        # A new month voids the previous month's observation and burst headroom.
        self._monthly_observed = False
        self._burst_remaining = None
        self._burst_observed_at = None

    def _usage_event(self, response: httpx.Response) -> UsageEvent:
        self._rollover_if_needed(datetime.now(UTC))
        self._monthly_used += Decimal("1")
        metadata: dict[str, int] = {}
        remaining = self._rate_limit_remaining(response.headers.get("X-RateLimit-Remaining"))
        if remaining is not None:
            metadata["rate_limit_remaining"] = remaining
            self._burst_remaining = remaining
            self._burst_observed_at = datetime.now(UTC)
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

    def _snapshot_from_counter(self, observed_at: datetime, reset: int | None) -> QuotaSnapshot:
        """Project the local monthly counter when headers carry no monthly pair."""

        limit = self._monthly_limit
        implied = True
        if limit is not None:
            implied = self._monthly_limit_implied
        else:
            limit = _IMPLIED_MONTHLY_LIMIT
        remaining = max(Decimal("0"), limit - self._monthly_used)
        metadata = self._base_metadata()
        if implied:
            metadata["limit_implied"] = True
        return QuotaSnapshot(
            provider=self.name,
            source=QuotaSource.ESTIMATED if implied else QuotaSource.OBSERVED,
            remaining=remaining,
            limit=limit,
            reset_at=(
                observed_at + timedelta(seconds=reset)
                if reset is not None
                else _next_month_start(observed_at)
            ),
            observed_at=observed_at,
            unit_kind=UnitKind.REQUEST,
            display_unit="requests",
            metadata=metadata,
        )

    def _quota_snapshot(self, response: httpx.Response) -> QuotaSnapshot:
        observed_at = datetime.now(UTC)
        self._rollover_if_needed(observed_at)
        remaining = monthly_header_value(response.headers.get("X-RateLimit-Remaining"))
        limit = monthly_header_value(response.headers.get("X-RateLimit-Limit"))
        reset = monthly_header_value(response.headers.get("X-RateLimit-Reset"))
        if any(value is not None for value in (remaining, limit, reset)):
            self._monthly_observed = True
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
        if limit is not None:
            # A vendor-reported monthly limit re-anchors the local ledger:
            # seed the limit once, then per-request counting tracks usage.
            self._monthly_limit = Decimal(limit)
            self._monthly_limit_implied = False
        if remaining is not None and limit is not None:
            self._monthly_used = max(Decimal("0"), Decimal(limit) - Decimal(remaining))
            return QuotaSnapshot(
                provider=self.name,
                source=QuotaSource.OBSERVED,
                remaining=Decimal(remaining),
                limit=Decimal(limit),
                reset_at=observed_at + timedelta(seconds=reset) if reset is not None else None,
                observed_at=observed_at,
                unit_kind=UnitKind.REQUEST,
                display_unit="requests",
                metadata=self._base_metadata(),
            )
        if remaining is not None and self._monthly_limit is not None:
            # Vendor remaining against a previously seeded limit: re-anchor.
            self._monthly_used = max(Decimal("0"), self._monthly_limit - Decimal(remaining))
            return QuotaSnapshot(
                provider=self.name,
                source=QuotaSource.OBSERVED,
                remaining=Decimal(remaining),
                limit=self._monthly_limit,
                reset_at=observed_at + timedelta(seconds=reset) if reset is not None else None,
                observed_at=observed_at,
                unit_kind=UnitKind.REQUEST,
                display_unit="requests",
                metadata=self._base_metadata(),
            )
        return self._snapshot_from_counter(observed_at, reset)

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
        self._monthly_observed = True
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

    async def usage_snapshot(self, request: UsageSyncRequest) -> NativeUsageSnapshot | None:
        """Return the observed USD budget of the Brave search rail.

        The adapter prices the monthly element of the rate-limit header pair
        with the documented per-request cost. The monthly pair element supplies
        the allowance and the remaining. The burst element of the same pair
        becomes a one-second rate observation only, never a budget figure. A
        request count the vendor never reported stays absent.
        """

        auth_mode = self.limit_auth_mode
        observed_at = request.observed_at
        self._rollover_if_needed(datetime.now(UTC))
        quota = (
            self._last_quota
            if self._monthly_observed
            else self._snapshot_from_counter(datetime.now(UTC), None)
        )
        limit = quota.limit
        # A figure is vendor-header sourced only when the vendor supplied the
        # monthly limit and no local projection stands behind the value.
        vendor_limit = self._monthly_limit is not None and not self._monthly_limit_implied
        from_headers = (
            vendor_limit and limit is not None and not bool(quota.metadata.get("limit_implied"))
        )
        return NativeUsageSnapshot(
            pool_id=native_pool_id(self.name, auth_mode, UnitKind.USD),
            provider=self.name,
            auth_mode=auth_mode,
            native_unit=UnitKind.USD,
            observed_at=observed_at,
            source="vendor_headers" if from_headers else "local_ledger",
            confidence=Confidence.OBSERVED if from_headers else Confidence.ESTIMATED,
            remaining=self._usd_from_requests(quota.remaining),
            allowance=self._usd_from_requests(limit),
            reset_at=quota.reset_at,
            credential_generation=request.credential_generation,
            rate_observations=self._burst_observations(auth_mode),
        )

    @staticmethod
    def _usd_from_requests(value: Decimal | None) -> Decimal | None:
        """Convert an integral request count to documented USD, else None."""

        if value is None or not value.is_finite() or value < 0:
            return None
        if value != value.to_integral_value():
            return None
        return brave_spend_usd(value)

    def _burst_observations(self, auth_mode: AuthMode) -> list[RateObservation]:
        """Return the last observed per-second burst headroom, if any."""

        remaining = self._burst_remaining
        observed_at = self._burst_observed_at
        if remaining is None or observed_at is None:
            return []
        return [
            RateObservation(
                bucket_id=f"{self.name}:{auth_mode.value}:search:{RateUnit.REQUESTS.value}",
                provider=self.name,
                auth_mode=auth_mode,
                window=RateWindowName.SECOND,
                unit=RateUnit.REQUESTS,
                remaining=Decimal(remaining),
                observed_at=observed_at,
                operation=LimitOperation.SEARCH,
                source="vendor_headers",
                confidence=Confidence.OBSERVED,
            )
        ]

    def _http_error(self, response: httpx.Response) -> ProviderOperationError:
        """Return the normalized error of one failed Brave response.

        A body marker or a 402 answer means a spent budget, so the error is
        final and keeps the vendor status. Every other answer is a transport
        error whose retryability follows the shared status policy.
        """

        status = response.status_code
        if status == 402 or self._is_quota_exhaustion(response):
            # An exhausted budget is never retried, and a 429 QUOTA_LIMITED
            # keeps its original vendor status in the record.
            return self._error(
                "quota_exhausted",
                f"HTTP {status}",
                retryable=False,
                status=status,
            )
        return self._error(
            "http_error",
            f"HTTP {status}",
            retryable=status in RETRYABLE_STATUS_CODES,
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
