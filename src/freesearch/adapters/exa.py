"""Exa provider adapter built on the official ``exa-py`` async SDK.

The adapter wraps every SDK call in the shared :class:`ResilientRunner` and
resolves the API key only through the process-wide provider secret resolver.
The SDK owns its HTTPX client (``AsyncExa.client``), created lazily with the
resolver key, so the caller's shared client is never mutated or closed; the
adapter closes the SDK-owned client in :meth:`aclose`. Exa exposes no quota
endpoint, so :meth:`quota` stays inherited (``None``), and request-cost
evidence is surfaced only from the ``costDollars`` telemetry the API reports
per response - never fabricated.
"""

import re
from datetime import UTC, datetime
from decimal import Decimal
from math import isfinite
from typing import Any, cast
from urllib.parse import urlsplit

import httpx
from exa_py import AsyncExa
from exa_py.api import Result
from exa_py.api import SearchResponse as ExaSearchResponse
from pydantic import AnyHttpUrl

from freesearch.adapters.base import ProviderAdapter
from freesearch.configuration.provider_config import get_provider_secret_resolver
from freesearch.infrastructure.dates import parse_iso_datetime
from freesearch.infrastructure.resilience import (
    RETRYABLE_STATUS_CODES,
    ProviderOperationError,
    ResilientRunner,
)
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
)

__all__ = ["EXA_DEFAULT_MONTHLY_BUDGET_USD", "ExaAdapter"]

_NAME = "exa"
EXA_DEFAULT_MONTHLY_BUDGET_USD = Decimal("10.00")
# The SDK surfaces HTTP failures as ``ValueError("Request failed with status
# code {status}: {body}")``; only the status code is parsed out - the body is
# never included so provider text cannot leak.
_SDK_STATUS_RE = re.compile(r"Request failed with status code (\d+)")


def _parse_published_at(value: str | None) -> datetime | None:
    """Parse Exa's ISO-8601 ``published_date``; unparseable values are None."""
    return parse_iso_datetime(value)


def _same_url(left: str, right: str) -> bool:
    """Compare URLs case-insensitively for scheme/host, path/query case preserved.

    An empty path is treated as equal to ``/``: pydantic normalizes
    ``AnyHttpUrl("https://example.com")`` to a trailing slash while the SDK
    echoes the URL exactly as requested.
    """
    try:
        left_parts, right_parts = urlsplit(left), urlsplit(right)
    except ValueError:
        return left == right
    return (
        left_parts.scheme.lower() == right_parts.scheme.lower()
        and left_parts.netloc.lower() == right_parts.netloc.lower()
        and _path_without_root_slash(left_parts.path) == _path_without_root_slash(right_parts.path)
        and left_parts.query == right_parts.query
        and left_parts.fragment == right_parts.fragment
    )


def _path_without_root_slash(path: str) -> str:
    """The path with a root-only ``/`` normalized to the empty string."""
    return "" if path == "/" else path


def _month_start(value: datetime) -> datetime:
    return datetime(value.year, value.month, 1, tzinfo=UTC)


def _next_month_start(value: datetime) -> datetime:
    if value.month == 12:
        return datetime(value.year + 1, 1, 1, tzinfo=UTC)
    return datetime(value.year, value.month + 1, 1, tzinfo=UTC)


