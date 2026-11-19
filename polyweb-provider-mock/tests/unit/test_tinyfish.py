"""Tinyfish plugin wire behavior through the in-process app."""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

import httpx
import pytest

from polyweb_provider_mock.faults import FaultKind, FaultParams, FaultSpec
from polyweb_provider_mock.store import MockStore
from polyweb_provider_mock.windows import WindowSpec

_SEARCH_HOST = {"Host": "api.search.tinyfish.ai"}
_FETCH_HOST = {"Host": "api.fetch.tinyfish.ai"}
_QUERY = {"query": "polyweb test", "page": "0"}
_FETCH = {"urls": ["https://docs.python.org/3/library/json.html"], "format": "markdown"}


@pytest.fixture
def key(store: MockStore) -> str:
    return next(item.key for item in store.keys("tinyfish") if item.label == "default")


@pytest.fixture
def search_headers(key: str) -> dict[str, str]:
    return {**_SEARCH_HOST, "X-API-Key": key}


@pytest.fixture
def fetch_headers(key: str) -> dict[str, str]:
    return {**_FETCH_HOST, "X-API-Key": key}


def _assert_error(response: httpx.Response, status: int, code: str) -> dict[str, Any]:
    body = response.json()
    assert response.status_code == status
    assert response.headers["content-type"] == "application/json"
    # Recorded: only the edge's 401s say no-store; the application's errors do not.
    if status == 401:
        assert response.headers["cache-control"] == "no-store"
    else:
        assert "cache-control" not in response.headers
        assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["x-cache"] == "Error from cloudfront"
    assert body["error"]["code"] == code
    assert body["request_id"] == response.headers["x-request-id"]
    UUID(body["request_id"])
    return dict(body["error"])


async def test_search_shape_headers_and_ledger(
    client: httpx.AsyncClient, store: MockStore, search_headers: dict[str, str]
) -> None:
    response = await client.get("/", params=_QUERY, headers=search_headers)

    body = response.json()
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json"
    assert response.headers["x-ratelimit-limit"] == "30"
    assert response.headers["x-ratelimit-remaining"] == "29"
    assert int(response.headers["x-ratelimit-reset"]) > 0
    assert response.headers["x-cache"] == "Miss from cloudfront"
    assert list(body) == ["query", "results", "total_results", "page"]
    assert (body["query"], body["page"], body["total_results"]) == ("polyweb test", 0, 10)
    first = body["results"][0]
    assert {"position", "site_name", "title", "snippet", "url"} <= set(first)
    assert [item["position"] for item in body["results"]] == list(range(1, 11))
    assert store.ledger("tinyfish")[-1].operation == "search"


async def test_search_pages_news_and_research(
    client: httpx.AsyncClient, search_headers: dict[str, str]
) -> None:
    second = (await client.get("/", params={**_QUERY, "page": "1"}, headers=search_headers)).json()
    news = (
        await client.get("/", params={**_QUERY, "domain_type": "news"}, headers=search_headers)
    ).json()
    papers = (
        await client.get(
            "/",
            params={**_QUERY, "domain_type": "research_paper", "pub_year_min": "2020"},
            headers=search_headers,
        )
    ).json()
    filtered = (
        await client.get(
            "/", params={**_QUERY, "include_domains": "github.com"}, headers=search_headers
        )
    ).json()

    assert second["page"] == 1 and second["results"][0]["position"] == 11
    assert all({"date", "publisher"} <= set(item) for item in news["results"])
    assert all(
        {"authors", "venue", "year", "cited_by_count"} <= set(item) for item in papers["results"]
    )
    assert all(item["site_name"] == "github.com" for item in filtered["results"])


