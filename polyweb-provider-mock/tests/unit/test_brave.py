"""Brave plugin wire behavior through the in-process app."""

import random
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import httpx
import pytest

from polyweb_provider_mock.app import MockApplication
from polyweb_provider_mock.faults import FaultKind, FaultParams, FaultSpec
from polyweb_provider_mock.providers import discover
from polyweb_provider_mock.store import MockStore

BRAVE = {"Host": "api.search.brave.com"}
_WEB = "/res/v1/web/search"
_CONTEXT = "/res/v1/llm/context"


@pytest.fixture
def keys(store: MockStore) -> dict[str, str]:
    return {key.label: key.key for key in store.keys("brave")}


@pytest.fixture
def search(keys: dict[str, str]) -> dict[str, str]:
    return {**BRAVE, "X-Subscription-Token": keys["search"]}


async def test_web_search_shape_options_and_debit(
    client: httpx.AsyncClient, store: MockStore, search: dict[str, str]
) -> None:
    params = {"q": "polyweb test", "count": "3", "extra_snippets": "true"}
    response = await client.get(_WEB, params=params, headers=search)

    body = response.json()
    assert response.status_code == 200
    assert list(body) == [
        "type",
        "query",
        "discussions",
        "faq",
        "infobox",
        "mixed",
        "videos",
        "web",
    ]
    results = body["web"]["results"]
    assert len(results) == 3 and body["query"]["original"] == "polyweb test"
    assert all(
        "extra_snippets" in item and "fetched_content_timestamp" not in item for item in results
    )
    assert [entry["index"] for entry in body["mixed"]["main"] if entry["type"] == "web"] == [
        0,
        1,
        2,
    ]
    assert "<strong>" in results[0]["description"]
    assert store.account("brave").credits_used == 1
    assert store.ledger("brave")[-1].usd == Decimal("0.005")


async def test_web_search_offset_filter_and_plain_text(
    client: httpx.AsyncClient, search: dict[str, str]
) -> None:
    base = {"q": "rust ownership", "count": "2"}
    first = (await client.get(_WEB, params=base, headers=search)).json()
    second = await client.get(
        _WEB,
        params={**base, "offset": "1", "result_filter": "web", "text_decorations": "false"},
        headers=search,
    )

    body = second.json()
    assert set(body) == {"type", "query", "mixed", "web"}
    assert {r["url"] for r in body["web"]["results"]}.isdisjoint(
        r["url"] for r in first["web"]["results"]
    )
    assert all("<strong>" not in r["description"] for r in body["web"]["results"])


async def test_rate_limit_headers_follow_a_finite_monthly_cap(
    client: httpx.AsyncClient, store: MockStore, search: dict[str, str]
) -> None:
    store.set_credits("brave", Decimal(1000))
    response = await client.get(_WEB, params={"q": "x"}, headers=search)

    assert response.headers["x-ratelimit-limit"] == "50, 1000"
    assert response.headers["x-ratelimit-policy"] == "50;w=1, 1000;w=2592000"
    assert response.headers["x-ratelimit-remaining"] == "49, 999"
    reset = store.account("brave").period_reset
    assert reset is not None
    burst, monthly = response.headers["x-ratelimit-reset"].split(", ")
    expected = (reset - datetime.now(UTC)).total_seconds()
    assert burst == "1" and abs(int(monthly) - expected) < 5


async def test_spent_monthly_cap_is_429_quota_limited_without_debit(
    client: httpx.AsyncClient, store: MockStore, search: dict[str, str]
) -> None:
    store.set_credits("brave", Decimal(0))
    response = await client.get(_WEB, params={"q": "x"}, headers=search)

    error = response.json()["error"]
    assert response.status_code == 429
    assert error["code"] == "QUOTA_LIMITED" and error["status"] == 429
    assert response.headers["x-ratelimit-remaining"] == "50, 0"
    assert "retry-after" not in response.headers
    assert store.account("brave").credits_used == 0


@pytest.fixture
async def frozen(tmp_path: Path) -> AsyncIterator[tuple[httpx.AsyncClient, MockStore]]:
    """An app whose store clock stands still, so every call is in one burst window."""

    moment = datetime(2026, 11, 17, 12, 0, tzinfo=UTC)
    state = MockStore(tmp_path / "frozen.db", now=lambda: moment)
    state.seed(discover().values())
    app = MockApplication(state, discover(), rng=random.Random(3))
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1") as http:
        yield http, state


