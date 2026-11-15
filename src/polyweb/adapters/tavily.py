"""Tavily provider adapter built on the official ``tavily`` async SDK.

The adapter receives the shared async HTTPX client for resilience/transport
settings, wraps every SDK call in the shared :class:`ResilientRunner`, and
resolves the API key only through the caller's resolved secret. Keyed calls
carry ``Authorization: Bearer tvly-...`` set by the SDK; keyless calls carry
the explicit ``X-Tavily-Access-Mode: keyless`` header, which the SDK does not
add when it is handed an injected client, so the adapter-owned private client
sets it before the first request. A private response hook records the HTTP
status and the parsed ``Retry-After`` of every response before the SDK
converts errors, so a normalized 429 keeps its finite delay and a 402 keeps
its terminal out-of-Credits identity.
The SDK's per-call timeout defaults (search=60s, extract=30s) would silently
override the shared client's timeout, so the adapter forwards the shared read
timeout into every SDK call as a scalar clamped to the operation's vendor
range (minimum 1s; search 1-120s, extract 1-60s), and the borrowed transport
reasserts the shared phase-specific timeout on each request so the SDK's
scalar never replaces the shared connect/write/pool/read policy at the
network layer.
Quota is served from caches the adapter owns: the background usage read
(through ``usage_snapshot``) is the only path that can issue ``GET /usage``,
each read is bounded by a 30-second outer timeout, and direct or scheduled
callers coalesce under one adapter lock plus a 60-second local cadence before
the next poll. Search and extract never wait on that poll.
"""

import asyncio
import email.utils
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from math import ceil, isfinite
from typing import Any, Literal, cast
from urllib.parse import urlsplit

import httpx
from pydantic import SecretStr
from tavily import AsyncTavilyClient  # type: ignore[import-untyped]
from tavily.errors import (  # type: ignore[import-untyped]
    BadRequestError,
    ForbiddenError,
    InvalidAPIKeyError,
    KeylessUnsupportedEndpointError,
    MissingAPIKeyError,
    TavilyKeylessLimitError,
    UsageLimitExceededError,
)
from tavily.errors import (
    TimeoutError as TavilyTimeoutError,
)

from polyweb.adapters.base import ProviderAdapter
from polyweb.infrastructure.borrowed_transport import BorrowedTransport
from polyweb.infrastructure.dates import parse_iso_datetime
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
    QuotaSource,
    SearchRequest,
    SearchResponse,
    SearchResult,
    UnitKind,
    UsageEvent,
    UsageOperation,
)
from polyweb.models.provider_limits import (
    AuthMode,
    Confidence,
    FundingMode,
    NativeUsageSnapshot,
    ResetRule,
    TierBalance,
    UsageSyncRequest,
    native_pool_id,
)
from polyweb.models.tavily import (
    tavily_extract_credits,
    tavily_extract_depth,
    tavily_search_depth,
)

__all__ = ["TavilyAdapter"]

_NAME = "tavily"
_MAX_SEARCH_RESULTS = 20
# Scalar timeouts forwarded to the SDK are capped at the vendor maxima: the
# SDK clamps search per-call timeouts to 120s and the extract API caps its
# server-side timeout at 60s.
_SDK_SEARCH_TIMEOUT_MAX = 120.0
_SDK_EXTRACT_TIMEOUT_MAX = 60.0
# The usage endpoint is not exposed by the SDK, so the adapter reads it
# directly on the scoped client that already carries the resolver key. The
# read runs under its own runner cooldown key so a usage 429 never delays
# search or extract, a 30-second outer timeout, and a 60-second local
# cadence.
_USAGE_URL = "https://api.tavily.com/usage"
_USAGE_RUNNER_KEY = "tavily-usage"
_USAGE_REQUEST_TIMEOUT_SECONDS = 30.0
_USAGE_CADENCE_SECONDS = 60.0
# Documented Tavily free-plan facts used to project tier facts.
_FREE_PLAN_ALLOWANCE = Decimal("1000")
_FREE_PLAN_NAMES = frozenset({"researcher", "free"})
_KEYLESS_ACCESS_HEADER = "X-Tavily-Access-Mode"
_KEYLESS_ACCESS_MODE = "keyless"
_TAVILY_USAGE_URL = "https://app.tavily.com/home"
# Tavily's documented country enum uses names rather than ISO alpha-2 codes.
_TAVILY_COUNTRIES = {
    "AD": "andorra",
    "AE": "united arab emirates",
    "AF": "afghanistan",
    "AL": "albania",
    "AM": "armenia",
    "AO": "angola",
    "AR": "argentina",
    "AT": "austria",
    "AU": "australia",
    "AZ": "azerbaijan",
    "BA": "bosnia and herzegovina",
    "BB": "barbados",
    "BD": "bangladesh",
    "BE": "belgium",
    "BF": "burkina faso",
    "BG": "bulgaria",
    "BH": "bahrain",
    "BI": "burundi",
    "BJ": "benin",
    "BN": "brunei",
    "BO": "bolivia",
    "BR": "brazil",
    "BS": "bahamas",
    "BT": "bhutan",
    "BW": "botswana",
    "BY": "belarus",
    "BZ": "belize",
    "CA": "canada",
    "CF": "central african republic",
    "CG": "congo",
    "CH": "switzerland",
    "CL": "chile",
    "CM": "cameroon",
    "CN": "china",
    "CO": "colombia",
    "CR": "costa rica",
    "CU": "cuba",
    "CV": "cape verde",
    "CY": "cyprus",
    "CZ": "czech republic",
    "DE": "germany",
    "DJ": "djibouti",
    "DK": "denmark",
    "DO": "dominican republic",
    "DZ": "algeria",
    "EC": "ecuador",
    "EE": "estonia",
    "EG": "egypt",
    "ER": "eritrea",
    "ES": "spain",
    "ET": "ethiopia",
    "FI": "finland",
    "FJ": "fiji",
    "FR": "france",
    "GA": "gabon",
    "GB": "united kingdom",
    "GE": "georgia",
    "GH": "ghana",
    "GM": "gambia",
    "GN": "guinea",
    "GQ": "equatorial guinea",
    "GR": "greece",
    "GT": "guatemala",
    "HN": "honduras",
    "HR": "croatia",
    "HT": "haiti",
    "HU": "hungary",
    "ID": "indonesia",
    "IE": "ireland",
    "IL": "israel",
    "IN": "india",
    "IQ": "iraq",
    "IR": "iran",
    "IS": "iceland",
    "IT": "italy",
    "JM": "jamaica",
    "JO": "jordan",
    "JP": "japan",
    "KE": "kenya",
    "KG": "kyrgyzstan",
    "KH": "cambodia",
    "KM": "comoros",
    "KP": "north korea",
    "KR": "south korea",
    "KW": "kuwait",
    "KZ": "kazakhstan",
    "LB": "lebanon",
    "LI": "liechtenstein",
    "LK": "sri lanka",
    "LR": "liberia",
    "LS": "lesotho",
    "LT": "lithuania",
    "LU": "luxembourg",
    "LV": "latvia",
    "LY": "libya",
    "MA": "morocco",
    "MC": "monaco",
    "MD": "moldova",
    "ME": "montenegro",
    "MG": "madagascar",
    "MK": "north macedonia",
    "ML": "mali",
    "MM": "myanmar",
    "MN": "mongolia",
    "MR": "mauritania",
    "MT": "malta",
    "MU": "mauritius",
    "MV": "maldives",
    "MW": "malawi",
    "MX": "mexico",
    "MY": "malaysia",
    "MZ": "mozambique",
    "NA": "namibia",
    "NE": "niger",
    "NG": "nigeria",
    "NI": "nicaragua",
    "NL": "netherlands",
    "NO": "norway",
    "NP": "nepal",
    "NZ": "new zealand",
    "OM": "oman",
    "PA": "panama",
    "PE": "peru",
    "PG": "papua new guinea",
    "PH": "philippines",
    "PK": "pakistan",
    "PL": "portugal",
    "PY": "paraguay",
    "QA": "qatar",
    "RO": "romania",
    "RS": "serbia",
    "RU": "russia",
    "RW": "rwanda",
    "SA": "saudi arabia",
    "SD": "sudan",
    "SE": "sweden",
    "SG": "singapore",
    "SI": "slovenia",
    "SK": "slovakia",
    "SN": "senegal",
    "SO": "somalia",
    "SS": "south sudan",
    "SV": "el salvador",
    "SY": "syria",
    "TD": "chad",
    "TG": "togo",
    "TH": "thailand",
    "TJ": "tajikistan",
    "TM": "turkmenistan",
    "TN": "tunisia",
    "TR": "turkey",
    "TT": "trinidad and tobago",
    "TW": "taiwan",
    "TZ": "tanzania",
    "UA": "ukraine",
    "UG": "uganda",
    "US": "united states",
    "UY": "uruguay",
    "UZ": "uzbekistan",
    "VE": "venezuela",
    "VN": "vietnam",
    "YE": "yemen",
    "ZA": "south africa",
    "ZM": "zambia",
    "ZW": "zimbabwe",
}


