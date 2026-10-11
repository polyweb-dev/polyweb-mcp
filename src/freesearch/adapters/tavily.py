"""Tavily provider adapter built on the official ``tavily`` async SDK.

The adapter receives the shared async HTTPX client for resilience/transport
settings, wraps every SDK call in the shared :class:`ResilientRunner`, and
resolves the API key only through the process-wide provider secret resolver.
The SDK's per-call timeout defaults (search=60s, extract=30s) would silently
override the shared client's timeout, so the adapter forwards the shared read
timeout into every SDK call as a scalar clamped to the operation's vendor
range (minimum 1s; search 1-120s, extract 1-60s), and the borrowed transport
reasserts the shared phase-specific timeout on each request so the SDK's
scalar never replaces the shared connect/write/pool/read policy at the
network layer.
The SDK scopes its Authorization header and base URL to an adapter-owned
HTTPX client so the shared client is never mutated; that client starts with
a clean header set (only the caller's User-Agent) so no other provider's
secrets can reach Tavily and the resolver key is never preempted. The key
stays a ``SecretStr`` that is never logged or exposed.
"""

from datetime import UTC, datetime
from decimal import Decimal
from math import isfinite
from typing import Any, cast
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
    UsageLimitExceededError,
)
from tavily.errors import (
    TimeoutError as TavilyTimeoutError,
)

from freesearch.adapters.base import ProviderAdapter
from freesearch.infrastructure.borrowed_transport import BorrowedTransport
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
    Confidence,
    NativeUsageSnapshot,
    UsageSyncRequest,
    native_pool_id,
)

__all__ = ["TavilyAdapter"]

_NAME = "tavily"
_MAX_SEARCH_RESULTS = 20
# Tavily bills basic extraction as one credit per five successful URLs.
_FETCH_CREDIT_PER_URL = Decimal("0.2")
# Scalar timeouts forwarded to the SDK are capped at the vendor maxima: the
# SDK clamps search per-call timeouts to 120s and the extract API caps its
# server-side timeout at 60s.
_SDK_SEARCH_TIMEOUT_MAX = 120.0
_SDK_EXTRACT_TIMEOUT_MAX = 60.0
# The usage endpoint is not exposed by the SDK, so the adapter reads it
# directly on the scoped client that already carries the resolver key.
_USAGE_URL = "https://api.tavily.com/usage"
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
    "PL": "poland",
    "PT": "portugal",
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


def _parse_published_at(value: Any) -> datetime | None:
    """Parse Tavily's ISO-8601 ``published_date``; unparseable values are None."""
    return parse_iso_datetime(value)


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


