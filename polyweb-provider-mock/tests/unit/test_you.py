"""You.com plugin wire behavior through the in-process app."""

from datetime import timedelta
from decimal import Decimal

import httpx
import pytest

from polyweb_provider_mock.faults import FaultKind, FaultParams, FaultSpec
from polyweb_provider_mock.store import MockStore

GATEWAY = {"Host": "ydc-index.io"}
API = {"Host": "api.you.com"}
_SEARCH = {"query": "polyweb test", "count": 3}
_CONTENTS = {"urls": ["https://example.com"], "formats": ["markdown", "metadata"], "max_age": 0}


@pytest.fixture
def you_key(store: MockStore) -> str:
    return next(key.key for key in store.keys("you") if key.label == "default")


@pytest.fixture
def gateway(you_key: str) -> dict[str, str]:
    return {**GATEWAY, "X-API-Key": you_key}


@pytest.fixture
def api(you_key: str) -> dict[str, str]:
    return {**API, "X-API-Key": you_key}


async def _balance(client: httpx.AsyncClient, api: dict[str, str]) -> float:
    response = await client.get("/v1/billing/account_balance", headers=api)
    assert response.status_code == 200
    return float(response.json()["data"]["attributes"]["balance"])


async def test_search_shape_debit_and_balance(
    client: httpx.AsyncClient, store: MockStore, gateway: dict[str, str], api: dict[str, str]
) -> None:
    assert await _balance(client, api) == 10_000.0

    response = await client.post("/v1/search", json=_SEARCH, headers=gateway)

    body = response.json()
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json"
    assert response.headers["x-amzn-remapped-server"] == "uvicorn"
    assert "x-ratelimit-limit" not in response.headers
    assert list(body) == ["results", "metadata"]
    assert list(body["metadata"]) == ["query", "search_uuid", "latency"]
    assert len(body["results"]["web"]) == 3
    first = body["results"]["web"][0]
    assert list(first)[:3] == ["url", "title", "description"]
    assert first["favicon_url"].startswith("https://you.com/favicon?domain=")
    assert all(isinstance(snippet, str) for snippet in first["snippets"])
    assert await _balance(client, api) == 9_999.5
    assert store.account("you").credits_used == Decimal("0.5")
    again = (await client.post("/v1/search", json=_SEARCH, headers=gateway)).json()
    assert again["results"] == body["results"]
    assert again["metadata"]["search_uuid"] != body["metadata"]["search_uuid"]


async def test_search_offset_pages_and_domains(
    client: httpx.AsyncClient, gateway: dict[str, str]
) -> None:
    first = (await client.post("/v1/search", json=_SEARCH, headers=gateway)).json()
    second = await client.post("/v1/search", json={**_SEARCH, "offset": 1}, headers=gateway)
    scoped = await client.post(
        "/v1/search", json={**_SEARCH, "include_domains": ["docs.python.org"]}, headers=gateway
    )

    urls = {item["url"] for item in first["results"]["web"]}
    assert not urls & {item["url"] for item in second.json()["results"]["web"]}
    assert {item["url"].split("/")[2] for item in scoped.json()["results"]["web"]} == {
        "docs.python.org"
    }


async def test_full_page_fetch_bills_live_pages_and_highlights_drop_snippets(
    client: httpx.AsyncClient, store: MockStore, gateway: dict[str, str]
) -> None:
    full_page = {
        "extraction_mode": "full_page",
        "extraction_source": "fetch",
        "full_page": {"extraction_formats": ["html"]},
    }
    page = await client.post(
        "/v1/search", json={**_SEARCH, "extraction": full_page}, headers=gateway
    )
    highlights = await client.post(
        "/v1/search",
        json={**_SEARCH, "extraction": {"extraction_mode": "highlights", "highlights": {}}},
        headers=gateway,
    )

    item = page.json()["results"]["web"][0]
    assert list(item["contents"]) == ["html"] and item["contents"]["html"].startswith("<!DOCTYPE")
    assert store.account("you").credits_used == Decimal("0.5") + Decimal("0.5") + Decimal("0.3")
    hit = highlights.json()["results"]["web"][0]
    assert "snippets" not in hit and hit["description"] == ""
    assert hit["contents"]["highlights"]


