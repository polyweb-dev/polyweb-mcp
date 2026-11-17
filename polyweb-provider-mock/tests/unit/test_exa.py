"""Exa plugin wire behavior through the in-process app."""

import uuid
from decimal import Decimal

import httpx
import pytest

from polyweb_provider_mock.faults import FaultKind, FaultParams, FaultSpec
from polyweb_provider_mock.providers.exa import PLUGIN
from polyweb_provider_mock.store import MockStore

_API = {"Host": "api.exa.ai"}
_ADMIN = {"Host": "admin-api.exa.ai"}
_SEARCH = {"query": "polyweb test", "numResults": 3, "contents": {"highlights": True}}
_CONTENTS = {"urls": ["https://docs.python.org/3/library/json.html"], "text": True}


def _key(store: MockStore, label: str = "default") -> str:
    return next(item.key for item in store.keys("exa") if item.label == label)


@pytest.fixture
def headers(store: MockStore) -> dict[str, str]:
    return {**_API, "x-api-key": _key(store)}


def _usage_path(key: str) -> str:
    return f"/team-management/api-keys/{key}/usage"


def test_seeded_keys_are_uuid_shaped_and_visibly_fake(store: MockStore) -> None:
    keys = store.keys("exa")
    assert [key.label for key in keys] == ["default", "secondary", "service"]
    for key in keys:
        assert str(uuid.UUID(key.key)) == key.key and key.key.startswith("6d6f636b-")
    assert keys[2].scopes == ("team_management",)
    assert PLUGIN.key_format.generate() != PLUGIN.key_format.generate()


async def test_search_shape_cost_debit_and_request_id(
    client: httpx.AsyncClient, store: MockStore, headers: dict[str, str]
) -> None:
    response = await client.post("/search", json=_SEARCH, headers=headers)

    body = response.json()
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json; charset=utf-8"
    assert response.headers["x-request-id"] == body["requestId"]
    assert response.headers["x-exa-queued"] == "false"
    assert list(body) == ["requestId", "resolvedSearchType", "results", "searchTime", "costDollars"]
    assert body["costDollars"] == {"total": 0.007, "search": {"neural": 0.007}}
    assert len(body["results"]) == 3
    first = body["results"][0]
    assert first["id"] == first["url"] and first["highlights"][0].startswith(first["title"])
    assert {"publishedDate", "author", "image", "favicon", "entities"} <= set(first)
    assert "text" not in first and "summary" not in first
    assert store.account("exa").credits_used == Decimal("0.007")
    again = (await client.post("/search", json=_SEARCH, headers=headers)).json()
    assert again["results"] == body["results"] and again["requestId"] != body["requestId"]


@pytest.mark.parametrize(
    ("request_body", "cost"),
    [
        (
            {"query": "q", "numResults": 12, "contents": {"summary": True}},
            {"total": 0.021, "search": {"neural": 0.009}, "summary": 0.012},
        ),
        (
            {"query": "q", "numResults": 1, "type": "instant"},
            {"total": 0.004, "search": {"instant": 0.004}},
        ),
        (
            {"query": "q", "numResults": 1, "type": "deep"},
            {"total": 0.012, "search": {"deep": 0.012}},
        ),
        (
            {"query": "q", "numResults": 1, "type": "deep-reasoning"},
            {"total": 0.015, "search": {"deep-reasoning": 0.015}},
        ),
    ],
)
async def test_search_prices_follow_type_results_and_summaries(
    client: httpx.AsyncClient,
    store: MockStore,
    headers: dict[str, str],
    request_body: dict[str, object],
    cost: dict[str, object],
) -> None:
    body = (await client.post("/search", json=request_body, headers=headers)).json()

    assert body["costDollars"] == cost
    assert store.account("exa").credits_used == Decimal(str(cost["total"]))
    if str(request_body.get("type", "")).startswith("deep"):
        assert body["output"]["grounding"][0]["citations"]


