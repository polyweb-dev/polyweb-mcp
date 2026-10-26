"""Offline Behave steps for the Parallel OAuth device flow and balance poll."""

from __future__ import annotations

import tempfile
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx
from behave import given, then, when  # type: ignore[import-untyped]
from fastapi.testclient import TestClient

from freesearch.adapters.base import ProviderAdapter
from freesearch.models.contracts import (
    CostEstimate,
    FetchedDocument,
    FetchRequest,
    FetchResponse,
    ProviderCapabilities,
    SearchRequest,
    SearchResponse,
    UsageOperation,
)
from freesearch.persistence.storage import SQLiteRepository
from freesearch.routers.api import create_app
from freesearch.services.monitoring import refresh_quotas
from freesearch.services.parallel_oauth import (
    METADATA_RUNTIME_KEY,
    clear_oauth_poll_state,
    clear_oauth_test_seams,
    set_oauth_test_seams,
)
from tests.fixtures.auth import (
    TEMP_PASSWORD,
    configure_bdd_secret,
    promote_to_system_admin,
    temp_email,
)

_BALANCE_PATH = "/account/service/v1/balance"


class _VaultDouble:
    """Dict-backed offline vault double for the OAuth BDD scenarios."""

    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    def get(self, name: str) -> str | None:
        return self.values.get(name)

    def set(self, name: str, value: str) -> None:
        self.values[name] = value

    def delete(self, name: str) -> None:
        self.values.pop(name, None)


class _OAuthStubAdapter(ProviderAdapter):
    """Deterministic parallel stand-in; quota stays off so the OAuth hook owns it."""

    @property
    def name(self) -> str:
        return "parallel"

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(search=True)

    async def search(self, request: SearchRequest) -> SearchResponse:
        return SearchResponse(query=request.query, provider=self.name, results=[])

    async def fetch(self, request: FetchRequest) -> FetchResponse:
        return FetchResponse(
            provider=self.name,
            document=FetchedDocument(url=request.url, content="", fetched_at=datetime.now(UTC)),
        )

    async def estimate_cost(self, request: SearchRequest | FetchRequest) -> CostEstimate:
        operation = (
            UsageOperation.SEARCH if isinstance(request, SearchRequest) else UsageOperation.FETCH
        )
        return CostEstimate(provider=self.name, operation=operation, units=Decimal("0"))


class _PlatformStub:
    """Stubbed Parallel platform/account HTTP with observable call history."""

    def __init__(self) -> None:
        self.calls: list[httpx.Request] = []
        self.token_queue: list[httpx.Response] = []
        self.balance_queue: list[httpx.Response] = []
        self.client_id = "stub-client-1"
        self.device_code = "stub-device-code-1"
        self.access_token = "stub-access-token-1"
        self.refresh_token = "stub-refresh-token-1"

    def __call__(self, request: httpx.Request) -> httpx.Response:
        assert "access_token" not in (request.url.query or "")
        assert "device_code" not in (request.url.query or "")
        self.calls.append(request)
        path = request.url.path
        if path == "/getServiceKeys/register":
            return httpx.Response(200, json={"client_id": self.client_id})
        if path == "/getServiceKeys/device/code":
            return httpx.Response(
                200,
                json={
                    "device_code": self.device_code,
                    "user_code": "STUB-4821",
                    "verification_uri": "https://platform.test/activate",
                    "verification_uri_complete": "https://platform.test/activate?code=STUB-4821",
                    "expires_in": 1800,
                    "interval": 5,
                },
            )
        if path == "/getServiceKeys/token":
            if self.token_queue:
                return self.token_queue.pop(0)
            return httpx.Response(400, json={"error": "authorization_pending"})
        if path == "/getServiceKeys/token/revoke":
            return httpx.Response(200, json={})
        if path == _BALANCE_PATH:
            if self.balance_queue:
                return self.balance_queue.pop(0)
            return httpx.Response(
                200,
                json={
                    "org_id": "stub-org-1",
                    "credit_balance_cents": 1250,
                    "pending_debit_balance_cents": 250,
                    "will_invoice": False,
                },
            )
        raise AssertionError("unexpected oauth stub path: " + path)

    def calls_to(self, path: str) -> list[httpx.Request]:
        return [call for call in self.calls if call.url.path == path]

    def token_success(self) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "access_token": self.access_token,
                "refresh_token": self.refresh_token,
                "expires_in": 3600,
                "token_type": "Bearer",
            },
        )


