"""Keenable plugin wire behavior through the in-process app."""

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

import httpx
import pytest

from polyweb_provider_mock.faults import FaultKind, FaultParams, FaultSpec
from polyweb_provider_mock.store import MockStore

_HOST = {"Host": "api.keenable.ai"}
_PUBLIC = {**_HOST, "X-Keenable-Title": "polyweb"}
_SEARCH = {"query": "polyweb test", "max_results": 3}
_FETCH = {"url": "https://docs.python.org/3/library/json.html"}


@pytest.fixture
def key(store: MockStore) -> str:
    return next(item.key for item in store.keys("keenable") if item.label == "default")


@pytest.fixture
def keyed(key: str) -> dict[str, str]:
    return {**_HOST, "X-API-Key": key}


def _assert_envelope(response: httpx.Response, status: int, code: str) -> dict[str, object]:
    body = response.json()
    assert response.status_code == status
    assert response.headers["content-type"] == "application/json; charset=utf-8"
    assert body["code"] == code
    assert body["request_id"] == response.headers["x-request-id"]
    assert UUID(response.headers["x-request-id"]).version == 7
    assert body["docs_url"] == "https://docs.keenable.ai/errors#" + code.replace("_", "-")
    return dict(body)


async def test_public_search_shape_and_rate_headers(
    client: httpx.AsyncClient, store: MockStore
) -> None:
    response = await client.post("/v1/search/public", json=_SEARCH, headers=_PUBLIC)

    body = response.json()
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json; charset=utf-8"
    assert response.headers["x-ratelimit-limit"] == "1000"
    assert response.headers["x-ratelimit-remaining"] == "999"
    assert response.headers["x-ratelimit-reset"].endswith("Z")
    assert response.headers["etag"].startswith('W/"')
    assert UUID(response.headers["x-request-id"]).version == 7
    assert list(body) == ["query", "mode", "results"]
    assert (body["query"], body["mode"], len(body["results"])) == ("polyweb test", "pro", 3)
    assert list(body["results"][0]) == ["title", "url", "description", "snippet", "acquired_at"]
    assert body["results"][0]["description"] == ""
    assert store.account("keenable").credits_used == 0
    assert store.log_tail("keenable")[-1].key_label == "keyless"


async def test_public_pools_are_per_endpoint(client: httpx.AsyncClient) -> None:
    await client.post("/v1/search/public", json=_SEARCH, headers=_PUBLIC)
    search = await client.post("/v1/search/public", json=_SEARCH, headers=_PUBLIC)
    fetch = await client.get("/v1/fetch/public", params=_FETCH, headers=_PUBLIC)

    assert search.headers["x-ratelimit-remaining"] == "998"
    assert fetch.headers["x-ratelimit-remaining"] == "999"


async def test_missing_title_spends_no_rate_slot(client: httpx.AsyncClient) -> None:
    missing = await client.post("/v1/search/public", json=_SEARCH, headers=_HOST)
    invalid = await client.post(
        "/v1/search/public", json={"query": "x", "max_results": 0}, headers=_PUBLIC
    )

    body = _assert_envelope(missing, 400, "missing_app_title")
    assert body["param"] == "X-Keenable-Title" and body["retryable"] is False
    assert "x-ratelimit-limit" not in missing.headers
    assert _assert_envelope(invalid, 400, "invalid_parameter")["param"] == "max_results"
    assert invalid.headers["x-ratelimit-remaining"] == "999"


async def test_title_query_parameter_is_accepted(client: httpx.AsyncClient) -> None:
    response = await client.get(
        "/v1/fetch/public", params={**_FETCH, "keenable_title": "polyweb"}, headers=_HOST
    )
    assert response.status_code == 200


async def test_keyed_search_reports_usage_and_debits(
    client: httpx.AsyncClient, store: MockStore, keyed: dict[str, str]
) -> None:
    response = await client.post("/v1/search", json={**_SEARCH, "mode": "realtime"}, headers=keyed)

    body = response.json()
    assert response.status_code == 200
    assert body["mode"] == "realtime"
    assert body["usage"] == {
        "sku": "search.realtime",
        "amount": 1,
        "credits": 1,
        "paid": False,
        "credits_remaining": 99_999,
    }
    assert response.headers["x-ratelimit-limit"] == "10"
    assert store.account("keenable").credits_used == 1


