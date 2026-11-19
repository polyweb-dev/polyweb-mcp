"""Tavily plugin wire behavior through the in-process app."""

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import httpx
import pytest

from polyweb_provider_mock.faults import FaultKind, FaultParams, FaultSpec
from polyweb_provider_mock.providers import discover
from polyweb_provider_mock.providers.base import ErrorContext, ErrorKind
from polyweb_provider_mock.store import MockStore
from tests.conftest import TAVILY

_SEARCH = {"query": "polyweb test", "max_results": 3, "include_usage": True}
_EXTRACT = {"urls": ["https://example.com"], "extract_depth": "basic", "include_usage": True}


async def test_basic_search_shape_debit_and_headers(
    client: httpx.AsyncClient, store: MockStore, tavily_headers: dict[str, str]
) -> None:
    response = await client.post("/search", json=_SEARCH, headers=tavily_headers)

    body = response.json()
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json"
    assert "content-security-policy" in response.headers
    assert list(body) == [
        "query",
        "follow_up_questions",
        "answer",
        "images",
        "results",
        "response_time",
        "usage",
        "request_id",
    ]
    assert body["usage"] == {"credits": 1}
    assert len(body["results"]) == 3
    assert list(body["results"][0]) == ["url", "title", "content", "score", "raw_content", "id"]
    assert store.account("tavily").credits_used == 1
    again = await client.post("/search", json=_SEARCH, headers=tavily_headers)
    assert again.json()["results"] == body["results"]
    assert again.json()["request_id"] != body["request_id"]


async def test_search_options_shape_the_body(
    client: httpx.AsyncClient, tavily_headers: dict[str, str]
) -> None:
    request = {
        **_SEARCH,
        "search_depth": "advanced",
        "topic": "news",
        "include_answer": "advanced",
        "include_raw_content": "text",
        "include_images": True,
        "include_image_descriptions": True,
        "include_favicon": True,
        "auto_parameters": True,
    }
    body = (await client.post("/search", json=request, headers=tavily_headers)).json()

    assert body["usage"] == {"credits": 2}
    assert isinstance(body["answer"], str)
    assert set(body["images"][0]) == {"url", "title", "description"}
    assert body["auto_parameters"] == {"topic": "news", "search_depth": "advanced"}
    first = body["results"][0]
    assert first["published_date"].endswith("GMT")
    assert isinstance(first["raw_content"], str)
    assert set(first["images"][0]) == {"url", "description", "description_source", "score"}
    assert first["favicon"].endswith("/favicon.ico")


async def test_search_without_usage_flag_omits_usage(
    client: httpx.AsyncClient, tavily_headers: dict[str, str]
) -> None:
    body = (await client.post("/search", json={"query": "x"}, headers=tavily_headers)).json()
    assert "usage" not in body and len(body["results"]) == 5


@pytest.mark.parametrize(
    ("request_body", "status", "fragment"),
    [
        ({"query": []}, 422, "string_type"),
        ({}, 422, "missing"),
        ({"query": "x", "search_depth": "deep"}, 400, "Invalid search depth"),
        ({"query": "x", "topic": "sports"}, 400, "Invalid topic"),
        ({"query": "x", "max_results": 50}, 400, "max_results"),
    ],
)
async def test_search_validation_errors_are_free(
    client: httpx.AsyncClient,
    store: MockStore,
    tavily_headers: dict[str, str],
    request_body: dict[str, object],
    status: int,
    fragment: str,
) -> None:
    response = await client.post("/search", json=request_body, headers=tavily_headers)

    assert response.status_code == status
    assert fragment in response.text
    assert store.account("tavily").credits_used == 0


async def test_bad_json_is_a_fastapi_422(
    client: httpx.AsyncClient, tavily_headers: dict[str, str]
) -> None:
    response = await client.post(
        "/search",
        content=b"{not json",
        headers={**tavily_headers, "content-type": "application/json"},
    )
    assert response.status_code == 422
    assert response.json()["detail"][0]["type"] == "json_invalid"


@pytest.mark.parametrize(
    ("headers", "label"),
    [
        ({"Authorization": "Bearer tvly-dev-wrong"}, "invalid-key"),
        ({}, "missing-key"),
        ({"Authorization": "Bearer "}, "missing-key"),
    ],
)
async def test_missing_or_unknown_keys_are_401(
    client: httpx.AsyncClient, store: MockStore, headers: dict[str, str], label: str
) -> None:
    response = await client.post("/search", json=_SEARCH, headers={**TAVILY, **headers})

    assert response.status_code == 401
    assert response.json() == {"detail": {"error": "Unauthorized: missing or invalid API key."}}
    assert store.log_tail("tavily")[-1].key_label == label