async def test_burst_window_is_shared_and_answers_429_rate_limited(
    frozen: tuple[httpx.AsyncClient, MockStore],
) -> None:
    client, store = frozen
    token = next(key.key for key in store.keys("brave") if key.label == "search")
    headers = {**BRAVE, "X-Subscription-Token": token}
    remaining = []
    for _ in range(50):
        response = await client.get(_CONTEXT, params={"q": "x", "count": "1"}, headers=headers)
        remaining.append(response.headers["x-ratelimit-remaining"])

    limited = await client.get(_WEB, params={"q": "x"}, headers=headers)

    assert remaining[0] == "49, 0" and remaining[-1] == "0, 0"
    assert limited.status_code == 429
    assert limited.json()["error"]["code"] == "RATE_LIMITED"
    assert limited.headers["retry-after"] == "1"
    assert limited.headers["x-ratelimit-remaining"] == "0, 0"
    assert store.account("brave").credits_used == 50


async def test_answers_key_is_option_not_in_plan_on_both_endpoints(
    client: httpx.AsyncClient, store: MockStore, keys: dict[str, str]
) -> None:
    headers = {**BRAVE, "X-Subscription-Token": keys["answers"]}
    for path in (_WEB, _CONTEXT):
        response = await client.get(path, params={"q": "x"}, headers=headers)
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "OPTION_NOT_IN_PLAN"
    assert store.ledger("brave") == []


@pytest.mark.parametrize(
    ("headers", "code"),
    [
        ({"X-Subscription-Token": "BSAwrong"}, "SUBSCRIPTION_TOKEN_INVALID"),
        ({}, "VALIDATION"),
    ],
)
async def test_unknown_or_missing_token_is_an_edge_422(
    client: httpx.AsyncClient, headers: dict[str, str], code: str
) -> None:
    response = await client.get(_WEB, params={"q": "x"}, headers={**BRAVE, **headers})

    body = response.json()
    assert response.status_code == 422
    assert body["error"]["code"] == code
    assert "id" not in body["error"] and "time" not in body
    assert "x-ratelimit-limit" not in response.headers


async def test_revoked_token_is_rendered_as_invalid(
    client: httpx.AsyncClient, store: MockStore, search: dict[str, str]
) -> None:
    store.set_key_status("brave", "search", "revoked")
    response = await client.get(_WEB, params={"q": "x"}, headers=search)
    assert response.json()["error"]["code"] == "SUBSCRIPTION_TOKEN_INVALID"


@pytest.mark.parametrize(
    ("path", "params", "kind"),
    [
        (_WEB, {"q": "x", "count": "21"}, "less_than_equal"),
        (_WEB, {"q": "x", "count": "many"}, "int_parsing"),
        (_WEB, {"q": "x", "safesearch": "none"}, "enum"),
        (_WEB, {"q": "x", "spellcheck": "maybe"}, "bool_parsing"),
        (_WEB, {"q": ""}, "string_too_short"),
        (_CONTEXT, {"q": "x", "count": "51"}, "less_than_equal"),
        (_CONTEXT, {"q": "x", "maximum_number_of_tokens": "500"}, "greater_than_equal"),
    ],
)
async def test_parameter_validation_is_a_free_422(
    client: httpx.AsyncClient,
    store: MockStore,
    search: dict[str, str],
    path: str,
    params: dict[str, str],
    kind: str,
) -> None:
    response = await client.get(path, params=params, headers=search)

    error = response.json()["error"]
    assert response.status_code == 422
    assert error["code"] == "VALIDATION"
    assert error["meta"]["errors"][0]["type"] == kind
    assert store.account("brave").credits_used == 0


async def test_context_honours_url_snippet_and_local_options(
    client: httpx.AsyncClient, search: dict[str, str]
) -> None:
    params = {
        "q": "coffee shops",
        "count": "5",
        "maximum_number_of_urls": "3",
        "maximum_number_of_snippets_per_url": "1",
        "enable_local": "true",
    }
    body = (await client.get(_CONTEXT, params=params, headers=search)).json()

    grounding = body["grounding"]
    assert len(grounding["generic"]) == 3
    assert all(len(item["snippets"]) == 1 for item in grounding["generic"])
    assert set(grounding["poi"]) == {"name", "url", "title", "snippets"}
    assert len(grounding["map"]) == 2
    urls = [item["url"] for item in [*grounding["generic"], grounding["poi"], *grounding["map"]]]
    assert set(body["sources"]) == set(urls)
    assert set(next(iter(body["sources"].values()))) == {"title", "hostname", "age"}