async def test_search_contents_selectors_shape_results(
    client: httpx.AsyncClient, headers: dict[str, str]
) -> None:
    request = {
        "query": "polyweb test",
        "numResults": 1,
        "contents": {
            "text": {"maxCharacters": 40},
            "highlights": {"highlightsPerUrl": 2, "numSentences": 1},
            "summary": {"query": "what is it"},
            "extras": {"links": 2, "imageLinks": 1},
        },
    }
    result = (await client.post("/search", json=request, headers=headers)).json()["results"][0]

    assert len(result["text"]) == 40
    assert len(result["highlights"]) == 2
    assert result["summary"].startswith("The webpage is ")
    assert len(result["extras"]["links"]) == 2 and len(result["extras"]["imageLinks"]) == 1
    off = {"query": "x", "contents": {"text": False, "highlights": False, "summary": False}}
    bare = (await client.post("/search", json=off, headers=headers)).json()["results"][0]
    assert set(bare) == {"id", "title", "url", "publishedDate", "author", "image", "favicon"}


async def test_contents_per_type_costs_and_url_level_failures_are_free(
    client: httpx.AsyncClient, store: MockStore, headers: dict[str, str]
) -> None:
    request = {
        "urls": [
            "https://example.com/",
            "https://blocked.example.org/page",
            "https://gone.invalid/",
            "https://timeout.example.net/slow",
        ],
        "text": False,
        "highlights": True,
        "summary": True,
    }
    body = (await client.post("/contents", json=request, headers=headers)).json()

    assert [item["url"] for item in body["results"]] == ["https://example.com/"]
    assert body["results"][0]["author"] is None
    assert [status["status"] for status in body["statuses"]] == [
        "success",
        "error",
        "error",
        "error",
    ]
    assert [status.get("error", {}).get("tag") for status in body["statuses"]] == [
        None,
        "CRAWL_HTTP_403",
        "CRAWL_NOT_FOUND",
        "CRAWL_LIVECRAWL_TIMEOUT",
    ]
    assert body["costDollars"] == {
        "total": 0.002,
        "contents": {"highlights": 0.001, "summary": 0.001},
    }
    assert store.account("exa").credits_used == Decimal("0.002")


async def test_contents_defaults_to_text_and_echoes_the_url(
    client: httpx.AsyncClient, headers: dict[str, str]
) -> None:
    url = "https://docs.python.org/3/library/json.html"
    body = (await client.post("/contents", json={"urls": [url]}, headers=headers)).json()

    assert body["results"][0]["url"] == url and body["results"][0]["text"]
    assert body["statuses"] == [{"id": url, "status": "success", "source": "cached"}]
    assert body["costDollars"] == {"total": 0.001, "contents": {"text": 0.001}}


@pytest.mark.parametrize(
    ("path", "request_body", "tag", "fragment"),
    [
        ("/search", {"numResults": 1}, "INVALID_REQUEST_BODY", 'received undefined at "query"'),
        ("/search", {"query": 3}, "INVALID_REQUEST_BODY", "received number"),
        ("/search", {"query": "q", "type": "smart"}, "INVALID_REQUEST_BODY", '"type"'),
        ("/search", {"query": "q", "numResults": 0}, "INVALID_REQUEST_BODY", "Too small"),
        (
            "/search",
            {"query": "q", "numResults": 101, "contents": {"highlights": True}},
            "INVALID_NUM_RESULTS",
            "100",
        ),
        ("/search", {"query": "q", "numResults": 101}, "NUM_RESULTS_EXCEEDED", "limit"),
        ("/contents", {"text": True}, "INVALID_REQUEST_BODY", "Must provide either ids or urls"),
    ],
)
async def test_validation_errors_are_tagged_and_free(
    client: httpx.AsyncClient,
    store: MockStore,
    headers: dict[str, str],
    path: str,
    request_body: dict[str, object],
    tag: str,
    fragment: str,
) -> None:
    response = await client.post(path, json=request_body, headers=headers)

    assert response.status_code == 400
    assert response.json()["tag"] == tag and fragment in response.json()["error"]
    assert response.headers["x-request-id"] == response.json()["requestId"]
    assert store.account("exa").credits_used == 0