def _login_admin(context: Any) -> dict[str, str]:
    # Register one account, assign the Admin role, and return one access header.
    email = temp_email("oauth-admin")
    with _client(context) as client:
        registered = client.post("/auth/register", json={"email": email, "password": TEMP_PASSWORD})
        assert registered.status_code == 201
        context.loop.run_until_complete(promote_to_system_admin(context.repository, email))
        logged_in = client.post(
            "/auth/jwt/login", data={"username": email, "password": TEMP_PASSWORD}
        )
        assert logged_in.status_code == 200
        headers = {"Authorization": f"Bearer {logged_in.json()['access_token']}"}
    context.auth_headers = headers
    return headers


def _open_oauth_api(context: Any, stub: _PlatformStub | None = None) -> None:
    clear_oauth_test_seams()
    clear_oauth_poll_state()
    configure_bdd_secret(context)
    previous = getattr(context, "http_client", None)
    if previous is not None:
        context.loop.run_until_complete(previous.aclose())
    context.platform_stub = stub or _PlatformStub()
    context.http_client = httpx.AsyncClient(
        transport=httpx.MockTransport(context.platform_stub), timeout=30.0
    )
    with tempfile.NamedTemporaryFile(
        prefix="freesearch-oauth-", suffix=".db", dir=Path.cwd(), delete=False
    ) as temporary_file:
        context.database_path = temporary_file.name
    context.repository = context.loop.run_until_complete(
        SQLiteRepository.open(Path(context.database_path))
    )
    context.secret_store = _VaultDouble()
    context.app = create_app(
        [_OAuthStubAdapter()],
        repository=context.repository,
        secret_store=context.secret_store,
    )
    context.app.state.oauth_http_client = context.http_client
    # OAuth routes need the Admin role.
    _login_admin(context)


def _client(context: Any) -> TestClient:
    return TestClient(context.app)


def _start_flow(context: Any) -> None:
    with _client(context) as client:
        context.device_response = client.post(
            "/api/v1/providers/parallel/oauth/device-code", headers=context.auth_headers
        )
        context.device_body = context.device_response.json()


def _pair_bearer(context: Any) -> None:
    _start_flow(context)
    assert context.device_response.status_code == 200
    context.platform_stub.token_queue.append(context.platform_stub.token_success())
    with _client(context) as client:
        response = client.get(
            "/api/v1/providers/parallel/oauth/status", headers=context.auth_headers
        )
    assert response.status_code == 200
    assert response.json()["status"] == "ready"


@given("an offline Parallel OAuth API with stubbed platform responses")
def step_given_oauth_api(context: Any) -> None:
    _open_oauth_api(context)


@given("an offline Parallel OAuth API with a pending device flow")
def step_given_pending_flow(context: Any) -> None:
    _open_oauth_api(context)
    _start_flow(context)
    assert context.device_response.status_code == 200


@given("an offline Parallel OAuth API with an expired device code")
def step_given_expired_flow(context: Any) -> None:
    _open_oauth_api(context)
    _start_flow(context)
    assert context.device_response.status_code == 200
    payload = context.loop.run_until_complete(
        context.repository.get_runtime_setting(METADATA_RUNTIME_KEY)
    )
    assert isinstance(payload, dict)
    payload["device_expires_at"] = datetime(2020, 1, 1, tzinfo=UTC).isoformat()
    context.loop.run_until_complete(
        context.repository.set_runtime_setting(METADATA_RUNTIME_KEY, payload)
    )


@given("an offline Parallel OAuth API with a paired bearer")
def step_given_paired_bearer(context: Any) -> None:
    _open_oauth_api(context)
    _pair_bearer(context)


@when("I start the Parallel device flow")
def step_when_start_flow(context: Any) -> None:
    _start_flow(context)


@then("the device code response should carry the user code and verification URIs")
def step_then_device_shape(context: Any) -> None:
    assert context.device_response.status_code == 200
    body = context.device_body
    assert set(body) == {
        "provider",
        "user_code",
        "verification_uri",
        "verification_uri_complete",
        "expires_in",
        "interval",
    }
    assert body["provider"] == "parallel"
    assert body["user_code"] == "STUB-4821"
    assert body["verification_uri"].startswith("https://")
    assert isinstance(body["expires_in"], int) and body["expires_in"] >= 1
    assert isinstance(body["interval"], int) and body["interval"] >= 1


