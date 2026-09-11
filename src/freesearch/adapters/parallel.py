"""Parallel provider adapter: direct HTTPX against ``api.parallel.ai``, no SDK.

Wire calls go through the shared :class:`ResilientRunner`; the API key is
resolved once via the process-wide provider secret resolver (absent
credentials fail closed) and travels as a per-request ``x-api-key`` header.
Responses normalize to the shared contracts: ``search_id`` / ``extract_id``
map to the usage request id; any final non-2xx status is a typed error and
malformed payloads are the redaction-safe, non-retryable ``invalid_response``.
"""

import logging
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import httpx

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
    QuotaSource,
    SearchRequest,
    SearchResponse,
    SearchResult,
    UnitKind,
    UsageEvent,
    UsageOperation,
    parse_decimal,
)

logger = logging.getLogger(__name__)

__all__ = ["ParallelAdapter"]

_NAME = "parallel"
_SEARCH_URL = "https://api.parallel.ai/v1/search"
_EXTRACT_URL = "https://api.parallel.ai/v1/extract"
_RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})
_STATUS_ERROR_CODES = {
    400: "bad_request",
    401: "invalid_api_key",
    402: "insufficient_balance",
    403: "forbidden",
    422: "invalid_response",
}
SEARCH_USD_BY_MODE: dict[str, Decimal] = {
    "turbo": Decimal("0.001"),
    "basic": Decimal("0.005"),
    "advanced": Decimal("0.005"),
    "extra_bundle": Decimal("0.001"),
}


def _month_start(value: datetime) -> datetime:
    return datetime(value.year, value.month, 1, tzinfo=UTC)


def _month_end(value: datetime) -> datetime:
    if value.month == 12:
        return datetime(value.year + 1, 1, 1, tzinfo=UTC)
    return datetime(value.year, value.month + 1, 1, tzinfo=UTC)


def search_cost_usd(mode: str | None = None, extra_bundles: int = 0) -> Decimal:
    """Price a Parallel search using the documented mode and bundle table."""

    selected = "advanced" if mode in (None, "omitted") else mode
    if selected not in SEARCH_USD_BY_MODE:
        raise ValueError("unknown Parallel search mode")
    if extra_bundles < 0:
        raise ValueError("extra bundles must be non-negative")
    return SEARCH_USD_BY_MODE[selected] + SEARCH_USD_BY_MODE["extra_bundle"] * Decimal(
        extra_bundles
    )


def extract_cost_usd(url_count: int) -> Decimal:
    """Price Parallel extraction at one thousandth of a dollar per URL."""

    if url_count < 0:
        raise ValueError("url_count must be non-negative")
    return Decimal("0.001") * Decimal(url_count)