@pytest.mark.parametrize(
    ("params", "path"),
    [
        ({"page": "0"}, ["query"]),
        ({"query": " "}, ["query"]),
        ({**_QUERY, "page": "11"}, ["page"]),
        ({**_QUERY, "page": "x"}, ["page"]),
        ({**_QUERY, "domain_type": "images"}, ["domain_type"]),
        ({**_QUERY, "after_date": "2026/01/01"}, ["after_date"]),
        ({**_QUERY, "recency_minutes": "60", "after_date": "2026-01-01"}, ["recency_minutes"]),
        ({**_QUERY, "after_date": "2026-02-01", "before_date": "2026-01-01"}, ["before_date"]),
        ({**_QUERY, "pub_year_min": "2020"}, ["domain_type"]),
        ({**_QUERY, "domain_type": "research_paper", "recency_minutes": "5"}, ["domain_type"]),
    ],
)
async def test_search_validation_spends_a_slot_not_a_credit(
    client: httpx.AsyncClient,
    store: MockStore,
    search_headers: dict[str, str],
    params: dict[str, str],
    path: list[str],
) -> None:
    response = await client.get("/", params=params, headers=search_headers)

    error = _assert_error(response, 400, "INVALID_INPUT")
    assert error["details"][0]["path"] == path
    assert error["message"].startswith(f'Field "{path[0]}"')
    assert response.headers["x-ratelimit-remaining"] == "29"
    assert response.headers["x-tf-user-id"].startswith("user_")
    assert store.ledger("tinyfish") == []


async def test_fetch_shape_and_options(
    client: httpx.AsyncClient, store: MockStore, fetch_headers: dict[str, str]
) -> None:
    request = {
        **_FETCH,
        "links": True,
        "image_links": True,
        "iframe_links": True,
        "include_etag_and_last_modified": True,
    }
    response = await client.post("/", json=request, headers=fetch_headers)

    body = response.json()
    assert response.status_code == 200
    assert response.headers["x-ratelimit-limit"] == "150"
    assert body["errors"] == []
    item = body["results"][0]
    assert item["url"] == _FETCH["urls"][0]
    assert item["format"] == "markdown" and item["text"].startswith("# ")
    assert {"links", "image_links", "iframe_links", "etag", "last_modified"} <= set(item)
    assert store.ledger("tinyfish")[-1].units == 1


@pytest.mark.parametrize(("fmt", "kind"), [("html", str), ("json", dict)])
async def test_fetch_formats(
    client: httpx.AsyncClient, fetch_headers: dict[str, str], fmt: str, kind: type
) -> None:
    body = (await client.post("/", json={**_FETCH, "format": fmt}, headers=fetch_headers)).json()
    assert isinstance(body["results"][0]["text"], kind)
    assert body["results"][0]["format"] == fmt


async def test_fetch_highlights_and_selectors(
    client: httpx.AsyncClient, fetch_headers: dict[str, str]
) -> None:
    highlights = (
        await client.post(
            "/",
            json={**_FETCH, "highlights": {"query": "json", "max_snippets": 2}},
            headers=fetch_headers,
        )
    ).json()["results"][0]
    partial = (
        await client.post(
            "/", json={**_FETCH, "include_selectors": ["main", ".sidebar"]}, headers=fetch_headers
        )
    ).json()["results"][0]
    miss = (
        await client.post(
            "/", json={**_FETCH, "include_selectors": [".nav"]}, headers=fetch_headers
        )
    ).json()

    assert highlights["text"] is None
    assert [item["rank"] for item in highlights["highlights"]] == [1, 2]
    assert partial["unmatched_selectors"] == [".sidebar"]
    assert miss["results"] == [] and miss["errors"][0]["error"] == "selector_not_matched"