def _sdk_timeout_seconds(client: httpx.AsyncClient, *, cap: float) -> float:
    """The shared client's read timeout as the SDK's scalar, clamped to ``[1, cap]``.

    The SDK only accepts a scalar per-call timeout and the vendor enforces an
    operation-specific range (search 1-120s, extract 1-60s), so the shared read
    phase is forwarded clamped to that range; a value below the vendor minimum
    would be rejected and a value above the cap would only be silently reduced
    by the SDK. A ``None`` read phase (no deadline in the shared policy) yields
    the cap - the most generous scalar the SDK/API accepts - rather than
    letting the SDK's own per-call defaults (search 60s, extract 30s) apply.
    """
    timeout = getattr(client, "timeout", None)
    if isinstance(timeout, httpx.Timeout):
        read = timeout.read
    elif isinstance(timeout, (int, float)):
        read = float(timeout)
    else:
        read = None
    if read is None:
        return cap
    return max(1.0, min(read, cap))


def _same_url(left: str, right: str) -> bool:
    """Compare URLs case-insensitively for scheme/host, path/query case preserved."""
    try:
        left_parts, right_parts = urlsplit(left), urlsplit(right)
    except ValueError:
        return left == right
    return (
        left_parts.scheme.lower() == right_parts.scheme.lower()
        and left_parts.netloc.lower() == right_parts.netloc.lower()
        and left_parts.path == right_parts.path
        and left_parts.query == right_parts.query
        and left_parts.fragment == right_parts.fragment
    )


def _next_month_start(value: datetime) -> datetime:
    """Return the first instant of the month after ``value`` in UTC."""

    if value.month == 12:
        return datetime(value.year + 1, 1, 1, tzinfo=UTC)
    return datetime(value.year, value.month + 1, 1, tzinfo=UTC)


def response_retry_after(response: httpx.Response) -> float | None:
    """Parse ``Retry-After`` (integer seconds or HTTP-date) into seconds.

    A missing or malformed value yields ``None``; the caller then keeps the
    calculated backoff. A well-formed zero delay stays zero. A value that
    fails the numeric form, including a non-finite or negative one, falls
    through to the HTTP-date form, which resolves against the wall clock.
    """

    value = response.headers.get("retry-after")
    if value is None:
        return None
    raw = value.strip()
    if not raw:
        return None
    delay = _seconds_delay(raw)
    if delay is not None:
        return delay
    return _date_delay(raw)


def _seconds_delay(raw: str) -> float | None:
    """Return the finite nonnegative numeric form of ``Retry-After``, else ``None``."""

    try:
        seconds = float(raw)
    except (TypeError, ValueError):
        return None
    if isfinite(seconds) and seconds >= 0:
        return seconds
    return None


def _date_delay(raw: str) -> float | None:
    """Return the HTTP-date form of ``Retry-After`` as remaining seconds."""

    try:
        retry_at = email.utils.parsedate_to_datetime(raw)
    except (TypeError, ValueError, OverflowError):
        return None
    if retry_at.tzinfo is None:
        retry_at = retry_at.replace(tzinfo=UTC)
    delay = (retry_at - datetime.now(UTC)).total_seconds()
    if not isfinite(delay) or delay < 0:
        return None
    return delay


def _envelope_retry_after(response: httpx.Response) -> float | None:
    """Read the keyless recoverable-error envelope's retry delay, if present.

    Keyless limit responses carry ``error.retry_after_seconds`` in the body;
    a malformed body or a value that is not a real nonnegative number yields
    ``None``.
    """

    try:
        body = response.json()
    except Exception:
        return None
    error = body.get("error") if isinstance(body, dict) else None
    value = error.get("retry_after_seconds") if isinstance(error, dict) else None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    seconds = float(value)
    if isfinite(seconds) and seconds >= 0:
        return seconds
    return None


