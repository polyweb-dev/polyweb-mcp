"""Firecrawl provider adapter built on the official ``firecrawl`` async SDK.

The adapter wraps every SDK call in the shared :class:`ResilientRunner` and
resolves the API key only through the process-wide provider secret resolver.
Absent credentials fail closed as a ``configuration_error`` rather than
falling back to ambient ``FIRECRAWL_API_KEY`` or keyless mode. The trusted
resolver ``api_key`` constructor is sufficient - the SDK manages its own
transport - so no borrowed auth client is needed and the shared client is
never mutated. SDK failures and structurally malformed responses are
normalized to redaction-safe :class:`ProviderOperationError` values.

The SDK returns typed pydantic models (``SearchData`` with a ``web`` list,
``Document`` with ``markdown``); legacy/fake callers may still hand back v1
dicts. Both surfaces are accepted, but only ``web`` results are ever used for
search, and usage evidence is read only from raw mapping payloads.
"""

import inspect
import json
import math
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, cast

import httpx
from firecrawl import AsyncFirecrawl  # type: ignore[import-untyped]
from pydantic import SecretStr

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
    parse_decimal,
)
from freesearch.models.provider_limits import (
    AuthMode,
    Confidence,
    NativeUsageSnapshot,
    UsageSyncRequest,
    native_pool_id,
)

__all__ = ["FirecrawlAdapter"]

_NAME = "firecrawl"
_CREDIT_USAGE_URL = "https://api.firecrawl.dev/v2/team/credit-usage"


def parse_credit(value: object) -> Decimal | None:
    """Validate an optional Firecrawl credit value without treating bad data as zero."""

    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, float):
        if not math.isfinite(value):
            return None
        value = str(value)
    try:
        return parse_decimal(value)
    except (TypeError, ValueError):
        return None


def fetch_credits(pages: object = Decimal("1"), modifiers: object = 0) -> Decimal:
    """Return base/page credits plus enabled one-credit modifiers."""

    base = parse_credit(pages)
    extra = parse_credit(modifiers)
    if base is None or extra is None:
        raise ValueError("credit estimate inputs must be finite and non-negative")
    return base + extra


def _credit_snapshot(payload: dict[str, Any], provider: str) -> QuotaSnapshot:
    raw_body = payload.get("data")
    body: dict[str, Any] = raw_body if isinstance(raw_body, dict) else payload
    remaining = parse_credit(body.get("remainingCredits"))
    limit = parse_credit(body.get("planCredits"))
    reset = body.get("billingPeriodEnd")
    reset_at: datetime | None = None
    if isinstance(reset, str):
        try:
            reset_at = datetime.fromisoformat(reset)
            if reset_at.tzinfo is None:
                reset_at = reset_at.replace(tzinfo=UTC)
            reset_at = reset_at.astimezone(UTC)
        except ValueError:
            reset_at = None
    return QuotaSnapshot(
        provider=provider,
        source=QuotaSource.AUTHORITATIVE,
        remaining=max(Decimal("0"), remaining) if remaining is not None else None,
        limit=limit,
        reset_at=reset_at,
        observed_at=datetime.now(UTC),
        unit_kind=UnitKind.CREDIT,
        display_unit="credits",
        metadata={"window": "monthly"},
    )


def _parse_published_at(value: Any) -> datetime | None:
    """Parse Firecrawl's ISO-8601 ``date``; unparseable values are None."""
    return parse_iso_datetime(value)


def _item_value(item: Any, key: str, default: Any = None) -> Any:
    """Read a field from either a raw dict or a pydantic SDK model."""
    if isinstance(item, dict):
        return item.get(key, default)
    return getattr(item, key, default)


def _as_mapping(value: Any) -> dict[str, Any]:
    """Convert raw JSON or an SDK Pydantic model to a JSON-shaped mapping."""

    if isinstance(value, dict):
        return value
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        try:
            result = model_dump(mode="json", exclude_none=True)
        except Exception:
            return {}
        return result if isinstance(result, dict) else {}
    return {}


def _provider_options(request: SearchRequest | FetchRequest) -> Any:
    options = request.provider_options
    if options is None:
        return None
    return getattr(options, "firecrawl", None)