async def test_context_token_budget_limits_the_snippets(
    client: httpx.AsyncClient, search: dict[str, str]
) -> None:
    small = {"q": "llm grounding", "count": "20", "maximum_number_of_tokens": "1024"}
    large = {**small, "maximum_number_of_tokens": "32768"}

    def snippets(body: dict[str, object]) -> int:
        grounding = body["grounding"]
        assert isinstance(grounding, dict)
        return sum(len(item["snippets"]) for item in grounding["generic"])

    few = snippets((await client.get(_CONTEXT, params=small, headers=search)).json())
    many = snippets((await client.get(_CONTEXT, params=large, headers=search)).json())
    assert 0 < few < many


@pytest.mark.parametrize(
    ("spec", "status", "code"),
    [
        (FaultSpec(provider="brave", kind=FaultKind.QUOTA_EXHAUSTED), 429, "QUOTA_LIMITED"),
        (
            FaultSpec(
                provider="brave", kind=FaultKind.QUOTA_EXHAUSTED, params=FaultParams(status=402)
            ),
            402,
            "CREDIT_EXHAUSTED",
        ),
        (
            FaultSpec(
                provider="brave",
                kind=FaultKind.QUOTA_EXHAUSTED,
                params=FaultParams(scope="spend_cap"),
            ),
            429,
            "USAGE_LIMIT_EXCEEDED",
        ),
        (FaultSpec(provider="brave", kind=FaultKind.RATE_LIMIT), 429, "RATE_LIMITED"),
        (
            FaultSpec(provider="brave", kind=FaultKind.HTTP_ERROR, params=FaultParams(status=500)),
            500,
            "INTERNAL",
        ),
    ],
)
async def test_faults_use_the_application_envelope(
    client: httpx.AsyncClient,
    store: MockStore,
    search: dict[str, str],
    spec: FaultSpec,
    status: int,
    code: str,
) -> None:
    store.add_fault(spec)
    response = await client.get(_WEB, params={"q": "x"}, headers=search)

    body = response.json()
    assert response.status_code == status
    assert body["type"] == "ErrorResponse" and body["error"]["code"] == code
    assert isinstance(body["error"]["id"], str) and isinstance(body["time"], int)


async def test_fault_rate_limit_carries_the_ledger_rate_headers(
    client: httpx.AsyncClient, store: MockStore, search: dict[str, str]
) -> None:
    store.set_credits("brave", Decimal(1000), "brave-search", used=Decimal(7))
    store.add_fault(FaultSpec(provider="brave", kind=FaultKind.RATE_LIMIT, count=1))

    limited = await client.get(_WEB, params={"q": "x"}, headers=search)

    assert limited.status_code == 429
    assert limited.headers["retry-after"] == "60"
    assert limited.headers["x-ratelimit-limit"] == "50, 1007"
    assert limited.headers["x-ratelimit-remaining"] == "50, 1000"
    assert limited.headers["x-ratelimit-policy"] == "50;w=1, 1007;w=2592000"
    assert "server" not in limited.headers


async def test_outage_is_the_load_balancer_page(
    client: httpx.AsyncClient, store: MockStore, search: dict[str, str]
) -> None:
    store.add_fault(FaultSpec(provider="brave", kind=FaultKind.OUTAGE))
    response = await client.get(_WEB, params={"q": "x"}, headers=search)

    assert response.status_code == 503
    assert response.headers["content-type"].startswith("text/html")
    assert "503 Service Temporarily Unavailable" in response.text


async def test_fixture_overrides_the_web_body(
    client: httpx.AsyncClient, store: MockStore, search: dict[str, str]
) -> None:
    saved = {"type": "search", "web": {"type": "search", "results": []}}
    store.save_fixture("brave", "web_search", "nothing here", saved)

    response = await client.get(_WEB, params={"q": "Nothing  here"}, headers=search)

    assert response.json() == saved
    assert response.headers["x-ratelimit-remaining"] == "49, 0"
    assert store.log_tail("brave")[-1].match_key == "nothing here"


@pytest.mark.parametrize(("path", "victim"), [(_WEB, "web"), (_CONTEXT, "grounding")])
async def test_missing_field_fault_drops_the_envelope(
    client: httpx.AsyncClient, store: MockStore, search: dict[str, str], path: str, victim: str
) -> None:
    store.add_fault(
        FaultSpec(
            provider="brave", kind=FaultKind.MALFORMED, params=FaultParams(variant="missing_field")
        )
    )
    body = (await client.get(path, params={"q": "x"}, headers=search)).json()
    assert victim not in body