@pytest.mark.parametrize(
    ("url", "entry"),
    [
        ("https://blocked.example.org/a", {"error": "bot_blocked"}),
        ("https://timeout.example.org/a", {"error": "timeout"}),
        ("https://missing.example.org/a", {"error": "page_not_found", "status": 404}),
        ("https://status-503.example.org/a", {"error": "target_http_error", "status": 503}),
        ("https://unreachable.example.org/a", {"error": "target_unreachable"}),
        ("https://site.invalid/a", {"error": "invalid_url"}),
        ("http://10.0.0.1/", {"error": "invalid_url"}),
    ],
)
async def test_fetch_target_failures_are_200_errors(
    client: httpx.AsyncClient,
    store: MockStore,
    fetch_headers: dict[str, str],
    url: str,
    entry: dict[str, object],
) -> None:
    response = await client.post("/", json={"urls": [url]}, headers=fetch_headers)

    assert response.status_code == 200
    assert response.json() == {
        "results": [],
        "errors": [{"url": url, **entry}],
        "request_id": response.headers["x-request-id"],
    }
    assert store.ledger("tinyfish") == []


@pytest.mark.parametrize(
    ("body", "status"),
    [
        ({"format": "markdown"}, 400),
        ({"urls": []}, 400),
        ({"urls": [f"https://e{i}.example.org/" for i in range(11)]}, 400),
        ({"urls": ["not a url"]}, 400),
        ({**_FETCH, "format": "pdf"}, 400),
        ({**_FETCH, "per_url_timeout_ms": 0}, 400),
        ({**_FETCH, "links": "yes"}, 400),
        ({**_FETCH, "highlights": {"query": "x"}, "format": "html"}, 400),
        (
            {"urls": ["https://a.example.org/", "https://b.example.org/"], "if_none_match": '"x"'},
            400,
        ),
        ({**_FETCH, "include_selectors": ["div[class"]}, 422),
    ],
)
async def test_fetch_validation(
    client: httpx.AsyncClient, fetch_headers: dict[str, str], body: dict[str, object], status: int
) -> None:
    response = await client.post("/", json=body, headers=fetch_headers)
    _assert_error(response, status, "INVALID_INPUT")


async def test_highlights_without_beta_are_403(
    client: httpx.AsyncClient, store: MockStore, fetch_headers: dict[str, str]
) -> None:
    with store.db.transaction() as conn:
        conn.execute("UPDATE accounts SET attributes = '{}' WHERE provider = 'tinyfish'")
    response = await client.post(
        "/", json={**_FETCH, "highlights": {"query": "x"}}, headers=fetch_headers
    )
    _assert_error(response, 403, "FORBIDDEN")


@pytest.mark.parametrize(
    ("headers", "code", "message"),
    [
        ({}, "MISSING_API_KEY", "X-API-Key header is required"),
        ({"X-API-Key": "wrong"}, "INVALID_API_KEY", "Invalid or expired API key"),
        ({"Authorization": "Bearer wrong"}, "MISSING_API_KEY", "X-API-Key header is required"),
    ],
)
async def test_auth_errors_match_recordings(
    client: httpx.AsyncClient, headers: dict[str, str], code: str, message: str
) -> None:
    response = await client.get("/", params=_QUERY, headers={**_SEARCH_HOST, **headers})

    assert _assert_error(response, 401, code) == {"code": code, "message": message}
    assert response.headers["www-authenticate"] == "ApiKey"
    assert response.headers["x-cache"] == "Error from cloudfront"


async def test_revoked_key_is_invalid_api_key(
    client: httpx.AsyncClient, store: MockStore, fetch_headers: dict[str, str]
) -> None:
    store.set_key_status("tinyfish", "default", "revoked")
    response = await client.post("/", json=_FETCH, headers=fetch_headers)
    _assert_error(response, 401, "INVALID_API_KEY")


async def test_routing_is_by_host(
    client: httpx.AsyncClient, key: str, search_headers: dict[str, str]
) -> None:
    wrong = await client.get("/", params=_QUERY, headers={**_FETCH_HOST, "X-API-Key": key})
    post_on_search = await client.post("/", json=_FETCH, headers=search_headers)
    unknown = await client.get("/v1/other", headers=search_headers)

    for refused in (wrong, post_on_search):
        assert (refused.status_code, refused.content) == (405, b"")
        assert "content-type" not in refused.headers
    assert unknown.status_code == 404
    assert unknown.headers["content-type"] == "text/html; charset=utf-8"