@then("the device code response should contain no token or device secret")
def step_then_device_no_secrets(context: Any) -> None:
    text = context.device_response.text
    assert context.platform_stub.device_code not in text
    assert "access_token" not in text
    assert "refresh_token" not in text


@when("I check the Parallel OAuth status")
def step_when_check_status(context: Any) -> None:
    context.token_calls_before = len(context.platform_stub.calls_to("/getServiceKeys/token"))
    with _client(context) as client:
        context.status_response = client.get(
            "/api/v1/providers/parallel/oauth/status", headers=context.auth_headers
        )
        context.status_body = context.status_response.json()


@then("the OAuth status should be pending with a positive expiry")
def step_then_status_pending(context: Any) -> None:
    assert context.status_response.status_code == 200
    assert context.status_body["provider"] == "parallel"
    assert context.status_body["status"] == "pending"
    assert isinstance(context.status_body["expires_in"], int)
    assert context.status_body["expires_in"] > 0


@when("the poll interval elapses")
def step_when_interval_elapses(context: Any) -> None:
    payload = context.loop.run_until_complete(
        context.repository.get_runtime_setting(METADATA_RUNTIME_KEY)
    )
    assert isinstance(payload, dict)
    payload["last_poll_at"] = "2020-01-01T00:00:00+00:00"
    context.loop.run_until_complete(
        context.repository.set_runtime_setting(METADATA_RUNTIME_KEY, payload)
    )


@when("the stubbed user approves the device code")
def step_when_approve(context: Any) -> None:
    context.platform_stub.token_queue.append(context.platform_stub.token_success())


@then("the OAuth status should be ready")
def step_then_status_ready(context: Any) -> None:
    assert context.status_response.status_code == 200
    assert context.status_body["status"] == "ready"
    assert isinstance(context.status_body["expires_in"], int)
    assert context.status_body["expires_in"] > 0


@then("each status check should have attempted at most one token call")
def step_then_bounded_poll(context: Any) -> None:
    made = len(context.platform_stub.calls_to("/getServiceKeys/token")) - context.token_calls_before
    assert made <= 1


@when("I check the Parallel OAuth status twice in quick succession")
def step_when_check_status_twice(context: Any) -> None:
    with _client(context) as client:
        first = client.get("/api/v1/providers/parallel/oauth/status", headers=context.auth_headers)
        second = client.get("/api/v1/providers/parallel/oauth/status", headers=context.auth_headers)
    context.status_response = second
    context.status_body = second.json()
    assert first.status_code == 200


@then("the token endpoint should have been called exactly once")
def step_then_token_called_once(context: Any) -> None:
    assert len(context.platform_stub.calls_to("/getServiceKeys/token")) == 1


@when("the stubbed user denies the device code")
def step_when_deny(context: Any) -> None:
    context.platform_stub.token_queue.append(httpx.Response(400, json={"error": "access_denied"}))


@then("the OAuth status should be denied")
def step_then_status_denied(context: Any) -> None:
    assert context.status_response.status_code == 200
    assert context.status_body["status"] == "denied"
    assert context.status_body["expires_in"] is None


@when("I check the Parallel OAuth status again")
def step_when_check_status_again(context: Any) -> None:
    context.token_calls_before = len(context.platform_stub.calls_to("/getServiceKeys/token"))
    with _client(context) as client:
        context.status_response = client.get(
            "/api/v1/providers/parallel/oauth/status", headers=context.auth_headers
        )
        context.status_body = context.status_response.json()


@then("the OAuth status should still be denied with no extra token call")
def step_then_denied_terminal(context: Any) -> None:
    assert context.status_body["status"] == "denied"
    made = len(context.platform_stub.calls_to("/getServiceKeys/token")) - context.token_calls_before
    assert made == 0


@then("the OAuth status should be expired")
def step_then_status_expired(context: Any) -> None:
    assert context.status_response.status_code == 200
    assert context.status_body["status"] == "expired"
    assert context.status_body["expires_in"] is None