@pytest.mark.parametrize(
    "request_body",
    [
        {"count": 1},
        {"query": "x", "count": 0},
        {"query": "x", "count": 101},
        {"query": "x", "offset": 10},
        {"query": "x", "include_domains": ["a.com"], "exclude_domains": ["b.com"]},
        {"query": "x", "include_domains": ["a.com"], "boost_domains": ["b.com"]},
        {"query": "x", "safesearch": "none"},
        {"query": "x", "count": 51, "extraction": {"extraction_mode": "highlights"}},
        {"query": "x", "crawl_timeout": 5, "extraction": {"extraction_mode": "highlights"}},
        {"query": "x", "extraction": {"extraction_mode": "full_page", "extraction_source": "web"}},
        {"query": "x", "extraction": {"extraction_mode": "full_page", "highlights": {}}},
    ],
)
async def test_search_validation_is_free_422(
    client: httpx.AsyncClient,
    store: MockStore,
    gateway: dict[str, str],
    request_body: dict[str, object],
) -> None:
    response = await client.post("/v1/search", json=request_body, headers=gateway)

    assert response.status_code == 422
    assert response.json() == {"error": "invalid request parameter(s)"}
    assert store.account("you").credits_used == 0


async def test_contents_returns_requested_formats_and_echoes_the_url(
    client: httpx.AsyncClient, store: MockStore, gateway: dict[str, str]
) -> None:
    urls = ["https://example.com", "https://docs.python.org/3/", "https://blocked.example.org/x"]
    response = await client.post(
        "/v1/contents",
        json={**_CONTENTS, "urls": [*urls, "https://gone.invalid/"]},
        headers=gateway,
    )

    pages = response.json()
    assert response.status_code == 200
    assert [page["url"] for page in pages] == urls[:2]
    assert list(pages[0]) == ["url", "metadata", "markdown", "title"]
    assert pages[0]["metadata"] == {
        "site_name": "",
        "favicon_url": "https://api.ydc-index.io/favicon?domain=example.com&size=128",
    }
    assert pages[1]["metadata"]["site_name"] == "Python"
    assert store.account("you").credits_used == Decimal("0.2")


@pytest.mark.parametrize(
    ("request_body", "kind", "loc"),
    [
        ({"formats": ["markdown"]}, "missing", ["body", "urls"]),
        ({"urls": "https://example.com"}, "list_type", ["body", "urls"]),
        ({"urls": ["https://a.com"], "formats": ["pdf"]}, "enum", ["body", "formats", 0]),
        (
            {"urls": ["https://a.com"], "crawl_timeout": 61},
            "less_than_equal",
            ["body", "crawl_timeout"],
        ),
        ({"urls": ["https://a.com"], "max_age": -1}, "greater_than_equal", ["body", "max_age"]),
    ],
)
async def test_contents_validation_is_a_fastapi_422(
    client: httpx.AsyncClient,
    gateway: dict[str, str],
    request_body: dict[str, object],
    kind: str,
    loc: list[object],
) -> None:
    response = await client.post("/v1/contents", json=request_body, headers=gateway)

    assert response.status_code == 422
    detail = response.json()["detail"][0]
    assert (detail["type"], detail["loc"]) == (kind, loc)


@pytest.mark.parametrize(
    ("headers", "status", "body", "errortype"),
    [
        ({"X-API-Key": "ydc-sk-wrong"}, 403, {"message": "Forbidden"}, "ForbiddenException"),
        ({}, 402, None, "AccessDeniedException"),
    ],
)
async def test_gateway_authentication_errors(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    status: int,
    body: dict[str, str] | None,
    errortype: str,
) -> None:
    response = await client.post("/v1/search", json=_SEARCH, headers={**GATEWAY, **headers})

    assert response.status_code == status
    assert response.headers["x-amzn-errortype"] == errortype
    assert "x-amzn-remapped-server" not in response.headers
    if body is None:
        assert response.json()["error"] == "payment_required"
    else:
        assert response.json() == body


@pytest.mark.parametrize(
    ("headers", "detail"),
    [({"X-API-Key": "ydc-sk-wrong"}, "Invalid or expired API key"), ({}, "API key is required")],
)
async def test_balance_authentication_errors_are_401(
    client: httpx.AsyncClient, headers: dict[str, str], detail: str
) -> None:
    response = await client.get("/v1/billing/account_balance", headers={**API, **headers})

    assert response.status_code == 401
    assert response.json() == {"detail": detail}
    assert response.headers["cf-cache-status"] == "DYNAMIC"