class ExaAdapter(ProviderAdapter):
    """Search, fetch, and cost operations against the Exa API."""

    def __init__(
        self,
        client: httpx.AsyncClient | None = None,
        *,
        runner: ResilientRunner | None = None,
        sdk_client: AsyncExa | None = None,
        monthly_budget: Decimal | None = None,
    ) -> None:
        """Wrap operations in the shared resilience runner.

        ``client`` is the caller-owned shared HTTPX client; when omitted the
        adapter creates a fallback client it owns and closes in
        :meth:`aclose`. ``sdk_client`` is a test-only seam replacing the real
        SDK client. The SDK owns its own HTTPX client carrying the resolver
        key; the caller's client is never mutated or closed here.
        ``monthly_budget`` seeds the local monthly USD spend allowance.
        """
        sdk = sdk_client or self._build_sdk()
        if client is None:
            client = httpx.AsyncClient()
            self._owns_client = True
        else:
            self._owns_client = False
        self._client = client
        self._runner = runner or ResilientRunner(client)
        self._sdk = sdk
        self._monthly_budget = (
            self._validate_budget(monthly_budget) if monthly_budget is not None else None
        )
        self._spend = Decimal("0")
        self._soft_zero = False
        self._ledger_month = _month_start(datetime.now(UTC))
        self._hydrated_month: datetime | None = None

    @staticmethod
    def _validate_budget(budget: Any) -> Decimal:
        if isinstance(budget, (bool, float)):
            raise ValueError("Exa budget must be an exact Decimal input")
        parsed = Decimal(str(budget)) if not isinstance(budget, Decimal) else budget
        if not parsed.is_finite() or parsed < 0:
            raise ValueError("Exa budget must be finite and non-negative")
        return parsed

    def set_monthly_budget(self, budget: Decimal | None) -> None:
        """Apply a validated local monthly budget without mutating other state."""
        parsed = self._validate_budget(budget) if budget is not None else None
        if parsed == self._monthly_budget:
            return
        self._monthly_budget = parsed
        self._spend = Decimal("0")
        self._soft_zero = False
        self._ledger_month = _month_start(datetime.now(UTC))
        self._hydrated_month = None

    def _rollover_if_needed(self, now: datetime) -> None:
        month = _month_start(now)
        if month == self._ledger_month:
            return
        self._ledger_month = month
        self._spend = Decimal("0")
        self._soft_zero = False
        self._hydrated_month = None

    def _current_snapshot(self, *, now: datetime | None = None) -> QuotaSnapshot | None:
        if self._monthly_budget is None:
            return None
        observed_at = now or datetime.now(UTC)
        self._rollover_if_needed(observed_at)
        metadata: dict[str, Any] = {
            "window": "monthly",
            "spend_usd": self._spend,
            "soft_zero": self._soft_zero,
        }

        limit = self._monthly_budget
        remaining = Decimal("0") if self._soft_zero else max(Decimal("0"), limit - self._spend)
        return QuotaSnapshot(
            provider=self.name,
            source=QuotaSource.ESTIMATED,
            remaining=remaining,
            limit=limit,
            unit_kind=UnitKind.USD,
            display_unit="USD",
            observed_at=observed_at,
            reset_at=_next_month_start(observed_at),
            metadata=metadata,
        )

    async def quota(self) -> QuotaSnapshot | None:
        """Return the current local monthly USD snapshot."""
        return self._current_snapshot()

    def quota_after_success(
        self, response: object, *, operation: UsageOperation | None = None
    ) -> QuotaSnapshot | None:
        """Update spend from response usage event and return updated snapshot."""
        usage = getattr(response, "usage", None)
        units = getattr(usage, "units", None)
        if units is not None and isinstance(units, Decimal) and units.is_finite() and units > 0:
            now = datetime.now(UTC)
            self._rollover_if_needed(now)
            self._spend += units
            self._soft_zero = False
        return self._current_snapshot()

    def quota_after_error(self, status: int | None) -> QuotaSnapshot | None:
        """Record soft zero on 402; 429 stays transient rate limit."""
        if status == 402:
            self._soft_zero = True
            return self._current_snapshot()
        return None

    async def hydrate_quota(self, repository: Any) -> QuotaSnapshot | None:
        """Restore monthly spend ledger from database usage events."""
        if self._monthly_budget is None:
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
            and event.unit_kind is UnitKind.USD
        ]
        self._spend = sum((event.units for event in current), Decimal("0"))
        later_success = any(
            event.observed_at > latest.observed_at for event in current if latest is not None
        )
        self._soft_zero = bool(
            latest is not None
            and latest.remaining == Decimal("0")
            and not later_success
            and latest.observed_at >= month_start
            and latest.metadata.get("soft_zero") is True
        )
        self._hydrated_month = month_start
        return self._current_snapshot(now=now)

    def _build_sdk(self) -> AsyncExa:
        """Build the official SDK with the resolver key.

        The key comes only from the shared resolver; absent credentials fail
        closed rather than letting the SDK fall back to ambient ``EXA_API_KEY``
        (the SDK raises ``ValueError`` for a missing key, which would surface
        as a confusing provider error).
        """
        resolved = get_provider_secret_resolver().get(ProviderName.EXA)
        if resolved is None:
            raise self._error("configuration_error", "no Exa API key configured")
        return AsyncExa(api_key=resolved.get_secret_value())

    async def aclose(self) -> None:
        """Close the SDK-owned HTTPX client and the fallback client if owned."""
        await self._sdk.client.aclose()
        if self._owns_client:
            await self._client.aclose()

    @property
    def name(self) -> str:
        return _NAME

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(search=True, fetch=True, quota=False)

    async def search(self, request: SearchRequest) -> SearchResponse:
        response = await self._runner.run(self.name, lambda: self._search_sdk(request))
        try:
            results = [self._normalize_result(item) for item in response.results]
            usage = self._usage_event(response, UsageOperation.SEARCH)
        except ProviderOperationError:
            raise
        except Exception:
            # A structurally malformed payload must not escape as a raw
            # AttributeError/ValidationError after the call succeeded.
            raise self._error("invalid_response", "malformed search response") from None
        return SearchResponse(
            query=request.query,
            provider=self.name,
            results=results,
            total_results=len(results),
            usage=usage,
        )

    async def _search_sdk(self, request: SearchRequest) -> ExaSearchResponse[Result]:
        kwargs: dict[str, Any] = {
            "query": request.query,
            "num_results": request.limit,
            "contents": {"highlights": True},
        }
        if request.domains:
            kwargs["include_domains"] = list(request.domains)
        try:
            return await self._sdk.search(**kwargs)
        except httpx.TransportError:
            raise  # the shared ResilientRunner normalizes transport failures
        except Exception as exc:
            raise self._normalize_error(exc) from None

    def _normalize_result(self, item: Result) -> SearchResult:
        highlights = item.highlights or []
        score = item.score
        if not isinstance(score, (int, float)) or not 0 <= score <= 1:
            score = None
        metadata: dict[str, Any] = {}
        for key in ("id", "favicon"):
            value = getattr(item, key, None)
            if value is not None:
                metadata[key] = value
        return SearchResult(
            title=item.title or "",
            url=cast(AnyHttpUrl, item.url),
            snippet=highlights[0] if highlights else (item.text or ""),
            published_at=_parse_published_at(item.published_date),
            score=score,
            metadata=metadata,
        )

    async def fetch(self, request: FetchRequest) -> FetchResponse:
        response = await self._runner.run(self.name, lambda: self._fetch_sdk(request))
        try:
            target = str(request.url)
            match = next(
                (r for r in response.results if _same_url(str(r.url or ""), target)),
                None,
            )
            if match is None:
                raise self._error("fetch_failed", "no successful contents result") from None
            # An explicit empty string is a valid (empty) document; a missing
            # or non-string text means the payload is malformed.
            content = match.text
            if not isinstance(content, str):
                raise self._error("invalid_response", "malformed fetch response")
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
            # AttributeError/TypeError/ValidationError after the call succeeded.
            raise self._error("invalid_response", "malformed fetch response") from None

    async def _fetch_sdk(self, request: FetchRequest) -> ExaSearchResponse[Result]:
        try:
            # get_contents has no return annotation in the SDK, so the result
            # is cast to the documented SearchResponse[Result] shape.
            return cast(
                ExaSearchResponse[Result],
                await self._sdk.get_contents([str(request.url)], text=True),
            )
        except httpx.TransportError:
            raise  # the shared ResilientRunner normalizes transport failures
        except Exception as exc:
            raise self._normalize_error(exc) from None

    async def estimate_cost(self, request: SearchRequest | FetchRequest) -> CostEstimate:
        operation = (
            UsageOperation.SEARCH if isinstance(request, SearchRequest) else UsageOperation.FETCH
        )
        return CostEstimate(
            provider=self.name,
            operation=operation,
            units=Decimal("0"),
            currency="USD",
            notes=(
                "Exa does not publish a per-request price; actual cost is "
                "reported per response in costDollars telemetry when present"
            ),
        )

    def _usage_event(
        self, response: ExaSearchResponse[Result], operation: UsageOperation
    ) -> UsageEvent | None:
        """Return an event only when the response reported real numeric cost.

        Exa reports a ``costDollars.total`` dollar figure per response. A
        malformed value (bool, non-finite, or otherwise not a real number) is
        surfaced as the redaction-safe ``invalid_response`` error; a negative
        figure is dropped. No cost evidence is ever fabricated.
        """
        cost = response.cost_dollars
        if cost is None:
            return None
        total = cost.total
        if isinstance(total, bool) or not isinstance(total, (int, float)) or not isfinite(total):
            raise self._error("invalid_response", "malformed cost in response")
        if total < 0:
            return None
        return UsageEvent(
            provider=self.name,
            operation=operation,
            units=Decimal(str(total)),
            unit_kind=UnitKind.USD,
            display_unit="USD",
            observed_at=datetime.now(UTC),
            metadata={},
        )

    def _normalize_error(self, exc: Exception) -> ProviderOperationError:
        status = _sdk_status_code(exc)
        if status is not None:
            if status == 429:
                return self._error(
                    "rate_limited", "usage limit exceeded", retryable=True, status=429
                )
            if status == 401:
                return self._error("invalid_api_key", "invalid API key", status=401)
            if status == 403:
                return self._error("forbidden", "request forbidden", status=403)
            if status == 400:
                return self._error("bad_request", "bad request", status=400)
            return self._error(
                "http_error",
                f"HTTP {status}",
                retryable=status in RETRYABLE_STATUS_CODES,
                status=status,
            )
        if isinstance(exc, httpx.HTTPStatusError):
            status = exc.response.status_code
            return self._error(
                "http_error",
                f"HTTP {status}",
                retryable=status in RETRYABLE_STATUS_CODES,
                status=status,
            )
        return self._error("exa_error", type(exc).__name__)

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


def _sdk_status_code(exc: Exception) -> int | None:
    """The HTTP status parsed from the SDK's ``ValueError`` message, if any.

    Only the status digits are extracted; the provider's message body is never
    surfaced so it cannot leak credential-shaped text.
    """
    if not isinstance(exc, ValueError):
        return None
    match = _SDK_STATUS_RE.search(str(exc))
    return int(match.group(1)) if match is not None else None