async def test_revoked_key_is_401(
    client: httpx.AsyncClient, store: MockStore, tavily_headers: dict[str, str]
) -> None:
    store.set_key_status("tavily", "default", "revoked")
    response = await client.post("/search", json=_SEARCH, headers=tavily_headers)
    assert response.status_code == 401


async def test_extract_success_failures_and_accumulated_credits(
    client: httpx.AsyncClient, store: MockStore, tavily_headers: dict[str, str]
) -> None:
    urls = [
        "https://example.com",
        "https://docs.python.org/3/library/json.html",
        "https://blocked.example.org/page",
        "https://gone.invalid/",
        "not-a-url",
    ]
    request = {"urls": urls, "include_usage": True, "include_favicon": True}
    body = (await client.post("/extract", json=request, headers=tavily_headers)).json()

    assert [item["url"] for item in body["results"]] == urls[:2]
    assert list(body["results"][0]) == ["url", "title", "raw_content", "images", "favicon"]
    assert body["results"][0]["favicon"] is None
    errors = {item["url"]: item["error"] for item in body["failed_results"]}
    assert errors["not-a-url"] == "Validation Error: Invalid URL format"
    assert "403" in errors["https://blocked.example.org/page"]
    assert "https://gone.invalid/" in errors
    assert body["usage"] == {"credits": 0}
    for _ in range(3):
        await client.post("/extract", json=request, headers=tavily_headers)
    assert store.account("tavily").credits_used == 1


async def test_extract_all_invalid_is_400_with_failed_results(
    client: httpx.AsyncClient, tavily_headers: dict[str, str]
) -> None:
    response = await client.post(
        "/extract", json={"urls": ["not-a-url"], "include_usage": True}, headers=tavily_headers
    )
    assert response.status_code == 400
    assert response.json() == {
        "detail": {
            "error": "All URLs failed validation.",
            "failed_results": [
                {"url": "not-a-url", "error": "Validation Error: Invalid URL format"}
            ],
        }
    }


async def test_usage_reports_ledger_counters(
    client: httpx.AsyncClient, store: MockStore, tavily_headers: dict[str, str]
) -> None:
    await client.post(
        "/search", json={**_SEARCH, "search_depth": "advanced"}, headers=tavily_headers
    )
    store.charge(
        store.resolve("tavily", tavily_headers["Authorization"][7:]), "extract.advanced", Decimal(5)
    )  # type: ignore[arg-type]

    usage = (await client.get("/usage", headers=tavily_headers)).json()

    assert usage["key"] == {
        "usage": 4,
        "limit": None,
        "search_usage": 2,
        "crawl_usage": 0,
        "extract_usage": 2,
        "map_usage": 0,
        "research_usage": 0,
    }
    assert usage["account"]["plan_usage"] == 4
    assert usage["account"]["plan_limit"] == 1000
    assert usage["account"]["current_plan"] == "Researcher"
    assert usage["account"]["paygo_limit"] is None


async def test_keyless_rail_budget_and_disable(client: httpx.AsyncClient, store: MockStore) -> None:
    keyless = {**TAVILY, "X-Tavily-Access-Mode": "keyless"}
    ok = await client.post("/search", json=_SEARCH, headers=keyless)
    assert ok.status_code == 200 and ok.json()["usage"] == {"credits": 1}
    assert store.account("tavily").credits_used == 0

    store.set_keyless("tavily", per_day=1)
    capped = await client.post("/extract", json=_EXTRACT, headers=keyless)
    assert capped.status_code == 429
    assert int(capped.headers["retry-after"]) == capped.json()["error"]["retry_after_seconds"]
    assert capped.json()["error"]["code"] == "daily_cap_reached"
    assert [action["type"] for action in capped.json()["error"]["next_actions"]] == [
        "agentic_payment",
        "signup",
    ]

    store.set_keyless("tavily", enabled=False)
    assert (await client.post("/search", json=_SEARCH, headers=keyless)).status_code == 401
    usage = await client.get("/usage", headers=keyless)
    assert usage.status_code == 401


async def test_bearer_key_wins_over_keyless_header(
    client: httpx.AsyncClient, store: MockStore, tavily_headers: dict[str, str]
) -> None:
    headers = {**tavily_headers, "X-Tavily-Access-Mode": "keyless"}
    assert (await client.post("/search", json=_SEARCH, headers=headers)).status_code == 200
    assert store.account("tavily").credits_used == 1