async def test_revoked_key_follows_each_host(
    client: httpx.AsyncClient, store: MockStore, gateway: dict[str, str], api: dict[str, str]
) -> None:
    store.set_key_status("you", "default", "revoked")

    search = await client.post("/v1/search", json=_SEARCH, headers=gateway)
    balance = await client.get("/v1/billing/account_balance", headers=api)

    assert (search.status_code, search.json()) == (403, {"message": "Forbidden"})
    assert (balance.status_code, balance.json()) == (401, {"detail": "Invalid or expired API key"})


async def test_wrong_host_and_unknown_path(
    client: httpx.AsyncClient, gateway: dict[str, str], api: dict[str, str]
) -> None:
    on_gateway = await client.get("/v1/billing/account_balance", headers=gateway)
    on_api = await client.post("/v1/search", json=_SEARCH, headers=api)
    unknown = await client.get("/v1/nothing", headers=api)

    assert (on_gateway.status_code, on_gateway.json()) == (
        403,
        {"message": "Missing Authentication Token"},
    )
    assert on_gateway.headers["x-amzn-errortype"] == "MissingAuthenticationTokenException"
    assert on_api.status_code == 404 and unknown.status_code == 404


def _key(store: MockStore, label: str) -> str:
    return next(key.key for key in store.keys("you") if key.label == label)


async def test_seeded_accounts_are_the_verified_and_unverified_signup_grants(
    client: httpx.AsyncClient, store: MockStore
) -> None:
    verified, unverified = store.account("you"), store.account("you", "you-unverified")
    headers = {**API, "X-API-Key": _key(store, "unverified")}

    assert (verified.credit_limit, verified.reset_rule) == (Decimal(10_000), "none")
    assert (unverified.credit_limit, unverified.reset_rule) == (Decimal(1_000), "none")
    for account in (verified, unverified):
        assert account.grant_expires_at is not None
        assert account.grant_expires_at - account.period_start == timedelta(days=60)
    assert await _balance(client, headers) == 1_000.0
    exported = [item for item in store.export_keys() if item[0].startswith("POLYWEB_YOU")]
    assert exported == [("POLYWEB_YOU_API_KEY", _key(store, "default"))]


async def test_signup_credit_expires_after_60_days_leaving_prepaid(
    client: httpx.AsyncClient, store: MockStore, gateway: dict[str, str], api: dict[str, str]
) -> None:
    store.add_prepaid("you", Decimal(200))
    assert await _balance(client, api) == 10_200.0
    seeded = store.now()

    store.now = lambda: seeded + timedelta(days=59)
    assert await _balance(client, api) == 10_200.0
    store.now = lambda: seeded + timedelta(days=60, seconds=1)
    assert await _balance(client, api) == 200.0
    assert (await client.post("/v1/search", json=_SEARCH, headers=gateway)).status_code == 200

    assert await _balance(client, api) == 199.5
    assert store.account("you").prepaid_used == Decimal("0.5")


async def test_empty_wallet_is_402_insufficient_credits(
    client: httpx.AsyncClient, store: MockStore, gateway: dict[str, str], api: dict[str, str]
) -> None:
    store.set_credits("you", Decimal(0))

    search = await client.post("/v1/search", json=_SEARCH, headers=gateway)
    contents = await client.post("/v1/contents", json=_CONTENTS, headers=gateway)

    for response in (search, contents):
        assert (response.status_code, response.json()) == (402, {"detail": "Insufficient credits"})
    assert await _balance(client, api) == 0.0
    assert store.account("you").credits_used == store.account("you").credit_limit


async def test_key_spend_cap_is_429_and_retry_does_not_clear_it(
    client: httpx.AsyncClient, store: MockStore, api: dict[str, str]
) -> None:
    capped = _key(store, "capped")
    principal = store.resolve("you", capped)
    assert principal is not None and principal.key is not None
    assert principal.key.credit_limit == Decimal(100)
    store.charge(principal, "search", Decimal(199))
    headers = {**GATEWAY, "X-API-Key": capped}
    assert (await client.post("/v1/search", json=_SEARCH, headers=headers)).status_code == 200

    first = await client.post("/v1/search", json=_SEARCH, headers=headers)
    again = await client.post("/v1/search", json=_SEARCH, headers=headers)
    other = await client.post("/v1/search", json=_SEARCH, headers={**api, **GATEWAY})

    for response in (first, again):
        assert (response.status_code, response.json()["error"]) == (429, "spend_cap_exceeded")
        assert "retry-after" not in response.headers
    assert other.status_code == 200
    assert store.account("you").credits_used == Decimal(100) + Decimal("0.5")


