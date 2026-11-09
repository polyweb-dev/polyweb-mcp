"""Private helpers for the You.com (YDC Index) adapter.

The URL/date/metadata normalization helpers used by
:mod:`polyweb.adapters.youcom`. The adapter module re-exports each name
so imports of ``polyweb.adapters.youcom`` keep working unchanged. The
borrowed HTTPX transport lives in
:mod:`polyweb.infrastructure.borrowed_transport`.
"""

from datetime import UTC, datetime
from decimal import Decimal
from math import isfinite
from typing import Any
from urllib.parse import urlsplit

import httpx

from polyweb.infrastructure.dates import parse_iso_datetime
from polyweb.models.contracts import (
    FetchRequest,
    QuotaSnapshot,
    QuotaSource,
    SearchRequest,
    UnitKind,
)
from polyweb.models.provider_options import YouSearchOptions

# Published unit prices in USD: Web Search at $5 per 1,000 calls and contents
# fetch per URL. ``estimate_cost`` and quota mapping share the same constants.
_SEARCH_UNIT_PRICE = Decimal("0.005")
_FETCH_UNIT_PRICE = Decimal("0.001")
_BALANCE_URL = "https://api.you.com/v1/billing/account_balance"
_MAX_SEARCH_RESULTS = 100
_SEARCH_URL = "https://ydc-index.io/v1/search"
_CONTENTS_URL = "https://ydc-index.io/v1/contents"


def _search_domain_params(
    request: SearchRequest, options: YouSearchOptions | None
) -> dict[str, list[str]]:
    include_domains = options.include_domains if options is not None else None
    if include_domains is None:
        include_domains = request.domains
    params: dict[str, list[str]] = {}
    if include_domains:
        params["include_domains"] = list(include_domains)
    if options is not None:
        for key in ("exclude_domains", "boost_domains"):
            value = getattr(options, key)
            if value:
                params[key] = list(value)
    return params


async def _search_request(client: httpx.AsyncClient, request: SearchRequest) -> httpx.Response:
    payload: dict[str, Any] = {
        "query": request.query,
        "count": min(request.limit, _MAX_SEARCH_RESULTS),
    }

    options = request.provider_options.you if request.provider_options is not None else None
    payload.update(_search_domain_params(request, options))

    country = (
        options.country
        if options is not None and options.country is not None
        else request.country_code
    )
    language = (
        options.language
        if options is not None and options.language is not None
        else request.language
    )
    if country is not None:
        payload["country"] = country
    if language is not None:
        payload["language"] = language

    if options is not None:
        for key in (
            "freshness",
            "offset",
            "safesearch",
            "knowledge",
            "strict_operators",
            "crawl_timeout",
            "livecrawl",
        ):
            value = getattr(options, key)
            if value is not None:
                payload[key] = value
        if options.livecrawl_formats is not None:
            payload["livecrawl_formats"] = list(options.livecrawl_formats)
        if options.extraction is not None:
            extraction: dict[str, Any] = {"extraction_mode": options.extraction.mode}
            if options.extraction.source is not None:
                extraction["extraction_source"] = options.extraction.source
            if options.extraction.highlights is not None:
                extraction["highlights"] = options.extraction.highlights.model_dump(
                    exclude_none=True
                )
            if options.extraction.full_page is not None:
                extraction["full_page"] = options.extraction.full_page.model_dump(exclude_none=True)
            payload["extraction"] = extraction
    return await client.post(_SEARCH_URL, json=payload)


async def _fetch_request(client: httpx.AsyncClient, request: FetchRequest) -> httpx.Response:
    options = request.provider_options.you if request.provider_options is not None else None
    payload: dict[str, Any] = {
        "urls": [str(request.url)],
        "formats": (
            list(options.formats)
            if options is not None and options.formats is not None
            else ["markdown", "metadata"]
        ),
    }
    payload["max_age"] = (
        options.max_age if options is not None and options.max_age is not None else 0
    )
    if options is not None and options.crawl_timeout is not None:
        payload["crawl_timeout"] = options.crawl_timeout
    return await client.post(
        _CONTENTS_URL,
        json=payload,
    )


def _parse_published_at(value: Any) -> datetime | None:
    """Parse You.com's ISO-8601 date fields (``publish_date``, ``page_age``)."""
    return parse_iso_datetime(value)