class TavilyAdapter(ProviderAdapter):
    """Search, fetch, cost-estimate, and quota operations against the Tavily API."""

    def __init__(
        self,
        client: httpx.AsyncClient,
        *,
        runner: ResilientRunner | None = None,
        sdk_client: AsyncTavilyClient | None = None,
        api_key: SecretStr | None = None,
    ) -> None:
        """Wrap the caller-owned ``client`` in the shared resilience runner.

        ``sdk_client`` is a test-only seam replacing the real SDK client; the
        caller owns the shared HTTPX client and is responsible for closing it.
        The SDK client built here owns a dedicated HTTPX client that the
        adapter closes via :meth:`aclose`.
        """
        self._runner = runner or ResilientRunner(client)
        self._owned_http: httpx.AsyncClient | None = None
        self._sdk_search_timeout = _sdk_timeout_seconds(client, cap=_SDK_SEARCH_TIMEOUT_MAX)
        self._sdk_extract_timeout = _sdk_timeout_seconds(client, cap=_SDK_EXTRACT_TIMEOUT_MAX)
        self._sdk = sdk_client or self._build_sdk(client, api_key)

    def _build_sdk(
        self, client: httpx.AsyncClient, api_key: SecretStr | None = None
    ) -> AsyncTavilyClient:
        """Build the official SDK scoped to an adapter-owned HTTPX client.

        The SDK stamps its Authorization header and base URL onto whatever
        client it is handed, but only sets headers that are not already
        present, so the adapter-owned client must start clean: copying the
        shared client's headers would both preempt the resolver key and leak
        other providers' secrets (e.g. ``Authorization``, ``X-API-Key``) to
        Tavily. Only the harmless User-Agent is forwarded; the SDK then fills
        in its own Authorization and base URL on the private client. Its
        non-owning transport delegates to the shared client's selected pool,
        preserving limits/proxy/TLS policy without closing it. The key comes
        only from the shared resolver; absent credentials fail closed rather
        than letting the SDK fall back to ambient ``TAVILY_API_KEY`` or keyless
        mode.
        """
        resolved = api_key
        if resolved is None:
            raise self._error("configuration_error", "no Tavily API key configured")
        forwarded = {
            key: value for key, value in client.headers.items() if key.lower() == "user-agent"
        }
        self._owned_http = httpx.AsyncClient(
            follow_redirects=client.follow_redirects,
            headers=forwarded,
            max_redirects=client.max_redirects,
            timeout=client.timeout,
            transport=BorrowedTransport(client, reassert_timeout=True),
        )
        return AsyncTavilyClient(
            api_key=resolved.get_secret_value(),
            client=self._owned_http,
        )

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
        )

    async def _search_sdk(self, request: SearchRequest) -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "query": request.query,
            "max_results": min(request.limit, _MAX_SEARCH_RESULTS),
            "include_usage": True,
        }
        # Always forward a scalar clamped to the vendor's 1-120s search range,
        # so the SDK never silently reverts to its 60s default or rejects a
        # sub-second value; the borrowed transport reasserts the shared phase
        # policy at request time.
        kwargs["timeout"] = self._sdk_search_timeout
        if request.domains:
            kwargs["include_domains"] = list(request.domains)
        if request.country_code is not None:
            country = _TAVILY_COUNTRIES.get(request.country_code.upper())
            if country is not None:
                kwargs["country"] = country
        try:
            return cast(dict[str, Any], await self._sdk.search(**kwargs))
        except httpx.TransportError:
            raise  # the shared ResilientRunner normalizes transport failures
        except Exception as exc:
            raise self._normalize_error(exc) from None

    def _normalize_result(self, item: Any) -> SearchResult:
        score = item.get("score")
        if not isinstance(score, (int, float)) or not 0 <= score <= 1:
            score = None
        metadata: dict[str, Any] = {}
        for key in ("id", "favicon"):
            if item.get(key) is not None:
                metadata[key] = item[key]
        return SearchResult(
            title=item.get("title") or "",
            url=item["url"],
            snippet=item.get("content") or "",
            published_at=_parse_published_at(item.get("published_date")),
            score=score,
            metadata=metadata,
        )

    async def fetch(self, request: FetchRequest) -> FetchResponse:
        response = await self._runner.run(self.name, lambda: self._fetch_sdk(request))
        try:
            results = response.get("results") or []
            target = str(request.url)
            match = next(
                (r for r in results if _same_url(str(r.get("url") or ""), target)),
                None,
            )
            if match is None:
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
            )
        except ProviderOperationError:
            raise
        except Exception:
            # A structurally malformed payload must not escape as a raw
            # AttributeError/KeyError/TypeError after the call succeeded.
            raise self._error("invalid_response", "malformed fetch response") from None

    async def _fetch_sdk(self, request: FetchRequest) -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "urls": [str(request.url)],
            "format": "markdown",
            "include_usage": True,
        }
        # Always forward a scalar clamped to the vendor's 1-60s extract range,
        # so the SDK never silently reverts to its 30s default or rejects a
        # sub-second value; the borrowed transport reasserts the shared phase
        # policy at request time.
        kwargs["timeout"] = self._sdk_extract_timeout
        try:
            return cast(dict[str, Any], await self._sdk.extract(**kwargs))
        except httpx.TransportError:
            raise  # the shared ResilientRunner normalizes transport failures
        except Exception as exc:
            raise self._normalize_error(exc) from None

    async def quota(self) -> QuotaSnapshot | None:
        """Fetch and map the account's authoritative usage snapshot.

        The request goes out on the adapter-owned scoped client that already
        carries the resolver key and routes through the shared resilience
        runner, so HTTP status and transport failures reuse the same
        retry/breaker policy as search and fetch. The runner sees the raw
        ``httpx.Response``, so a 429 honors its ``Retry-After`` header and
        records the provider cooldown before a final non-2xx is normalized
        here with the same status mapping as the SDK paths. A structurally
        malformed payload surfaces as the redaction-safe, non-retryable
        ``invalid_response`` error rather than a raw parsing failure.
        """
        response = await self._runner.run(self.name, lambda: self._quota_request())
        try:
            if response.is_error:
                status = response.status_code
                raise self._error(
                    "http_error",
                    f"HTTP {status}",
                    retryable=status in RETRYABLE_STATUS_CODES,
                    status=status,
                ) from None
            return self._quota_snapshot(cast(dict[str, Any], response.json()))
        except ProviderOperationError:
            raise
        except Exception:
            # A structurally malformed payload must not escape as a raw
            # AttributeError/KeyError/TypeError/JSONDecodeError after the
            # call succeeded.
            raise self._error("invalid_response", "malformed usage response") from None

    async def _quota_request(self) -> httpx.Response:
        """GET the ``/usage`` endpoint on the scoped client, unnormalized.

        The raw ``httpx.Response`` is returned so the shared runner can apply
        its built-in 429 ``Retry-After``/cooldown behavior before ``quota``
        normalizes the final status.
        """
        client = self._owned_http
        if client is None:
            # The scoped client exists only when the resolver key was present
            # at construction; absent credentials fail closed rather than
            # attempting a keyless request.
            raise self._error("configuration_error", "no Tavily API key configured")
        return await client.get(_USAGE_URL)

    async def usage_snapshot(self, request: UsageSyncRequest) -> NativeUsageSnapshot | None:
        """Return the account credit observation of the existing usage read.

        The plan limit minus the plan usage gives the plan remaining. A tighter
        per-key ceiling caps that remaining when the payload supplies both key
        figures. PAYGO stays an access mode and never becomes stored credits.
        An absent remaining stays absent.
        """

        response = await self._runner.run(self.name, lambda: self._quota_request())
        try:
            if response.is_error:
                status = response.status_code
                raise self._error(
                    "http_error",
                    f"HTTP {status}",
                    retryable=status in RETRYABLE_STATUS_CODES,
                    status=status,
                ) from None
            payload = response.json()
            if not isinstance(payload, dict):
                raise ValueError("usage payload is not a mapping")
            body = cast(dict[str, Any], payload)
            snapshot = self._quota_snapshot(body)
            remaining = self._capped_remaining(body, snapshot.remaining)
        except ProviderOperationError:
            raise
        except Exception:
            # A structurally malformed payload must not escape as a raw
            # AttributeError/KeyError/TypeError/JSONDecodeError after the
            # call succeeded.
            raise self._error("invalid_response", "malformed usage response") from None
        auth_mode = self.limit_auth_mode
        return NativeUsageSnapshot(
            pool_id=native_pool_id(self.name, auth_mode, UnitKind.CREDIT),
            provider=self.name,
            auth_mode=auth_mode,
            native_unit=UnitKind.CREDIT,
            observed_at=request.observed_at,
            source="vendor_api",
            confidence=Confidence.AUTHORITATIVE if remaining is not None else Confidence.UNKNOWN,
            remaining=remaining,
            allowance=snapshot.limit,
            reset_at=snapshot.reset_at,
            credential_generation=request.credential_generation,
        )

    def _capped_remaining(
        self,
        payload: dict[str, Any],
        plan_remaining: Decimal | None,
    ) -> Decimal | None:
        """Cap the plan remaining at the per-key ceiling when the payload has both.

        A key figure that is absent or not a real finite non-negative number
        supplies no ceiling, so the plan figure stays. That figure never
        becomes zero through malformed data.
        """

        key = payload.get("key")
        if not isinstance(key, dict):
            return plan_remaining
        limit = key.get("limit")
        usage = key.get("usage")
        if not self._is_quota_number(limit) or not self._is_quota_number(usage):
            return plan_remaining
        key_remaining = max(Decimal(0), Decimal(str(limit)) - Decimal(str(usage)))
        if plan_remaining is None:
            return key_remaining
        return min(plan_remaining, key_remaining)

    @staticmethod
    def _is_quota_number(value: Any) -> bool:
        """Return whether a payload value is a real, finite, non-negative number."""

        return (
            not isinstance(value, bool)
            and isinstance(value, (int, float))
            and isfinite(value)
            and value >= 0
        )

    async def estimate_cost(self, request: SearchRequest | FetchRequest) -> CostEstimate:
        if isinstance(request, SearchRequest):
            return CostEstimate(
                provider=self.name,
                operation=UsageOperation.SEARCH,
                units=Decimal("1"),
                currency="credits",
                notes="basic search costs one credit per request",
            )
        return CostEstimate(
            provider=self.name,
            operation=UsageOperation.FETCH,
            units=_FETCH_CREDIT_PER_URL,
            currency="credits",
            notes=(
                "average per URL; Tavily bills basic extraction as one credit "
                "per five successful URLs"
            ),
        )

    def _quota_snapshot(self, response: dict[str, Any]) -> QuotaSnapshot:
        """Map the ``/usage`` payload to an authoritative bounded snapshot.

        The account plan figures are authoritative; when either side is
        absent the key figures bind remaining instead. A present-but-
        malformed numeric (bool, non-finite, negative, or otherwise not a
        real number) or a present-but-non-mapping ``account`` (e.g. a list)
        is surfaced as the redaction-safe ``invalid_response`` error rather
        than a raw ``Decimal`` failure or a silent key-figure fallback. Only
        genuinely absent, null, or incomplete account figures fall back to
        the key figures. Pay-as-you-go status is ignored: such plans simply
        lack a plan limit and fall back to the key figures.
        """
        observed_at = datetime.now(UTC)
        account = response.get("account")
        if account is not None and not isinstance(account, dict):
            raise self._error("invalid_response", "malformed usage response") from None
        if isinstance(account, dict):
            usage = account.get("plan_usage")
            limit = account.get("plan_limit")
            if usage is not None and limit is not None:
                plan_usage = self._quota_number(usage)
                plan_limit = self._quota_number(limit)
                assert plan_usage is not None and plan_limit is not None
                return QuotaSnapshot(
                    provider=self.name,
                    source=QuotaSource.AUTHORITATIVE,
                    remaining=max(Decimal(0), plan_limit - plan_usage),
                    limit=plan_limit,
                    reset_at=None,
                    observed_at=observed_at,
                    unit_kind=UnitKind.CREDIT,
                    display_unit="credits",
                    metadata={"window": "monthly"},
                )
            # Incomplete plan figures: validate any present value so a
            # malformed one still errors, then fall back to the key figures.
            if usage is not None:
                self._quota_number(usage)
            if limit is not None:
                self._quota_number(limit)
        key = response.get("key")
        if not isinstance(key, dict) or key.get("usage") is None:
            raise self._error("invalid_response", "malformed usage response")
        key_usage = self._quota_number(key["usage"])
        key_limit = self._quota_number(key.get("limit"))
        if key_limit is None:
            # Without a key limit the bounded remaining is unknowable.
            return QuotaSnapshot(
                provider=self.name,
                source=QuotaSource.AUTHORITATIVE,
                remaining=None,
                limit=None,
                reset_at=None,
                observed_at=observed_at,
                unit_kind=UnitKind.CREDIT,
                display_unit="credits",
                metadata={"window": "monthly"},
            )
        assert key_usage is not None
        return QuotaSnapshot(
            provider=self.name,
            source=QuotaSource.AUTHORITATIVE,
            remaining=max(Decimal(0), key_limit - key_usage),
            limit=key_limit,
            reset_at=None,
            observed_at=observed_at,
            unit_kind=UnitKind.CREDIT,
            display_unit="credits",
            metadata={"window": "monthly"},
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
            return None
        return UsageEvent(
            provider=self.name,
            operation=operation,
            units=Decimal(str(credits)),
            unit_kind=UnitKind.CREDIT,
            display_unit="credits",
            observed_at=datetime.now(UTC),
            request_id=response.get("request_id"),
        )

    def _normalize_error(self, exc: Exception) -> ProviderOperationError:
        if isinstance(exc, UsageLimitExceededError):
            return self._error("rate_limited", "usage limit exceeded", retryable=True, status=429)
        if isinstance(exc, InvalidAPIKeyError):
            return self._error("invalid_api_key", "invalid API key", status=401)
        if isinstance(exc, ForbiddenError):
            return self._error("forbidden", "request forbidden", status=403)
        if isinstance(exc, BadRequestError):
            return self._error("bad_request", "bad request", status=400)
        if isinstance(exc, TavilyTimeoutError):
            return self._error("timeout_error", "request timed out", retryable=True)
        if isinstance(exc, (MissingAPIKeyError, KeylessUnsupportedEndpointError)):
            return self._error("configuration_error", "SDK configuration error")
        if isinstance(exc, httpx.HTTPStatusError):
            status = exc.response.status_code
            return self._error(
                "http_error",
                f"HTTP {status}",
                retryable=status in RETRYABLE_STATUS_CODES,
                status=status,
            )
        return self._error("tavily_error", type(exc).__name__)

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