async def test_search_and_contents_allow_10_requests_per_second_each(
    client: httpx.AsyncClient, store: MockStore, gateway: dict[str, str]
) -> None:
    frozen = store.now()
    store.now = lambda: frozen
    for _ in range(10):
        assert (await client.post("/v1/search", json=_SEARCH, headers=gateway)).status_code == 200

    limited = await client.post("/v1/search", json=_SEARCH, headers=gateway)
    contents = await client.post("/v1/contents", json=_CONTENTS, headers=gateway)
    store.now = lambda: frozen + timedelta(seconds=1)
    later = await client.post("/v1/search", json=_SEARCH, headers=gateway)

    assert (limited.status_code, limited.json()) == (429, {"message": "Too Many Requests"})
    assert limited.headers["x-amzn-errortype"] == "TooManyRequestsException"
    assert limited.headers["retry-after"] == "1"
    assert limited.headers["x-ratelimit-limit"] == "10"
    assert contents.status_code == 200 and later.status_code == 200
    assert store.account("you").credits_used == Decimal("5.5") + Decimal("0.1")


async def test_rate_limit_fault_has_retry_after_and_rate_headers(
    client: httpx.AsyncClient, store: MockStore, gateway: dict[str, str]
) -> None:
    store.add_fault(
        FaultSpec(provider="you", kind=FaultKind.RATE_LIMIT, params=FaultParams(retry_after=3))
    )
    response = await client.post("/v1/search", json=_SEARCH, headers=gateway)

    assert response.status_code == 429
    assert response.json() == {"message": "Too Many Requests"}
    assert response.headers["retry-after"] == "3"
    assert response.headers["x-ratelimit-limit"] == "10"
    assert response.headers["x-ratelimit-remaining"] == "0"
    assert int(response.headers["x-ratelimit-reset"]) > 1_700_000_000


@pytest.mark.parametrize(
    ("status", "body"),
    [
        (500, {"detail": "Internal Server Error"}),
        (502, {"message": "Internal server error"}),
        (503, {"message": "Service Unavailable"}),
        (504, {"message": "Endpoint request timed out"}),
    ],
)
async def test_server_faults_use_the_gateway_bodies(
    client: httpx.AsyncClient,
    store: MockStore,
    gateway: dict[str, str],
    status: int,
    body: dict[str, str],
) -> None:
    store.add_fault(
        FaultSpec(provider="you", kind=FaultKind.HTTP_ERROR, params=FaultParams(status=status))
    )
    response = await client.post("/v1/search", json=_SEARCH, headers=gateway)
    assert (response.status_code, response.json()) == (status, body)


async def test_fixtures_override_search_and_contents(
    client: httpx.AsyncClient, store: MockStore, gateway: dict[str, str]
) -> None:
    saved = {"results": {"web": [{"url": "https://saved.example.net/", "title": "Saved"}]}}
    store.save_fixture("you", "search", "polyweb test", {**saved, "metadata": {"query": "q"}})
    store.save_fixture("you", "contents", "https://example.com", [])

    search = (await client.post("/v1/search", json=_SEARCH, headers=gateway)).json()
    contents = (await client.post("/v1/contents", json=_CONTENTS, headers=gateway)).json()

    assert search["results"] == saved["results"]
    assert search["metadata"]["search_uuid"]
    assert contents == []


@pytest.mark.parametrize(
    ("operation", "path", "method"),
    [
        ("search", "/v1/search", "POST"),
        ("contents", "/v1/contents", "POST"),
        ("balance", "/v1/billing/account_balance", "GET"),
    ],
)
async def test_missing_field_fault_removes_what_the_adapter_needs(
    client: httpx.AsyncClient,
    store: MockStore,
    you_key: str,
    operation: str,
    path: str,
    method: str,
) -> None:
    store.add_fault(
        FaultSpec(
            provider="you",
            operation=operation,
            kind=FaultKind.MALFORMED,
            params=FaultParams(variant="missing_field"),
        )
    )
    host = API if operation == "balance" else GATEWAY
    body = {"search": _SEARCH, "contents": _CONTENTS}.get(operation)
    response = await client.request(method, path, json=body, headers={**host, "X-API-Key": you_key})

    payload = response.json()
    if operation == "search":
        assert all("url" not in item for item in payload["results"]["web"])
    elif operation == "contents":
        assert payload and all("markdown" not in page for page in payload)
    else:
        assert "attributes" not in payload["data"]