async def test_keyed_fetch_live_sku_and_paid_after_free_allowance(
    client: httpx.AsyncClient, store: MockStore, keyed: dict[str, str]
) -> None:
    store.set_credits("keenable", Decimal(5), used=Decimal(100_000))

    body = (await client.get("/v1/fetch", params={**_FETCH, "live": "true"}, headers=keyed)).json()

    assert body["usage"]["sku"] == "fetch.live"
    assert body["usage"]["paid"] is True
    assert body["usage"]["credits_remaining"] == 4


async def test_fetch_caps_content_and_echoes_final_url(
    client: httpx.AsyncClient, keyed: dict[str, str]
) -> None:
    body = (
        await client.get(
            "/v1/fetch", params={"url": "https://example.com", "max_chars": "20"}, headers=keyed
        )
    ).json()

    assert body["url"] == "https://example.com/"
    assert body["title"] == "Example Domain"
    assert len(body["content"]) == 20 and body["content"].endswith("...")
    assert body["truncated"] is True and body["total_chars"] > 20
    assert list(body) == [
        "url",
        "title",
        "content",
        "description",
        "truncated",
        "total_chars",
        "usage",
    ]


@pytest.mark.parametrize(
    ("params", "status", "code"),
    [
        ({}, 400, "missing_parameter"),
        ({"url": "ftp://example.com"}, 400, "invalid_parameter"),
        ({**_FETCH, "max_chars": "0"}, 400, "invalid_parameter"),
        ({**_FETCH, "live": "yes"}, 400, "invalid_parameter"),
        ({**_FETCH, "format": "html"}, 400, "unknown_parameter"),
        ({"url": "https://blocked.example.org/a"}, 403, "target_blocked"),
        ({"url": "https://missing.example.org/a"}, 404, "page_not_found"),
        ({"url": "https://paywall.example.org/a"}, 422, "target_paywalled"),
        ({"url": "http://127.0.0.1/admin"}, 403, "private_url_not_allowed"),
        ({"url": "https://site.invalid/a"}, 502, "target_unreachable"),
    ],
)
async def test_fetch_errors_are_free(
    client: httpx.AsyncClient,
    store: MockStore,
    keyed: dict[str, str],
    params: dict[str, str],
    status: int,
    code: str,
) -> None:
    response = await client.get("/v1/fetch", params=params, headers=keyed)

    _assert_envelope(response, status, code)
    assert store.account("keenable").credits_used == 0


@pytest.mark.parametrize(
    ("body", "code", "param"),
    [
        ({"max_results": 2}, "missing_parameter", "query"),
        ({"query": 5}, "invalid_parameter", "query"),
        ({"query": "x", "mode": "deep"}, "invalid_parameter", "mode"),
        ({"query": "x", "max_results": 51}, "invalid_parameter", "max_results"),
        ({"query": "x", "snippet_max_length": 10}, "invalid_parameter", "snippet_max_length"),
        ({"query": "x", "published_after": "last week"}, "invalid_parameter", "published_after"),
        ({"query": "x", "count": 3}, "unknown_parameter", "count"),
    ],
)
async def test_search_validation(
    client: httpx.AsyncClient, keyed: dict[str, str], body: dict[str, object], code: str, param: str
) -> None:
    response = await client.post("/v1/search", json=body, headers=keyed)
    assert _assert_envelope(response, 400, code)["param"] == param


async def test_search_options_shape_results(
    client: httpx.AsyncClient, keyed: dict[str, str]
) -> None:
    body = (
        await client.post(
            "/v1/search",
            json={
                "query": "json",
                "max_results": 2,
                "site": "docs.python.org",
                "snippet_max_length": 180,
            },
            headers=keyed,
        )
    ).json()

    assert all(item["url"].startswith("https://docs.python.org/") for item in body["results"])
    assert all(len(item["snippet"]) <= 180 for item in body["results"])


async def test_bad_json_is_invalid_json(client: httpx.AsyncClient, keyed: dict[str, str]) -> None:
    response = await client.post(
        "/v1/search", content=b"{nope", headers={**keyed, "content-type": "application/json"}
    )
    _assert_envelope(response, 400, "invalid_json")