@pytest.mark.parametrize(
    ("spec", "status", "check"),
    [
        (
            FaultSpec(kind=FaultKind.RATE_LIMIT, params=FaultParams(retry_after=7)),
            429,
            lambda r: r.headers["retry-after"] == "7" and "excessive" in r.text,
        ),
        (FaultSpec(kind=FaultKind.OUTAGE), 503, lambda r: "Service Unavailable" in r.text),
        (
            FaultSpec(kind=FaultKind.OUTAGE, params=FaultParams(status=502)),
            502,
            lambda r: "Bad Gateway" in r.text,
        ),
        (
            FaultSpec(kind=FaultKind.HTTP_ERROR),
            500,
            lambda r: r.json() == {"detail": {"error": "Internal Server Error"}},
        ),
        (FaultSpec(kind=FaultKind.QUOTA_EXHAUSTED), 432, lambda r: "plan's set usage" in r.text),
        (
            FaultSpec(kind=FaultKind.QUOTA_EXHAUSTED, params=FaultParams(scope="paygo")),
            433,
            lambda r: "pay-as-you-go" in r.text,
        ),
        (
            FaultSpec(kind=FaultKind.QUOTA_EXHAUSTED, params=FaultParams(status=402)),
            402,
            lambda r: "detail" in r.json(),
        ),
        (FaultSpec(kind=FaultKind.AUTH_INVALID), 401, lambda r: "Unauthorized" in r.text),
        (
            FaultSpec(kind=FaultKind.TIMEOUT, params=FaultParams(seconds=0, status=504)),
            504,
            lambda r: "Gateway Timeout" in r.text,
        ),
    ],
)
async def test_fault_rules_render_tavily_errors(
    client: httpx.AsyncClient,
    store: MockStore,
    tavily_headers: dict[str, str],
    spec: FaultSpec,
    status: int,
    check: object,
) -> None:
    store.add_fault(spec.model_copy(update={"provider": "tavily", "operation": "search"}))

    response = await client.post("/search", json=_SEARCH, headers=tavily_headers)

    assert response.status_code == status
    assert callable(check) and check(response)
    assert store.account("tavily").credits_used == 0
    assert store.log_tail("tavily")[-1].fault == f"{spec.kind.value}#1"


async def test_keyless_rate_limit_fault_uses_the_envelope(
    client: httpx.AsyncClient, store: MockStore
) -> None:
    store.add_fault(
        FaultSpec(
            kind=FaultKind.RATE_LIMIT,
            params=FaultParams(retry_after=9, retry_after_header=False),
        )
    )
    response = await client.post(
        "/search", json=_SEARCH, headers={**TAVILY, "X-Tavily-Access-Mode": "keyless"}
    )
    assert response.status_code == 429
    assert "retry-after" not in response.headers
    assert response.json()["error"]["retry_after_seconds"] == 9


@pytest.mark.parametrize(
    ("variant", "check"),
    [
        ("invalid_json", lambda r: r.text.startswith("<html>")),
        ("truncated", lambda r: r.text.startswith('{"query"') and not r.text.endswith("}")),
        ("wrong_content_type", lambda r: r.headers["content-type"].startswith("text/html")),
        ("missing_field", lambda r: "results" not in r.json() and "query" in r.json()),
    ],
)
async def test_malformed_faults_damage_successful_bodies(
    client: httpx.AsyncClient,
    store: MockStore,
    tavily_headers: dict[str, str],
    variant: str,
    check: object,
) -> None:
    store.add_fault(
        FaultSpec(kind=FaultKind.MALFORMED, params=FaultParams.model_validate({"variant": variant}))
    )
    response = await client.post("/search", json=_SEARCH, headers=tavily_headers)

    assert response.status_code == 200
    assert callable(check) and check(response)
    assert store.account("tavily").credits_used == 1


async def test_fault_on_other_operation_does_not_apply(
    client: httpx.AsyncClient, store: MockStore, tavily_headers: dict[str, str]
) -> None:
    store.add_fault(FaultSpec(provider="tavily", operation="extract", kind=FaultKind.OUTAGE))
    store.add_fault(FaultSpec(provider="exa", kind=FaultKind.OUTAGE))
    assert (await client.post("/search", json=_SEARCH, headers=tavily_headers)).status_code == 200


