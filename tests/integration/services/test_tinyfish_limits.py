"""Tinyfish integration: Polyweb MCP and fetch preserve rate plus null budget split.

Tinyfish slice only. Real adapter with real catalog records and mock-transport
HTTP. No vendor I/O, no live keys, no wallet calls.
"""

from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, cast

import httpx
from pydantic import SecretStr

from polyweb.adapters.tinyfish import TinyfishAdapter
from polyweb.models.contracts import FetchRequest, SearchRequest
from polyweb.models.provider_limits import AuthMode, UsageSyncRequest

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
        for req in calls:
            text = str(req.url).lower()
            assert "wallet" not in text
            assert "usage" not in text
            assert "agent" not in text
            assert "browser" not in text

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
    finally:
        await client.aclose()