@pytest.mark.parametrize(
    ("headers", "status", "code", "message"),
    [
        (
            {},
            401,
            "missing_api_key",
            "Either X-API-Key header or Authorization Bearer token is required",
        ),
        ({"X-API-Key": "keen_notarealkey"}, 401, "invalid_api_key", "Invalid API key"),
        ({"X-API-Key": "sk-wrong"}, 401, "invalid_api_key", "Malformed API key"),
    ],
)
async def test_auth_errors(
    client: httpx.AsyncClient, headers: dict[str, str], status: int, code: str, message: str
) -> None:
    response = await client.post("/v1/search", json=_SEARCH, headers={**_HOST, **headers})

    body = _assert_envelope(response, status, code)
    assert body["message"] == message
    assert body["keyless"].startswith("/v1/search/public")
    assert body["api_keys_url"] == "https://app.keenable.ai/console/api-keys"


async def test_bearer_key_is_accepted(client: httpx.AsyncClient, key: str) -> None:
    response = await client.post(
        "/v1/search", json=_SEARCH, headers={**_HOST, "Authorization": f"Bearer {key}"}
    )
    assert response.status_code == 200


async def test_revoked_key_is_403_credentials_forbidden(
    client: httpx.AsyncClient, store: MockStore, keyed: dict[str, str]
) -> None:
    store.set_key_status("keenable", "default", "revoked")
    response = await client.get("/v1/fetch", params=_FETCH, headers=keyed)
    assert _assert_envelope(response, 403, "credentials_forbidden")["message"] == "Key revoked"


async def test_exhausted_credits_are_402(
    client: httpx.AsyncClient, store: MockStore, keyed: dict[str, str]
) -> None:
    store.set_credits("keenable", Decimal(0))
    response = await client.post("/v1/search", json=_SEARCH, headers=keyed)

    body = _assert_envelope(response, 402, "insufficient_credits")
    assert body["retryable"] is False
    assert {"billing_url", "auto_top_up_url"} <= set(body)


async def test_keyed_per_second_limit_is_shared_by_the_organization(
    client: httpx.AsyncClient, store: MockStore, keyed: dict[str, str]
) -> None:
    frozen = datetime(2026, 11, 17, 12, 0, 0, tzinfo=UTC)
    store.now = lambda: frozen
    other = next(item.key for item in store.keys("keenable") if item.label == "secondary")
    for index in range(10):
        headers = keyed if index % 2 else {**_HOST, "X-API-Key": other}
        assert (await client.post("/v1/search", json=_SEARCH, headers=headers)).status_code == 200

    response = await client.post("/v1/search", json=_SEARCH, headers=keyed)

    body = _assert_envelope(response, 429, "rate_limit_per_second")
    assert body["limit"] == {
        "scope": "organization",
        "window": "second",
        "max": 10,
        "resets_at": "2026-11-17T12:00:01.000Z",
    }
    assert body["retry_after_seconds"] == body["retryAfter"] == 1
    assert response.headers["retry-after"] == "1"
    assert response.headers["x-ratelimit-remaining"] == "0"


async def test_public_hourly_pool_runs_out(client: httpx.AsyncClient, store: MockStore) -> None:
    clock = [datetime(2026, 11, 17, 1, 0, 0, tzinfo=UTC)]
    store.now = lambda: clock[0]
    from polyweb_provider_mock.providers._rate_windows import WindowSpec, add

    add(store, WindowSpec("keenable:public:fetch:hour", 1000, 3600), 1000)
    clock[0] = clock[0].replace(minute=30)

    response = await client.get("/v1/fetch/public", params=_FETCH, headers=_PUBLIC)

    body = _assert_envelope(response, 429, "public_rate_limit_hourly")
    assert body["limit"]["scope"] == "ip" and body["limit"]["max"] == 1000
    assert body["retry_after_seconds"] == 1800
    assert (
        await client.post("/v1/search/public", json=_SEARCH, headers=_PUBLIC)
    ).status_code == 200


