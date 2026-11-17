"""Parallel plugin wire behavior through the in-process app, plus its CLI and admin routes.

The store runs on a controlled clock, so device-code expiry, poll pacing, and
token lifetimes are deterministic.
"""

import json
import random
import sqlite3
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx
import pytest

from polyweb_provider_mock.app import MockApplication
from polyweb_provider_mock.cli import main
from polyweb_provider_mock.faults import FaultKind, FaultParams, FaultSpec
from polyweb_provider_mock.providers import discover
from polyweb_provider_mock.providers._parallel_account import ParallelAccount, bridge_label
from polyweb_provider_mock.store import MockStore

API = {"Host": "api.parallel.ai"}
PLATFORM = {"Host": "platform.parallel.ai"}
DEVICE_GRANT = "urn:ietf:params:oauth:grant-type:device_code"
_SEARCH = {
    "objective": "polyweb test",
    "search_queries": ["polyweb test"],
    "mode": "fast",
    "advanced_settings": {"max_results": 3},
}
_EXTRACT = {"urls": ["https://example.com/"], "advanced_settings": {"full_content": True}}


class Clock:
    def __init__(self) -> None:
        self.now = datetime(2026, 11, 17, 12, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += timedelta(seconds=seconds)


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def store(tmp_path: Path, clock: Clock) -> MockStore:
    state = MockStore(tmp_path / "mock.db", now=clock)
    state.seed(discover().values())
    return state


@pytest.fixture
async def client(store: MockStore) -> AsyncIterator[httpx.AsyncClient]:
    app = MockApplication(store, discover(), rng=random.Random(7))
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:8212") as http:
        yield http


@pytest.fixture
def key(store: MockStore) -> str:
    return next(item.key for item in store.keys("parallel") if item.label == "default")


@pytest.fixture
def headers(key: str) -> dict[str, str]:
    return {**API, "x-api-key": key}


def _spent(store: MockStore) -> Decimal:
    return store.account("parallel").credits_used


# ----------------------------------------------------------------- product


async def test_search_shape_ids_headers_and_debit(
    client: httpx.AsyncClient, store: MockStore, headers: dict[str, str]
) -> None:
    response = await client.post("/v1/search", json=_SEARCH, headers=headers)

    body = response.json()
    rid = response.headers["x-request-id"]
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json"
    assert list(body) == ["search_id", "results", "warnings", "usage", "metadata", "session_id"]
    assert (body["search_id"], body["session_id"]) == (f"search_{rid}", f"session_{rid}")
    assert body["usage"] == [{"name": "sku_search", "count": 1}]
    assert len(body["results"]) == 3
    assert set(body["results"][0]) == {"url", "title", "publish_date", "excerpts"}
    assert all(isinstance(text, str) and text for text in body["results"][0]["excerpts"])
    assert _spent(store) == Decimal("0.001")
    again = (await client.post("/v1/search", json=_SEARCH, headers=headers)).json()
    assert again["results"] == body["results"] and again["search_id"] != body["search_id"]


@pytest.mark.parametrize(
    ("extra", "results", "cost"),
    [
        ({"mode": "turbo", "advanced_settings": {"max_results": 3}}, 3, "0.001"),
        ({"mode": "basic", "advanced_settings": {"max_results": 3}}, 3, "0.005"),
        ({}, 10, "0.005"),
        # $0.001 for each result beyond the first ten.
        ({"advanced_settings": {"max_results": 14}}, 14, "0.009"),
    ],
)
async def test_search_mode_and_result_count_pricing(
    client: httpx.AsyncClient,
    store: MockStore,
    headers: dict[str, str],
    extra: dict[str, Any],
    results: int,
    cost: str,
) -> None:
    request = {"search_queries": ["polyweb test"], **extra}

    body = (await client.post("/v1/search", json=request, headers=headers)).json()

    assert len(body["results"]) == results
    assert _spent(store) == Decimal(cost)


async def test_search_options_session_domains_and_excerpt_size(
    client: httpx.AsyncClient, headers: dict[str, str]
) -> None:
    request = {
        **_SEARCH,
        "session_id": "session-from-client",
        "advanced_settings": {
            "max_results": 4,
            "source_policy": {"include_domains": ["docs.python.org"]},
            "excerpt_settings": {"max_chars_per_result": 50},
            "location": "us",
        },
    }
    body = (await client.post("/v1/search", json=request, headers=headers)).json()

    assert body["session_id"] == "session-from-client"
    assert {result["url"].split("/")[2] for result in body["results"]} == {"docs.python.org"}
    assert all(len(result["excerpts"][0]) <= 50 for result in body["results"])


@pytest.mark.parametrize(
    ("request_body", "loc", "kind"),
    [
        ({}, ["body", "search_queries"], "missing"),
        ({"search_queries": "polyweb"}, ["body", "search_queries"], "list_type"),
        ({"search_queries": ["a"], "mode": "slow"}, ["body", "mode"], "literal_error"),
        ({"search_queries": ["a"], "query": "x"}, ["body", "query"], "extra_forbidden"),
        (
            {"search_queries": ["a"], "advanced_settings": {"max_results": 0}},
            ["body", "advanced_settings", "max_results"],
            "greater_than_equal",
        ),
    ],
)
async def test_search_validation_uses_the_v1_envelope(
    client: httpx.AsyncClient,
    store: MockStore,
    headers: dict[str, str],
    request_body: dict[str, Any],
    loc: list[str],
    kind: str,
) -> None:
    response = await client.post("/v1/search", json=request_body, headers=headers)

    error = response.json()["error"]
    assert response.status_code == 422
    assert error["ref_id"] == response.headers["x-request-id"]
    assert error["message"] == "Request validation error."
    assert [(item["loc"], item["type"]) for item in error["detail"]["errors"]] == [(loc, kind)]
    assert _spent(store) == 0


async def test_extract_full_content_failures_and_billing(
    client: httpx.AsyncClient, store: MockStore, headers: dict[str, str]
) -> None:
    urls = [
        "https://docs.python.org/3/library/json.html",
        "https://blocked.example.org/page",
        "https://nowhere.invalid/",
        "ftp://example.com/file",
    ]
    request = {**_EXTRACT, "urls": urls, "objective": "json module"}
    response = await client.post("/v1/extract", json=request, headers=headers)

    body = response.json()
    assert response.status_code == 200
    assert body["extract_id"] == f"extract_{response.headers['x-request-id']}"
    assert [item["url"] for item in body["results"]] == [urls[0]]
    assert body["results"][0]["full_content"].startswith("# ")
    assert body["results"][0]["acquired_at"] == "2026-11-17T00:00:00Z"
    assert [(item["error_type"], item["http_status_code"]) for item in body["errors"]] == [
        ("fetch_error", 403),
        ("fetch_error", None),
        ("invalid_url", None),
    ]
    assert body["warnings"] is None
    assert body["usage"] == [{"name": "sku_extract_excerpts", "count": 1}]
    assert _spent(store) == Decimal("0.001")


async def test_extract_content_modes_and_default_warning(
    client: httpx.AsyncClient, headers: dict[str, str]
) -> None:
    url = "https://docs.python.org/3/library/json.html"
    excerpts_only = (await client.post("/v1/extract", json={"urls": [url]}, headers=headers)).json()
    capped = (
        await client.post(
            "/v1/extract",
            json={
                "urls": [url],
                "advanced_settings": {"full_content": {"max_chars_per_result": 40}, "links": True},
            },
            headers=headers,
        )
    ).json()

    assert excerpts_only["results"][0]["full_content"] is None
    assert excerpts_only["warnings"][0]["type"] == "warning"
    assert len(capped["results"][0]["full_content"]) == 40
    assert capped["results"][0]["links"][0].startswith("https://docs.python.org/")


async def test_extract_validation_and_url_limit(
    client: httpx.AsyncClient, headers: dict[str, str]
) -> None:
    too_many = {"urls": [f"https://example.com/{index}" for index in range(21)]}
    response = await client.post("/v1/extract", json=too_many, headers=headers)
    assert response.status_code == 422
    assert response.json()["error"]["detail"]["errors"][0]["type"] == "too_long"

    bad = await client.post(
        "/v1/extract",
        json={"urls": ["https://example.com/"], "advanced_settings": {"excerpts": True}},
        headers=headers,
    )
    assert bad.json()["error"]["detail"]["errors"][0]["loc"] == [
        "body",
        "advanced_settings",
        "excerpts",
    ]


async def test_saved_fixtures_override_synthetic_content(
    client: httpx.AsyncClient, store: MockStore, headers: dict[str, str]
) -> None:
    saved = {"results": [{"url": "https://saved.example/", "excerpts": ["saved"]}]}
    store.save_fixture("parallel", "search", "polyweb test", saved)
    store.save_fixture(
        "parallel",
        "extract",
        "https://example.com/",
        {"title": "Saved", "excerpts": ["saved"], "full_content": "saved body"},
    )

    search = (await client.post("/v1/search", json=_SEARCH, headers=headers)).json()
    extract = (await client.post("/v1/extract", json=_EXTRACT, headers=headers)).json()

    assert search["results"] == saved["results"]
    assert extract["results"][0] == {
        "title": "Saved",
        "excerpts": ["saved"],
        "full_content": "saved body",
        "url": "https://example.com/",
    }


async def test_keys_missing_wrong_and_revoked(
    client: httpx.AsyncClient, store: MockStore, key: str
) -> None:
    missing = await client.post("/v1/search", json=_SEARCH, headers=API)
    wrong = await client.post("/v1/extract", json=_EXTRACT, headers={**API, "x-api-key": "nope"})
    store.set_key_status("parallel", "default", "revoked")
    revoked = await client.post("/v1/search", json=_SEARCH, headers={**API, "x-api-key": key})

    assert missing.json() == {"code": 16, "message": "No API key provided (C.0)"}
    assert wrong.json() == revoked.json() == {"code": 16, "message": "Invalid API key (C.1)"}
    assert {missing.status_code, wrong.status_code, revoked.status_code} == {401}
    assert "x-request-id" not in missing.headers
    assert missing.headers["content-type"] == "application/json; charset=utf-8"


async def test_paths_answer_only_on_their_real_host(
    client: httpx.AsyncClient, headers: dict[str, str]
) -> None:
    wrong_host = await client.post(
        "/v1/search", json=_SEARCH, headers={**headers, "Host": "platform.parallel.ai"}
    )
    oauth_on_api = await client.post("/getServiceKeys/register", json={}, headers=API)

    assert (wrong_host.status_code, oauth_on_api.status_code) == (404, 404)


async def test_credit_exhaustion_is_402(
    client: httpx.AsyncClient, store: MockStore, headers: dict[str, str]
) -> None:
    store.set_credits("parallel", Decimal("0.0005"))
    response = await client.post("/v1/search", json=_SEARCH, headers=headers)

    assert response.status_code == 402
    assert response.json()["type"] == "error"
    assert response.json()["error"]["ref_id"] == response.headers["x-request-id"]
    assert "credit" in response.json()["error"]["message"].lower()


@pytest.mark.parametrize(
    ("spec", "status"),
    [
        (FaultSpec(provider="parallel", kind=FaultKind.RATE_LIMIT), 429),
        (FaultSpec(provider="parallel", kind=FaultKind.QUOTA_EXHAUSTED), 402),
        (FaultSpec(provider="parallel", kind=FaultKind.OUTAGE), 503),
        (
            FaultSpec(
                provider="parallel", kind=FaultKind.HTTP_ERROR, params=FaultParams(status=502)
            ),
            502,
        ),
        (FaultSpec(provider="parallel", kind=FaultKind.AUTH_INVALID), 401),
    ],
)
async def test_product_faults_use_the_real_formats(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    spec: FaultSpec,
    status: int,
    store: MockStore,
) -> None:
    store.add_fault(spec)
    response = await client.post("/v1/search", json=_SEARCH, headers=headers)

    assert response.status_code == status
    body = response.json()
    if status == 401:
        assert body == {"code": 16, "message": "Invalid API key (C.1)"}
    else:
        assert body["type"] == "error" and body["error"]["ref_id"]
    assert ("retry-after" in response.headers) == (status == 429)
    if status == 429:
        assert response.headers["retry-after"] == "60"


async def test_malformed_missing_field_drops_results(
    client: httpx.AsyncClient, store: MockStore, headers: dict[str, str]
) -> None:
    store.add_fault(
        FaultSpec(
            provider="parallel",
            operation="search",
            kind=FaultKind.MALFORMED,
            params=FaultParams(variant="missing_field"),
        )
    )
    body = (await client.post("/v1/search", json=_SEARCH, headers=headers)).json()
    assert "results" not in body and "search_id" in body


# ------------------------------------------------------------------- OAuth


async def _register(client: httpx.AsyncClient) -> str:
    response = await client.post(
        "/getServiceKeys/register",
        json={"client_name": "polyweb", "platform": {"system": "Linux"}},
        headers=PLATFORM,
    )
    assert response.status_code == 200
    return str(response.json()["client_id"])


async def _device(client: httpx.AsyncClient, client_id: str, scope: str = "balance:read") -> Any:
    response = await client.post(
        "/getServiceKeys/device/code",
        data={"client_id": client_id, "scope": scope},
        headers=PLATFORM,
    )
    return response


async def _poll(client: httpx.AsyncClient, client_id: str, device_code: str) -> httpx.Response:
    return await client.post(
        "/getServiceKeys/token",
        data={"grant_type": DEVICE_GRANT, "client_id": client_id, "device_code": device_code},
        headers=PLATFORM,
    )


async def _refresh(client: httpx.AsyncClient, client_id: str, token: str) -> httpx.Response:
    return await client.post(
        "/getServiceKeys/token",
        data={"grant_type": "refresh_token", "client_id": client_id, "refresh_token": token},
        headers=PLATFORM,
    )


async def _connect(
    client: httpx.AsyncClient, store: MockStore, clock: Clock, scope: str = "balance:read"
) -> tuple[str, dict[str, Any]]:
    client_id = await _register(client)
    device = (await _device(client, client_id, scope)).json()
    ParallelAccount(store).decide(device["user_code"], "approve")
    response = await _poll(client, client_id, device["device_code"])
    assert response.status_code == 200, response.text
    return client_id, response.json()


async def test_device_flow_pending_slow_down_approve_and_single_use(
    client: httpx.AsyncClient, store: MockStore, clock: Clock
) -> None:
    client_id = await _register(client)
    device = (await _device(client, client_id)).json()

    assert device["verification_uri"] == "http://127.0.0.1:8212/_mock/parallel/oauth/device"
    assert device["verification_uri_complete"].endswith(f"?user_code={device['user_code']}")
    assert (device["expires_in"], device["interval"]) == (600, 5)
    first = await _poll(client, client_id, device["device_code"])
    fast = await _poll(client, client_id, device["device_code"])
    assert (first.status_code, first.json()["error"]) == (400, "authorization_pending")
    assert (fast.status_code, fast.json()["error"]) == (400, "slow_down")
    ParallelAccount(store).decide(device["user_code"].replace("-", "").lower(), "approve")
    clock.advance(9)
    assert (await _poll(client, client_id, device["device_code"])).json()["error"] == "slow_down"
    clock.advance(15)
    granted = await _poll(client, client_id, device["device_code"])
    clock.advance(20)
    reused = await _poll(client, client_id, device["device_code"])

    tokens = granted.json()
    assert granted.status_code == 200
    assert set(tokens) == {
        "access_token",
        "token_type",
        "expires_in",
        "refresh_token",
        "authorization_expires_in",
        "scope",
    }
    assert (tokens["token_type"], tokens["expires_in"], tokens["scope"]) == (
        "Bearer",
        600,
        "balance:read",
    )
    assert tokens["access_token"].count(".") == 2
    assert (reused.status_code, reused.json()["error"]) == (400, "invalid_grant")


@pytest.mark.parametrize(
    ("decision", "error"), [("deny", "access_denied"), ("expire", "expired_token")]
)
async def test_denied_and_expired_codes_are_terminal(
    client: httpx.AsyncClient, store: MockStore, decision: str, error: str
) -> None:
    client_id = await _register(client)
    device = (await _device(client, client_id)).json()
    ParallelAccount(store).decide(device["user_code"], decision)  # type: ignore[arg-type]

    response = await _poll(client, client_id, device["device_code"])
    assert (response.status_code, response.json()["error"]) == (400, error)
    with pytest.raises(ValueError, match="not pending"):
        ParallelAccount(store).decide(device["user_code"], "approve")


async def test_device_code_lapses_on_the_clock(
    client: httpx.AsyncClient, store: MockStore, clock: Clock
) -> None:
    client_id = await _register(client)
    device = (await _device(client, client_id)).json()
    clock.advance(601)

    assert (await _poll(client, client_id, device["device_code"])).json()["error"] == (
        "expired_token"
    )


async def test_device_request_errors(client: httpx.AsyncClient) -> None:
    client_id = await _register(client)
    bad_scope = await _device(client, client_id, "account:read")
    no_client = await _device(client, "unknown-client")
    other_grant = await client.post(
        "/getServiceKeys/token",
        data={"grant_type": "password", "client_id": client_id},
        headers=PLATFORM,
    )
    wrong_code = await _poll(client, client_id, "not-a-device-code")

    assert (bad_scope.status_code, bad_scope.json()["error"]) == (400, "invalid_scope")
    assert (no_client.status_code, no_client.json()["error"]) == (401, "invalid_client")
    assert other_grant.json()["error"] == "unsupported_grant_type"
    assert wrong_code.json()["error"] == "invalid_grant"


async def test_auto_approve_and_client_secret(client: httpx.AsyncClient, store: MockStore) -> None:
    ParallelAccount(store).update_settings(auto_approve=True, issue_client_secret=True)
    registered = (
        await client.post(
            "/getServiceKeys/register", json={"client_name": "polyweb"}, headers=PLATFORM
        )
    ).json()
    client_id, secret = registered["client_id"], registered["client_secret"]
    device = (
        await client.post(
            "/getServiceKeys/device/code",
            data={"client_id": client_id, "client_secret": secret, "scope": "balance:read"},
            headers=PLATFORM,
        )
    ).json()
    form = {
        "grant_type": DEVICE_GRANT,
        "client_id": client_id,
        "device_code": device["device_code"],
    }

    no_secret = await client.post("/getServiceKeys/token", data=form, headers=PLATFORM)
    granted = await client.post(
        "/getServiceKeys/token", data={**form, "client_secret": secret}, headers=PLATFORM
    )

    assert (no_secret.status_code, no_secret.json()["error"]) == (401, "invalid_client")
    assert granted.status_code == 200


async def test_refresh_rotates_and_revoke_ends_the_session(
    client: httpx.AsyncClient, store: MockStore, clock: Clock
) -> None:
    client_id, tokens = await _connect(client, store, clock)
    clock.advance(60)
    rotated = await _refresh(client, client_id, tokens["refresh_token"])
    stale = await _refresh(client, client_id, tokens["refresh_token"])

    new = rotated.json()
    assert rotated.status_code == 200
    assert new["refresh_token"] != tokens["refresh_token"]
    assert new["access_token"] != tokens["access_token"]
    assert (stale.status_code, stale.json()["error"]) == (400, "invalid_grant")

    revoke = await client.post(
        "/getServiceKeys/token/revoke",
        data={"refresh_token": new["refresh_token"]},
        headers=PLATFORM,
    )
    assert (revoke.status_code, revoke.json()) == (200, {})
    assert (await _refresh(client, client_id, new["refresh_token"])).json()["error"] == (
        "invalid_grant"
    )
    # Revocation keeps issued access tokens valid until they expire.
    balance = await client.get(
        "/account/service/v1/balance",
        headers={**API, "Authorization": f"Bearer {new['access_token']}"},
    )
    assert balance.status_code == 200


async def test_refresh_expires_after_idle_period(
    client: httpx.AsyncClient, store: MockStore, clock: Clock
) -> None:
    client_id, tokens = await _connect(client, store, clock)
    clock.advance(30 * 86400 + 1)
    assert (await _refresh(client, client_id, tokens["refresh_token"])).json()["error"] == (
        "invalid_grant"
    )


async def test_balance_follows_the_ledger_and_account_facts(
    client: httpx.AsyncClient, store: MockStore, clock: Clock, headers: dict[str, str]
) -> None:
    _, tokens = await _connect(client, store, clock)
    bearer = {**API, "Authorization": f"Bearer {tokens['access_token']}"}

    fresh = await client.get("/account/service/v1/balance", headers=bearer)
    for _ in range(3):
        await client.post("/v1/search", json={**_SEARCH, "mode": "basic"}, headers=headers)
    spent = (await client.get("/account/service/v1/balance", headers=bearer)).json()
    ParallelAccount(store).set_balance(pending_debit_cents=250)
    pending = (await client.get("/account/service/v1/balance", headers=bearer)).json()
    ParallelAccount(store).set_balance(will_invoice=True)
    invoiced = (await client.get("/account/service/v1/balance", headers=bearer)).json()

    assert fresh.status_code == 200
    assert fresh.headers["x-request-id"].count("-") == 4
    assert set(fresh.json()) == {
        "org_id",
        "credit_balance_cents",
        "pending_debit_balance_cents",
        "will_invoice",
    }
    assert fresh.json()["credit_balance_cents"] == 500
    assert spent["credit_balance_cents"] == 498
    assert pending["pending_debit_balance_cents"] == 250
    assert (invoiced["will_invoice"], invoiced["credit_balance_cents"]) == (True, 0)


async def test_balance_bearer_failures(
    client: httpx.AsyncClient, store: MockStore, clock: Clock, key: str
) -> None:
    _, tokens = await _connect(client, store, clock, scope="usage:read")
    missing = await client.get("/account/service/v1/balance", headers=API)
    api_key = await client.get(
        "/account/service/v1/balance", headers={**API, "Authorization": f"Bearer {key}"}
    )
    scoped = await client.get(
        "/account/service/v1/balance",
        headers={**API, "Authorization": f"Bearer {tokens['access_token']}"},
    )
    clock.advance(601)
    expired = await client.get(
        "/account/service/v1/balance",
        headers={**API, "Authorization": f"Bearer {tokens['access_token']}"},
    )

    assert (missing.status_code, missing.headers["www-authenticate"]) == (401, "Bearer")
    assert missing.json() == {"error": "unauthorized", "message": "Missing bearer token"}
    assert api_key.json()["fault"]["detail"]["errorcode"] == "steps.jwt.InvalidToken"
    assert scoped.status_code == 403
    assert (expired.status_code, expired.json()["fault"]["detail"]["errorcode"]) == (
        401,
        "steps.jwt.TokenExpired",
    )


async def test_oauth_token_as_product_key_follows_the_setting(
    client: httpx.AsyncClient, store: MockStore, clock: Clock
) -> None:
    _, tokens = await _connect(client, store, clock)
    token_key = {**API, "x-api-key": tokens["access_token"]}

    allowed = await client.post("/v1/search", json=_SEARCH, headers=token_key)
    ParallelAccount(store).update_settings(token_product_access=False)
    refused = await client.post("/v1/search", json=_SEARCH, headers=token_key)
    ParallelAccount(store).update_settings(token_product_access=True)
    clock.advance(601)
    expired = await client.post("/v1/search", json=_SEARCH, headers=token_key)

    assert allowed.status_code == 200
    assert store.log_tail("parallel")[-3].key_label == bridge_label("parallel-org")
    assert refused.json() == expired.json() == {"code": 16, "message": "Invalid API key (C.1)"}


async def test_apps_and_key_minting(
    client: httpx.AsyncClient, store: MockStore, clock: Clock
) -> None:
    _, tokens = await _connect(client, store, clock, scope="apps:read keys:create keys:delete")
    bearer = {**API, "Authorization": f"Bearer {tokens['access_token']}"}

    apps = (await client.get("/account/service/v1/apps", headers=bearer)).json()["apps"]
    app_id = apps[0]["app_id"]
    minted = await client.post(
        f"/account/service/v1/apps/{app_id}/keys", json={"api_key_name": "ci"}, headers=bearer
    )
    raw = minted.json()["raw_api_key"]
    search = await client.post("/v1/search", json=_SEARCH, headers={**API, "x-api-key": raw})
    missing_name = await client.post(
        f"/account/service/v1/apps/{app_id}/keys", json={}, headers=bearer
    )
    deleted = await client.delete(
        f"/account/service/v1/apps/{app_id}/keys/{minted.json()['api_key_id']}", headers=bearer
    )
    after = await client.post("/v1/search", json=_SEARCH, headers={**API, "x-api-key": raw})

    assert set(apps[0]) == {"app_name", "org_name", "app_id", "org_id"}
    assert minted.status_code == 200
    assert set(minted.json()) == {
        "api_key_id",
        "api_key_name",
        "app_id",
        "app_name",
        "created_by_user_id",
        "created_by_user_email",
        "display_value",
        "raw_api_key",
        "created_at",
        "is_service_scoped",
    }
    assert search.status_code == 200
    assert missing_name.status_code == 422
    assert missing_name.json()["detail"][0]["loc"] == ["body", "api_key_name"]
    assert (deleted.status_code, after.status_code) == (200, 401)


@pytest.mark.parametrize(
    ("message", "status", "error"),
    [(None, 503, "temporarily_unavailable"), ("invalid_grant", 400, "invalid_grant")],
)
async def test_platform_faults_use_oauth_errors(
    client: httpx.AsyncClient, store: MockStore, message: str | None, status: int, error: str
) -> None:
    kind = FaultKind.OUTAGE if status == 503 else FaultKind.HTTP_ERROR
    store.add_fault(
        FaultSpec(
            provider="parallel",
            operation="token",
            kind=kind,
            params=FaultParams(status=status, message=message),
        )
    )
    response = await _refresh(client, "any", "any")
    assert (response.status_code, response.json()["error"]) == (status, error)


# ------------------------------------------------------- admin and the CLI


async def test_admin_device_page_and_decisions(client: httpx.AsyncClient) -> None:
    client_id = await _register(client)
    first = (await _device(client, client_id)).json()
    second = (await _device(client, client_id)).json()

    page = await client.get(
        "/_mock/parallel/oauth/device", params={"user_code": first["user_code"]}
    )
    approved = await client.post(
        "/_mock/parallel/oauth/approve", data={"user_code": first["user_code"]}
    )
    denied = await client.post(
        "/_mock/parallel/oauth/deny", json={"user_code": second["user_code"]}
    )
    unknown = await client.post("/_mock/parallel/oauth/approve", json={"user_code": "ZZZZ-ZZZZ"})
    state = (await client.get("/_mock/parallel/oauth")).json()

    assert page.headers["content-type"].startswith("text/html")
    assert first["user_code"] in page.text
    assert approved.status_code == 200 and "approved" in approved.text
    assert denied.json()["status"] == "denied"
    assert unknown.status_code == 404
    assert [item["status"] for item in state["devices"]] == ["approved", "denied"]
    assert all("device_code" not in item for item in state["devices"])
    settings = await client.put("/_mock/parallel/oauth/settings", json={"auto_approve": True})
    assert settings.json()["auto_approve"] is True


async def test_device_page_stays_usable_behind_the_admin_token(store: MockStore) -> None:
    app = MockApplication(store, discover(), admin_token="s3cret", rng=random.Random(7))
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:8212") as http:
        client_id = await _register(http)
        devices = [(await _device(http, client_id)).json() for _ in range(3)]
        first, second, third = [{"user_code": item["user_code"]} for item in devices]
        page = await http.get("/_mock/parallel/oauth/device", params=first)
        refused = await http.post("/_mock/parallel/oauth/approve", data=first)
        posted = await http.post(
            "/_mock/parallel/oauth/approve", data={**first, "admin_token": "s3cret"}
        )
        remembered = await http.post("/_mock/parallel/oauth/deny", data=second)
        http.cookies.clear()
        linked = await http.get(
            "/_mock/parallel/oauth/device", params={**third, "admin_token": "s3cret"}
        )
        by_cookie = await http.post("/_mock/parallel/oauth/approve", data=third)
        http.cookies.clear()
        wrong = await http.get("/_mock/parallel/oauth/device", params={"admin_token": "nope"})
        overview = await http.get("/_mock/parallel/oauth")

    assert page.status_code == 200 and 'name="admin_token"' in page.text
    assert refused.status_code == 401
    assert posted.status_code == 200 and "approved" in posted.text
    assert "polyweb_mock_admin" in posted.headers["set-cookie"]
    assert remembered.status_code == 200 and "denied" in remembered.text
    assert linked.status_code == 200 and 'name="admin_token"' not in linked.text
    assert "httponly" in linked.headers["set-cookie"].lower()
    assert by_cookie.status_code == 200
    assert "set-cookie" not in wrong.headers and 'name="admin_token"' in wrong.text
    assert overview.status_code == 401
    assert all("s3cret" not in json.dumps(item) for item in devices)


async def test_oauth_and_minted_key_secrets_never_reach_the_request_log(
    client: httpx.AsyncClient, store: MockStore, clock: Clock
) -> None:
    client_id, tokens = await _connect(client, store, clock, scope="apps:read keys:create")
    bearer = {**API, "Authorization": f"Bearer {tokens['access_token']}"}
    app_id = (await client.get("/account/service/v1/apps", headers=bearer)).json()["apps"][0]
    minted = await client.post(
        f"/account/service/v1/apps/{app_id['app_id']}/keys",
        json={"api_key_name": "ci"},
        headers=bearer,
    )
    rotated = (await _refresh(client, client_id, tokens["refresh_token"])).json()
    token_key = {**API, "x-api-key": rotated["access_token"]}
    assert (await client.post("/v1/search", json=_SEARCH, headers=token_key)).status_code == 200
    raw_key = minted.json()["raw_api_key"]
    await client.post("/v1/search", json=_SEARCH, headers={**API, "x-api-key": raw_key})

    with sqlite3.connect(store.db.path) as conn:
        dumped = json.dumps(conn.execute("SELECT * FROM request_log").fetchall())
    secrets = [
        tokens["access_token"],
        tokens["refresh_token"],
        rotated["access_token"],
        rotated["refresh_token"],
        raw_key,
    ]
    assert all(secret not in dumped for secret in secrets)
    assert "eyJ" not in dumped
    token_rows = [entry for entry in store.log_tail("parallel", 50) if entry.operation == "token"]
    assert token_rows
    assert all(entry.request_summary["body"]["logged"] is False for entry in token_rows)
    with_bodies = store.log_tail("parallel", 50, with_bodies=True)
    assert all(
        entry.response_body is None
        for entry in with_bodies
        if entry.operation in {"register", "device_code", "token", "revoke", "create_key"}
    )
    assert any(entry.response_body for entry in with_bodies if entry.operation == "search")


class _Cli:
    def __init__(self, db: Path, capsys: pytest.CaptureFixture[str]) -> None:
        self.db = db
        self.capsys = capsys

    def __call__(self, *argv: str) -> Any:
        code = main(["--db", str(self.db), *argv])
        out, err = self.capsys.readouterr()
        assert code == 0, err
        return json.loads(out)

    def fails(self, *argv: str) -> str:
        assert main(["--db", str(self.db), *argv]) == 1
        return self.capsys.readouterr().err


async def test_cli_oauth_and_balance_commands(
    client: httpx.AsyncClient, store: MockStore, capsys: pytest.CaptureFixture[str]
) -> None:
    cli = _Cli(store.db.path, capsys)
    client_id = await _register(client)
    first = (await _device(client, client_id)).json()
    second = (await _device(client, client_id)).json()

    assert cli("parallel", "oauth", "approve", first["user_code"])["status"] == "approved"
    assert cli("parallel", "oauth", "deny", second["user_code"])["status"] == "denied"
    assert "not pending" in cli.fails("parallel", "oauth", "approve", second["user_code"])
    assert "no parallel device" in cli.fails("parallel", "oauth", "expire", "QQQQ-QQQQ")
    settings = cli("parallel", "oauth", "set", "--auto-approve", "on", "--interval", "2")
    assert (settings["auto_approve"], settings["interval"]) == (True, 2)
    cli("parallel", "oauth", "set", "--token-product-access", "off")
    bridge = next(
        item for item in store.keys("parallel") if item.label == bridge_label("parallel-org")
    )
    assert bridge.status == "revoked"
    shown = cli("parallel", "oauth", "show")
    assert len(shown["devices"]) == 2 and shown["settings"]["token_product_access"] is False
    balance = cli("parallel", "balance", "set", "--pending-cents", "40", "--will-invoice", "off")
    assert (balance["credit_balance_cents"], balance["pending_debit_balance_cents"]) == (500, 40)
    assert cli("parallel", "balance", "show")["pending_debit_balance_cents"] == 40
    assert cli("parallel", "oauth", "revoke-sessions") == {"revoked": 0}
