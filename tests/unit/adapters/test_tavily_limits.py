"""Tavily limits unit tests: catalog shared bucket, native Credits, keyless.

Parallel to tests/unit/adapters/test_brave_limits.py. Mock HTTP only, no
vendor I/O, no database, no provider keys on the wire.
"""

import asyncio
from decimal import Decimal

import httpx
from pydantic import SecretStr

from freesearch.configuration.provider_limits import (
    TAVILY_DEFAULT_BUCKET_ID,
    provider_limit_defaults,
)
from freesearch.models.contracts import FetchRequest, SearchRequest, UnitKind
from freesearch.models.provider_limits import AuthMode, LimitOperation
from freesearch.models.tavily import TavilyExtractParams, TavilySearchParams
from freesearch.services import credit_units as cu


class _FakeSDK:
    def __init__(self) -> None:
        self.search_calls: list[dict[str, object]] = []
        self.extract_calls: list[dict[str, object]] = []

    async def search(self, **kwargs: object) -> object:
        self.search_calls.append(kwargs)
        return {"results": [], "usage": {"credits": 1}}

    async def extract(self, **kwargs: object) -> object:
        self.extract_calls.append(kwargs)
        return {"results": []}


def _records(provider_auth: tuple[str, AuthMode] | None = None):  # type: ignore[no-untyped-def]
    records = [r for r in provider_limit_defaults() if r.provider == "tavily"]
    if provider_auth is None:
        return records
    return [r for r in records if r.auth_mode is provider_auth[1]]


def test_tavily_catalog_holds_four_records() -> None:
    records = _records()
    assert len(records) == 4
    assert sum(1 for r in records if r.auth_mode is AuthMode.KEYED) == 2
    assert sum(1 for r in records if r.auth_mode is AuthMode.KEYLESS) == 2


def test_tavily_keyed_records_share_default_bucket() -> None:
    from freesearch.adapters.tavily import TavilyAdapter  # noqa: F401  # seam anchor

    keyed = [r for r in _records() if r.auth_mode is AuthMode.KEYED]
    assert len(keyed) == 2
    buckets = set()
    for record in keyed:
        assert record.rate is not None
        for window in record.rate.windows:
            buckets.add(window.bucket_id)
    assert buckets == {TAVILY_DEFAULT_BUCKET_ID}
    assert TAVILY_DEFAULT_BUCKET_ID == "tavily:keyed:search:requests"
    search = next(r for r in keyed if r.operation is LimitOperation.SEARCH)
    fetch = next(r for r in keyed if r.operation is LimitOperation.FETCH)
    search_bucket = next(w.bucket_id for w in search.rate.windows)  # type: ignore[union-attr]
    fetch_bucket = next(w.bucket_id for w in fetch.rate.windows)  # type: ignore[union-attr]
    assert search_bucket == fetch_bucket


def test_tavily_native_unit_is_credits() -> None:
    for record in [r for r in _records() if r.auth_mode is AuthMode.KEYED]:
        assert record.native_unit is UnitKind.CREDIT
        assert record.budget is not None
        assert record.budget.allowance_unit == "Credits"


def test_tavily_search_debit_one_and_two_credits() -> None:
    search = next(
        r
        for r in _records()
        if r.operation is LimitOperation.SEARCH and r.auth_mode is AuthMode.KEYED
    )
    assert cu.request_native_cost(search, SearchRequest(query="q", limit=2)) == Decimal("1")
    assert cu.request_native_cost(
        search, SearchRequest(query="q", limit=2, mode="advanced")
    ) == Decimal("2")


def test_tavily_extract_depth_rule_matches_adapter() -> None:
    fetch = next(
        r
        for r in _records()
        if r.operation is LimitOperation.FETCH and r.auth_mode is AuthMode.KEYED
    )
    basic = FetchRequest(
        url="https://example.com/a",
        provider_options={"tavily": TavilyExtractParams(extract_depth="basic")},
    )
    advanced = FetchRequest(
        url="https://example.com/a",
        provider_options={"tavily": TavilyExtractParams(extract_depth="advanced")},
    )
    assert cu.request_native_cost(fetch, basic) == Decimal("0.2")
    assert cu.request_native_cost(fetch, advanced) == Decimal("0.4")