async def test_minute_limit_is_per_account(
    client: httpx.AsyncClient, store: MockStore, search_headers: dict[str, str]
) -> None:
    store.now = lambda: datetime(2026, 11, 17, 12, 0, 30, tzinfo=UTC)
    account = store.account("tinyfish").id
    store.count_window(WindowSpec(f"tinyfish:{account}:search:minute", 30, 60, aligned=True), 30)

    response = await client.get("/", params=_QUERY, headers=search_headers)

    error = _assert_error(response, 429, "RATE_LIMIT_EXCEEDED")
    assert error["details"] == {
        "limit": 30,
        "unit": "requests",
        "window_seconds": 60,
        "upgrade_url": "https://agent.tinyfish.ai/wallet?utm_source=api&utm_medium=rate_limit_error&utm_campaign=search",
    }
    assert response.headers["retry-after"] == "30"
    assert response.headers["x-ratelimit-remaining"] == "0"
    assert response.headers["x-ratelimit-reset"] == str(
        int(datetime(2026, 11, 17, 12, 1, tzinfo=UTC).timestamp())
    )


async def test_fetch_minute_limit_counts_urls(
    client: httpx.AsyncClient, store: MockStore, fetch_headers: dict[str, str]
) -> None:
    store.now = lambda: datetime(2026, 11, 17, 12, 0, 0, tzinfo=UTC)
    account = store.account("tinyfish").id
    store.count_window(WindowSpec(f"tinyfish:{account}:fetch:minute", 150, 60, aligned=True), 149)
    two = {"urls": ["https://a.example.org/x", "https://b.example.org/y"]}

    response = await client.post("/", json=two, headers=fetch_headers)

    assert _assert_error(response, 429, "RATE_LIMIT_EXCEEDED")["details"]["unit"] == "urls"
    assert (await client.post("/", json=_FETCH, headers=fetch_headers)).status_code == 200


def _use_allowance(store: MockStore, product: str, limit: int) -> None:
    account = store.account("tinyfish").id
    spec = WindowSpec(f"tinyfish:{account}:{product}:day", limit, 86400, aligned=True)
    store.count_window(spec, limit)


async def test_used_allowance_without_wallet_spending_is_429(
    client: httpx.AsyncClient, store: MockStore, fetch_headers: dict[str, str]
) -> None:
    store.now = lambda: datetime(2026, 11, 17, 23, 0, 0, tzinfo=UTC)
    # Documented: adding funds alone does not enable wallet spending.
    store.set_account_attributes("tinyfish", {"wallet_balance": "25.00"})
    _use_allowance(store, "fetch", 1000)

    response = await client.post("/", json=_FETCH, headers=fetch_headers)

    error = _assert_error(response, 429, "RATE_LIMIT_EXCEEDED")
    details = error["details"]
    assert details["reason"] == "free_allowance_exhausted"
    assert (details["limit"], details["unit"], details["window_seconds"]) == (1000, "urls", 86400)
    assert details["reset_at"] == "2026-11-18T00:00:00Z"
    assert response.headers["retry-after"] == "3600"
    assert response.headers["x-ratelimit-remaining"] == "0"
    assert response.headers["x-tf-user-id"].startswith("user_")
    assert store.ledger("tinyfish") == []


async def test_used_allowance_with_spending_and_empty_wallet_is_402(
    client: httpx.AsyncClient, store: MockStore, search_headers: dict[str, str]
) -> None:
    store.set_account_attributes("tinyfish", {"wallet_spending": True})
    _use_allowance(store, "search", 12_000)

    response = await client.get("/", params=_QUERY, headers=search_headers)

    error = _assert_error(response, 402, "INSUFFICIENT_CREDITS")
    assert set(error) == {"code", "message"}
    assert "Daily free Search allowance used" in error["message"]