def parse_seed(value: Decimal | None) -> Decimal | None:
    """Validate an optional exact, non-negative local seed."""

    return None if value is None else parse_decimal(value)


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
        free_seed: Decimal | None = None,
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
        self._free_seed = parse_seed(free_seed)
        self._spend = Decimal("0")
        self._soft_zero = False
        self._ledger_month = _month_start(datetime.now(UTC))
        self._hydrated_seed: Decimal | None = None
        self._hydrated_month: datetime | None = None

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
        if request.mode is not None:
            settings["mode"] = request.mode
        if request.extra_bundles:
            settings["extra_bundles"] = request.extra_bundles
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
            usage=self._usage_event(
                payload,
                UsageOperation.SEARCH,
                request_id,
                mode=request.mode,
                extra_bundles=request.extra_bundles,
            ),
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
            usage=self._usage_event(
                payload,
                UsageOperation.FETCH,
                request_id,
                url_count=request.url_count,
            ),
        )

    def _matching_result(self, results: list[Any], target: str) -> dict[str, Any]:
        for item in results:
            if isinstance(item, dict) and str(item.get("url") or "") == target:
                return item
        raise self._error("fetch_failed", "no successful extraction result") from None

    async def estimate_cost(self, request: SearchRequest | FetchRequest) -> CostEstimate:
        if isinstance(request, SearchRequest):
            units = search_cost_usd(request.mode, request.extra_bundles)
            operation = UsageOperation.SEARCH
            notes = "mode-aware local estimate"
        else:
            count = int(getattr(request, "url_count", 1))
            units = extract_cost_usd(count)
            operation = UsageOperation.FETCH
            notes = "estimated per extracted URL"
        return CostEstimate(
            provider=self.name,
            operation=operation,
            units=units,
            currency="USD",
            notes=notes,
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
        self,
        payload: dict[str, Any],
        operation: UsageOperation,
        request_id: str | None,
        *,
        mode: str | None = None,
        extra_bundles: int = 0,
        url_count: int = 1,
    ) -> UsageEvent | None:
        """Sum documented ``usage`` SKU counts; malformed usage is invalid_response."""
        usage = payload.get("usage")
        if usage is None:
            return None
        if not isinstance(usage, list) or any(not isinstance(e, dict) for e in usage):
            raise self._error("invalid_response", "malformed usage in response")
        units = Decimal(0)
        skus: list[dict[str, object]] = []
        for entry in usage:
            count = entry.get("count")
            if isinstance(count, bool) or not isinstance(count, (int, float)):
                raise self._error("invalid_response", "malformed usage in response")
            sku = entry.get("sku", entry.get("name"))
            if not isinstance(sku, str) or not sku:
                raise self._error("invalid_response", "malformed usage in response")
            amount = Decimal(str(count))
            if not amount.is_finite() or amount < 0:
                raise self._error("invalid_response", "malformed usage in response")
            units += amount
            skus.append({"sku": sku, "count": amount})
        metadata: dict[str, Any] = {"skus": skus}
        if operation is UsageOperation.SEARCH:
            metadata.update({"mode": mode or "advanced", "extra_bundles": extra_bundles})
        else:
            metadata["url_count"] = url_count
        return UsageEvent(
            provider=self.name,
            operation=operation,
            units=units,
            unit_kind=UnitKind.REQUEST,
            display_unit="requests",
            observed_at=datetime.now(UTC),
            request_id=request_id,
            metadata=metadata,
        )

    async def quota(self) -> QuotaSnapshot | None:
        """Return the local opt-in seed ledger, never an OAuth balance poll."""

        if self._free_seed is None:
            return None
        self._rollover_if_needed(datetime.now(UTC))
        return self._local_snapshot()

    def set_free_seed(self, seed: Decimal | None) -> None:
        """Apply a validated local seed without changing provider capabilities."""

        parsed = parse_seed(seed)
        if parsed == self._free_seed:
            return
        self._free_seed = parsed
        self._spend = Decimal("0")
        self._soft_zero = False
        self._ledger_month = _month_start(datetime.now(UTC))
        self._hydrated_seed = None
        self._hydrated_month = None

    async def hydrate_quota(self, repository: Any) -> QuotaSnapshot | None:
        """Rebuild local spend from the current-month snapshot and USD ledger."""

        if self._free_seed is None:
            return None
        now = datetime.now(UTC)
        month_start = _month_start(now)
        self._rollover_if_needed(now)
        if self._hydrated_seed == self._free_seed and self._hydrated_month == month_start:
            return None
        snapshot = await repository.latest_quota(self.name)
        events = await repository.list_usage(provider=self.name)
        current_events = [
            event
            for event in events
            if event.observed_at >= month_start and event.status.value == "success"
        ]
        ledger_spend = sum((self._event_spend(event) for event in current_events), Decimal("0"))
        snapshot_spend = self._snapshot_spend(snapshot)
        if snapshot is not None and self._snapshot_expired(snapshot, now):
            snapshot_spend = Decimal("0")
            self._soft_zero = False
        later_spend = sum(
            (
                self._event_spend(event)
                for event in current_events
                if snapshot is None or event.observed_at > snapshot.observed_at
            ),
            Decimal("0"),
        )
        self._spend = max(ledger_spend, snapshot_spend + later_spend)
        if snapshot is not None:
            self._soft_zero = bool(snapshot.metadata.get("soft_zero", False))
            if later_spend > 0:
                self._soft_zero = False
        self._hydrated_seed = self._free_seed
        self._hydrated_month = month_start
        return self._local_snapshot()

    def record_success_spend(self, amount: Decimal) -> QuotaSnapshot | None:
        """Record successful local spend, materializing only seeded balances."""

        parsed = parse_decimal(amount)
        if self._free_seed is None:
            return None
        self._rollover_if_needed(datetime.now(UTC))
        self._spend += parsed
        self._soft_zero = False
        return self._local_snapshot()

    def quota_after_success(
        self, response: object, *, operation: UsageOperation | None = None
    ) -> QuotaSnapshot | None:
        usage = getattr(response, "usage", None)
        reported = getattr(usage, "operation", None)
        selected = operation or (
            reported if isinstance(reported, UsageOperation) else UsageOperation.SEARCH
        )
        amount = self._project_success_spend(usage, selected)
        return self.record_success_spend(amount)

    @staticmethod
    def _project_success_spend(usage: object, operation: UsageOperation) -> Decimal:
        metadata = getattr(usage, "metadata", {})
        if not isinstance(metadata, dict):
            metadata = {}
        if operation is UsageOperation.FETCH:
            count = metadata.get("url_count", 1)
            return extract_cost_usd(int(count))
        mode = metadata.get("mode")
        bundles = metadata.get("extra_bundles", 0)
        if isinstance(mode, str) and mode not in SEARCH_USD_BY_MODE and mode != "omitted":
            logger.warning("skipping Parallel usage with unknown legacy mode: %s", mode)
            return Decimal("0")
        try:
            return search_cost_usd(mode if isinstance(mode, str) else None, int(bundles))
        except (TypeError, ValueError):
            logger.warning("skipping malformed Parallel usage pricing metadata")
            return Decimal("0")

    def quota_after_error(self, status: int | None) -> QuotaSnapshot | None:
        if status != 402 or self._free_seed is None:
            return None
        self._soft_zero = True
        return self._local_snapshot()

    def _rollover_if_needed(self, now: datetime) -> None:
        month = _month_start(now)
        if month != self._ledger_month:
            self._ledger_month = month
            self._spend = Decimal("0")
            self._soft_zero = False
            self._hydrated_month = None

    @staticmethod
    def _event_spend(event: UsageEvent) -> Decimal:
        if event.unit_kind is UnitKind.USD:
            return event.units
        if event.unit_kind is not UnitKind.REQUEST:
            return Decimal("0")
        metadata = event.metadata
        if not isinstance(metadata.get("skus"), list):
            return Decimal("0")
        if event.operation is UsageOperation.FETCH:
            return extract_cost_usd(int(metadata.get("url_count", 1)))
        mode = metadata.get("mode")
        bundles = metadata.get("extra_bundles", 0)
        if isinstance(mode, str) and mode not in SEARCH_USD_BY_MODE and mode != "omitted":
            logger.warning("skipping Parallel usage with unknown legacy mode: %s", mode)
            return Decimal("0")
        try:
            return search_cost_usd(mode if isinstance(mode, str) else None, int(bundles))
        except (TypeError, ValueError):
            logger.warning("skipping malformed Parallel usage pricing metadata")
            return Decimal("0")

    def _snapshot_spend(self, snapshot: QuotaSnapshot | None) -> Decimal:
        if snapshot is None or snapshot.remaining is None or self._free_seed is None:
            return Decimal("0")
        return max(Decimal("0"), self._free_seed - snapshot.remaining)

    @staticmethod
    def _snapshot_expired(snapshot: QuotaSnapshot, now: datetime) -> bool:
        return _month_start(snapshot.observed_at) != _month_start(now) or (
            snapshot.reset_at is not None and now >= snapshot.reset_at
        )

    def _local_snapshot(self) -> QuotaSnapshot:
        seed = self._free_seed
        assert seed is not None
        remaining = Decimal("0") if self._soft_zero else max(Decimal("0"), seed - self._spend)
        observed_at = datetime.now(UTC)
        return QuotaSnapshot(
            provider=self.name,
            source=QuotaSource.ESTIMATED,
            remaining=remaining,
            limit=seed,
            reset_at=_month_end(observed_at),
            observed_at=observed_at,
            unit_kind=UnitKind.USD,
            display_unit="USD",
            metadata={"soft_zero": self._soft_zero, "window": "monthly"},
        )

    def _error(
        self, code: str, message: str, *, retryable: bool = False, status: int | None = None
    ) -> ProviderOperationError:
        error = ProviderError(
            provider=self.name, code=code, message=message, retryable=retryable, status_code=status
        )
        return ProviderOperationError(error)
