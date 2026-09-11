"""Private helpers for the You.com (YDC Index) adapter.

The borrowed HTTPX transport and the URL/date/metadata normalization helpers
used by :mod:`freesearch.adapters.youcom`. The adapter module re-exports each
name so imports of ``freesearch.adapters.youcom`` keep working unchanged.
"""

from datetime import UTC, datetime
from decimal import Decimal
from math import isfinite
from typing import Any
from urllib.parse import urlsplit

import httpx

from freesearch.models.contracts import (
    FetchRequest,
    QuotaSnapshot,
    QuotaSource,
    SearchRequest,
    UnitKind,
)

# Published unit prices in USD: Web Search at $5 per 1,000 calls and contents
# fetch per URL. ``estimate_cost`` and quota mapping share the same constants.
_SEARCH_UNIT_PRICE = Decimal("0.005")
_FETCH_UNIT_PRICE = Decimal("0.001")
_BALANCE_URL = "https://api.you.com/v1/billing/account_balance"
_MAX_SEARCH_RESULTS = 100
_SEARCH_URL = "https://ydc-index.io/v1/search"
_CONTENTS_URL = "https://ydc-index.io/v1/contents"


class _BorrowedTransport(httpx.AsyncBaseTransport):
    """Route through a caller-owned client's pools without owning their lifecycle."""

    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        # The scoped client's own timeout equals the shared client's, but
        # reassert it per request so nothing can substitute a scalar that
        # collapses the phase-specific policy.
        request.extensions["timeout"] = self._client.timeout.as_dict()
        return await self._client._transport_for_url(request.url).handle_async_request(request)


async def _search_request(client: httpx.AsyncClient, request: SearchRequest) -> httpx.Response:
    payload: dict[str, Any] = {
        "query": request.query,
        "count": min(request.limit, _MAX_SEARCH_RESULTS),
    }
    if request.domains:
        payload["include_domains"] = list(request.domains)
    if request.country_code is not None:
        payload["country"] = request.country_code
    if request.language is not None:
        payload["language"] = request.language
    return await client.post(_SEARCH_URL, json=payload)


async def _fetch_request(client: httpx.AsyncClient, request: FetchRequest) -> httpx.Response:
    return await client.post(
        _CONTENTS_URL,
        json={
            "urls": [str(request.url)],
            "formats": ["markdown", "metadata"],
            "max_age": 0,
        },
    )


def _parse_published_at(value: Any) -> datetime | None:
    """Parse You.com's ISO-8601 date fields (``publish_date``, ``page_age``)."""
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


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