async def test_core_keyless_budget_and_disable(client: httpx.AsyncClient, store: MockStore) -> None:
    store.set_keyless("keenable", per_minute=1)
    assert (
        await client.post("/v1/search/public", json=_SEARCH, headers=_PUBLIC)
    ).status_code == 200
    limited = await client.get("/v1/fetch/public", params=_FETCH, headers=_PUBLIC)
    assert (
        _assert_envelope(limited, 429, "public_rate_limit_per_second")["limit"]["window"]
        == "minute"
    )

    store.set_keyless("keenable", enabled=False, per_minute=None)
    disabled = await client.get("/v1/fetch/public", params=_FETCH, headers=_PUBLIC)
    assert "keyless" not in _assert_envelope(disabled, 401, "missing_api_key")


@pytest.mark.parametrize(
    ("operation", "status", "code", "retry_after"),
    [
        ("search", 529, "search_overloaded", "1"),
        ("search", 500, "internal_error", "2"),
        ("search", 503, "auth_unavailable", "5"),
        ("fetch", 502, "target_unreachable", "2"),
        ("fetch", 504, "target_timeout", "5"),
    ],
)
async def test_http_error_faults_render_keenable_codes(
    client: httpx.AsyncClient,
    store: MockStore,
    keyed: dict[str, str],
    operation: str,
    status: int,
    code: str,
    retry_after: str,
) -> None:
    store.add_fault(
        FaultSpec(
            provider="keenable",
            operation=operation,
            kind=FaultKind.HTTP_ERROR,
            params=FaultParams(status=status),
        )
    )
    if operation == "search":
        response = await client.post("/v1/search", json=_SEARCH, headers=keyed)
    else:
        response = await client.get("/v1/fetch", params=_FETCH, headers=keyed)

    body = _assert_envelope(response, status, code)
    assert body["retryable"] is True
    assert response.headers["retry-after"] == retry_after == str(body["retry_after_seconds"])


async def test_rate_limit_fault_on_public_path_is_public_code(
    client: httpx.AsyncClient, store: MockStore
) -> None:
    store.add_fault(
        FaultSpec(
            provider="keenable",
            kind=FaultKind.RATE_LIMIT,
            params=FaultParams(retry_after=9, scope="second"),
        )
    )
    response = await client.post("/v1/search/public", json=_SEARCH, headers=_PUBLIC)

    body = _assert_envelope(response, 429, "public_rate_limit_per_second")
    assert response.headers["retry-after"] == "9" == str(body["retry_after_seconds"])


async def test_quota_fault_skips_free_public_rail(
    client: httpx.AsyncClient, store: MockStore, keyed: dict[str, str]
) -> None:
    store.add_fault(FaultSpec(provider="keenable", kind=FaultKind.QUOTA_EXHAUSTED))

    keyed_response = await client.post("/v1/search", json=_SEARCH, headers=keyed)
    public = await client.post("/v1/search/public", json=_SEARCH, headers=_PUBLIC)

    _assert_envelope(keyed_response, 402, "insufficient_credits")
    assert public.status_code == 200


async def test_fixture_overrides_results(
    client: httpx.AsyncClient, store: MockStore, keyed: dict[str, str]
) -> None:
    saved = {"results": [{"title": "Saved", "url": "https://saved.example.org/"}]}
    store.save_fixture("keenable", "search", "polyweb test", saved)

    body = (await client.post("/v1/search", json=_SEARCH, headers=keyed)).json()

    assert body["results"] == saved["results"]
    assert body["query"] == "polyweb test" and body["usage"]["sku"] == "search.pro"


async def test_missing_field_fault_drops_fetch_content(
    client: httpx.AsyncClient, store: MockStore, keyed: dict[str, str]
) -> None:
    store.add_fault(
        FaultSpec(
            provider="keenable",
            operation="fetch",
            kind=FaultKind.MALFORMED,
            params=FaultParams(variant="missing_field"),
        )
    )
    body = (await client.get("/v1/fetch", params=_FETCH, headers=keyed)).json()
    assert "content" not in body and "title" in body


async def test_unknown_route_is_keenable_404(
    client: httpx.AsyncClient, keyed: dict[str, str]
) -> None:
    _assert_envelope(await client.get("/v1/nope", headers=keyed), 404, "not_found")