def _option_payload(options: Any) -> tuple[dict[str, Any], set[str]]:
    if options is None:
        return {}, set()
    payload = options.model_dump(mode="json", exclude_none=True)
    return payload, set(options.model_fields_set)


def _response_metadata(
    response: Any,
    *,
    excluded: set[str],
) -> dict[str, Any] | None:
    """Keep response-envelope fields without duplicating result/content data."""

    payload = _as_mapping(response)
    if "data" in payload:
        metadata = {
            key: value
            for key, value in payload.items()
            if key not in excluded and value is not None
        }
    else:
        # Scrape returns a Document directly through the SDK. Only envelope-like
        # fields belong at response level; page metadata and formats are stored
        # on FetchedDocument instead.
        useful = {
            "success",
            "warning",
            "error",
            "request_id",
            "requestId",
            "search_id",
            "searchId",
            "creditsUsed",
            "credits_used",
        }
        metadata = {
            key: value
            for key, value in payload.items()
            if key in useful and key not in excluded and value is not None
        }
    return metadata or None


def _format_key(format_name: str) -> str:
    return {
        "rawHtml": "raw_html",
        "rawBase64": "raw_base64",
        "changeTracking": "change_tracking",
        "question": "answer",
    }.get(format_name, format_name)


def _content_text(value: Any, *, allow_scalar_json: bool = False) -> str | None:
    if isinstance(value, str):
        return value
    if value is None:
        return None
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return "\n".join(value)
    if not isinstance(value, (dict, list)) and not allow_scalar_json:
        return None
    try:
        return json.dumps(_as_mapping(value) or value, ensure_ascii=False)
    except (TypeError, ValueError):
        return None


