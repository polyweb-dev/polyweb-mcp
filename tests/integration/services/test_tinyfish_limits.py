"""Tinyfish integration: Polyweb MCP and fetch preserve rate plus null budget split.

Tinyfish slice only. Real adapter with real catalog records and mock-transport
HTTP. No vendor I/O, no live keys, no wallet calls.
"""

import json
from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, cast

import httpx
from pydantic import SecretStr

from polyweb.adapters.tinyfish import TinyfishAdapter
from polyweb.configuration.provider_limits import provider_limit_defaults, provider_tier_defaults
from polyweb.models.contracts import FetchRequest, SearchRequest
from polyweb.models.provider_limits import (
    AuthMode,
    FundingMode,
    LimitOperation,
    RateScope,
    RateUnit,
    RateWindowName,
    UsageSyncRequest,
)

FIXED_AT = datetime(2026, 3, 10, 12, 0, 0, tzinfo=UTC)


def _search_payload() -> dict[str, object]:
    return {
        "query": "free proof",
        "results": [
            {
                "position": 1,
                "site_name": "Example Site",
                "title": "Example Result",
                "snippet": "A test snippet from Tinyfish.",
                "url": "https://example.com/item",
                "date": "2026-06-01T12:00:00Z",
            }
        ],
        "total_results": 1,
        "page": 0,
    }


def _fetch_payload() -> dict[str, object]:
    return {
        "results": [
            {
                "url": "https://example.com/page",
                "final_url": "https://example.com/page/final",
                "title": "Sample Doc",
                "description": "Doc description",
                "language": "en",
                "text": "# Sample Content\n\nExtracted markdown content.",
                "published_date": "2026-06-01",
            }
        ],
        "errors": [],
    }


def _handler(calls: list[httpx.Request]) -> Callable[[httpx.Request], httpx.Response]:
    def handle(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        host = request.url.host
        if host == "api.search.tinyfish.ai":
            return httpx.Response(200, json=_search_payload())
        if host == "api.fetch.tinyfish.ai":
            return httpx.Response(200, json=_fetch_payload())
        return httpx.Response(404, json={"error": "unexpected-egress"})

    return handle


async def test_tinyfish_free_operations_preserve_rate_budget_split() -> None:
    calls: list[httpx.Request] = []
    client = httpx.AsyncClient(transport=httpx.MockTransport(_handler(calls)), timeout=30.0)
    try:
        adapter = TinyfishAdapter(client, api_key=SecretStr("tinyfish-test-secret"))

        search = await adapter.search(
            SearchRequest(
                project_id="00000000-0000-4000-8000-0000000000aa", query="free proof", limit=2
            )
        )
        assert search.provider == "tinyfish"
        assert len(search.results) == 1
        assert str(search.results[0].url) == "https://example.com/item"
        assert search.usage is not None
        assert search.usage.units == Decimal("1")
        assert search.usage.metadata["cost_usd"] == Decimal("0")

        fetch = await adapter.fetch(
            FetchRequest(
                project_id="00000000-0000-4000-8000-0000000000aa",
                url=cast(Any, "https://example.com/page"),
            ),
        )
        assert fetch.provider == "tinyfish"
        assert str(fetch.document.url) == "https://example.com/page"
        assert fetch.document.content == "# Sample Content\n\nExtracted markdown content."
        assert fetch.usage is not None
        assert fetch.usage.units == Decimal("1")
        assert fetch.usage.metadata["cost_usd"] == Decimal("0")

        assert len(calls) == 2
        hosts = sorted(r.url.host for r in calls)
        assert hosts == ["api.fetch.tinyfish.ai", "api.search.tinyfish.ai"]
        fetch_req = next(r for r in calls if r.url.host == "api.fetch.tinyfish.ai")
        fetch_payload = json.loads(fetch_req.content)
        assert fetch_payload["urls"] == ["https://example.com/page"]
        assert len(fetch_payload["urls"]) == 1
        assert len(fetch_payload["urls"]) <= 10
        for req in calls:
            text = str(req.url).lower()
            assert "wallet" not in text
            assert "usage" not in text
            assert "agent" not in text
            assert "browser" not in text

        records = [r for r in provider_limit_defaults() if r.provider == "tinyfish"]
        assert len(records) == 2
        search_record = next(r for r in records if r.operation is LimitOperation.SEARCH)
        fetch_record = next(r for r in records if r.operation is LimitOperation.FETCH)
        assert search_record.auth_mode is AuthMode.KEYED
        assert fetch_record.auth_mode is AuthMode.KEYED
        assert search_record.rate is not None
        assert fetch_record.rate is not None
        search_windows = {w.window: w for w in search_record.rate.windows}
        fetch_windows = {w.window: w for w in fetch_record.rate.windows}
        assert set(search_windows) == {RateWindowName.MINUTE, RateWindowName.HOUR}
        assert set(fetch_windows) == {RateWindowName.MINUTE, RateWindowName.DAY}
        assert search_windows[RateWindowName.MINUTE].limit == Decimal("30")
        assert search_windows[RateWindowName.MINUTE].scope is RateScope.KEY
        assert search_windows[RateWindowName.MINUTE].unit is RateUnit.REQUESTS
        assert search_windows[RateWindowName.HOUR].limit == Decimal("500")
        assert search_windows[RateWindowName.HOUR].scope is RateScope.KEY
        assert fetch_windows[RateWindowName.MINUTE].limit == Decimal("150")
        assert fetch_windows[RateWindowName.MINUTE].scope is RateScope.KEY
        assert fetch_windows[RateWindowName.MINUTE].unit is RateUnit.URLS
        assert fetch_windows[RateWindowName.DAY].limit == Decimal("1000")
        assert fetch_windows[RateWindowName.DAY].scope is RateScope.KEY
        assert search_windows[RateWindowName.MINUTE].bucket_id == (
            search_windows[RateWindowName.HOUR].bucket_id
        )
        assert fetch_windows[RateWindowName.MINUTE].bucket_id == (
            fetch_windows[RateWindowName.DAY].bucket_id
        )
        assert search_windows[RateWindowName.MINUTE].bucket_id != (
            fetch_windows[RateWindowName.MINUTE].bucket_id
        )
        assert search_record.budget is None
        assert fetch_record.budget is None
        tiers = provider_tier_defaults().get("tinyfish:keyed", [])
        assert len(tiers) == 1
        assert tiers[0].funding_mode is FundingMode.NO_BUDGET

        before = len(calls)
        snapshot = await adapter.usage_snapshot(
            UsageSyncRequest(
                provider="tinyfish",
                auth_mode=AuthMode.KEYED,
                observed_at=FIXED_AT,
            )
        )
        assert snapshot is None
        assert len(calls) == before

        search_est = await adapter.estimate_cost(
            SearchRequest(project_id="00000000-0000-4000-8000-0000000000aa", query="free proof")
        )
        fetch_est = await adapter.estimate_cost(
            FetchRequest(
                project_id="00000000-0000-4000-8000-0000000000aa",
                url=cast(Any, "https://example.com/page"),
            ),
        )
        assert search_est.units == Decimal("0")
        assert search_est.currency == "USD"
        assert fetch_est.units == Decimal("0")
        assert fetch_est.currency == "USD"
    finally:
        await client.aclose()