class _ResponseProbe:
    """Recorded status and Retry-After of the last response in one task."""

    __slots__ = ("retry_after_seconds", "status")

    def __init__(self, status: int | None, retry_after_seconds: float | None) -> None:
        self.status = status
        self.retry_after_seconds = retry_after_seconds


class _UsageFacts:
    """Validated account and key figures of one ``/usage`` payload.

    Absent allowance, balance, or payment fields stay unknown; a present but
    malformed numeric is rejected by the caller. Key figures cap the plan
    remaining, and PAYGO figures record payment access rather than balances.
    """

    __slots__ = (
        "current_plan",
        "free_confirmed",
        "key_limit",
        "key_remaining",
        "key_usage",
        "paygo_limit",
        "paygo_usage",
        "plan_limit",
        "plan_remaining",
        "plan_usage",
    )

    def __init__(
        self,
        *,
        current_plan: str | None,
        plan_usage: Decimal | None,
        plan_limit: Decimal | None,
        paygo_usage: Decimal | None,
        paygo_limit: Decimal | None,
        key_usage: Decimal | None,
        key_limit: Decimal | None,
    ) -> None:
        self.current_plan = current_plan
        self.plan_usage = plan_usage
        self.plan_limit = plan_limit
        self.paygo_usage = paygo_usage
        self.paygo_limit = paygo_limit
        self.key_usage = key_usage
        self.key_limit = key_limit
        self.plan_remaining = (
            max(Decimal("0"), plan_limit - plan_usage)
            if plan_usage is not None and plan_limit is not None
            else None
        )
        self.key_remaining = (
            max(Decimal("0"), key_limit - key_usage)
            if key_usage is not None and key_limit is not None
            else None
        )
        plan = (current_plan or "").strip().lower()
        self.free_confirmed = plan in _FREE_PLAN_NAMES or (
            plan_limit is not None and plan_limit == _FREE_PLAN_ALLOWANCE
        )

    @property
    def remaining(self) -> Decimal | None:
        """Return the aggregate remaining Credits, capped by the key ceiling."""
        if self.plan_remaining is not None and self.key_remaining is not None:
            return min(self.plan_remaining, self.key_remaining)
        return self.plan_remaining if self.plan_remaining is not None else self.key_remaining

    @property
    def allowance(self) -> Decimal | None:
        """Return the applicable monthly allowance, or ``None`` when unknown."""
        if self.plan_remaining is not None:
            return self.plan_limit
        return self.key_limit

    @property
    def paygo_observed(self) -> bool:
        """Return whether the payload reports PAYGO payment state."""
        return self.paygo_usage is not None or self.paygo_limit is not None

    @property
    def plan_paid_confirmed(self) -> bool:
        """Return whether the payload confirms a paid plan."""
        return self.plan_limit is not None and not self.free_confirmed

    @property
    def overage_confirmed(self) -> bool:
        """Return whether PAYGO overage is confirmed by usage or PAYGO fields."""
        return self.paygo_observed or self.plan_paid_confirmed

    @property
    def plan_name(self) -> str | None:
        """Return the reported plan name, or ``None`` when absent."""
        return self.current_plan or None


