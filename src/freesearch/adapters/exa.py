"""Exa provider adapter built on the official ``exa-py`` async SDK.

The adapter wraps every SDK call in the shared :class:`ResilientRunner` and
receives its API key only through vault-backed dependency injection. The SDK
owns its HTTPX client (``AsyncExa.client``), created lazily with that injected
key, so the caller's shared client is never mutated or closed; the
adapter closes the SDK-owned client in :meth:`aclose`. Exa exposes no remote
quota endpoint, so :meth:`quota` returns only local spend state and never polls
the provider. Measured ``costDollars`` telemetry wins; published pricing is used
only when that response telemetry is absent.
"""

import re
from dataclasses import asdict, is_dataclass
from datetime import UTC, datetime
from decimal import Decimal
from math import isfinite
from typing import Any, cast
from urllib.parse import urlsplit

import httpx
from exa_py import AsyncExa
from exa_py.api import Result
from exa_py.api import SearchResponse as ExaSearchResponse
from pydantic import AnyHttpUrl, SecretStr

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
    NativeUsageSnapshot,
    UsageSyncRequest,
    native_pool_id,
)

__all__ = ["ExaAdapter"]

_NAME = "exa"
_SEARCH_BASE_USD = Decimal("0.007")
_SEARCH_INCREMENT_USD = Decimal("0.001")
_CONTENTS_PAGE_USD = Decimal("0.001")
_FALLBACK_PRICING_DATE = "2026-09-18"
_EXA_402_CODES = ("NO_MORE_CREDITS", "API_KEY_BUDGET_EXCEEDED", "TEAM_BUDGET_EXCEEDED")


def _detect_402_vendor_code(exc: Exception) -> str | None:
    text = str(exc)
    for code in _EXA_402_CODES:
        if code in text:
            return code
    if isinstance(exc, httpx.HTTPStatusError):
        try:
            body = exc.response.text
            for code in _EXA_402_CODES:
                if code in body:
                    return code
        except Exception:
            pass
    return None


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


def _search_fallback_cost(result_count: int, summary_count: int) -> Decimal:
    """Return the published search fallback price using exact USD decimals."""
    extra_results = max(0, result_count - 10)
    return _SEARCH_BASE_USD + _SEARCH_INCREMENT_USD * Decimal(extra_results + summary_count)


def _contents_fallback_cost(page_count: int, content_type_count: int) -> Decimal:
    """Return the published contents fallback price per page and content type."""
    return _CONTENTS_PAGE_USD * Decimal(page_count) * Decimal(content_type_count)


def _summary_count(results: list[Result]) -> int:
    """Count non-empty AI summaries; omitted summary fields cost nothing."""
    return sum(1 for item in results if bool(getattr(item, "summary", None)))


def _metadata_value(value: Any) -> Any:
    """Convert SDK dataclasses and containers to response-serializable values."""
    if is_dataclass(value) and not isinstance(value, type):
        return _metadata_value(asdict(value))
    if isinstance(value, dict):
        return {str(key): _metadata_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_metadata_value(item) for item in value]
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        return _metadata_value(model_dump(mode="json"))
    return value


def _result_metadata(item: Result, *, include_text: bool = True) -> dict[str, Any]:
    """Keep Exa's useful identity, extraction, and page metadata with a result."""
    metadata: dict[str, Any] = {}
    for key in (
        "id",
        "author",
        "image",
        "favicon",
        "published_date",
        "crawl_date",
        "subpages",
        "extras",
        "entities",
        "summary",
        "highlights",
        "highlight_scores",
    ):
        value = getattr(item, key, None)
        if value is not None:
            metadata[key] = _metadata_value(value)
    if include_text:
        text = getattr(item, "text", None)
        if text is not None:
            metadata["text"] = _metadata_value(text)
    return metadata


def _response_metadata(
    response: ExaSearchResponse[Result], *, include_statuses: bool = False
) -> dict[str, Any] | None:
    """Retain non-metering response metadata exposed by the Exa SDK."""
    metadata: dict[str, Any] = {}
    for key in ("resolved_search_type", "auto_date", "search_time", "output"):
        value = getattr(response, key, None)
        if value is not None:
            metadata[key] = _metadata_value(value)
    if include_statuses:
        statuses = getattr(response, "statuses", None)
        if statuses is not None:
            metadata["statuses"] = _metadata_value(statuses)
    return metadata or None