def _run_bounded_poll(context: Any) -> None:
    set_oauth_test_seams(secret_store=context.secret_store, http_client=context.http_client)
    try:
        context.loop.run_until_complete(refresh_quotas(context.repository, []))
        context.quota_snapshot = context.loop.run_until_complete(
            context.repository.latest_quota("parallel")
        )
    finally:
        clear_oauth_test_seams()


@when("the bounded quota poll runs with credit {credit:d} cents and pending {pending:d} cents")
def step_when_bounded_poll(context: Any, credit: int, pending: int) -> None:
    context.platform_stub.balance_queue.append(
        httpx.Response(
            200,
            json={
                "org_id": "stub-org-1",
                "credit_balance_cents": credit,
                "pending_debit_balance_cents": pending,
                "will_invoice": False,
            },
        )
    )
    _run_bounded_poll(context)


@then("the Parallel latest quota should be AUTHORITATIVE USD {expected} with unknown limit")
def step_then_authoritative_snapshot(context: Any, expected: str) -> None:
    snapshot = context.quota_snapshot
    assert snapshot is not None
    assert snapshot.provider == "parallel"
    assert snapshot.source == "authoritative"
    assert snapshot.unit_kind == "USD"
    assert snapshot.display_unit == "USD"
    assert snapshot.limit is None
    assert isinstance(snapshot.remaining, Decimal)
    assert snapshot.remaining == Decimal(expected)
    with _client(context) as client:
        dashboard = client.get("/dashboard", headers=context.auth_headers)
    assert dashboard.status_code == 200
    entries = [item for item in dashboard.json()["latest_quota"] if item["provider"] == "parallel"]
    assert len(entries) == 1
    assert entries[0]["source"] == "authoritative"
    assert Decimal(str(entries[0]["remaining"])) == Decimal(expected)


@when(
    "the bounded quota poll runs with credit {credit:d} cents and pending {pending:d} "
    "cents invoiced {invoiced:w}"
)
def step_when_bounded_poll_outline(context: Any, credit: int, pending: int, invoiced: str) -> None:
    context.platform_stub.balance_queue.append(
        httpx.Response(
            200,
            json={
                "org_id": "stub-org-1",
                "credit_balance_cents": credit,
                "pending_debit_balance_cents": pending,
                "will_invoice": invoiced == "true",
            },
        )
    )
    _run_bounded_poll(context)


@then('the Parallel balance outcome should be "{outcome}"')
def step_then_balance_outcome(context: Any, outcome: str) -> None:
    snapshot = context.quota_snapshot
    if outcome == "neutralized UNKNOWN":
        # An invoiced org exposes no prepaid balance, so the vendor body yields
        # no AUTHORITATIVE snapshot and the previously authoritative display is
        # neutralized to an ESTIMATED-unknown tombstone: the documented
        # invoice switch path, not a missing row.
        assert snapshot is not None, "an invoiced poll must tombstone, not vanish"
        assert snapshot.provider == "parallel"
        assert snapshot.source == "estimated", (
            "invoice switch must drop the authoritative claim: " + repr(snapshot)
        )
        assert snapshot.unit_kind == "USD"
        assert snapshot.display_unit == "USD"
        assert snapshot.remaining is None, "neutralized remaining must be unknown: " + (
            repr(snapshot)
        )
        assert snapshot.limit is None, "neutralized limit must be unknown: " + repr(snapshot)
        with _client(context) as client:
            dashboard = client.get("/dashboard", headers=context.auth_headers)
        assert dashboard.status_code == 200
        entries = [
            item for item in dashboard.json()["latest_quota"] if item["provider"] == "parallel"
        ]
        assert len(entries) == 1
        assert entries[0]["source"] != "authoritative", repr(entries)
        assert entries[0]["remaining"] is None, "dashboard must not quote stale funds"
        return
    assert outcome.startswith("USD ")
    assert snapshot is not None
    assert snapshot.provider == "parallel"
    assert snapshot.source == "authoritative", repr(snapshot)
    assert snapshot.limit is None, "balance is remaining-only"
    assert snapshot.remaining == Decimal(outcome.removeprefix("USD "))


@when("the bounded quota poll runs with a rejected bearer")
def step_when_rejected_bearer(context: Any) -> None:
    context.platform_stub.balance_queue.append(httpx.Response(401, json={"error": "denied"}))
    context.balance_calls_before = len(context.platform_stub.calls_to(_BALANCE_PATH))
    _run_bounded_poll(context)