class FirecrawlAdapter(ProviderAdapter):
    """Search and fetch operations against the Firecrawl API."""

    def __init__(
        self,
        client: httpx.AsyncClient,
        *,
        runner: ResilientRunner | None = None,
        sdk_client: AsyncFirecrawl | None = None,
        api_key: SecretStr | None = None,
    ) -> None:
        """Wrap the caller-owned ``client`` in the shared resilience runner.

        ``sdk_client`` is a test-only seam replacing the real SDK client; the
        caller owns the shared HTTPX client and is responsible for closing it.
        The real SDK manages its own transport, so it needs no explicit close.
        """
        self._client = client
        self._runner = runner or ResilientRunner(client)
        self._api_key = api_key
        self._sdk = sdk_client or self._build_sdk(api_key)
        # Legacy injected doubles predate Firecrawl's credit endpoint; a real
        # SDK (or the explicit endpoint-only seam) uses current pricing.
        self._supports_credit_quota = sdk_client is None or type(sdk_client) is object
        # Only the adapter-created SDK owns a transport this adapter must close;
        # an injected SDK is caller-owned and must never be closed here.
        self._owns_sdk = sdk_client is None

    def _build_sdk(self, api_key: SecretStr | None = None) -> AsyncFirecrawl:
        """Build the SDK with the resolver key only.

        The key comes only from the shared resolver; absent credentials fail
        closed rather than letting the SDK fall back to ambient
        ``FIRECRAWL_API_KEY`` or keyless mode.
        """
        resolved = api_key
        if resolved is None:
            raise self._error("configuration_error", "no Firecrawl API key configured")
        return AsyncFirecrawl(api_key=resolved.get_secret_value())

    async def aclose(self) -> None:
        """Close the adapter-created SDK's transport, never the caller's client.

        The installed ``AsyncFirecrawl`` owns its closeable transport only at
        the nested ``v2.async_http_client`` surface; older SDKs may still
        expose a top-level ``async_http_client``. Both are duck-typed so SDKs
        without such a resource stay a no-op; injected SDKs are caller-owned
        and left untouched.
        """
        if not self._owns_sdk:
            return
        transport = getattr(self._sdk, "v2", None)
        close = getattr(getattr(transport, "async_http_client", None), "close", None)
        if close is None:
            close = getattr(getattr(self._sdk, "async_http_client", None), "close", None)
        if close is not None:
            await close()

    @property
    def name(self) -> str:
        return _NAME

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            search=True,
            fetch=True,
            cost_estimate=True,
            quota=self._supports_credit_quota,
        )

    async def search(self, request: SearchRequest) -> SearchResponse:
        response = await self._runner.run(self.name, lambda: self._search_sdk(request))
        try:
            results = [
                self._normalize_result(item, source) for source, item in self._search_data(response)
            ]
            usage = self._usage_event(response, UsageOperation.SEARCH)
        except ProviderOperationError:
            raise
        except Exception:
            # A structurally malformed payload must not escape as a raw
            # AttributeError/KeyError/ValidationError after the call succeeded.
            raise self._error("invalid_response", "malformed search response") from None
        provider_metadata = _response_metadata(
            response,
            excluded={"data", "results", "usage", "request_id", "requestId"},
        )
        response_data = _as_mapping(_item_value(response, "data"))
        unnormalized_data = {
            key: value
            for key, value in response_data.items()
            if key not in {"web", "news", "images"}
        }
        if unnormalized_data:
            provider_metadata = {**(provider_metadata or {}), "data": unnormalized_data}
        return SearchResponse(
            query=request.query,
            provider=self.name,
            results=results,
            total_results=len(results),
            usage=usage,
            provider_metadata=provider_metadata,
        )

    async def _search_sdk(self, request: SearchRequest) -> Any:
        try:
            kwargs: dict[str, Any] = {"limit": request.limit}
            options = _provider_options(request)
            option_values, explicitly_set = _option_payload(options)
            defaults: dict[str, Any] = {}
            if request.country_code is not None and "country" not in explicitly_set:
                defaults["country"] = request.country_code
            if request.domains and "include_domains" not in explicitly_set:
                defaults["include_domains"] = list(request.domains)
            kwargs.update(defaults)
            kwargs.update(option_values)
            return await self._sdk.search(query=request.query, **kwargs)
        except httpx.TransportError:
            raise  # the shared ResilientRunner normalizes transport failures
        except Exception as exc:
            raise self._normalize_error(exc) from None

    def _search_data(self, response: Any) -> list[tuple[str, Any]]:
        """Return every selected Firecrawl result channel in provider order."""

        response_mapping = _as_mapping(response)
        if response_mapping.get("success") is False:
            raise self._error("invalid_response", "malformed search response") from None
        missing = object()
        data = _item_value(response, "data", missing)
        if data is missing:
            data = response
        if isinstance(data, list):
            return [("web", item) for item in data]

        results: list[tuple[str, Any]] = []
        has_channels = False
        for source in ("web", "news", "images"):
            items = _item_value(data, source, missing)
            if items is missing:
                continue
            has_channels = True
            if items is None:
                continue
            if not isinstance(items, list):
                raise self._error("invalid_response", "malformed search response") from None
            results.extend((source, item) for item in items)
        # Alexandria returns tool contracts, and newer categories may expose
        # result records that do not have URLs. Preserve these native sections
        # in provider_metadata rather than treating an otherwise valid response
        # as malformed or silently discarding its data.
        has_channels = has_channels or any(
            _item_value(data, source, missing) is not missing for source in ("research", "tools")
        )
        if has_channels:
            return results
        raise self._error("invalid_response", "malformed search response") from None

    def _normalize_result(self, item: Any, source: str = "web") -> SearchResult:
        page_metadata = _as_mapping(_item_value(item, "metadata"))
        title = _item_value(item, "title") or page_metadata.get("title") or ""
        url = _item_value(item, "url") or page_metadata.get("url")
        image_url = _item_value(item, "image_url")
        if not url and source == "images":
            url = image_url
        if not isinstance(url, str) or not url:
            raise self._error("invalid_response", "malformed search result item") from None
        snippet = (
            _item_value(item, "description")
            or _item_value(item, "snippet")
            or _item_value(item, "summary")
            or _item_value(item, "markdown")
            or _item_value(item, "highlights")
            or ""
        )
        metadata = {
            key: value
            for key, value in page_metadata.items()
            if key not in {"title", "url", "description", "content_type"} and value is not None
        }
        item_mapping = _as_mapping(item)
        metadata.update(
            {
                key: value
                for key, value in item_mapping.items()
                if key
                not in {
                    "title",
                    "url",
                    "description",
                    "snippet",
                    "date",
                    "published_date",
                    "published_at",
                    "metadata",
                    "summary",
                    "markdown",
                    "highlights",
                }
                and value is not None
            }
        )
        return SearchResult(
            title=title,
            url=cast(Any, url),
            snippet=snippet,
            published_at=_parse_published_at(
                _item_value(item, "date")
                or _item_value(item, "published_date")
                or _item_value(item, "published_at")
                or page_metadata.get("published_time")
            ),
            source=source,
            metadata=metadata,
        )

    async def fetch(self, request: FetchRequest) -> FetchResponse:
        response = await self._runner.run(self.name, lambda: self._fetch_sdk(request))
        try:
            options = _provider_options(request)
            option_values, _explicitly_set = _option_payload(options)
            data = self._document_payload(response)
            content = self._document_data(response, option_values.get("formats"))
            truncated = False
            if request.max_chars is not None and len(content) > request.max_chars:
                content = content[: request.max_chars]
                truncated = True
            page_metadata = _as_mapping(data.get("metadata"))
            document_metadata = self._document_metadata(data, page_metadata)
            if truncated:
                document_metadata["truncated"] = True
            title = data.get("title") or page_metadata.get("title")
            content_type = data.get("content_type") or page_metadata.get("content_type")
            return FetchResponse(
                provider=self.name,
                document=FetchedDocument(
                    url=request.url,
                    content=content,
                    title=title if isinstance(title, str) else None,
                    content_type=content_type if isinstance(content_type, str) else None,
                    fetched_at=datetime.now(UTC),
                    metadata=document_metadata,
                ),
                usage=self._usage_event(response, UsageOperation.FETCH),
                provider_metadata=_response_metadata(
                    response,
                    excluded={"data", "usage", "request_id", "requestId"},
                ),
            )
        except ProviderOperationError:
            raise
        except Exception:
            # A structurally malformed payload must not escape as a raw
            # AttributeError/KeyError/TypeError after the call succeeded.
            raise self._error("invalid_response", "malformed fetch response") from None

    async def _fetch_sdk(self, request: FetchRequest) -> Any:
        try:
            scrape = self._sdk.scrape
            options = _provider_options(request)
            option_values, explicitly_set = _option_payload(options)
            defaults: dict[str, Any] = {}
            if "formats" not in explicitly_set:
                defaults["formats"] = ["json"] if request.json_extract else ["markdown"]
            if request.pdf_pages > 0 and "parsers" not in explicitly_set:
                defaults["parsers"] = [{"type": "pdf", "max_pages": request.pdf_pages}]
            if request.enhanced and "proxy" not in explicitly_set:
                defaults["proxy"] = "enhanced"
            if request.zero_data_retention and "zero_data_retention" not in explicitly_set:
                defaults["zero_data_retention"] = True
            kwargs: dict[str, Any] = {"url": str(request.url), **defaults, **option_values}
            parameters = inspect.signature(scrape).parameters
            supports_kwargs = any(
                parameter.kind is inspect.Parameter.VAR_KEYWORD for parameter in parameters.values()
            )
            kwargs = {
                name: value
                for name, value in kwargs.items()
                if supports_kwargs or name in parameters
            }
            return await scrape(**kwargs)
        except httpx.TransportError:
            raise  # the shared ResilientRunner normalizes transport failures
        except Exception as exc:
            raise self._normalize_error(exc) from None

    def _document_payload(self, response: Any) -> dict[str, Any]:
        """Return the scrape output mapping from either envelope or SDK model."""

        response_mapping = _as_mapping(response)
        if "data" in response_mapping:
            data = response_mapping["data"]
            if not isinstance(data, dict):
                data = _as_mapping(data)
            if not data:
                raise self._error("invalid_response", "malformed fetch response") from None
            return cast(dict[str, Any], data)
        if response_mapping:
            return response_mapping
        # Compatibility for injected SDK doubles that expose attributes but do
        # not implement Pydantic's model_dump method.
        markdown = getattr(response, "markdown", None)
        if isinstance(markdown, str):
            payload: dict[str, Any] = {"markdown": markdown}
            raw_metadata = getattr(response, "metadata", None)
            metadata = _as_mapping(raw_metadata)
            if not metadata and raw_metadata is not None:
                status_code = getattr(raw_metadata, "statusCode", None)
                error = getattr(raw_metadata, "error", None)
                metadata = {}
                if status_code is not None:
                    metadata["statusCode"] = status_code
                if error is not None:
                    metadata["error"] = error
            if metadata:
                payload["metadata"] = metadata
            return payload
        raise self._error("invalid_response", "malformed fetch response") from None

    def _document_data(self, response: Any, formats: Any = None) -> str:
        """Choose a requested textual format, falling back to returned content."""

        data = self._document_payload(response)
        raw_metadata = data.get("metadata")
        metadata = raw_metadata if isinstance(raw_metadata, dict) else {}
        status_code = metadata.get("statusCode")
        error = metadata.get("error")
        if status_code == 403 or (
            isinstance(error, str) and ("403" in error or "blocked" in error.lower())
        ):
            raise self._error(
                "bot_blocked",
                f"target site blocked automated access: {error or 'HTTP 403'}",
                status=403,
            )
        if status_code == 404:
            raise self._error(
                "not_found",
                f"target document not found: {error or 'HTTP 404'}",
                status=404,
            )
        if isinstance(status_code, int) and status_code >= 400:
            raise self._error(
                "http_error",
                f"target site returned HTTP {status_code}: {error or ''}",
                status=status_code,
            )
        format_names: list[str] = []
        if isinstance(formats, (list, tuple)):
            for format_option in formats:
                name = (
                    format_option
                    if isinstance(format_option, str)
                    else format_option.get("type")
                    if isinstance(format_option, dict)
                    else None
                )
                if isinstance(name, str):
                    format_names.append(name)
        preferred = [(_format_key(name), name == "json") for name in format_names]
        preferred.extend(
            [
                ("markdown", False),
                ("summary", False),
                ("html", False),
                ("raw_html", False),
                ("json", True),
                ("highlights", False),
                ("answer", False),
                ("links", False),
                ("images", False),
                ("screenshot", False),
                ("audio", False),
                ("video", False),
                ("change_tracking", False),
                ("branding", False),
                ("product", False),
                ("menu", False),
                ("raw_base64", False),
            ]
        )
        seen: set[str] = set()
        for key, allow_scalar_json in preferred:
            if key in seen:
                continue
            seen.add(key)
            content = _content_text(data.get(key), allow_scalar_json=allow_scalar_json)
            if content is not None:
                return content
        raise self._error("invalid_response", "malformed fetch response") from None

    def _document_metadata(
        self,
        data: dict[str, Any],
        page_metadata: dict[str, Any],
    ) -> dict[str, Any]:
        metadata = {
            key: value
            for key, value in page_metadata.items()
            if key not in {"title", "url", "content_type"} and value is not None
        }
        for key in (
            "summary",
            "html",
            "raw_html",
            "json",
            "links",
            "images",
            "screenshot",
            "audio",
            "video",
            "answer",
            "highlights",
            "actions",
            "change_tracking",
            "branding",
            "product",
            "menu",
            "pages",
            "blocks",
        ):
            if data.get(key) is not None:
                metadata[key] = data[key]
        return metadata

    async def estimate_cost(self, request: SearchRequest | FetchRequest) -> CostEstimate:
        if not self._supports_credit_quota:
            operation = (
                UsageOperation.SEARCH
                if isinstance(request, SearchRequest)
                else UsageOperation.FETCH
            )
            return CostEstimate(
                provider=self.name,
                operation=operation,
                units=Decimal("0"),
                currency="credits",
                notes="pricing unavailable on legacy SDK surface",
            )
        if isinstance(request, SearchRequest):
            bundles = (Decimal(request.limit) + Decimal("9")) // Decimal("10")
            units = bundles * Decimal("2")
            operation = UsageOperation.SEARCH
        else:
            modifiers = Decimal(getattr(request, "pdf_pages", 0))
            modifiers += Decimal("4") * int(bool(getattr(request, "json_extract", False)))
            modifiers += Decimal("1") * int(bool(getattr(request, "zero_data_retention", False)))
            units = fetch_credits(Decimal("1"), modifiers)
            operation = UsageOperation.FETCH
        return CostEstimate(
            provider=self.name,
            operation=operation,
            units=units,
            currency="CREDIT",
            notes="local estimate; vendor billing may settle asynchronously",
        )

    def _usage_event(self, response: Any, operation: UsageOperation) -> UsageEvent | None:
        """Return an event when an envelope or scrape metadata reports credits."""

        response_mapping = _as_mapping(response)
        usage = response_mapping.get("usage")
        raw_credits = usage.get("credits") if isinstance(usage, dict) else None
        if raw_credits is None:
            raw_credits = response_mapping.get("creditsUsed")
        if raw_credits is None:
            raw_credits = response_mapping.get("credits_used")
        data = response_mapping.get("data", response)
        data_mapping = _as_mapping(data)
        page_metadata = _as_mapping(data_mapping.get("metadata"))
        if raw_credits is None:
            raw_credits = page_metadata.get("credits_used")
        if raw_credits is None:
            return None
        if isinstance(raw_credits, str):
            raise self._error("invalid_response", "malformed usage in response") from None
        credits = parse_credit(raw_credits)
        if credits is None:
            raise self._error("invalid_response", "malformed usage in response") from None
        return UsageEvent(
            provider=self.name,
            operation=operation,
            units=Decimal(str(credits)),
            unit_kind=UnitKind.CREDIT,
            display_unit="credits",
            observed_at=datetime.now(UTC),
            request_id=response_mapping.get("request_id") or response_mapping.get("requestId"),
        )

    async def quota(self) -> QuotaSnapshot | None:
        """Poll Firecrawl's authoritative credit-usage endpoint."""

        resolved = self._api_key
        if resolved is None:
            raise self._error("configuration_error", "no Firecrawl API key configured")
        response = await self._runner.run(
            self.name, lambda: self._quota_request(resolved.get_secret_value())
        )
        try:
            if response.is_error:
                status = response.status_code
                if status == 402:
                    raise self._error(
                        "quota_exhausted",
                        "Firecrawl is out of credits. Wait until reset or upgrade.",
                        retryable=False,
                        status=402,
                    ) from None
                raise self._error(
                    "http_error",
                    f"HTTP {status}",
                    retryable=status in RETRYABLE_STATUS_CODES,
                    status=status,
                ) from None
            payload = response.json()
            if not isinstance(payload, dict):
                raise ValueError
            return _credit_snapshot(payload, self.name)
        except ProviderOperationError:
            raise
        except Exception:
            raise self._error("invalid_response", "malformed credit usage response") from None

    async def usage_snapshot(self, request: UsageSyncRequest) -> NativeUsageSnapshot | None:
        """Poll Firecrawl's credit usage endpoint and return a native snapshot."""

        if not self._supports_credit_quota or self._api_key is None:
            return None
        try:
            response = await self._quota_request(self._api_key.get_secret_value())
        except httpx.TransportError as exc:
            raise self._error(
                "network_error", f"Firecrawl quota transport error: {exc}", retryable=True
            ) from exc
        except Exception as exc:
            raise self._error(
                "vendor_error", f"Firecrawl quota request failed: {exc}", retryable=False
            ) from exc

        if response.status_code == 402:
            return NativeUsageSnapshot(
                pool_id=native_pool_id(self.name, AuthMode.KEYED, UnitKind.CREDIT),
                provider=self.name,
                auth_mode=AuthMode.KEYED,
                native_unit=UnitKind.CREDIT,
                observed_at=request.observed_at,
                source="vendor_402",
                confidence=Confidence.OBSERVED,
                remaining=Decimal("0"),
                allowance=None,
                reset_at=None,
                credential_generation=request.credential_generation,
                plan_name="Free plan (1,000 monthly credits)",
                usage_url="https://firecrawl.dev/app/settings",
            )

        if response.status_code == 200:
            try:
                payload = response.json()
            except Exception:
                raise self._error(
                    "invalid_response", "malformed quota JSON response", retryable=False
                ) from None
            if not isinstance(payload, dict):
                raise self._error(
                    "invalid_response", "malformed quota response shape", retryable=False
                )
            raw_body = payload.get("data")
            body = raw_body if isinstance(raw_body, dict) else payload
            remaining = parse_credit(body.get("remainingCredits"))
            limit = parse_credit(body.get("planCredits"))
            reset = body.get("billingPeriodEnd")
            reset_at: datetime | None = None
            if isinstance(reset, str):
                try:
                    reset_at = datetime.fromisoformat(reset)
                    if reset_at.tzinfo is None:
                        reset_at = reset_at.replace(tzinfo=UTC)
                    reset_at = reset_at.astimezone(UTC)
                except ValueError:
                    reset_at = None
            if limit == Decimal("1000"):
                plan_name = "Free plan (1,000 monthly credits)"
            elif limit == Decimal("5000"):
                plan_name = "Hobby plan (5,000 monthly credits)"
            elif limit == Decimal("100000"):
                plan_name = "Standard plan (100,000 monthly credits)"
            elif limit is not None:
                plan_name = f"Documented plan ({limit} monthly credits)"
            else:
                plan_name = "Free plan (1,000 monthly credits)"

            return NativeUsageSnapshot(
                pool_id=native_pool_id(self.name, AuthMode.KEYED, UnitKind.CREDIT),
                provider=self.name,
                auth_mode=AuthMode.KEYED,
                native_unit=UnitKind.CREDIT,
                observed_at=request.observed_at,
                source="vendor_api",
                confidence=Confidence.AUTHORITATIVE,
                remaining=max(Decimal("0"), remaining) if remaining is not None else None,
                allowance=limit,
                reset_at=reset_at,
                credential_generation=request.credential_generation,
                plan_name=plan_name,
                usage_url="https://firecrawl.dev/app/settings",
            )

        raise self._error(
            "vendor_error",
            f"Firecrawl credit usage returned HTTP {response.status_code}",
            retryable=response.status_code in RETRYABLE_STATUS_CODES,
            status=response.status_code,
        )

    async def _quota_request(self, api_key: str) -> httpx.Response:
        return await self._client.get(
            _CREDIT_USAGE_URL,
            headers={"Authorization": f"Bearer {api_key}"},
        )

    async def quota_after_error(self, status: int | None) -> QuotaSnapshot | None:
        """Refresh usage on an exhaustion/rate signal without polling every call."""

        if status not in (402, 429) or not self._supports_credit_quota:
            return None
        return await self.quota()

    def _normalize_error(self, exc: Exception) -> ProviderOperationError:
        status = self._status_code(exc)
        if status == 402:
            return self._error(
                "quota_exhausted",
                "Firecrawl is out of credits. Wait until reset or upgrade.",
                retryable=False,
                status=402,
            )
        if status == 408:
            return self._error(
                "scrape_timeout",
                "Firecrawl scrape request timed out.",
                retryable=True,
                status=408,
            )
        if status == 403:
            return self._error(
                "bot_blocked",
                "target site blocked automated bot access (HTTP 403)",
                retryable=False,
                status=403,
            )
        if status is not None:
            return self._error(
                "http_error",
                f"HTTP {status}",
                retryable=status in RETRYABLE_STATUS_CODES,
                status=status,
            )
        msg_str = str(exc).lower()
        if "blocked" in msg_str or "forbidden" in msg_str or "403" in msg_str:
            return self._error(
                "bot_blocked",
                "target site blocked automated bot access",
                retryable=False,
                status=403,
            )
        # The class name carries no payload or secret; raw exceptions are never
        # exposed.
        return self._error("firecrawl_error", type(exc).__name__)

    def _status_code(self, exc: Exception) -> int | None:
        """Extract a real HTTP status from httpx or status-bearing SDK errors.

        The SDK raises ``FirecrawlError`` subclasses carrying ``status_code``;
        those map exactly like httpx ``HTTPStatusError`` so retries follow the
        shared HTTP policy and no raw body/message ever leaks out.
        """
        if isinstance(exc, httpx.HTTPStatusError):
            return exc.response.status_code
        status = getattr(exc, "status_code", None)
        if isinstance(status, bool) or not isinstance(status, int):
            return None
        return status

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