class ExaAdapter(ProviderAdapter):
    """Search, fetch, and cost operations against the Exa API."""

    def __init__(
        self,
        client: httpx.AsyncClient | None = None,
        *,
        runner: ResilientRunner | None = None,
        sdk_client: AsyncExa | None = None,
        api_key: SecretStr | None = None,
        monthly_budget: Decimal | None = None,
        manual_starting_credits: Decimal | None = None,
    ) -> None:
        """Wrap operations in the shared resilience runner.

        ``client`` is the caller-owned shared HTTPX client; when omitted the
        adapter creates a fallback client it owns and closes in
        :meth:`aclose`. ``sdk_client`` is a test-only seam replacing the real
        SDK client. The SDK owns its own HTTPX client carrying the injected
        vault key; the caller's client is never mutated or closed here.
        ``manual_starting_credits`` takes precedence over ``monthly_budget``
        when the operator stores a prepaid balance through the manual-quota route.
        """
        sdk = sdk_client or self._build_sdk(api_key)
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
        self._manual_starting_credits = (
            self._validate_budget(manual_starting_credits)
            if manual_starting_credits is not None
            else None
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

    def set_manual_starting_credits(self, credits: Decimal | None) -> None:
        """Apply the operator-entered prepaid balance without resetting spend."""
        self._manual_starting_credits = (
            self._validate_budget(credits) if credits is not None else None
        )

    def _effective_limit(self) -> tuple[Decimal | None, str | None]:
        if self._manual_starting_credits is not None:
            return self._manual_starting_credits, "manual_starting_credits"
        if self._monthly_budget is not None:
            return self._monthly_budget, "monthly_budget"
        return None, None

    def _rollover_if_needed(self, now: datetime) -> None:
        month = _month_start(now)
        if month == self._ledger_month:
            return
        self._ledger_month = month
        self._spend = Decimal("0")
        self._soft_zero = False
        self._hydrated_month = None

    def _current_snapshot(self, *, now: datetime | None = None) -> QuotaSnapshot:
        limit, limit_source = self._effective_limit()
        observed_at = now or datetime.now(UTC)
        self._rollover_if_needed(observed_at)
        metadata: dict[str, Any] = {
            "window": "monthly",
            "spend_usd": self._spend,
            "soft_zero": self._soft_zero,
            "limit_source": limit_source,
        }

        remaining = None
        if limit is not None:
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

    def _exhaustion_snapshot(self, status: int) -> QuotaSnapshot:
        """Return an observed zero without inventing a prepaid limit."""
        observed_at = datetime.now(UTC)
        self._rollover_if_needed(observed_at)
        limit, limit_source = self._effective_limit()
        return QuotaSnapshot(
            provider=self.name,
            source=QuotaSource.OBSERVED,
            remaining=Decimal("0"),
            limit=limit,
            unit_kind=UnitKind.USD,
            display_unit="USD",
            observed_at=observed_at,
            reset_at=None,
            metadata={
                "window": "monthly",
                "spend_usd": self._spend,
                "soft_zero": True,
                "limit_source": limit_source,
                "exhaustion": True,
                "exhaustion_status": status,
            },
        )

    async def quota(self) -> QuotaSnapshot | None:
        """Return the current local monthly USD snapshot without a network poll."""
        return self._current_snapshot()

    def quota_after_success(
        self, response: object, *, operation: UsageOperation | None = None
    ) -> QuotaSnapshot | None:
        """Update spend from response usage event and return updated snapshot."""
        usage = getattr(response, "usage", None)
        units = getattr(usage, "units", None)
        if isinstance(units, Decimal) and units.is_finite():
            now = datetime.now(UTC)
            self._rollover_if_needed(now)
            if units > 0:
                self._spend += units
            self._soft_zero = False
        return self._current_snapshot()

    def quota_after_error(self, status: int | None) -> QuotaSnapshot | None:
        """Mirror Brave's observed exhaustion snapshot for Exa 402 and 429."""
        if status not in (402, 429):
            return None
        self._soft_zero = True
        return self._exhaustion_snapshot(status)

    async def hydrate_quota(self, repository: Any) -> QuotaSnapshot | None:
        """Restore monthly spend ledger from database usage events."""
        now = datetime.now(UTC)
        month_start = _month_start(now)
        self._rollover_if_needed(now)
        if self._hydrated_month == month_start:
            return None
        latest = await repository.latest_quota(self.name)
        events = await repository.list_provider_usage(provider=self.name)
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

    async def usage_snapshot(self, request: UsageSyncRequest) -> NativeUsageSnapshot | None:
        """Return a native usage snapshot for the Exa USD pool."""
        quota = self._current_snapshot(now=request.observed_at)
        source = "vendor_402" if self._soft_zero else "local_ledger"
        confidence = Confidence.OBSERVED if self._soft_zero else Confidence.ESTIMATED
        return NativeUsageSnapshot(
            pool_id=native_pool_id(self.name, AuthMode.KEYED, UnitKind.USD),
            provider=self.name,
            auth_mode=AuthMode.KEYED,
            native_unit=UnitKind.USD,
            observed_at=request.observed_at,
            source=source,
            confidence=confidence,
            remaining=quota.remaining,
            allowance=quota.limit,
            reset_at=quota.reset_at,
            credential_generation=request.credential_generation,
            plan_name="Free $10 monthly grant + bonus",
            usage_url="https://dashboard.exa.ai/",
        )

    def _build_sdk(self, api_key: SecretStr | None = None) -> AsyncExa:
        """Build the official SDK with the injected vault key.

        The key comes only from dependency injection; absent credentials fail
        closed rather than letting the SDK fall back to ambient ``EXA_API_KEY``
        (the SDK raises ``ValueError`` for a missing key, which would surface
        as a confusing provider error).
        """
        resolved = api_key
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
        return ProviderCapabilities(search=True, fetch=True, quota=True)

    async def search(self, request: SearchRequest) -> SearchResponse:
        response = await self._runner.run(self.name, lambda: self._search_sdk(request))
        try:
            results = [self._normalize_result(item) for item in response.results]
            summary_count = _summary_count(response.results)
            usage = self._usage_event_with_fallback(
                response,
                UsageOperation.SEARCH,
                units=_search_fallback_cost(len(response.results), summary_count),
                metadata={
                    "result_count": len(response.results),
                    "summary_count": summary_count,
                },
            )
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
            provider_metadata=_response_metadata(response),
        )

    async def _search_sdk(self, request: SearchRequest) -> ExaSearchResponse[Result]:
        kwargs: dict[str, Any] = {
            "query": request.query,
            "num_results": request.limit,
        }
        options = request.provider_options.exa if request.provider_options is not None else None
        contents: dict[str, Any] = {"highlights": True}
        if options is not None:
            option_values = options.model_dump(exclude_none=True, exclude={"contents"}, mode="json")
            # The common FreeSearch domains are defaults. An explicitly supplied
            # provider include_domains value, including an empty tuple, wins.
            if "include_domains" not in option_values and request.domains:
                option_values["include_domains"] = list(request.domains)
            if "user_location" not in option_values and request.country_code is not None:
                option_values["user_location"] = {"country": request.country_code.upper()}
            kwargs.update(option_values)
            if options.contents is not None:
                contents.update(options.contents.model_dump(exclude_none=True, mode="json"))
        elif request.domains:
            kwargs["include_domains"] = list(request.domains)
        if options is None and request.country_code is not None:
            kwargs["user_location"] = {"country": request.country_code.upper()}
        kwargs["contents"] = contents
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
        for key in (
            "id",
            "favicon",
            "author",
            "image",
            "published_date",
            "crawl_date",
            "subpages",
            "extras",
            "entities",
            "text",
            "summary",
            "highlights",
            "highlight_scores",
        ):
            value = getattr(item, key, None)
            if value is not None:
                metadata[key] = _metadata_value(value)
        return SearchResult(
            title=item.title or "",
            url=cast(AnyHttpUrl, item.url),
            snippet=highlights[0] if highlights else (item.text or item.summary or ""),
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
            # An explicit empty string is a valid (empty) document. When the
            # caller selected summary/highlights instead of text, use that
            # returned content as the document body and retain the other
            # content fields as metadata.
            content = match.text
            if not isinstance(content, str) and isinstance(match.summary, str):
                content = match.summary
            if (
                not isinstance(content, str)
                and isinstance(match.highlights, list)
                and all(isinstance(highlight, str) for highlight in match.highlights)
            ):
                content = "\n\n".join(match.highlights)
            options = request.provider_options.exa if request.provider_options is not None else None
            if not isinstance(content, str) and options is not None and options.text is False:
                content = ""
            if not isinstance(content, str):
                raise self._error("invalid_response", "malformed fetch response")
            truncated = False
            if request.max_chars is not None and len(content) > request.max_chars:
                content = content[: request.max_chars]
                truncated = True
            document_metadata = _result_metadata(match, include_text=False)
            if truncated:
                document_metadata["truncated"] = True
            return FetchResponse(
                provider=self.name,
                document=FetchedDocument(
                    url=request.url,
                    content=content,
                    title=match.title,
                    fetched_at=datetime.now(UTC),
                    metadata=document_metadata,
                ),
                usage=self._usage_event_with_fallback(
                    response,
                    UsageOperation.FETCH,
                    units=_contents_fallback_cost(len(response.results), 1),
                    metadata={
                        "page_count": len(response.results),
                        "content_type_count": 1,
                    },
                ),
                provider_metadata=_response_metadata(response, include_statuses=True),
            )
        except ProviderOperationError:
            raise
        except Exception:
            # A structurally malformed payload must not escape as a raw
            # AttributeError/TypeError/ValidationError after the call succeeded.
            raise self._error("invalid_response", "malformed fetch response") from None

    async def _fetch_sdk(self, request: FetchRequest) -> ExaSearchResponse[Result]:
        options = request.provider_options.exa if request.provider_options is not None else None
        contents: dict[str, Any] = {"text": True}
        if options is not None:
            contents.update(options.model_dump(exclude_none=True, mode="json"))
        try:
            # get_contents has no return annotation in the SDK, so the result
            # is cast to the documented SearchResponse[Result] shape.
            return cast(
                ExaSearchResponse[Result],
                await self._sdk.get_contents([str(request.url)], **contents),
            )
        except httpx.TransportError:
            raise  # the shared ResilientRunner normalizes transport failures
        except Exception as exc:
            raise self._normalize_error(exc) from None

    async def estimate_cost(self, request: SearchRequest | FetchRequest) -> CostEstimate:
        if isinstance(request, SearchRequest):
            operation = UsageOperation.SEARCH
            extra = max(0, request.limit - 10)
            units = _SEARCH_BASE_USD + Decimal(extra) * _SEARCH_INCREMENT_USD
            notes = "published fallback estimate; response costDollars wins; summaries excluded"
        else:
            operation = UsageOperation.FETCH
            units = _CONTENTS_PAGE_USD * Decimal(request.url_count)
            notes = "published text-content fallback estimate; response costDollars wins"
        return CostEstimate(
            provider=self.name,
            operation=operation,
            units=units,
            currency=UnitKind.USD.value,
            notes=notes,
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

    def _usage_event_with_fallback(
        self,
        response: ExaSearchResponse[Result],
        operation: UsageOperation,
        *,
        units: Decimal,
        metadata: dict[str, Any],
    ) -> UsageEvent | None:
        """Prefer measured costDollars; estimate only when telemetry is absent."""
        measured = self._usage_event(response, operation)
        if response.cost_dollars is not None:
            return measured
        return UsageEvent(
            provider=self.name,
            operation=operation,
            units=units,
            unit_kind=UnitKind.USD,
            display_unit="USD",
            observed_at=datetime.now(UTC),
            metadata={
                "provenance": "exa_pricing_fallback",
                "source": QuotaSource.ESTIMATED.value,
                "pricing_date": _FALLBACK_PRICING_DATE,
                **metadata,
            },
        )

    def _normalize_error(self, exc: Exception) -> ProviderOperationError:
        vendor_code = _detect_402_vendor_code(exc)
        status = _sdk_status_code(exc)
        if status is not None:
            if status == 429:
                return self._error(
                    "rate_limited", "rate limit exceeded", retryable=True, status=429
                )
            if status == 402 or vendor_code is not None:
                details = {"error_code": vendor_code} if vendor_code is not None else {}
                return self._error(
                    "quota_exhausted",
                    "Exa credits or spend budget exhausted. Wait until monthly reset or top up.",
                    retryable=False,
                    status=402,
                    details=details,
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
            if status == 429:
                return self._error(
                    "rate_limited", "rate limit exceeded", retryable=True, status=429
                )
            if status == 402 or vendor_code is not None:
                details = {"error_code": vendor_code} if vendor_code is not None else {}
                return self._error(
                    "quota_exhausted",
                    "Exa credits or spend budget exhausted. Wait until monthly reset or top up.",
                    retryable=False,
                    status=402,
                    details=details,
                )
            return self._error(
                "http_error",
                f"HTTP {status}",
                retryable=status in RETRYABLE_STATUS_CODES,
                status=status,
            )
        if vendor_code is not None:
            return self._error(
                "quota_exhausted",
                "Exa credits or spend budget exhausted. Wait until monthly reset or top up.",
                retryable=False,
                status=402,
                details={"error_code": vendor_code},
            )
        return self._error("exa_error", type(exc).__name__)

    def _error(
        self,
        code: str,
        message: str,
        *,
        retryable: bool = False,
        status: int | None = None,
        details: dict[str, Any] | None = None,
    ) -> ProviderOperationError:
        return ProviderOperationError(
            ProviderError(
                provider=self.name,
                code=code,
                message=message,
                retryable=retryable,
                status_code=status,
                details=details or {},
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