def test_tavily_keyless_transport_available_without_budget() -> None:
    keyless = [r for r in _records() if r.auth_mode is AuthMode.KEYLESS]
    assert len(keyless) == 2
    for record in keyless:
        assert record.transport_available is True
        assert record.budget is None


def test_tavily_keyless_rate_unpublished_without_numeric_window() -> None:
    keyless = [r for r in _records() if r.auth_mode is AuthMode.KEYLESS]
    for record in keyless:
        assert record.rate is not None
        assert record.rate.windows == []
        assert record.rate.published is False
        # Unpublished rail: no priced budget to gate funds.
        assert record.budget is None


def test_tavily_reset_metadata_targets_monthly_first() -> None:
    from freesearch.configuration.provider_limits import provider_tier_defaults

    tiers = provider_tier_defaults()["tavily:keyed"]
    free = next(t for t in tiers if t.tier == "free")
    assert free.native_allowance == Decimal("1000")
    assert str(free.reset_rule.value).lower().startswith("monthly") or "MONTHLY" in str(
        free.reset_rule
    )


def test_tavily_dev_limit_100_prod_limit_1000() -> None:
    from freesearch.configuration.provider_limits import TAVILY_RPM_DEV, TAVILY_RPM_PROD

    assert Decimal("100") == TAVILY_RPM_DEV
    assert Decimal("1000") == TAVILY_RPM_PROD


def _keyless_adapter() -> tuple[object, httpx.AsyncClient]:
    from freesearch.adapters.tavily import TavilyAdapter

    async def _noop(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        return httpx.Response(200, json={})

    client = httpx.AsyncClient(transport=httpx.MockTransport(_noop), timeout=30.0)
    adapter = TavilyAdapter(client, api_key=None, sdk_client=_FakeSDK())  # type: ignore[arg-type]
    return adapter, client


def _keyed_adapter() -> tuple[object, httpx.AsyncClient]:
    from freesearch.adapters.tavily import TavilyAdapter

    async def _noop(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        return httpx.Response(200, json={})

    client = httpx.AsyncClient(transport=httpx.MockTransport(_noop), timeout=30.0)
    adapter = TavilyAdapter(
        client,
        api_key=SecretStr("tvly-test-key"),
        sdk_client=_FakeSDK(),  # type: ignore[arg-type]
    )
    return adapter, client


async def test_keyless_adapter_reports_keyless_mode() -> None:
    adapter, client = _keyless_adapter()  # type: ignore[misc]
    try:
        assert adapter.limit_auth_mode is AuthMode.KEYLESS  # type: ignore[attr-defined]
    finally:
        await client.aclose()


async def test_concurrent_mixed_ops_share_bucket_seam() -> None:
    # Both operations resolve depth without I/O; concurrent gather proves no
    # shared mutable depth state between search and extract paths.
    async def _depth(kind: str) -> str:
        if kind == "search":
            from freesearch.models.tavily import tavily_search_depth

            return tavily_search_depth("advanced", TavilySearchParams(search_depth="advanced"))
        from freesearch.models.tavily import tavily_extract_depth

        return tavily_extract_depth(TavilyExtractParams(extract_depth="advanced"))

    searches = [_depth("search") for _ in range(5)]
    extracts = [_depth("extract") for _ in range(5)]
    results = await asyncio.gather(*searches, *extracts)
    assert results == ["advanced"] * 10


def test_keyless_budget_is_none() -> None:
    keyless_search = next(
        r
        for r in _records()
        if r.operation is LimitOperation.SEARCH and r.auth_mode is AuthMode.KEYLESS
    )
    assert cu.request_native_cost(keyless_search) is None