async def test_used_allowance_with_spending_and_funds_is_served(
    client: httpx.AsyncClient, store: MockStore, fetch_headers: dict[str, str]
) -> None:
    store.set_account_attributes("tinyfish", {"wallet_spending": "true", "wallet_balance": "5"})
    _use_allowance(store, "fetch", 1000)

    response = await client.post("/", json=_FETCH, headers=fetch_headers)

    assert response.status_code == 200
    # The overage price is undocumented: nothing draws the wallet.
    assert store.account("tinyfish").attributes["wallet_balance"] == "5"
    assert store.ledger("tinyfish")[-1].usd == Decimal(0)


async def test_failed_urls_do_not_use_the_allowance(
    client: httpx.AsyncClient, store: MockStore, fetch_headers: dict[str, str]
) -> None:
    store.set_account_attributes("tinyfish", {"fetch_daily_free": 1})
    blocked = {"urls": ["https://blocked.example.org/a"]}

    assert (await client.post("/", json=blocked, headers=fetch_headers)).status_code == 200
    assert (await client.post("/", json=_FETCH, headers=fetch_headers)).status_code == 200
    assert (await client.post("/", json=_FETCH, headers=fetch_headers)).status_code == 429


async def test_invalid_requests_and_usage_reads_share_a_minute_limit(
    client: httpx.AsyncClient,
    store: MockStore,
    search_headers: dict[str, str],
    fetch_headers: dict[str, str],
) -> None:
    store.now = lambda: datetime(2026, 11, 17, 12, 0, 20, tzinfo=UTC)
    store.set_account_attributes("tinyfish", {"invalid_per_minute": 3})

    statuses = [
        (await client.get("/", params={"query": " "}, headers=search_headers)).status_code,
        (await client.post("/", json={"urls": []}, headers=fetch_headers)).status_code,
        (await client.get("/usage", headers=search_headers)).status_code,
    ]
    over = await client.get("/usage", headers=fetch_headers)
    invalid = await client.get("/", params={"query": " "}, headers=search_headers)
    valid = await client.get("/", params=_QUERY, headers=search_headers)

    assert statuses == [400, 400, 200]
    for response in (over, invalid):
        error = _assert_error(response, 429, "RATE_LIMIT_EXCEEDED")
        assert error["details"]["reason"] == "invalid_or_usage_limit"
        assert error["details"]["limit"] == 3
        assert response.headers["retry-after"] == "40"
    # Valid Search and Fetch requests are outside the combined limit.
    assert valid.status_code == 200


async def test_invalid_limit_defaults_to_sixty(
    client: httpx.AsyncClient, store: MockStore, search_headers: dict[str, str]
) -> None:
    store.now = lambda: datetime(2026, 11, 17, 12, 0, 0, tzinfo=UTC)
    account = store.account("tinyfish").id
    spec = WindowSpec(f"tinyfish:{account}:invalid:minute", 60, 60, aligned=True)
    store.count_window(spec, 59)

    assert (await client.get("/usage", headers=search_headers)).status_code == 200
    response = await client.get("/usage", headers=search_headers)
    assert _assert_error(response, 429, "RATE_LIMIT_EXCEEDED")["details"]["limit"] == 60


async def test_zero_credits_is_402(
    client: httpx.AsyncClient, store: MockStore, search_headers: dict[str, str]
) -> None:
    store.set_credits("tinyfish", Decimal(0))
    response = await client.get("/", params=_QUERY, headers=search_headers)
    _assert_error(response, 402, "INSUFFICIENT_CREDITS")