class TavilyAdapter(ProviderAdapter):
    """Search, fetch, cost-estimate, and cached-quota operations on the Tavily API."""

    def __init__(
        self,
        client: httpx.AsyncClient,
        *,
        runner: ResilientRunner | None = None,
        sdk_client: AsyncTavilyClient | None = None,
        api_key: SecretStr | None = None,
        key_environment: Literal["dev", "prod"] = "dev",
        paygo_enabled: bool = False,
    ) -> None:
        """Wrap the caller-owned ``client`` in the shared resilience runner.

        ``api_key`` is the caller-resolved secret; a ``None`` key selects the
        keyless public rail on the explicit access-mode header instead of
        failing construction. ``key_environment`` is the explicit, non-secret
        development or production key choice documented by the vendor rate
        table, and ``paygo_enabled`` is the operator's pay-as-you-go
        confirmation that permits overage once the plan balance reaches zero.
        ``sdk_client`` is a test-only seam replacing the real SDK client; the
        caller owns the shared HTTPX client and is responsible for closing
        it. The SDK client built here owns a dedicated HTTPX client that the
        adapter closes via :meth:`aclose`.
        """
        self._runner = runner or ResilientRunner(client)
        self._owned_http: httpx.AsyncClient | None = None
        self._resolved_key = api_key
        self._key_environment = key_environment
        self._paygo_enabled = bool(paygo_enabled)
        self._sdk_search_timeout = _sdk_timeout_seconds(client, cap=_SDK_SEARCH_TIMEOUT_MAX)
        self._sdk_extract_timeout = _sdk_timeout_seconds(client, cap=_SDK_EXTRACT_TIMEOUT_MAX)
        # Per-task records of the last response's status and Retry-After, so a
        # normalized SDK error keeps the vendor delay the SDK itself drops.
        self._response_probes: dict[int, _ResponseProbe] = {}
        # Cached quota state. Only the lock-serialized usage path refreshes it;
        # search, extract, and every quota read stay cache-only.
        self._usage_lock = asyncio.Lock()
        self._usage_attempt_at: datetime | None = None
        self._usage_cache: NativeUsageSnapshot | None = None
        self._quota_cache: QuotaSnapshot | None = None
        # Terminal out-of-Credits state set by a vendor 402 and cleared at the
        # monthly reset; a stale positive usage read cannot override it.
        self._terminal_402 = False
        self._terminal_reset_at: datetime | None = None
        # The usage read gets its own runner instance so one scheduled poll
        # spends exactly one attempt and its cooldowns stay isolated from the
        # shared search/extract cooldown key.
        self._usage_runner = ResilientRunner(client, max_attempts=1)
        self._sdk = sdk_client or self._build_sdk(client)

    def _build_sdk(self, client: httpx.AsyncClient) -> AsyncTavilyClient:
        """Build the official SDK scoped to an adapter-owned HTTPX client.

        The SDK stamps its Authorization header and base URL onto whatever
        client it is handed, but only sets headers that are not already
        present, so the adapter-owned client must start clean: copying the
        shared client's headers would both preempt the resolver key and leak
        other providers' secrets (e.g. ``Authorization``, ``X-API-Key``) to
        Tavily. Only the harmless User-Agent is forwarded; the SDK then fills
        in its own Authorization and base URL on the private client. Its
        non-owning transport delegates to the shared client's selected pool,
        preserving limits/proxy/TLS policy without closing it.
        Keyless mode sets the access-mode header explicitly on the private
        client and hands the SDK an empty explicit key, because the SDK only
        adds the keyless header when it owns the client and would otherwise
        fall back to the ambient ``TAVILY_API_KEY``. A resolved key keeps the
        ``Authorization: Bearer`` header authoritative even when both access
        headers exist.
        """
        forwarded = {
            key: value for key, value in client.headers.items() if key.lower() == "user-agent"
        }
        if self._resolved_key is None:
            headers: dict[str, str] = {**forwarded, _KEYLESS_ACCESS_HEADER: _KEYLESS_ACCESS_MODE}
        else:
            headers = forwarded
        self._owned_http = httpx.AsyncClient(
            follow_redirects=client.follow_redirects,
            headers=headers,
            max_redirects=client.max_redirects,
            timeout=client.timeout,
            transport=BorrowedTransport(client, reassert_timeout=True),
            event_hooks={"response": [self._check_response]},
        )
        sdk_key = "" if self._resolved_key is None else self._resolved_key.get_secret_value()
        return AsyncTavilyClient(api_key=sdk_key, client=self._owned_http)

    async def aclose(self) -> None:
        """Close the adapter-owned SDK HTTPX client; the shared client stays open."""
        if self._owned_http is not None:
            await self._owned_http.aclose()

    @property
    def name(self) -> str:
        return _NAME

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(search=True, fetch=True, cost_estimate=True, quota=True)

    @property
    def limit_auth_mode(self) -> AuthMode:
        """Return the auth rail this adapter instance executes on."""

        return AuthMode.KEYED if self._resolved_key is not None else AuthMode.KEYLESS

    @property
    def key_environment(self) -> Literal["dev", "prod"]:
        """Return the explicit, non-secret key-environment choice."""

        return self._key_environment

    @property
    def paygo_enabled(self) -> bool:
        """Return the operator's PAYGO overage confirmation."""

        return self._paygo_enabled

    # -------------------------------------------------------------- requests

    async def search(self, request: SearchRequest) -> SearchResponse:
        response = await self._runner.run(self.name, lambda: self._search_sdk(request))
        try:
            results = [self._normalize_result(item) for item in response.get("results", [])]
            usage = self._usage_event(response, UsageOperation.SEARCH)
        except ProviderOperationError:
            raise
        except Exception:
            # A structurally malformed payload must not escape as a raw
            # AttributeError/KeyError/ValidationError/InvalidOperation after
            # the call succeeded.
            raise self._error("invalid_response", "malformed search response") from None
        return SearchResponse(
            query=request.query,
            provider=self.name,
            results=results,
            total_results=len(results),
            usage=usage,
            provider_metadata=self._provider_metadata(
                response, excluded={"query", "results", "usage"}
            ),
        )

    async def _search_sdk(self, request: SearchRequest) -> dict[str, Any]:
        kwargs = self._search_kwargs(request)
        try:
            return cast(dict[str, Any], await self._sdk.search(**kwargs))
        except httpx.TransportError:
            raise  # the shared ResilientRunner normalizes transport failures
        except Exception as exc:
            raise self._normalize_error(exc) from None
        finally:
            self._clear_probe()

    def _search_kwargs(self, request: SearchRequest) -> dict[str, Any]:
        """Build SDK kwargs with nested options taking precedence over defaults.

        The adapter retains ownership of usage metering, the request identity
        and result cap, and the shared timeout policy.
        """
        params = None if request.provider_options is None else request.provider_options.tavily
        depth = (
            params.search_depth
            if params is not None and params.search_depth is not None
            else tavily_search_depth(request.mode, None)
        )
        kwargs: dict[str, Any] = {
            "query": request.query,
            "max_results": min(request.limit, _MAX_SEARCH_RESULTS),
            "include_usage": True,
            "search_depth": depth,
        }
        # Always forward a scalar clamped to the vendor's 1-120s search range,
        # so the SDK never silently reverts to its 60s default or rejects a
        # sub-second value; the borrowed transport reasserts the shared phase
        # policy at request time.
        kwargs["timeout"] = self._sdk_search_timeout
        if request.language is not None:
            kwargs["language"] = request.language
        if request.domains:
            kwargs.setdefault("include_domains", list(request.domains))
        self._derived_country(request, kwargs, params)
        if params is not None:
            kwargs.update(params.model_dump(mode="json", exclude_none=True))
        kwargs.update(
            {
                "query": request.query,
                "max_results": min(request.limit, _MAX_SEARCH_RESULTS),
                "include_usage": True,
                "search_depth": depth,
                "timeout": self._sdk_search_timeout,
            }
        )
        return kwargs

    def _derived_country(
        self,
        request: SearchRequest,
        kwargs: dict[str, Any],
        params: Any,
    ) -> None:
        """Apply the caller country; an explicit parameter country wins."""

        if params is not None and params.country is not None:
            kwargs["country"] = params.country
            return
        if request.country_code is not None:
            country = _TAVILY_COUNTRIES.get(request.country_code.upper())
            if country is not None:
                kwargs["country"] = country

    def _normalize_result(self, item: Any) -> SearchResult:
        score = item.get("score")
        if not isinstance(score, (int, float)) or not 0 <= score <= 1:
            score = None
        metadata: dict[str, Any] = {}
        for key in ("id", "favicon", "images"):
            if item.get(key) is not None:
                metadata[key] = item[key]
        return SearchResult(
            title=item.get("title") or "",
            url=item["url"],
            snippet=item.get("content") or "",
            published_at=parse_iso_datetime(item.get("published_date")),
            score=score,
            metadata=metadata,
        )

    async def fetch(self, request: FetchRequest) -> FetchResponse:
        response = await self._runner.run(self.name, lambda: self._fetch_sdk(request))
        try:
            results = response.get("results") or []
            failed_results = response.get("failed_results") or []
            target = str(request.url)
            match = next(
                (r for r in results if _same_url(str(r.get("url") or ""), target)),
                None,
            )
            if match is None:
                failed_match = next(
                    (f for f in failed_results if _same_url(str(f.get("url") or ""), target)),
                    None,
                )
                if failed_match:
                    err = str(failed_match.get("error", ""))
                    if any(term in err.lower() for term in ("blocked", "forbidden", "403")):
                        raise self._error(
                            "bot_blocked",
                            f"target site blocked automated access: {err}",
                            status=403,
                        )
                    raise self._error("fetch_failed", f"target fetch failed: {err}")
                raise self._error("fetch_failed", "no successful extraction result") from None
            # An explicit empty string is a valid (empty) document; a missing
            # or non-string raw_content means the payload is malformed.
            raw_content = match.get("raw_content")
            if not isinstance(raw_content, str):
                raise self._error("invalid_response", "malformed fetch response")
            content = raw_content
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
                provider_metadata=self._provider_metadata(response, excluded={"results", "usage"}),
            )
        except ProviderOperationError:
            raise
        except Exception:
            # A structurally malformed payload must not escape as a raw
            # AttributeError/KeyError/TypeError after the call succeeded.
            raise self._error("invalid_response", "malformed fetch response") from None

    async def _fetch_sdk(self, request: FetchRequest) -> dict[str, Any]:
        kwargs = self._fetch_kwargs(request)
        try:
            return cast(dict[str, Any], await self._sdk.extract(**kwargs))
        except httpx.TransportError:
            raise  # the shared ResilientRunner normalizes transport failures
        except Exception as exc:
            raise self._normalize_error(exc) from None
        finally:
            self._clear_probe()

    def _fetch_kwargs(self, request: FetchRequest) -> dict[str, Any]:
        """Build the SDK extract call with the resolved extract depth.

        Basic depth stays the default, the caller ``format`` choice wins over
        the documented markdown default, and the optional query, chunk, and
        image fields ride along identically on both auth rails.
        """
        params = None if request.provider_options is None else request.provider_options.tavily
        depth = tavily_extract_depth(params)
        kwargs: dict[str, Any] = {
            "urls": [str(request.url)],
            "format": params.format if params is not None and params.format else "markdown",
            "include_usage": True,
            "extract_depth": depth,
        }
        # Always forward a scalar clamped to the vendor's 1-60s extract range,
        # so the SDK never silently reverts to its 30s default or rejects a
        # sub-second value; the borrowed transport reasserts the shared phase
        # policy at request time.
        kwargs["timeout"] = self._sdk_extract_timeout
        if params is not None:
            kwargs.update(params.model_dump(mode="json", exclude_none=True))
        kwargs.update(
            {
                "urls": [str(request.url)],
                "include_usage": True,
                "extract_depth": depth,
                "timeout": self._sdk_extract_timeout,
            }
        )
        return kwargs

    @staticmethod
    def _provider_metadata(
        response: dict[str, Any], *, excluded: set[str]
    ) -> dict[str, Any] | None:
        """Keep unnormalized Tavily response fields available to callers."""

        metadata = {key: value for key, value in response.items() if key not in excluded}
        return metadata or None

    # ------------------------------------------------- response observation

    async def _check_response(self, response: httpx.Response) -> None:
        """Record status and Retry-After before the SDK converts the response.

        The SDK drops the ``Retry-After`` header when it raises
        ``UsageLimitExceededError``, so the hook records both the status and
        the parsed delay keyed by the running task. Keyless limit envelopes
        carry their delay in the body, so it is read as a fallback. A
        bookkeeping failure never breaks the request itself.
        """
        try:
            retry_after = response_retry_after(response)
            if retry_after is None and response.status_code == 429:
                retry_after = _envelope_retry_after(response)
            self._response_probes[self._task_key()] = _ResponseProbe(
                response.status_code, retry_after
            )
        except Exception:
            pass

    def _task_key(self) -> int:
        task = asyncio.current_task()
        return id(task) if task is not None else 0

    def _probe(self) -> _ResponseProbe | None:
        return self._response_probes.get(self._task_key())

    def _probe_retry_after(self) -> int | None:
        """Return the recorded Retry-After delay as whole seconds, else ``None``."""
        probe = self._probe()
        if probe is None or probe.retry_after_seconds is None:
            return None
        return max(0, ceil(probe.retry_after_seconds))

    def _clear_probe(self) -> None:
        self._response_probes.pop(self._task_key(), None)

    # --------------------------------------------------------------- errors

    def _normalize_error(self, exc: Exception) -> ProviderOperationError:
        status = self._normalization_status(exc)
        if status == 429:
            return self._rate_limited(exc)
        if status in (402, 432, 433):
            # A Tavily 402 is the out-of-Credits rail: terminal, never
            # retried, and never classified as a rate outcome. The cached
            # balance never softens it.
            return self._quota_exhausted()
        if isinstance(exc, TavilyTimeoutError):
            return self._error("timeout_error", "request timed out", retryable=True)
        if isinstance(exc, (MissingAPIKeyError, KeylessUnsupportedEndpointError)):
            return self._error("configuration_error", "SDK configuration error")
        if isinstance(exc, InvalidAPIKeyError):
            return self._error("invalid_api_key", "invalid API key", status=401)
        if isinstance(exc, ForbiddenError):
            return self._error("forbidden", "request forbidden", status=403)
        if isinstance(exc, BadRequestError):
            return self._error("bad_request", "bad request", status=400)
        if isinstance(exc, httpx.HTTPStatusError):
            code_status = exc.response.status_code
            return self._error(
                "http_error",
                f"HTTP {code_status}",
                retryable=code_status in RETRYABLE_STATUS_CODES,
                status=code_status,
            )
        return self._error("tavily_error", type(exc).__name__)

    def _normalization_status(self, exc: Exception) -> int | None:
        """Return the vendor HTTP status of one SDK failure.

        The response hook records the real status before SDK conversion, so
        the recorded status wins; exception taxonomy supplies the status only
        when no response was observed.
        """
        probe = self._probe()
        if probe is not None and probe.status is not None:
            return probe.status
        if isinstance(exc, (UsageLimitExceededError, TavilyKeylessLimitError)):
            return 429
        if isinstance(exc, InvalidAPIKeyError):
            return 401
        if isinstance(exc, ForbiddenError):
            return 403
        if isinstance(exc, BadRequestError):
            return 400
        if isinstance(exc, httpx.HTTPStatusError):
            return exc.response.status_code
        return None

    def _rate_limited(self, exc: Exception) -> ProviderOperationError:
        """Normalize HTTP 429 by status and header, never by message text."""
        details: dict[str, Any] = {}
        delay = self._probe_retry_after()
        if delay is None and isinstance(exc, TavilyKeylessLimitError):
            value = exc.retry_after_seconds
            if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
                delay = value
        if delay is not None:
            details["retry_after_seconds"] = delay
        return self._error(
            "rate_limited",
            "usage limit exceeded",
            retryable=True,
            status=429,
            details=details or None,
        )

    def _quota_exhausted(self) -> ProviderOperationError:
        return self._error(
            "quota_exhausted",
            "Tavily is out of Credits. Wait until reset or upgrade.",
            retryable=False,
            status=402,
        )

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

    # ---------------------------------------------------------------- quota

    async def quota(self) -> QuotaSnapshot | None:
        """Return the cached quota snapshot without any vendor I/O.

        This read is cache-only: the lock-serialized ``usage_snapshot`` path
        is the only Tavily path that can issue ``GET /usage``. A keyed adapter
        that has never observed a balance reports the unknown state (``None``),
        and keyless mode never reports quota. The terminal out-of-Credits
        state expires at the documented monthly reset.
        """
        self._expire_terminal(datetime.now(UTC))
        if self.limit_auth_mode is AuthMode.KEYLESS:
            return None
        cached = self._quota_cache
        # A copy per call keeps a caller write from corrupting the cache.
        return cached.model_copy() if cached is not None else None

    async def usage_snapshot(self, request: UsageSyncRequest) -> NativeUsageSnapshot | None:
        """Return the native credit observation of the single allowed usage read.

        Keyless mode issues no usage request and returns ``None``. Direct and
        scheduled callers coalesce under one adapter lock: within 60 seconds
        of the last attempt the cached observation (or ``None``) is returned
        without a request, and one fresh poll spends exactly one attempt under
        a 30-second outer timeout. Failures preserve the last valid balance
        and reach the scheduler as the normalized error so it can mark the
        cached state stale.
        """
        if self.limit_auth_mode is AuthMode.KEYLESS:
            return None
        async with self._usage_lock:
            now = datetime.now(UTC)
            if self._usage_attempt_at is not None and now - self._usage_attempt_at < timedelta(
                seconds=_USAGE_CADENCE_SECONDS
            ):
                return self._usage_cache
            self._usage_attempt_at = now
            try:
                snapshot = await asyncio.wait_for(
                    self._refresh_usage(request), timeout=_USAGE_REQUEST_TIMEOUT_SECONDS
                )
            except ProviderOperationError:
                raise
            except TimeoutError:
                raise self._error(
                    "timeout_error", "usage request timed out", retryable=True
                ) from None
            self._usage_cache = snapshot
            return snapshot

    async def _refresh_usage(self, request: UsageSyncRequest) -> NativeUsageSnapshot | None:
        """Issue the single usage read and map it to the native observation.

        The method maps the payload to the aggregate Credits pool observation
        with tier facts, stores the projected quota cache, and applies the
        terminal-402 clamp so a late positive usage read cannot override an
        out-of-Credits month.
        """
        self._expire_terminal(datetime.now(UTC))
        payload = await self._usage_request()
        try:
            facts = self._plan_facts(payload)
            snapshot = self._usage_snapshot_from_payload(payload, facts, request)
            self._quota_cache = self._quota_cache_from_facts(facts, snapshot.remaining)
        except ProviderOperationError:
            raise
        except Exception:
            # A structurally malformed payload must not escape as a raw
            # AttributeError/KeyError/TypeError/JSONDecodeError after the
            # call succeeded.
            raise self._error("invalid_response", "malformed usage response") from None
        return snapshot

    async def _usage_request(self) -> dict[str, Any]:
        """GET the ``/usage`` endpoint once and parse or normalize it.

        The read runs under the isolated one-attempt usage runner, so one
        scheduled poll spends exactly one network attempt, its rate cooldowns
        stay on the ``tavily-usage`` key separate from the shared
        search/extract cooldown key, and transport failures normalize through
        the shared runner policy without an immediate retry.
        """
        try:
            return await self._usage_runner.run(_USAGE_RUNNER_KEY, self._usage_get)
        finally:
            self._clear_probe()

    async def _usage_get(self) -> dict[str, Any]:
        client = self._owned_http
        if client is None:
            # The scoped client exists only when construction built it; the
            # injected-SDK seam without a private client has no usage rail,
            # which is not the same condition as a missing key.
            raise self._error("configuration_error", "no adapter-owned usage client")
        response = await client.get(_USAGE_URL)
        if response.is_error:
            status = response.status_code
            details: dict[str, Any] | None = None
            if status == 429:
                delay = self._probe_retry_after()
                if delay is not None:
                    details = {"retry_after_seconds": delay}
            raise self._error(
                "http_error",
                f"HTTP {status}",
                retryable=status in RETRYABLE_STATUS_CODES,
                status=status,
                details=details,
            ) from None
        try:
            payload = response.json()
        except Exception:
            raise self._error("invalid_response", "malformed usage response") from None
        if not isinstance(payload, dict):
            raise self._error("invalid_response", "malformed usage response")
        return payload

    def _expire_terminal(self, now: datetime) -> None:
        """Clear the terminal 402 state after its monthly reset instant."""

        if (
            self._terminal_402
            and self._terminal_reset_at is not None
            and now >= self._terminal_reset_at
        ):
            self._terminal_402 = False
            self._terminal_reset_at = None
            self._quota_cache = None
            self._usage_cache = None

    def _mark_terminal(self, now: datetime) -> None:
        """Enter the terminal out-of-Credits state for the rest of this month."""
        if not self._terminal_402:
            self._terminal_402 = True
        self._terminal_reset_at = _next_month_start(now)

    def _usage_snapshot_from_payload(
        self,
        payload: dict[str, Any],
        facts: _UsageFacts,
        request: UsageSyncRequest,
    ) -> NativeUsageSnapshot:
        """Map validated usage facts to the aggregate Credits pool snapshot."""

        remaining = self._terminal_clamp(facts.remaining)
        reset_at = _next_month_start(datetime.now(UTC))
        source = "vendor_402" if self._terminal_402 else "vendor_api"
        tiers = self._usage_tiers(facts)
        return NativeUsageSnapshot(
            pool_id=native_pool_id(_NAME, self.limit_auth_mode, UnitKind.CREDIT),
            provider=_NAME,
            auth_mode=self.limit_auth_mode,
            native_unit=UnitKind.CREDIT,
            observed_at=request.observed_at,
            source=source,
            confidence=(
                Confidence.AUTHORITATIVE if facts.remaining is not None else Confidence.UNKNOWN
            ),
            remaining=remaining,
            allowance=facts.allowance,
            reset_at=reset_at,
            credential_generation=request.credential_generation,
            plan_name=facts.plan_name,
            usage_url=_TAVILY_USAGE_URL,
            tiers=tiers,
            tier_split_known=any(tier.native_remaining is not None for tier in tiers),
        )

    def _terminal_clamp(self, remaining: Decimal | None) -> Decimal | None:
        """Clamp a late positive balance to zero while terminal state holds.

        A vendor 402 overrides a positive cached balance at once, so the
        current month reports zero Credits until the reset clears the
        terminal state. An absent figure stays unknown, and the pool row
        keeps the terminal ``vendor_402`` source, so the funds denial still
        holds when the vendor reports no figures.
        """

        if remaining is None or not self._terminal_402:
            return remaining
        return Decimal("0")

    def _quota_cache_from_facts(
        self, facts: _UsageFacts, remaining: Decimal | None
    ) -> QuotaSnapshot:
        """Project the cached quota snapshot from the same validated facts."""

        metadata: dict[str, Any] = {
            "window": "monthly",
            "projected_from_usage": True,
        }
        observed_at = datetime.now(UTC)
        if self._paygo_enabled or facts.overage_confirmed:
            metadata["paygo_confirmed"] = True
        return QuotaSnapshot(
            provider=_NAME,
            source=QuotaSource.AUTHORITATIVE,
            remaining=remaining,
            limit=facts.allowance,
            reset_at=_next_month_start(observed_at),
            observed_at=observed_at,
            unit_kind=UnitKind.CREDIT,
            display_unit="Credits",
            metadata=metadata,
        )

    def _usage_tiers(self, facts: _UsageFacts) -> list[TierBalance]:
        """Project free, paid-plan, and PAYGO tier facts without duplicate funds.

        The aggregate remaining value lives in exactly one active tier: the
        free tier carries it while the free plan is confirmed, the paid tier
        carries it while a paid plan is confirmed, and both stay unknown
        until a figure arrives. PAYGO stays access, never a Credits balance.
        """
        observed = Confidence.OBSERVED
        tiers: list[TierBalance] = []
        if facts.free_confirmed:
            free_remaining = facts.plan_remaining
            free_confidence = observed if free_remaining is not None else Confidence.UNKNOWN
        elif facts.plan_paid_confirmed:
            free_remaining = Decimal("0")
            free_confidence = observed
        else:
            free_remaining = None
            free_confidence = Confidence.UNKNOWN
        tiers.append(
            TierBalance(
                pool_id=f"{_NAME}:keyed:free",
                tier="free",
                native_unit=UnitKind.CREDIT,
                native_remaining=free_remaining,
                native_allowance=_FREE_PLAN_ALLOWANCE,
                reset_rule=ResetRule.MONTHLY_FIRST,
                funding_mode=FundingMode.RECURRING,
                confidence=free_confidence,
                label="Free plan Credits (resets on the first)",
            )
        )
        if facts.plan_limit is not None and not facts.free_confirmed:
            tiers.append(
                TierBalance(
                    pool_id=f"{_NAME}:keyed:plan",
                    tier="paid",
                    native_unit=UnitKind.CREDIT,
                    native_remaining=facts.plan_remaining,
                    native_allowance=facts.plan_limit,
                    reset_rule=ResetRule.MONTHLY_FIRST,
                    funding_mode=FundingMode.RECURRING,
                    confidence=observed,
                    label="Paid plan allowance (plan dependent)",
                )
            )
        tiers.append(
            TierBalance(
                pool_id=f"{_NAME}:keyed:paygo",
                tier="paid",
                native_unit=UnitKind.CREDIT,
                native_remaining=None,
                native_allowance=None,
                reset_rule=ResetRule.NEVER,
                funding_mode=FundingMode.POSTPAID,
                confidence=observed if facts.paygo_observed else Confidence.UNKNOWN,
                label="PAYGO access or an explicit spend cap (not stored credits)",
            )
        )
        return tiers

    def _plan_facts(self, payload: dict[str, Any]) -> _UsageFacts:
        """Validate the account and key numbers of one usage payload.

        A present-but-non-mapping ``account`` (e.g. a list) and a present but
        malformed numeric are surfaced as the redaction-safe, non-retryable
        ``invalid_response`` error rather than a raw ``Decimal`` failure or a
        silent fallback. Genuinely absent fields stay unknown.
        """
        account = payload.get("account")
        if account is not None and not isinstance(account, dict):
            raise self._error("invalid_response", "malformed usage response") from None
        current_plan: str | None = None
        plan_usage: Decimal | None = None
        plan_limit: Decimal | None = None
        paygo_usage: Decimal | None = None
        paygo_limit: Decimal | None = None
        if isinstance(account, dict):
            plan = account.get("current_plan")
            current_plan = plan if isinstance(plan, str) else None
            plan_usage = self._quota_number(account.get("plan_usage"))
            plan_limit = self._quota_number(account.get("plan_limit"))
            paygo_usage = self._quota_number(account.get("paygo_usage"))
            paygo_limit = self._quota_number(account.get("paygo_limit"))
        key_usage: Decimal | None = None
        key_limit: Decimal | None = None
        key = payload.get("key")
        if isinstance(key, dict):
            key_usage = self._quota_number(key.get("usage"))
            key_limit = self._quota_number(key.get("limit"))
        return _UsageFacts(
            current_plan=current_plan,
            plan_usage=plan_usage,
            plan_limit=plan_limit,
            paygo_usage=paygo_usage,
            paygo_limit=paygo_limit,
            key_usage=key_usage,
            key_limit=key_limit,
        )

    async def estimate_cost(self, request: SearchRequest | FetchRequest) -> CostEstimate:
        if isinstance(request, SearchRequest):
            search_params = (
                None if request.provider_options is None else request.provider_options.tavily
            )
            depth = (
                search_params.search_depth
                if search_params is not None and search_params.search_depth is not None
                else tavily_search_depth(request.mode, None)
            )
            return CostEstimate(
                provider=self.name,
                operation=UsageOperation.SEARCH,
                units=Decimal("2") if depth == "advanced" else Decimal("1"),
                currency="Credits",
                notes=("basic search costs 1 Credit per call and advanced search costs 2 Credits"),
            )
        extract_params = (
            None if request.provider_options is None else request.provider_options.tavily
        )
        depth = tavily_extract_depth(extract_params)
        return CostEstimate(
            provider=self.name,
            operation=UsageOperation.FETCH,
            units=tavily_extract_credits(successful_urls=1, depth=depth),
            currency="Credits",
            notes=(
                "Tavily bills 1 Credit per 5 successful URLs at basic depth and "
                "2 Credits per 5 at advanced depth; this estimates one good URL"
            ),
        )

    def _quota_snapshot(self, response: dict[str, Any]) -> QuotaSnapshot:
        """Map the ``/usage`` payload to an authoritative bounded snapshot.

        The account plan figures are authoritative; when either side is
        absent the key figures bind remaining instead, so absent fields stay
        unknown and a present-but-malformed numeric raises the redaction-safe
        ``invalid_response`` error. PAYGO records payment access; reset
        metadata targets the next first day of the month.
        """
        facts = self._plan_facts(response)
        observed_at = datetime.now(UTC)
        remaining = self._terminal_clamp(facts.remaining)
        metadata: dict[str, Any] = {"window": "monthly", "projected_from_usage": True}
        if self._paygo_enabled or facts.overage_confirmed:
            metadata["paygo_confirmed"] = True
        return QuotaSnapshot(
            provider=self.name,
            source=QuotaSource.AUTHORITATIVE,
            remaining=remaining,
            limit=facts.allowance,
            reset_at=_next_month_start(observed_at),
            observed_at=observed_at,
            unit_kind=UnitKind.CREDIT,
            display_unit="Credits",
            metadata=metadata,
        )

    def _quota_number(self, value: Any) -> Decimal | None:
        """A validated quota figure; absent (``None``) values stay absent.

        Malformed numerics (bool, non-finite, negative, or otherwise not a
        real number) raise the redaction-safe, non-retryable
        ``invalid_response`` error instead of escaping as a raw ``Decimal``
        failure.
        """
        if value is None:
            return None
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not isfinite(value)
            or value < 0
        ):
            raise self._error("invalid_response", "malformed usage response")
        return Decimal(str(value))

    def _usage_event(
        self, response: dict[str, Any], operation: UsageOperation
    ) -> UsageEvent | None:
        """Return an event only when Tavily actually reported credit usage.

        Malformed credit values (bool, non-finite, or otherwise not a real
        number) are surfaced as the redaction-safe, non-retryable
        ``invalid_response`` error rather than a raw ``Decimal`` failure;
        both callers route this through their response normalization guard.
        """
        usage = response.get("usage")
        if not isinstance(usage, dict):
            return None
        credits = usage.get("credits")
        if credits is None:
            return None
        if (
            isinstance(credits, bool)
            or not isinstance(credits, (int, float))
            or not isfinite(credits)
        ):
            raise self._error("invalid_response", "malformed usage in response")
        if credits < 0:
            # A negative vendor credit value is malformed data, not an
            # absent report: the debit must never fall back to an invented
            # estimate for it.
            raise self._error("invalid_response", "malformed usage in response")
        return UsageEvent(
            provider=self.name,
            operation=operation,
            units=Decimal(str(credits)),
            unit_kind=UnitKind.CREDIT,
            display_unit="Credits",
            observed_at=datetime.now(UTC),
            request_id=response.get("request_id"),
        )

    # ------------------------------------------------------------ quota hooks

    def quota_after_success(self, response: SearchResponse | FetchResponse) -> QuotaSnapshot | None:
        """Project the cached balance after a successful call, without a usage GET.

        The result subtracts the Credits the vendor reported for this call, so
        the budget view reflects the debit the moment the call succeeds, and
        the projection re-anchors the adapter cache, so consecutive calls
        project from fresh state. The next usage poll overwrites the cache
        with vendor truth, so no drift accumulates. No observation means the
        projection returns ``None`` and the pending cache stays untouched.
        """
        cached = self._quota_cache
        if cached is None or self.limit_auth_mode is AuthMode.KEYLESS:
            return None
        remaining = cached.remaining
        usage = response.usage
        if remaining is not None and usage is not None and usage.unit_kind is UnitKind.CREDIT:
            remaining = max(Decimal("0"), remaining - usage.units)
        projected = cached.model_copy(
            update={
                "remaining": remaining,
                "observed_at": datetime.now(UTC),
                "metadata": {**cached.metadata, "projection": "local_debit"},
            }
        )
        self._quota_cache = projected
        return projected

    async def quota_after_error(self, status: int | None) -> QuotaSnapshot | None:
        """Publish zero Credits after a vendor 402 without a usage GET.

        A 402 marks the terminal out-of-Credits state for the rest of the
        month, so a later positive usage read from the same key stays clamped.
        The cached balance never softens the zero.
        """
        if status != 402 or self.limit_auth_mode is AuthMode.KEYLESS:
            return None
        now = datetime.now(UTC)
        self._mark_terminal(now)
        cached = self._quota_cache
        limit = cached.limit if cached is not None and cached.limit is not None else None
        if limit is not None and limit <= 0:
            limit = None
        metadata: dict[str, Any] = {
            "window": "monthly",
            "exhaustion": True,
            "exhaustion_status": status,
            "vendor_402": True,
        }
        if self._paygo_enabled or (cached is not None and cached.metadata.get("paygo_confirmed")):
            metadata["paygo_confirmed"] = True
        snapshot = QuotaSnapshot(
            provider=self.name,
            source=QuotaSource.OBSERVED,
            remaining=Decimal("0"),
            limit=limit,
            reset_at=self._terminal_reset_at,
            observed_at=now,
            unit_kind=UnitKind.CREDIT,
            display_unit="Credits",
            metadata=metadata,
        )
        self._quota_cache = snapshot
        return snapshot