async def test_missing_key_is_a_payment_challenge_and_wrong_or_revoked_is_401(
    client: httpx.AsyncClient, store: MockStore
) -> None:
    missing = await client.post("/contents", json=_CONTENTS, headers=_API)
    wrong = await client.post(
        "/contents", json=_CONTENTS, headers={**_API, "x-api-key": str(uuid.uuid4())}
    )
    bearer = await client.post(
        "/contents", json=_CONTENTS, headers={**_API, "Authorization": f"Bearer {_key(store)}"}
    )
    store.set_key_status("exa", "default", "revoked")
    revoked = await client.post(
        "/contents", json=_CONTENTS, headers={**_API, "x-api-key": _key(store)}
    )

    assert (missing.status_code, missing.json()["tag"]) == (402, "X402_PAYMENT_REQUIRED")
    assert missing.json()["resource"]["url"] == "https://api.exa.ai/contents"
    assert "payment-required" in missing.headers and "www-authenticate" in missing.headers
    assert (wrong.status_code, wrong.json()["tag"]) == (401, "INVALID_API_KEY")
    assert bearer.status_code == 200
    assert (revoked.status_code, revoked.json()["tag"]) == (401, "INVALID_API_KEY")
    assert [entry.key_label for entry in store.log_tail("exa")] == [
        "missing-key",
        "invalid-key",
        "default",
        "default",
    ]


async def test_credit_exhaustion_is_402_and_never_half_debits(
    client: httpx.AsyncClient, store: MockStore, headers: dict[str, str]
) -> None:
    store.set_credits("exa", Decimal("0.010"))
    expensive = {"query": "q", "numResults": 12, "contents": {"summary": True}}

    refused = await client.post("/search", json=expensive, headers=headers)
    affordable = await client.post("/search", json={"query": "q"}, headers=headers)
    store.set_credits("exa", Decimal(0))
    empty = await client.post("/search", json={"query": "q"}, headers=headers)

    assert (refused.status_code, refused.json()["tag"]) == (402, "NO_MORE_CREDITS")
    assert affordable.status_code == 200
    assert (empty.status_code, empty.json()["tag"]) == (402, "NO_MORE_CREDITS")
    assert store.account("exa").credits_used == Decimal("0.007")


async def test_key_budget_is_api_key_budget_exceeded(
    client: httpx.AsyncClient, store: MockStore
) -> None:
    budget = store.create_key(
        "exa", PLUGIN.key_format, label="capped", credit_limit=Decimal("0.005")
    )
    response = await client.post(
        "/search", json={"query": "q"}, headers={**_API, "x-api-key": budget.key}
    )
    assert (response.status_code, response.json()["tag"]) == (402, "API_KEY_BUDGET_EXCEEDED")


@pytest.mark.parametrize(
    ("spec", "status", "tag"),
    [
        (
            FaultSpec(provider="exa", kind=FaultKind.RATE_LIMIT, params=FaultParams(retry_after=9)),
            429,
            "RATE_LIMIT_EXCEEDED",
        ),
        (FaultSpec(provider="exa", kind=FaultKind.OUTAGE), 503, "SERVICE_OVERLOADED"),
        (FaultSpec(provider="exa", kind=FaultKind.HTTP_ERROR), 500, "INTERNAL_SERVER_ERROR"),
        (
            FaultSpec(provider="exa", kind=FaultKind.HTTP_ERROR, params=FaultParams(status=403)),
            403,
            "FEATURE_DISABLED",
        ),
        (
            FaultSpec(
                provider="exa", kind=FaultKind.QUOTA_EXHAUSTED, params=FaultParams(scope="team")
            ),
            402,
            "TEAM_BUDGET_EXCEEDED",
        ),
        (FaultSpec(provider="exa", kind=FaultKind.AUTH_INVALID), 401, "INVALID_API_KEY"),
    ],
)
async def test_faults_render_in_the_exa_error_envelope(
    client: httpx.AsyncClient,
    store: MockStore,
    headers: dict[str, str],
    spec: FaultSpec,
    status: int,
    tag: str,
) -> None:
    store.add_fault(spec)
    response = await client.post("/search", json=_SEARCH, headers=headers)

    assert response.status_code == status
    assert set(response.json()) == {"requestId", "error", "tag"} and response.json()["tag"] == tag
    assert response.headers.get("retry-after") == ("9" if status == 429 else None)
    assert store.account("exa").credits_used == 0