@pytest.mark.parametrize(
    ("fault", "status", "code"),
    [
        (FaultSpec(provider="tinyfish", kind=FaultKind.OUTAGE), 503, "BACKEND_UNAVAILABLE"),
        (
            FaultSpec(
                provider="tinyfish", kind=FaultKind.OUTAGE, params=FaultParams(scope="store")
            ),
            503,
            "SERVICE_BUSY",
        ),
        (FaultSpec(provider="tinyfish", kind=FaultKind.HTTP_ERROR), 500, "INTERNAL_ERROR"),
        (
            FaultSpec(
                provider="tinyfish", kind=FaultKind.HTTP_ERROR, params=FaultParams(status=504)
            ),
            504,
            "BACKEND_UNAVAILABLE",
        ),
        (
            FaultSpec(
                provider="tinyfish",
                kind=FaultKind.QUOTA_EXHAUSTED,
                params=FaultParams(scope="free_allowance"),
            ),
            429,
            "RATE_LIMIT_EXCEEDED",
        ),
        (
            FaultSpec(
                provider="tinyfish",
                kind=FaultKind.QUOTA_EXHAUSTED,
                params=FaultParams(scope="wallet"),
            ),
            402,
            "INSUFFICIENT_CREDITS",
        ),
        # Without a scope the account decides; wallet spending is off by default.
        (
            FaultSpec(provider="tinyfish", kind=FaultKind.QUOTA_EXHAUSTED),
            429,
            "RATE_LIMIT_EXCEEDED",
        ),
        (FaultSpec(provider="tinyfish", kind=FaultKind.AUTH_INVALID), 401, "INVALID_API_KEY"),
    ],
)
async def test_faults_render_tinyfish_errors(
    client: httpx.AsyncClient,
    store: MockStore,
    search_headers: dict[str, str],
    fault: FaultSpec,
    status: int,
    code: str,
) -> None:
    store.add_fault(fault)
    response = await client.get("/", params=_QUERY, headers=search_headers)
    _assert_error(response, status, code)


async def test_rate_limit_fault_has_headers(
    client: httpx.AsyncClient, store: MockStore, fetch_headers: dict[str, str]
) -> None:
    store.add_fault(
        FaultSpec(provider="tinyfish", kind=FaultKind.RATE_LIMIT, params=FaultParams(retry_after=3))
    )
    response = await client.post("/", json=_FETCH, headers=fetch_headers)

    assert _assert_error(response, 429, "RATE_LIMIT_EXCEEDED")["details"]["unit"] == "urls"
    assert response.headers["retry-after"] == "3"


async def test_fixtures_override_search_and_fetch(
    client: httpx.AsyncClient,
    store: MockStore,
    search_headers: dict[str, str],
    fetch_headers: dict[str, str],
) -> None:
    saved = {"query": "polyweb test", "results": [], "total_results": 0, "page": 0}
    store.save_fixture("tinyfish", "search", "polyweb test", saved)
    url = _FETCH["urls"][0]
    store.save_fixture("tinyfish", "fetch", url, {"url": url, "error": "empty_content"})

    search = (await client.get("/", params=_QUERY, headers=search_headers)).json()
    fetch = (await client.post("/", json=_FETCH, headers=fetch_headers)).json()

    assert search == saved
    assert fetch.pop("request_id")
    assert fetch == {"results": [], "errors": [{"url": url, "error": "empty_content"}]}


async def test_usage_history_reflects_the_log(
    client: httpx.AsyncClient,
    search_headers: dict[str, str],
    fetch_headers: dict[str, str],
) -> None:
    await client.get("/", params=_QUERY, headers=search_headers)
    await client.post(
        "/", json={"urls": [*_FETCH["urls"], "https://blocked.example.org/"]}, headers=fetch_headers
    )

    search = (await client.get("/usage", headers=search_headers)).json()
    fetch = (await client.get("/usage", params={"status": "failed"}, headers=fetch_headers)).json()

    assert (search["total"], search["page"], search["has_more"]) == (1, 1, False)
    assert search["items"][0]["query"] == "polyweb test"
    assert search["items"][0]["result_count"] == 10
    assert fetch["total"] == 1 and fetch["items"][0]["error"] == "bot_blocked"