def _safe_url(value: Any) -> bool:
    """True only for http(s) URL strings; other schemes and junk are dropped."""
    return isinstance(value, str) and urlsplit(value).scheme in ("http", "https")


def _safe_metadata(item: Any) -> dict[str, Any]:
    """Copy the requested safe http(s) media fields verbatim into metadata."""
    metadata: dict[str, Any] = {}
    for key in ("thumbnail_url", "favicon_url"):
        if _safe_url(item.get(key)):
            metadata[key] = item[key]
    return metadata


def _match_page(pages: list[Any], target: str) -> dict[str, Any] | None:
    """The first page whose URL is equivalent to the requested target."""
    return next(
        (
            page
            for page in pages
            if isinstance(page, dict) and _same_url(str(page.get("url") or ""), target)
        ),
        None,
    )


def _page_metadata(match: dict[str, Any], truncated: bool) -> dict[str, Any]:
    """The truncation flag plus the page's OpenGraph site metadata, if any."""
    metadata: dict[str, Any] = {"truncated": True} if truncated else {}
    page_metadata = match.get("metadata")
    if not isinstance(page_metadata, dict):
        return metadata
    if isinstance(page_metadata.get("site_name"), str):
        metadata["site_name"] = page_metadata["site_name"]
    if _safe_url(page_metadata.get("favicon_url")):
        metadata["favicon_url"] = page_metadata["favicon_url"]
    return metadata


def _path_key(path: str) -> str:
    """Bare-origin slash forms are equivalent; elsewhere the slash is significant."""
    return "/" if path in ("", "/") else path


def _same_url(left: str, right: str) -> bool:
    """Compare URLs case-insensitively for scheme/host, path/query case preserved.

    You.com normalizes a bare origin to a trailing slash (``example.com`` ->
    ``example.com/``), so only those slash forms are interchangeable; a
    non-empty path keeps its trailing slash significance (``/docs`` != ``/docs/``).
    """
    try:
        left_parts, right_parts = urlsplit(left), urlsplit(right)
    except ValueError:
        return left == right
    return (
        left_parts.scheme.lower() == right_parts.scheme.lower()
        and left_parts.netloc.lower() == right_parts.netloc.lower()
        and _path_key(left_parts.path) == _path_key(right_parts.path)
        and left_parts.query == right_parts.query
        and left_parts.fragment == right_parts.fragment
    )


def _quota_balance(payload: Any) -> int | float:
    """Extract the balance USD-cents; invalid payloads raise ``ValueError``."""
    data = payload.get("data") if isinstance(payload, dict) else None
    attributes = data.get("attributes") if isinstance(data, dict) else None
    if not isinstance(attributes, dict):
        raise ValueError("quota payload is not a mapping")
    value = attributes.get("balance")
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not isfinite(value)
        or value < 0
    ):
        raise ValueError("quota balance is not a finite non-negative number")
    return value


def _quota_snapshot(provider: str, balance: int | float) -> QuotaSnapshot:
    """Expose the USD balance plus floored search and fetch equivalents."""
    balance_usd = Decimal(str(balance)) / Decimal("100")
    search_calls = balance_usd // _SEARCH_UNIT_PRICE
    fetch_calls = balance_usd // _FETCH_UNIT_PRICE
    return QuotaSnapshot(
        provider=provider,
        source=QuotaSource.ESTIMATED,
        remaining=balance_usd,
        limit=None,
        reset_at=None,
        observed_at=datetime.now(UTC),
        unit_kind=UnitKind.USD,
        display_unit="USD",
        metadata={
            "balance_usd": balance_usd,
            "search_calls": search_calls,
            "fetch_calls": fetch_calls,
        },
    )


def _estimated_quota(payload: Any, provider: str) -> QuotaSnapshot:
    """Map the account-balance payload to an estimated USD snapshot.

    The ``balance`` is the remaining USD credit balance in cents. It must be a
    real, finite, non-negative number; bools, strings, absent or non-mapping
    structure, NaN/inf, and negatives raise ``ValueError`` (the adapter
    surfaces it as the redaction-safe ``invalid_response`` error, so the raw
    payload never leaks). Remaining is the authoritative USD balance; the
    metadata carries floored Web Search and contents-call equivalents. The
    vendor exposes no plan limit or reset, so both stay ``None``.
    """
    return _quota_snapshot(provider, _quota_balance(payload))