async def test_saved_fixtures_override_synthetic_content(
    client: httpx.AsyncClient, store: MockStore, tavily_headers: dict[str, str]
) -> None:
    store.save_fixture(
        "tavily",
        "search",
        "polyweb test",
        {
            "query": "polyweb test",
            "results": [{"url": "https://saved.example/a", "title": "Saved"}],
        },
    )
    store.save_fixture(
        "tavily",
        "extract",
        "https://example.com",
        {"url": "https://example.com", "title": "Saved page", "raw_content": "saved", "images": []},
    )

    search = (
        await client.post(
            "/search", json={**_SEARCH, "query": " Polyweb  TEST"}, headers=tavily_headers
        )
    ).json()
    extract = (await client.post("/extract", json=_EXTRACT, headers=tavily_headers)).json()

    assert search["results"] == [{"url": "https://saved.example/a", "title": "Saved"}]
    assert search["usage"] == {"credits": 1} and "request_id" in search
    assert extract["results"][0]["raw_content"] == "saved"


async def test_logged_response_can_become_a_fixture(
    client: httpx.AsyncClient, store: MockStore, tavily_headers: dict[str, str]
) -> None:
    first = (await client.post("/search", json=_SEARCH, headers=tavily_headers)).json()
    entry = store.log_tail("tavily")[-1]
    assert entry.match_key == "polyweb test"
    store.save_fixture_from_log(entry.id)
    store.save_fixture(
        "tavily", "search", "polyweb test", {**first, "results": first["results"][:1]}
    )
    second = (await client.post("/search", json=_SEARCH, headers=tavily_headers)).json()
    assert second["results"] == first["results"][:1]
    assert json.loads(store.log_entry(entry.id).response_body or "{}")["query"] == "polyweb test"  # type: ignore[union-attr]


class _Clock:
    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


def _freeze(store: MockStore, now: datetime) -> _Clock:
    clock = _Clock(now)
    store.now = clock  # type: ignore[method-assign]
    return clock


def _headers_for(store: MockStore, label: str) -> dict[str, str]:
    key = next(item.key for item in store.keys("tavily") if item.label == label)
    return {**TAVILY, "Authorization": f"Bearer {key}"}


async def test_researcher_rpm_is_shared_by_every_key_of_the_account(
    client: httpx.AsyncClient, store: MockStore, tavily_headers: dict[str, str]
) -> None:
    clock = _freeze(store, datetime(2026, 11, 19, 12, 0, 0, tzinfo=UTC))
    secondary = _headers_for(store, "secondary")
    bad = {"query": "x", "search_depth": "deep"}  # free, but still a request
    for index in range(100):
        headers = tavily_headers if index % 2 else secondary
        assert (await client.post("/search", json=bad, headers=headers)).status_code == 400

    clock.now += timedelta(seconds=15)
    limited = await client.post("/extract", json=_EXTRACT, headers=secondary)
    assert limited.status_code == 429
    assert limited.headers["retry-after"] == "45"
    assert limited.json() == {
        "detail": {
            "error": "Your request has been blocked due to excessive requests. "
            "Please reduce the rate of requests."
        }
    }
    assert (await client.get("/usage", headers=tavily_headers)).status_code == 200
    assert store.account("tavily").credits_used == 0

    clock.now += timedelta(seconds=45)
    assert (await client.post("/search", json=_SEARCH, headers=tavily_headers)).status_code == 200


async def test_paid_plan_rpm_comes_from_the_account_attribute(
    client: httpx.AsyncClient, store: MockStore, tavily_headers: dict[str, str]
) -> None:
    _freeze(store, datetime(2026, 11, 19, 12, 0, 0, tzinfo=UTC))
    store.set_account_attributes("tavily", {"requests_per_minute": 1000})
    bad = {"query": "x", "search_depth": "deep"}
    for _ in range(101):
        response = await client.post("/search", json=bad, headers=tavily_headers)
    assert response.status_code == 400

    store.set_account_attributes("tavily", {"requests_per_minute": 101})
    limited = await client.post("/search", json=bad, headers=tavily_headers)
    assert limited.status_code == 429 and limited.headers["retry-after"] == "60"


async def test_usage_allows_ten_calls_per_ten_minutes(
    client: httpx.AsyncClient, store: MockStore, tavily_headers: dict[str, str]
) -> None:
    clock = _freeze(store, datetime(2026, 11, 19, 12, 0, 0, tzinfo=UTC))
    secondary = _headers_for(store, "secondary")
    for index in range(10):
        headers = tavily_headers if index % 2 else secondary
        assert (await client.get("/usage", headers=headers)).status_code == 200

    clock.now += timedelta(minutes=4)
    limited = await client.get("/usage", headers=tavily_headers)
    assert limited.status_code == 429 and limited.headers["retry-after"] == "360"
    assert "excessive requests" in limited.json()["detail"]["error"]
    assert (await client.post("/search", json=_SEARCH, headers=tavily_headers)).status_code == 200

    clock.now += timedelta(minutes=6)
    assert (await client.get("/usage", headers=tavily_headers)).status_code == 200