@then("the OAuth status should be unpaired")
def step_then_status_unpaired(context: Any) -> None:
    with _client(context) as client:
        response = client.get(
            "/api/v1/providers/parallel/oauth/status", headers=context.auth_headers
        )
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"provider", "status", "expires_in"}
    assert body["provider"] == "parallel"
    assert body["status"] == "unpaired"
    assert body["expires_in"] is None
    assert context.secret_store.get("parallel:oauth:access") is None
    assert context.secret_store.get("parallel:oauth:refresh") is None


@when("the bounded quota poll runs again immediately")
def step_when_poll_again(context: Any) -> None:
    context.balance_calls_before = len(context.platform_stub.calls_to(_BALANCE_PATH))
    _run_bounded_poll(context)


@then("no extra balance call should have been made")
def step_then_no_extra_balance_call(context: Any) -> None:
    made = len(context.platform_stub.calls_to(_BALANCE_PATH)) - context.balance_calls_before
    assert made == 0


@when("I start the Parallel device flow again")
def step_when_start_flow_again(context: Any) -> None:
    context.vendor_calls_before = len(context.platform_stub.calls)
    with _client(context) as client:
        context.conflict_response = client.post(
            "/api/v1/providers/parallel/oauth/device-code", headers=context.auth_headers
        )


@then("the device flow should conflict with 409 and the bearer should survive")
def step_then_conflict(context: Any) -> None:
    assert context.conflict_response.status_code == 409
    assert len(context.platform_stub.calls) == context.vendor_calls_before
    with _client(context) as client:
        status = client.get("/api/v1/providers/parallel/oauth/status", headers=context.auth_headers)
    assert status.json()["status"] == "ready"


@when("I disconnect the Parallel OAuth pairing")
def step_when_disconnect(context: Any) -> None:
    with _client(context) as client:
        context.disconnect_response = client.delete(
            "/api/v1/providers/parallel/oauth", headers=context.auth_headers
        )


@then("the revocation should precede the deletion and the status should be unpaired")
def step_then_revoke_before_delete(context: Any) -> None:
    assert context.disconnect_response.status_code == 204
    revoke_calls = context.platform_stub.calls_to("/getServiceKeys/token/revoke")
    revoke_paths = [call.url.path for call in revoke_calls]
    assert len(revoke_paths) == 2
    for call in revoke_calls:
        assert "application/x-www-form-urlencoded" in call.headers.get("content-type", "")
        assert "refresh_token=" in call.content.decode()
    assert context.secret_store.get("parallel:oauth:access") is None
    assert context.secret_store.get("parallel:oauth:refresh") is None
    assert context.secret_store.get("parallel:oauth:device") is None
    with _client(context) as client:
        response = client.get(
            "/api/v1/providers/parallel/oauth/status", headers=context.auth_headers
        )
    assert response.json()["status"] == "unpaired"


@when("I disconnect the Parallel OAuth pairing again")
def step_when_disconnect_again(context: Any) -> None:
    with _client(context) as client:
        context.disconnect_response = client.delete(
            "/api/v1/providers/parallel/oauth", headers=context.auth_headers
        )


@then("the disconnect should still return 204")
def step_then_disconnect_idempotent(context: Any) -> None:
    assert context.disconnect_response.status_code == 204


@when('I start the device flow for "{provider_id}"')
def step_when_start_flow_for(context: Any, provider_id: str) -> None:
    with _client(context) as client:
        context.oauth_error_response = client.post(
            f"/api/v1/providers/{provider_id}/oauth/device-code",
            headers=context.auth_headers,
        )


@then("the OAuth response should be 404 oauth-not-supported")
def step_then_oauth_not_supported(context: Any) -> None:
    assert context.oauth_error_response.status_code == 404
    assert "oauth-not-supported" in context.oauth_error_response.text


@when('I check the OAuth status for "{provider_id}"')
def step_when_check_status_for(context: Any, provider_id: str) -> None:
    with _client(context) as client:
        context.oauth_error_response = client.get(
            f"/api/v1/providers/{provider_id}/oauth/status", headers=context.auth_headers
        )


@then("the OAuth response should be 404 unknown provider")
def step_then_unknown_provider(context: Any) -> None:
    assert context.oauth_error_response.status_code == 404