async def test_usage_report_needs_a_service_key_and_reflects_the_ledger(
    client: httpx.AsyncClient, store: MockStore, headers: dict[str, str]
) -> None:
    await client.post(
        "/search", json={"query": "q", "contents": {"summary": True}}, headers=headers
    )
    await client.post("/contents", json=_CONTENTS, headers=headers)
    service = {**_ADMIN, "x-api-key": _key(store, "service")}
    target = _key(store)

    by_secret = await client.get(_usage_path(target), headers=service)
    public_id = by_secret.json()["id"]
    by_id = await client.get(_usage_path(public_id), headers=service)

    body = by_id.json()
    assert by_secret.status_code == by_id.status_code == 200
    assert public_id.startswith("key_") and body["api_key_id"] == target
    assert body["api_key_name"] == "default"
    assert body["total_cost_usd"] == 0.018
    assert {
        item["price_id"]: (item["quantity"], item["amount_usd"]) for item in body["cost_breakdown"]
    } == {
        "price_search_auto": (1, 0.007),
        "price_search_summary": (10, 0.01),
        "price_contents_text": (1, 0.001),
    }
    assert set(body) == {
        "id", "api_key_id", "api_key_name", "team_id", "period", "total_cost_usd",
        "cost_breakdown", "metadata",
    }  # fmt: skip
    other = (await client.get(_usage_path(_key(store, "secondary")), headers=service)).json()
    assert (other["total_cost_usd"], other["cost_breakdown"]) == (0, [])


@pytest.mark.parametrize(
    ("key_label", "path", "query", "status", "error"),
    [
        ("default", "key_mockresearch000", "", 401, "Unauthorized"),
        (None, "key_mockresearch000", "", 401, "Unauthorized"),
        ("service", "key_mockresearch000", "", 404, "API key not found"),
        ("service", "not-a-key", "", 400, "Invalid API key ID format."),
        ("service", "{default}", "?start_date=yesterday", 400, "Invalid date format"),
        ("service", "{default}", "?start_date=2020-01-01", 400, "too far in the past"),
        ("service", "{default}", "?group_by=week", 400, "group_by"),
        (
            "service",
            "{default}",
            "?start_date=2026-11-10&end_date=2026-11-01",
            400,
            "start_date must be before end_date",
        ),
    ],
)
async def test_usage_report_errors_use_the_admin_envelope(
    client: httpx.AsyncClient,
    store: MockStore,
    key_label: str | None,
    path: str,
    query: str,
    status: int,
    error: str,
) -> None:
    headers = dict(_ADMIN) if key_label is None else {**_ADMIN, "x-api-key": _key(store, key_label)}
    target = path.replace("{default}", _key(store))

    response = await client.get(_usage_path(target) + query, headers=headers)

    assert response.status_code == status
    assert list(response.json()) == ["error"] and error in response.json()["error"]
    assert "x-request-id" not in response.headers


async def test_each_host_serves_only_its_own_paths(
    client: httpx.AsyncClient, store: MockStore, headers: dict[str, str]
) -> None:
    on_admin = await client.post("/search", json=_SEARCH, headers={**headers, **_ADMIN})
    on_api = await client.get(
        _usage_path(_key(store)), headers={**_API, "x-api-key": _key(store, "service")}
    )
    unknown = await client.get("/nope", headers=headers)

    assert (on_admin.status_code, on_admin.json()) == (404, {"error": "Not Found"})
    assert (on_api.status_code, on_api.json()["tag"]) == (404, "NOT_FOUND")
    assert (unknown.status_code, unknown.json()["tag"]) == (404, "NOT_FOUND")