async def test_spent_plan_is_432_on_a_prepaid_account(
    client: httpx.AsyncClient, store: MockStore, tavily_headers: dict[str, str]
) -> None:
    store.set_credits("tavily", Decimal(1))
    assert (await client.post("/search", json=_SEARCH, headers=tavily_headers)).status_code == 200

    refused = await client.post("/search", json=_SEARCH, headers=tavily_headers)

    assert refused.status_code == 432
    assert "plan's set usage limit" in refused.json()["detail"]["error"]
    usage = (await client.get("/usage", headers=tavily_headers)).json()["account"]
    assert (usage["plan_usage"], usage["paygo_usage"], usage["paygo_limit"]) == (1, 0, None)


async def test_paygo_bills_overage_then_433_at_its_limit(
    client: httpx.AsyncClient, store: MockStore, tavily_headers: dict[str, str]
) -> None:
    store.set_credits("tavily", Decimal(1))
    store.set_funding("tavily", "postpaid", overage_limit=Decimal(3))
    advanced = {**_SEARCH, "search_depth": "advanced"}

    first = await client.post("/search", json=_SEARCH, headers=tavily_headers)
    second = await client.post("/search", json=advanced, headers=tavily_headers)
    over = await client.post("/search", json=advanced, headers=tavily_headers)

    assert (first.status_code, second.status_code) == (200, 200)
    assert second.json()["usage"] == {"credits": 2}
    assert over.status_code == 433
    assert "pay-as-you-go limit" in over.json()["detail"]["error"]
    usage = (await client.get("/usage", headers=tavily_headers)).json()
    assert usage["account"]["plan_usage"] == 1 and usage["account"]["plan_limit"] == 1
    assert (usage["account"]["paygo_usage"], usage["account"]["paygo_limit"]) == (2, 3)
    assert usage["key"]["usage"] == 3

    store.set_funding("tavily", "postpaid", overage_limit=None)
    assert (await client.post("/search", json=advanced, headers=tavily_headers)).status_code == 200
    account = (await client.get("/usage", headers=tavily_headers)).json()["account"]
    assert (account["paygo_usage"], account["paygo_limit"]) == (4, None)


async def test_key_credit_limit_is_432_and_spares_other_keys(
    client: httpx.AsyncClient, store: MockStore, tavily_headers: dict[str, str]
) -> None:
    plugin = discover()["tavily"]
    capped = store.create_key(
        "tavily", plugin.key_format, label="capped", credit_limit=Decimal(200)
    )
    headers = {**TAVILY, "Authorization": f"Bearer {capped.key}"}
    store.charge(store.resolve("tavily", capped.key), "search.basic", Decimal(199))  # type: ignore[arg-type]

    advanced = {**_SEARCH, "search_depth": "advanced"}
    refused = await client.post("/search", json=advanced, headers=headers)
    assert refused.status_code == 432
    assert "plan's set usage limit" in refused.json()["detail"]["error"]
    assert (await client.post("/search", json=_SEARCH, headers=headers)).status_code == 200
    assert (await client.post("/search", json=_SEARCH, headers=headers)).status_code == 432

    usage = (await client.get("/usage", headers=headers)).json()
    assert (usage["key"]["usage"], usage["key"]["limit"]) == (200, 200)
    assert (await client.post("/search", json=_SEARCH, headers=tavily_headers)).status_code == 200


async def test_keyless_daily_cap_waits_until_the_window_frees(
    client: httpx.AsyncClient, store: MockStore
) -> None:
    assert store.keyless("tavily").per_day == 500  # type: ignore[union-attr]
    _freeze(store, datetime(2026, 11, 19, 23, 46, 16, tzinfo=UTC))
    keyless = {**TAVILY, "X-Tavily-Access-Mode": "keyless"}
    store.set_keyless("tavily", per_day=0)

    capped = await client.post("/search", json=_SEARCH, headers=keyless)

    assert capped.status_code == 429 and capped.headers["retry-after"] == "824"
    assert capped.json()["error"]["retry_after_seconds"] == 824
    built = discover()["tavily"].error(
        ErrorKind.RATE_LIMITED, ErrorContext(operation="search", keyless=True, store=store)
    )
    assert built.headers["Retry-After"] == "824"
