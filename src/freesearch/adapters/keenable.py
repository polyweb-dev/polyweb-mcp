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
    QuotaSnapshot,
    QuotaSource,
    SearchRequest,
    SearchResponse,
    SearchResult,
    UnitKind,
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


def _month_start(value: datetime) -> datetime:
    return datetime(value.year, value.month, 1, tzinfo=UTC)


def _next_month_start(value: datetime) -> datetime:
    if value.month == 12:
        return datetime(value.year + 1, 1, 1, tzinfo=UTC)
    return datetime(value.year, value.month + 1, 1, tzinfo=UTC)


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
        self._allowance_limit = Decimal("100000")
        self._allowance_spend = Decimal("0")
        self._paid_spend = Decimal("0")
        self._paid_usage_seen = False
        self._hard_exhausted = False
        self._ledger_month = _month_start(datetime.now(UTC))
        self._hydrated_month: datetime | None = None

    @property
    def name(self) -> str:
        return _NAME

    @property
    def capabilities(self) -> ProviderCapabilities:
        keyed, _headers = self._auth()
        return ProviderCapabilities(
            search=True, fetch=True, cost_estimate=True, quota=keyed == _KEYED
        )

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
                usage=self._usage_event(UsageOperation.SEARCH, payload),
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
                usage=self._usage_event(UsageOperation.FETCH, payload),
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
        keyed, _headers = self._auth()
        amount = Decimal("0.004") if keyed == _KEYED else Decimal("0")
        return CostEstimate(
            provider=self.name,
            operation=operation,
            units=amount,
            currency="USD",
            notes="estimated keyed cloud request price" if amount else "keyless public tier",
        )

    def _usage_event(
        self, operation: UsageOperation, payload: dict[str, Any] | None = None
    ) -> UsageEvent:
        mode, _headers = self._auth()
        if mode != _KEYED:
            return UsageEvent(
                provider=self.name,
                operation=operation,
                units=Decimal("0"),
                unit_kind=UnitKind.FREE,
                display_unit="free",
                observed_at=datetime.now(UTC),
                metadata={"mode": mode},
            )
        credits, paid, metadata = self._reported_usage(payload)
        self.apply_usage(credits=credits, paid=paid)
        return UsageEvent(
            provider=self.name,
            operation=operation,
            units=credits,
            unit_kind=UnitKind.CREDIT,
            display_unit="credits",
            observed_at=datetime.now(UTC),
            metadata={"mode": mode, **metadata},
        )

    @staticmethod
    def _reported_usage(payload: dict[str, Any] | None) -> tuple[Decimal, bool, dict[str, Any]]:
        raw = payload.get("_meta", {}).get("keenable/usage") if payload else None
        if not isinstance(raw, dict):
            return Decimal("1"), False, {}
        credits = raw.get("credits", raw.get("amount", 1))
        if isinstance(credits, bool):
            raise ValueError("malformed Keenable usage")
        try:
            parsed = Decimal(str(credits))
        except (ArithmeticError, ValueError):
            raise ValueError("malformed Keenable usage") from None
        if not parsed.is_finite() or parsed < 0:
            raise ValueError("malformed Keenable usage")
        paid = raw.get("paid", False)
        if not isinstance(paid, bool):
            raise ValueError("malformed Keenable usage")
        metadata = {key: raw[key] for key in ("sku", "paid") if key in raw}
        return parsed, paid, metadata

    async def hydrate_quota(self, repository: Any) -> QuotaSnapshot | None:
        """Restore keyed allowance counters from the current month's ledger."""

        mode, _headers = self._auth()
        if mode != _KEYED:
            return None
        now = datetime.now(UTC)
        month_start = _month_start(now)
        self._rollover_if_needed(now)
        if self._hydrated_month == month_start:
            return None
        latest = await repository.latest_quota(self.name)
        events = await repository.list_usage(provider=self.name)
        current = [
            event
            for event in events
            if event.observed_at >= month_start
            and event.status.value == "success"
            and event.unit_kind is UnitKind.CREDIT
        ]
        self._allowance_spend = sum(
            (event.units for event in current if event.metadata.get("paid") is not True),
            Decimal("0"),
        )
        self._paid_spend = sum(
            (event.units for event in current if event.metadata.get("paid") is True),
            Decimal("0"),
        )
        self._paid_usage_seen = any(event.metadata.get("paid") is True for event in current)
        later_success = any(
            event.observed_at > latest.observed_at for event in current if latest is not None
        )
        self._hard_exhausted = bool(
            latest is not None
            and latest.remaining == Decimal("0")
            and not later_success
            and latest.observed_at >= month_start
        )
        self._hydrated_month = month_start
        return self._snapshot_sync()

    async def quota(self) -> QuotaSnapshot | None:
        """Return the keyed local monthly allowance; keyless has no quota."""

        mode, _headers = self._auth()
        if mode != _KEYED:
            return None
        self._rollover_if_needed(datetime.now(UTC))
        return self._snapshot_sync()

    async def quota_after_success(self, response: object) -> QuotaSnapshot | None:
        del response
        return await self.quota()

    async def quota_after_error(self, status: int | None) -> QuotaSnapshot | None:
        if status == 402 and self._auth()[0] == _KEYED:
            self._hard_exhausted = True
            return await self.quota()
        return None

    def apply_usage(self, *, credits: Decimal, paid: bool = False) -> QuotaSnapshot | None:
        """Apply a reported paid/free usage detail without mixing counters."""

        mode, _headers = self._auth()
        if mode != _KEYED:
            return None
        self._rollover_if_needed(datetime.now(UTC))
        if credits < 0:
            raise ValueError("usage credits must be non-negative")
        if paid:
            self._paid_spend += credits
            self._paid_usage_seen = True
        else:
            self._allowance_spend += credits
        return self._snapshot_sync()

    def _rollover_if_needed(self, now: datetime) -> None:
        month = _month_start(now)
        if month == self._ledger_month:
            return
        self._ledger_month = month
        self._allowance_spend = Decimal("0")
        self._paid_spend = Decimal("0")
        self._paid_usage_seen = False
        self._hard_exhausted = False
        self._hydrated_month = None

    def _snapshot_sync(self) -> QuotaSnapshot:
        remaining = (
            None
            if self._paid_usage_seen
            else (
                Decimal("0")
                if self._hard_exhausted
                else max(Decimal("0"), self._allowance_limit - self._allowance_spend)
            )
        )
        observed_at = datetime.now(UTC)
        metadata: dict[str, object] = {
            "free": max(Decimal("0"), self._allowance_limit - self._allowance_spend),
            "free_spend": self._allowance_spend,
            "soft_zero": False,
        }
        if self._paid_usage_seen:
            metadata["paid"] = self._paid_spend
            metadata["paid_spend"] = self._paid_spend
        return QuotaSnapshot(
            provider=self.name,
            source=QuotaSource.OBSERVED,
            remaining=remaining,
            limit=self._allowance_limit,
            reset_at=_next_month_start(observed_at),
            observed_at=observed_at,
            unit_kind=UnitKind.CREDIT,
            display_unit="credits",
            metadata=metadata,
        )

    def _http_error(self, response: httpx.Response) -> ProviderOperationError:
        status = response.status_code
        return self._error(
            "quota_exhausted" if status == 402 else "http_error",
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
