"""Unit tests for the Parallel OAuth device flow, vault, and balance poll.

All HTTP is stubbed with httpx.MockTransport; no live network, no real bearer
material (every token below is a synthetic stub value), and repositories are
workspace-local temp files mirroring the manual-quota suite.
"""

from __future__ import annotations

import asyncio
import gc
import json
import time
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl

import httpx
import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from pydantic import SecretStr, ValidationError

from freesearch.models.contracts import QuotaSnapshot, QuotaSource, UnitKind, UsageOperation
from freesearch.models.users import UserRole
from freesearch.persistence.storage import SQLiteRepository
from freesearch.routers.api import create_app
from freesearch.services.monitoring import _record_adapter_quota, refresh_quotas
from freesearch.services.parallel_oauth import (
    ACCESS_SECRET_KEY,
    DEVICE_SECRET_KEY,
    METADATA_RUNTIME_KEY,
    REFRESH_SECRET_KEY,
    BalancePayload,
    DeviceAccessDenied,
    DeviceAuthorizationPending,
    DeviceCodeExpired,
    DeviceCodeResponse,
    DeviceSlowDown,
    OAuthMetadata,
    OAuthStatusResponse,
    OAuthUnpaired,
    ParallelOAuthClient,
    ParallelOAuthError,
    balance_to_snapshot,
    clear_oauth_poll_state,
    clear_oauth_test_seams,
    disconnect_oauth,
    is_oauth_ready,
    poll_oauth_balance_snapshot,
    query_oauth_status,
    set_oauth_test_seams,
    start_device_flow,
)
from tests.fixtures.auth import raw_auth_headers, register_promote_login, temp_email

FIXED_NOW = datetime(2026, 9, 10, 12, 0, 0, tzinfo=UTC)


class AsyncVaultDouble:
    """Inline async dict double for the encrypted-DB vault (no keyring shim)."""

    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    async def get(self, name: str) -> str | None:
        return self.values.get(name)

    async def set(self, name: str, value: str) -> None:
        self.values[name] = value

    async def delete(self, name: str) -> None:
        self.values.pop(name, None)


@pytest_asyncio.fixture(autouse=True)
async def _clean_oauth_state():  # type: ignore[no-untyped-def]
    clear_oauth_test_seams()
    clear_oauth_poll_state()
    yield
    clear_oauth_test_seams()
    clear_oauth_poll_state()


def _unlink_with_retries(path: Path, *, attempts: int = 20) -> None:
    """Remove a test database after Windows releases delayed SQLite handles."""

    for attempt in range(attempts):
        try:
            path.unlink()
        except FileNotFoundError:
            return
        except PermissionError:
            if attempt == attempts - 1:
                raise
            gc.collect()
            time.sleep(0.05)
        else:
            return


@pytest_asyncio.fixture
async def repository(tmp_path: Path):  # type: ignore[no-untyped-def]
    path = tmp_path / "parallel-oauth.db"
    repo = await SQLiteRepository.open(path)
    try:
        yield repo
    finally:
        await repo.close()
        _unlink_with_retries(path)
        _unlink_with_retries(Path(str(path) + ".migration.lock"))


class _StubPlatform:
    """Programmable platform/account stub with full call history."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.token_queue: list[httpx.Response] = []
        self.balance_queue: list[httpx.Response] = []
        self.register_payload: dict[str, Any] = {"client_id": "stub-client-1"}
        self.device_payload: dict[str, Any] = {
            "device_code": "stub-device-code-1",
            "user_code": "STUB-4821",
            "verification_uri": "https://platform.test/activate",
            "verification_uri_complete": "https://platform.test/activate?code=STUB-4821",
            "expires_in": 1800,
            "interval": 5,
        }

    def __call__(self, request: httpx.Request) -> httpx.Response:
        assert "access_token" not in (request.url.query or "")
        assert "device_code" not in (request.url.query or "")
        self.requests.append(request)
        path = request.url.path
        if path == "/getServiceKeys/register":
            return httpx.Response(200, json=self.register_payload)
        if path == "/getServiceKeys/device/code":
            return httpx.Response(200, json=self.device_payload)
        if path == "/getServiceKeys/token":
            if self.token_queue:
                return self.token_queue.pop(0)
            return httpx.Response(400, json={"error": "authorization_pending"})
        if path == "/getServiceKeys/token/revoke":
            return httpx.Response(200, json={})
        if path == "/account/service/v1/balance":
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
        raise AssertionError("unexpected stub path: " + path)

    def calls_to(self, path: str) -> list[httpx.Request]:
        return [request for request in self.requests if request.url.path == path]

    @staticmethod
    def token_success(
        access: str = "stub-access-token-1",
        refresh: str = "stub-refresh-token-1",
        expires_in: int = 3600,
    ) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "access_token": access,
                "refresh_token": refresh,
                "expires_in": expires_in,
                "token_type": "Bearer",
            },
        )


def _client_for(stub: _StubPlatform) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(stub), timeout=30.0)


def _balance(credit: int, pending: int, invoiced: bool = False) -> BalancePayload:
    return BalancePayload(
        org_id="stub-org-1",
        credit_balance_cents=credit,
        pending_debit_balance_cents=pending,
        will_invoice=invoiced,
    )


# --- balance mapping: Decimal-exact, invoiced, clamped ---


def test_balance_maps_cents_to_exact_usd() -> None:
    snapshot = balance_to_snapshot(_balance(1250, 250), observed_at=FIXED_NOW)
    assert snapshot is not None
    assert snapshot.provider == "parallel"
    assert snapshot.source is QuotaSource.AUTHORITATIVE
    assert snapshot.unit_kind is UnitKind.USD
    assert snapshot.display_unit == "USD"
    assert snapshot.limit is None
    assert isinstance(snapshot.remaining, Decimal)
    assert snapshot.remaining == Decimal("10.00")
    assert not isinstance(snapshot.remaining, float)


def test_balance_single_cent_is_exact() -> None:
    snapshot = balance_to_snapshot(_balance(1, 0), observed_at=FIXED_NOW)
    assert snapshot is not None
    assert snapshot.remaining == Decimal("0.01")


def test_balance_over_pending_clamps_to_zero() -> None:
    snapshot = balance_to_snapshot(_balance(100, 500), observed_at=FIXED_NOW)
    assert snapshot is not None
    assert snapshot.remaining == Decimal("0")


def test_balance_will_invoice_maps_to_none() -> None:
    assert balance_to_snapshot(_balance(9999, 0, invoiced=True), observed_at=FIXED_NOW) is None


def test_balance_payload_rejects_fractional_bool_and_negative_cents() -> None:
    with pytest.raises(ValidationError):
        BalancePayload(
            org_id="stub-org-1",
            credit_balance_cents=12.5,  # type: ignore[arg-type]
            pending_debit_balance_cents=0,
            will_invoice=False,
        )
    with pytest.raises(ValidationError):
        BalancePayload(
            org_id="stub-org-1",
            credit_balance_cents=True,  # type: ignore[arg-type]
            pending_debit_balance_cents=0,
            will_invoice=False,
        )
    with pytest.raises(ValidationError):
        BalancePayload(
            org_id="stub-org-1",
            credit_balance_cents=-1,
            pending_debit_balance_cents=0,
            will_invoice=False,
        )
    with pytest.raises(ValidationError):
        BalancePayload(
            org_id="stub-org-1",
            credit_balance_cents=-5.0,  # type: ignore[arg-type]
            pending_debit_balance_cents=0,
            will_invoice=False,
        )


def test_balance_payload_accepts_integral_float_cents_exactly() -> None:
    """The wire schema types cents as JSON numbers; 1250.0 must map exactly."""

    payload = BalancePayload(
        org_id="stub-org-1",
        credit_balance_cents=1250.0,  # type: ignore[arg-type]
        pending_debit_balance_cents=250.0,  # type: ignore[arg-type]
        will_invoice=False,
    )
    assert payload.credit_balance_cents == 1250
    assert isinstance(payload.credit_balance_cents, int)
    assert not isinstance(payload.credit_balance_cents, float)
    snapshot = balance_to_snapshot(payload, observed_at=FIXED_NOW)
    assert snapshot is not None
    assert snapshot.remaining == Decimal("10.00")
    assert isinstance(snapshot.remaining, Decimal)


def test_balance_payload_forbids_extra_fields() -> None:
    with pytest.raises(ValidationError):
        BalancePayload.model_validate(
            {
                "org_id": "stub-org-1",
                "credit_balance_cents": 1,
                "pending_debit_balance_cents": 0,
                "will_invoice": False,
                "access_token": "must-never-fit",
            }
        )


def test_oauth_contract_models_forbid_extra_fields() -> None:
    with pytest.raises(ValidationError):
        DeviceCodeResponse.model_validate(
            {
                "provider": "parallel",
                "user_code": "STUB-1",
                "verification_uri": "https://platform.test/activate",
                "verification_uri_complete": None,
                "expires_in": 1800,
                "interval": 5,
                "device_code": "must-never-fit",
            }
        )
    with pytest.raises(ValidationError):
        OAuthStatusResponse.model_validate(
            {"provider": "parallel", "status": "ready", "expires_in": 10, "token": "nope"}
        )
    with pytest.raises(ValidationError):
        OAuthStatusResponse.model_validate(
            {"provider": "parallel", "status": "nope", "expires_in": None}
        )


# --- device-flow client edges ---


async def test_client_poll_maps_terminal_and_transient_errors() -> None:
    stub = _StubPlatform()
    stub.token_queue.extend(
        [
            httpx.Response(400, json={"error": "authorization_pending"}),
            httpx.Response(400, json={"error": "slow_down"}),
            httpx.Response(400, json={"error": "access_denied"}),
            httpx.Response(400, json={"error": "expired_token"}),
            httpx.Response(400, json={"error": "weird_future_code"}),
            httpx.Response(500, json={"error": "server"}),
        ]
    )
    caller = _client_for(stub)
    try:
        oauth = ParallelOAuthClient(caller, platform_base_url="https://platform.test")
        device = SecretStr("stub-device-code-1")
        with pytest.raises(DeviceAuthorizationPending):
            await oauth.poll_token("stub-client-1", device)
        with pytest.raises(DeviceSlowDown):
            await oauth.poll_token("stub-client-1", device)
        with pytest.raises(DeviceAccessDenied):
            await oauth.poll_token("stub-client-1", device)
        with pytest.raises(DeviceCodeExpired):
            await oauth.poll_token("stub-client-1", device)
        with pytest.raises(ParallelOAuthError):
            await oauth.poll_token("stub-client-1", device)
        with pytest.raises(ParallelOAuthError):
            await oauth.poll_token("stub-client-1", device)
    finally:
        await caller.aclose()


async def test_client_poll_success_shape() -> None:
    stub = _StubPlatform()
    stub.token_queue.append(_StubPlatform.token_success())
    caller = _client_for(stub)
    try:
        oauth = ParallelOAuthClient(caller, platform_base_url="https://platform.test")
        grant = await oauth.poll_token("stub-client-1", SecretStr("stub-device-code-1"))
    finally:
        await caller.aclose()
    assert grant.access_token.get_secret_value() == "stub-access-token-1"
    assert grant.refresh_token is not None
    assert grant.refresh_token.get_secret_value() == "stub-refresh-token-1"
    assert grant.expires_in == 3600


async def test_client_refresh_invalid_grant_unpairs() -> None:
    stub = _StubPlatform()
    stub.token_queue.append(httpx.Response(400, json={"error": "invalid_grant"}))
    caller = _client_for(stub)
    try:
        oauth = ParallelOAuthClient(caller, platform_base_url="https://platform.test")
        with pytest.raises(OAuthUnpaired):
            await oauth.refresh_access_token("stub-client-1", SecretStr("stub-refresh-1"))
    finally:
        await caller.aclose()


async def test_client_balance_uses_bearer_and_rejects_query_tokens() -> None:
    stub = _StubPlatform()
    caller = _client_for(stub)
    try:
        oauth = ParallelOAuthClient(
            caller,
            platform_base_url="https://platform.test",
            api_base_url="https://api.test",
        )
        payload = await oauth.get_balance(SecretStr("stub-access-token-9"))
    finally:
        await caller.aclose()
    assert payload.credit_balance_cents == 1250
    request = stub.calls_to("/account/service/v1/balance")[0]
    assert request.headers["authorization"] == "Bearer stub-access-token-9"
    assert not request.url.query


async def test_client_balance_401_maps_to_unpaired() -> None:
    stub = _StubPlatform()
    stub.balance_queue.append(httpx.Response(401, json={"error": "denied"}))
    caller = _client_for(stub)
    try:
        oauth = ParallelOAuthClient(
            caller,
            platform_base_url="https://platform.test",
            api_base_url="https://api.test",
        )
        with pytest.raises(OAuthUnpaired):
            await oauth.get_balance(SecretStr("stub-access-token-9"))
    finally:
        await caller.aclose()


async def test_client_revoke_never_raises() -> None:
    from pydantic import SecretStr

    def failing(request: httpx.Request) -> httpx.Response:
        raise AssertionError("revoke transport failed: " + str(request.url.path))

    caller = httpx.AsyncClient(transport=httpx.MockTransport(failing), timeout=30.0)
    try:
        oauth = ParallelOAuthClient(caller, platform_base_url="https://platform.test")
        await oauth.revoke_token(SecretStr("stub-access-token-1"), "access_token")
    finally:
        await caller.aclose()


async def test_client_register_rejects_malformed_body() -> None:
    stub = _StubPlatform()
    stub.register_payload = {"wrong": "shape"}
    caller = _client_for(stub)
    try:
        oauth = ParallelOAuthClient(caller, platform_base_url="https://platform.test")
        with pytest.raises(ParallelOAuthError):
            await oauth.register_client()
    finally:
        await caller.aclose()


async def test_client_uses_spec_paths_and_encodings() -> None:
    """Upstream calls match the Account API docs: paths, JSON vs form bodies."""

    stub = _StubPlatform()
    stub.token_queue.append(_StubPlatform.token_success())
    stub.token_queue.append(_StubPlatform.token_success())
    caller = _client_for(stub)
    try:
        oauth = ParallelOAuthClient(caller, platform_base_url="https://platform.test")
        client_id, _ = await oauth.register_client()
        await oauth.request_device_code(client_id)
        await oauth.poll_token(client_id, SecretStr("stub-device-code-1"))
        await oauth.refresh_access_token(client_id, SecretStr("stub-refresh-1"))
        await oauth.revoke_token(SecretStr("stub-refresh-1"), "refresh_token")
    finally:
        await caller.aclose()
    register = stub.calls_to("/getServiceKeys/register")[0]
    assert "application/json" in register.headers.get("content-type", "")
    register_body = json.loads(register.content.decode())
    assert register_body["client_name"] == "freesearch"
    assert set(register_body["platform"]) == {
        "machine",
        "os_name",
        "processor",
        "release",
        "system",
        "version",
    }
    assert all(isinstance(value, str) and value for value in register_body["platform"].values())
    assert stub.calls_to("/oauth/register") == []
    device = stub.calls_to("/getServiceKeys/device/code")[0]
    assert "application/x-www-form-urlencoded" in device.headers.get("content-type", "")
    device_form = dict(parse_qsl(device.content.decode()))
    assert device_form == {"client_id": "stub-client-1", "scope": "balance:read"}
    polls = stub.calls_to("/getServiceKeys/token")
    assert len(polls) == 2
    for call in polls:
        assert "application/x-www-form-urlencoded" in call.headers.get("content-type", "")
    poll_form = dict(parse_qsl(polls[0].content.decode()))
    assert poll_form["grant_type"] == "urn:ietf:params:oauth:grant-type:device_code"
    assert poll_form["device_code"] == "stub-device-code-1"
    assert poll_form["client_id"] == "stub-client-1"
    refresh_form = dict(parse_qsl(polls[1].content.decode()))
    assert refresh_form["grant_type"] == "refresh_token"
    assert refresh_form["refresh_token"] == "stub-refresh-1"
    revoke = stub.calls_to("/getServiceKeys/token/revoke")[0]
    assert "application/x-www-form-urlencoded" in revoke.headers.get("content-type", "")
    revoke_form = dict(parse_qsl(revoke.content.decode()))
    assert revoke_form == {"refresh_token": "stub-refresh-1"}


# --- vault service: start / status / disconnect ---


async def test_start_device_flow_persists_only_public_metadata(
    repository: SQLiteRepository,
) -> None:
    stub = _StubPlatform()
    store = AsyncVaultDouble()
    caller = _client_for(stub)
    try:
        response = await start_device_flow(
            secret_store=store,
            repository=repository,
            http_client=caller,
            platform_base_url="https://platform.test",
            api_base_url="https://api.test",
            now=FIXED_NOW,
        )
    finally:
        await caller.aclose()
    assert response.provider == "parallel"
    assert response.user_code == "STUB-4821"
    assert response.expires_in == 1800
    assert response.interval == 5
    assert await store.get(DEVICE_SECRET_KEY) == "stub-device-code-1"
    assert await store.get(ACCESS_SECRET_KEY) is None
    assert await store.get(REFRESH_SECRET_KEY) is None
    payload = await repository.get_runtime_setting(METADATA_RUNTIME_KEY)
    assert isinstance(payload, dict)
    assert payload["status"] == "pending"
    assert payload["client_id"] == "stub-client-1"
    encoded = str(payload)
    assert "stub-device-code-1" not in encoded


async def test_status_pending_then_ready_with_bounded_attempts(
    repository: SQLiteRepository,
) -> None:
    stub = _StubPlatform()
    store = AsyncVaultDouble()
    caller = _client_for(stub)
    try:
        await start_device_flow(
            secret_store=store,
            repository=repository,
            http_client=caller,
            platform_base_url="https://platform.test",
            api_base_url="https://api.test",
            now=FIXED_NOW,
        )
        pending = await query_oauth_status(
            secret_store=store,
            repository=repository,
            http_client=caller,
            platform_base_url="https://platform.test",
            api_base_url="https://api.test",
            now=FIXED_NOW,
        )
        assert pending.status == "pending"
        assert pending.expires_in == 1800
        assert len(stub.calls_to("/getServiceKeys/token")) == 1
        stub.token_queue.append(_StubPlatform.token_success())
        fresh = await query_oauth_status(
            secret_store=store,
            repository=repository,
            http_client=caller,
            platform_base_url="https://platform.test",
            api_base_url="https://api.test",
            now=FIXED_NOW + timedelta(seconds=10),
        )
        assert fresh.status == "ready"
        assert fresh.expires_in == 3600
        assert len(stub.calls_to("/getServiceKeys/token")) == 2
        assert await store.get(ACCESS_SECRET_KEY) == "stub-access-token-1"
        assert await store.get(DEVICE_SECRET_KEY) is None
        assert await is_oauth_ready(repository) is True
        again = await query_oauth_status(
            secret_store=store,
            repository=repository,
            http_client=caller,
            platform_base_url="https://platform.test",
            api_base_url="https://api.test",
            now=FIXED_NOW + timedelta(seconds=11),
        )
        assert again.status == "ready"
        assert len(stub.calls_to("/getServiceKeys/token")) == 2
    finally:
        await caller.aclose()


async def test_status_denied_is_terminal(repository: SQLiteRepository) -> None:
    stub = _StubPlatform()
    store = AsyncVaultDouble()
    caller = _client_for(stub)
    try:
        await start_device_flow(
            secret_store=store,
            repository=repository,
            http_client=caller,
            platform_base_url="https://platform.test",
            api_base_url="https://api.test",
            now=FIXED_NOW,
        )
        stub.token_queue.append(httpx.Response(400, json={"error": "access_denied"}))
        denied = await query_oauth_status(
            secret_store=store,
            repository=repository,
            http_client=caller,
            platform_base_url="https://platform.test",
            api_base_url="https://api.test",
            now=FIXED_NOW + timedelta(seconds=10),
        )
        assert denied.status == "denied"
        assert denied.expires_in is None
        calls = len(stub.calls_to("/getServiceKeys/token"))
        repeat = await query_oauth_status(
            secret_store=store,
            repository=repository,
            http_client=caller,
            platform_base_url="https://platform.test",
            api_base_url="https://api.test",
            now=FIXED_NOW + timedelta(seconds=11),
        )
        assert repeat.status == "denied"
        assert len(stub.calls_to("/getServiceKeys/token")) == calls
    finally:
        await caller.aclose()


async def test_disconnect_revokes_before_deleting_and_is_idempotent(
    repository: SQLiteRepository,
) -> None:
    stub = _StubPlatform()
    store = AsyncVaultDouble()
    caller = _client_for(stub)
    try:
        await start_device_flow(
            secret_store=store,
            repository=repository,
            http_client=caller,
            platform_base_url="https://platform.test",
            api_base_url="https://api.test",
            now=FIXED_NOW,
        )
        stub.token_queue.append(_StubPlatform.token_success())
        ready = await query_oauth_status(
            secret_store=store,
            repository=repository,
            http_client=caller,
            platform_base_url="https://platform.test",
            api_base_url="https://api.test",
            now=FIXED_NOW + timedelta(seconds=10),
        )
        assert ready.status == "ready"
        await disconnect_oauth(
            secret_store=store,
            repository=repository,
            http_client=caller,
            platform_base_url="https://platform.test",
            api_base_url="https://api.test",
        )
        revoke_calls = stub.calls_to("/getServiceKeys/token/revoke")
        assert len(revoke_calls) == 2
        for call in revoke_calls:
            assert "application/x-www-form-urlencoded" in call.headers.get("content-type", "")
        revoke_bodies = [call.content.decode() for call in revoke_calls]
        assert "stub-access-token-1" in revoke_bodies[0]
        assert "stub-refresh-token-1" in revoke_bodies[1]
        assert "token_type_hint" not in revoke_bodies[0]
        assert "token_type_hint" not in revoke_bodies[1]
        assert dict(parse_qsl(revoke_bodies[0])).get("refresh_token") == "stub-access-token-1"
        assert dict(parse_qsl(revoke_bodies[1])).get("refresh_token") == "stub-refresh-token-1"
        assert await store.get(ACCESS_SECRET_KEY) is None
        assert await store.get(REFRESH_SECRET_KEY) is None
        assert await store.get(DEVICE_SECRET_KEY) is None
        assert await is_oauth_ready(repository) is False
        await disconnect_oauth(
            secret_store=store,
            repository=repository,
            http_client=caller,
            platform_base_url="https://platform.test",
            api_base_url="https://api.test",
        )
    finally:
        await caller.aclose()


# --- refresh skew and single-flight ---


async def _seed_ready_pair(
    store: AsyncVaultDouble,
    repository: SQLiteRepository,
    *,
    access_expires_in: int,
    now: datetime = FIXED_NOW,
) -> None:
    await store.set(ACCESS_SECRET_KEY, "stub-access-token-1")
    await store.set(REFRESH_SECRET_KEY, "stub-refresh-token-1")
    await repository.set_runtime_setting(
        METADATA_RUNTIME_KEY,
        OAuthMetadata(
            client_id="stub-client-1",
            scope="balance:read",
            status="ready",
            access_expires_at=now + timedelta(seconds=access_expires_in),
        ).model_dump(mode="json"),
    )


async def test_refresh_skew_avoids_network_when_fresh(
    repository: SQLiteRepository,
) -> None:
    stub = _StubPlatform()
    store = AsyncVaultDouble()
    await _seed_ready_pair(store, repository, access_expires_in=61)
    caller = _client_for(stub)
    try:
        status = await query_oauth_status(
            secret_store=store,
            repository=repository,
            http_client=caller,
            platform_base_url="https://platform.test",
            api_base_url="https://api.test",
            now=FIXED_NOW,
        )
    finally:
        await caller.aclose()
    assert status.status == "ready"
    assert status.expires_in == 61
    assert stub.calls_to("/getServiceKeys/token") == []


async def test_refresh_skew_triggers_one_refresh_at_boundary(
    repository: SQLiteRepository,
) -> None:
    stub = _StubPlatform()
    stub.token_queue.append(_StubPlatform.token_success(expires_in=3600))
    store = AsyncVaultDouble()
    await _seed_ready_pair(store, repository, access_expires_in=60)
    caller = _client_for(stub)
    try:
        status = await query_oauth_status(
            secret_store=store,
            repository=repository,
            http_client=caller,
            platform_base_url="https://platform.test",
            api_base_url="https://api.test",
            now=FIXED_NOW,
        )
    finally:
        await caller.aclose()
    assert status.status == "ready"
    assert status.expires_in == 3600
    assert len(stub.calls_to("/getServiceKeys/token")) == 1


async def test_concurrent_refresh_is_single_flight(
    repository: SQLiteRepository,
) -> None:
    stub = _StubPlatform()
    stub.token_queue.append(_StubPlatform.token_success(expires_in=3600))
    store = AsyncVaultDouble()
    await _seed_ready_pair(store, repository, access_expires_in=10)
    caller = _client_for(stub)
    try:
        first, second = await asyncio.gather(
            query_oauth_status(
                secret_store=store,
                repository=repository,
                http_client=caller,
                platform_base_url="https://platform.test",
                api_base_url="https://api.test",
                now=FIXED_NOW,
            ),
            query_oauth_status(
                secret_store=store,
                repository=repository,
                http_client=caller,
                platform_base_url="https://platform.test",
                api_base_url="https://api.test",
                now=FIXED_NOW,
            ),
        )
    finally:
        await caller.aclose()
    assert first.status == "ready"
    assert second.status == "ready"
    assert len(stub.calls_to("/getServiceKeys/token")) == 1


async def test_refresh_invalid_grant_unpairs_vault(
    repository: SQLiteRepository,
) -> None:
    stub = _StubPlatform()
    stub.token_queue.append(httpx.Response(400, json={"error": "invalid_grant"}))
    store = AsyncVaultDouble()
    await _seed_ready_pair(store, repository, access_expires_in=10)
    caller = _client_for(stub)
    try:
        status = await query_oauth_status(
            secret_store=store,
            repository=repository,
            http_client=caller,
            platform_base_url="https://platform.test",
            api_base_url="https://api.test",
            now=FIXED_NOW,
        )
    finally:
        await caller.aclose()
    assert status.status == "unpaired"
    assert await store.get(ACCESS_SECRET_KEY) is None
    assert await store.get(REFRESH_SECRET_KEY) is None


# --- bounded balance poll: TTL, backoff, 401 ---


async def test_balance_poll_records_authoritative_snapshot(
    repository: SQLiteRepository,
) -> None:
    stub = _StubPlatform()
    store = AsyncVaultDouble()
    await _seed_ready_pair(store, repository, access_expires_in=3600)
    caller = _client_for(stub)
    try:
        snapshot = await poll_oauth_balance_snapshot(
            repository,
            secret_store=store,
            http_client=caller,
            platform_base_url="https://platform.test",
            api_base_url="https://api.test",
            now=FIXED_NOW,
        )
        assert snapshot is not None
        assert snapshot.remaining == Decimal("10.00")
        repeat = await poll_oauth_balance_snapshot(
            repository,
            secret_store=store,
            http_client=caller,
            platform_base_url="https://platform.test",
            api_base_url="https://api.test",
            now=FIXED_NOW,
        )
        assert repeat is None
        assert len(stub.calls_to("/account/service/v1/balance")) == 1
    finally:
        await caller.aclose()


async def test_balance_poll_accepts_float_cents_from_wire(
    repository: SQLiteRepository,
) -> None:
    stub = _StubPlatform()
    stub.balance_queue.append(
        httpx.Response(
            200,
            json={
                "org_id": "stub-org-1",
                "credit_balance_cents": 1250.0,
                "pending_debit_balance_cents": 250.0,
                "will_invoice": False,
            },
        )
    )
    store = AsyncVaultDouble()
    await _seed_ready_pair(store, repository, access_expires_in=3600)
    caller = _client_for(stub)
    try:
        snapshot = await poll_oauth_balance_snapshot(
            repository,
            secret_store=store,
            http_client=caller,
            platform_base_url="https://platform.test",
            api_base_url="https://api.test",
            now=FIXED_NOW,
        )
    finally:
        await caller.aclose()
    assert snapshot is not None
    assert snapshot.source is QuotaSource.AUTHORITATIVE
    assert snapshot.remaining == Decimal("10.00")
    assert isinstance(snapshot.remaining, Decimal)


async def test_balance_poll_401_unpairs_and_backs_off(
    repository: SQLiteRepository,
) -> None:
    stub = _StubPlatform()
    stub.balance_queue.append(httpx.Response(401, json={"error": "denied"}))
    store = AsyncVaultDouble()
    await _seed_ready_pair(store, repository, access_expires_in=3600)
    caller = _client_for(stub)
    try:
        assert (
            await poll_oauth_balance_snapshot(
                repository,
                secret_store=store,
                http_client=caller,
                platform_base_url="https://platform.test",
                api_base_url="https://api.test",
                now=FIXED_NOW,
            )
            is None
        )
        assert await store.get(ACCESS_SECRET_KEY) is None
        assert await is_oauth_ready(repository) is False
        assert (
            await poll_oauth_balance_snapshot(
                repository,
                secret_store=store,
                http_client=caller,
                platform_base_url="https://platform.test",
                api_base_url="https://api.test",
                now=FIXED_NOW,
            )
            is None
        )
        assert len(stub.calls_to("/account/service/v1/balance")) == 1
    finally:
        await caller.aclose()


async def test_balance_poll_transient_failure_backs_off(
    repository: SQLiteRepository,
) -> None:
    stub = _StubPlatform()
    stub.balance_queue.append(httpx.Response(500, json={"error": "busy"}))
    store = AsyncVaultDouble()
    await _seed_ready_pair(store, repository, access_expires_in=3600)
    caller = _client_for(stub)
    try:
        assert (
            await poll_oauth_balance_snapshot(
                repository,
                secret_store=store,
                http_client=caller,
                platform_base_url="https://platform.test",
                api_base_url="https://api.test",
                now=FIXED_NOW,
            )
            is None
        )
        assert (
            await poll_oauth_balance_snapshot(
                repository,
                secret_store=store,
                http_client=caller,
                platform_base_url="https://platform.test",
                api_base_url="https://api.test",
                now=FIXED_NOW,
            )
            is None
        )
        assert len(stub.calls_to("/account/service/v1/balance")) == 1
        assert await is_oauth_ready(repository) is True
    finally:
        await caller.aclose()


async def test_balance_poll_skips_without_network_when_unpaired(
    repository: SQLiteRepository,
) -> None:
    def unreachable(request: httpx.Request) -> httpx.Response:
        raise AssertionError("no network while unpaired: " + str(request.url.path))

    caller = httpx.AsyncClient(transport=httpx.MockTransport(unreachable), timeout=30.0)
    try:
        assert (
            await poll_oauth_balance_snapshot(
                repository,
                secret_store=AsyncVaultDouble(),
                http_client=caller,
                now=FIXED_NOW,
            )
            is None
        )
    finally:
        await caller.aclose()


# --- precedence: balance wins over the seed ledger ---


class _SeedLedgerDouble:
    """Parallel stand-in exposing the seed-ledger quota_after_success seam."""

    name = "parallel"

    def quota_after_success(self, argument: object, *, operation: object = None) -> Any:
        del argument, operation
        return QuotaSnapshot(
            provider="parallel",
            source=QuotaSource.ESTIMATED,
            remaining=Decimal("3.75"),
            limit=Decimal("5.00"),
            unit_kind=UnitKind.USD,
            display_unit="USD",
            observed_at=FIXED_NOW,
        )


async def test_seed_ledger_suppressed_while_oauth_ready(
    repository: SQLiteRepository,
) -> None:
    store = AsyncVaultDouble()
    await _seed_ready_pair(store, repository, access_expires_in=3600)
    set_oauth_test_seams(secret_store=store)
    try:
        await _record_adapter_quota(
            repository,
            _SeedLedgerDouble(),  # type: ignore[arg-type]
            "quota_after_success",
            object(),
            operation=UsageOperation.SEARCH,
        )
        assert await repository.latest_quota("parallel") is None
    finally:
        clear_oauth_test_seams()


async def test_oauth_balance_flows_through_refresh_quotas(
    repository: SQLiteRepository,
) -> None:
    stub = _StubPlatform()
    store = AsyncVaultDouble()
    await _seed_ready_pair(store, repository, access_expires_in=3600)
    caller = _client_for(stub)
    set_oauth_test_seams(secret_store=store, http_client=caller)
    try:
        snapshots = await refresh_quotas(repository, [], now=FIXED_NOW)
    finally:
        clear_oauth_test_seams()
        await caller.aclose()
    assert [snapshot.provider for snapshot in snapshots] == ["parallel"]
    assert snapshots[0].source is QuotaSource.AUTHORITATIVE
    assert snapshots[0].remaining == Decimal("10.00")


# --- control routes: frozen contract ---


def _control_app(
    repository: SQLiteRepository, store: AsyncVaultDouble, stub: _StubPlatform
) -> TestClient:
    app = create_app([], repository=repository, secret_store=store)
    client = _client_for(stub)
    app.state.oauth_http_client = client
    return TestClient(app)


async def test_control_device_code_shape_and_presence(
    repository: SQLiteRepository,
    auth_secret: str,
) -> None:
    stub = _StubPlatform()
    store = AsyncVaultDouble()
    app = _control_app(repository, store, stub)
    with app as client:
        # Anonymous calls need a 401 challenge.
        anonymous = client.post("/api/v1/providers/parallel/oauth/device-code")
        assert anonymous.status_code == 401
        # Use one Admin account for the OAuth route.
        pair = await register_promote_login(
            client, repository, temp_email("oauth-admin"), UserRole.ADMIN
        )
        headers = raw_auth_headers(pair["access_token"])
        response = client.post("/api/v1/providers/parallel/oauth/device-code", headers=headers)
    assert response.status_code == 200
    assert set(response.json()) == {
        "provider",
        "user_code",
        "verification_uri",
        "verification_uri_complete",
        "expires_in",
        "interval",
    }
    assert "stub-device-code-1" not in response.text


async def test_control_status_shape_and_terminal_views(
    repository: SQLiteRepository,
    auth_secret: str,
) -> None:
    stub = _StubPlatform()
    store = AsyncVaultDouble()
    app = _control_app(repository, store, stub)
    with app as client:
        # Anonymous calls need a 401 challenge.
        anonymous = client.get("/api/v1/providers/parallel/oauth/status")
        assert anonymous.status_code == 401
        # Use one Admin account for the OAuth routes.
        pair = await register_promote_login(
            client, repository, temp_email("oauth-admin"), UserRole.ADMIN
        )
        headers = raw_auth_headers(pair["access_token"])
        assert client.get("/api/v1/providers/parallel/oauth/status", headers=headers).json() == {
            "provider": "parallel",
            "status": "unpaired",
            "expires_in": None,
        }
        assert (
            client.post("/api/v1/providers/parallel/oauth/device-code", headers=headers).status_code
            == 200
        )
        pending = client.get("/api/v1/providers/parallel/oauth/status", headers=headers).json()
        assert set(pending) == {"provider", "status", "expires_in"}
        assert pending["status"] == "pending"


async def test_control_rejects_other_and_unknown_providers(
    repository: SQLiteRepository,
    auth_secret: str,
) -> None:
    stub = _StubPlatform()
    store = AsyncVaultDouble()
    app = _control_app(repository, store, stub)
    with app as client:
        # Anonymous calls need a 401 challenge.
        anonymous = client.get("/api/v1/providers/exa/oauth/status")
        assert anonymous.status_code == 401
        # Use one Admin account for the OAuth routes.
        pair = await register_promote_login(
            client, repository, temp_email("oauth-admin"), UserRole.ADMIN
        )
        headers = raw_auth_headers(pair["access_token"])
        for method, path in (
            ("post", "/api/v1/providers/exa/oauth/device-code"),
            ("get", "/api/v1/providers/exa/oauth/status"),
            ("delete", "/api/v1/providers/exa/oauth"),
        ):
            response = client.request(method.upper(), path, headers=headers)
            assert response.status_code == 404
            assert "oauth-not-supported" in response.text
        ghost = client.get("/api/v1/providers/ghost/oauth/status", headers=headers)
        assert ghost.status_code == 404
    assert stub.requests == []


async def test_control_disconnect_is_idempotent_204(
    repository: SQLiteRepository,
    auth_secret: str,
) -> None:
    stub = _StubPlatform()
    store = AsyncVaultDouble()
    app = _control_app(repository, store, stub)
    with app as client:
        # Anonymous calls need a 401 challenge.
        anonymous = client.delete("/api/v1/providers/parallel/oauth")
        assert anonymous.status_code == 401
        # Use one Admin account for the OAuth route.
        pair = await register_promote_login(
            client, repository, temp_email("oauth-admin"), UserRole.ADMIN
        )
        headers = raw_auth_headers(pair["access_token"])
        assert client.delete("/api/v1/providers/parallel/oauth", headers=headers).status_code == 204
        assert client.delete("/api/v1/providers/parallel/oauth", headers=headers).status_code == 204


# --- round-2 rulings: 409 gate, invalid_grant expiry, tombstones ---


async def test_start_device_flow_conflicts_when_paired(
    repository: SQLiteRepository,
) -> None:
    from freesearch.services.parallel_oauth import OAuthAlreadyPaired

    stub = _StubPlatform()
    store = AsyncVaultDouble()
    caller = _client_for(stub)
    try:
        await start_device_flow(
            secret_store=store,
            repository=repository,
            http_client=caller,
            platform_base_url="https://platform.test",
            api_base_url="https://api.test",
            now=FIXED_NOW,
        )
        stub.token_queue.append(_StubPlatform.token_success())
        ready = await query_oauth_status(
            secret_store=store,
            repository=repository,
            http_client=caller,
            platform_base_url="https://platform.test",
            api_base_url="https://api.test",
            now=FIXED_NOW + timedelta(seconds=10),
        )
        assert ready.status == "ready"
        calls_before = len(stub.requests)
        with pytest.raises(OAuthAlreadyPaired):
            await start_device_flow(
                secret_store=store,
                repository=repository,
                http_client=caller,
                platform_base_url="https://platform.test",
                api_base_url="https://api.test",
                now=FIXED_NOW + timedelta(seconds=11),
            )
        assert len(stub.requests) == calls_before, "409 path must not touch the vendor"
        assert await store.get(ACCESS_SECRET_KEY) == "stub-access-token-1"
        assert await is_oauth_ready(repository) is True
    finally:
        await caller.aclose()


async def test_control_device_code_409_when_paired(
    repository: SQLiteRepository,
    auth_secret: str,
) -> None:
    stub = _StubPlatform()
    store = AsyncVaultDouble()
    app = _control_app(repository, store, stub)
    with app as client:
        # Anonymous calls need a 401 challenge.
        anonymous = client.post("/api/v1/providers/parallel/oauth/device-code")
        assert anonymous.status_code == 401
        # Use one Admin account for the OAuth routes.
        pair = await register_promote_login(
            client, repository, temp_email("oauth-admin"), UserRole.ADMIN
        )
        headers = raw_auth_headers(pair["access_token"])
        assert (
            client.post("/api/v1/providers/parallel/oauth/device-code", headers=headers).status_code
            == 200
        )
        stub.token_queue.append(_StubPlatform.token_success())
        status = client.get("/api/v1/providers/parallel/oauth/status", headers=headers)
        assert status.json()["status"] == "ready"
        conflict = client.post("/api/v1/providers/parallel/oauth/device-code", headers=headers)
        assert conflict.status_code == 409, conflict.text[:300]
        assert (
            client.get("/api/v1/providers/parallel/oauth/status", headers=headers).json()["status"]
            == "ready"
        )


async def test_device_invalid_grant_fails_closed_to_expired(
    repository: SQLiteRepository,
) -> None:
    stub = _StubPlatform()
    stub.token_queue.append(httpx.Response(400, json={"error": "invalid_grant"}))
    store = AsyncVaultDouble()
    caller = _client_for(stub)
    try:
        await start_device_flow(
            secret_store=store,
            repository=repository,
            http_client=caller,
            platform_base_url="https://platform.test",
            api_base_url="https://api.test",
            now=FIXED_NOW,
        )
        first = await query_oauth_status(
            secret_store=store,
            repository=repository,
            http_client=caller,
            platform_base_url="https://platform.test",
            api_base_url="https://api.test",
            now=FIXED_NOW + timedelta(seconds=10),
        )
        assert first.status == "expired"
        assert first.expires_in is None
        assert await store.get(DEVICE_SECRET_KEY) is None
        calls = len(stub.calls_to("/getServiceKeys/token"))
        second = await query_oauth_status(
            secret_store=store,
            repository=repository,
            http_client=caller,
            platform_base_url="https://platform.test",
            api_base_url="https://api.test",
            now=FIXED_NOW + timedelta(seconds=11),
        )
        assert second.status == "expired"
        assert len(stub.calls_to("/getServiceKeys/token")) == calls
    finally:
        await caller.aclose()


async def _record_authoritative(
    repository: SQLiteRepository, remaining: str, observed_at: datetime = FIXED_NOW
) -> None:
    await repository.record_quota(
        QuotaSnapshot(
            provider="parallel",
            source=QuotaSource.AUTHORITATIVE,
            remaining=Decimal(remaining),
            limit=None,
            unit_kind=UnitKind.USD,
            display_unit="USD",
            observed_at=observed_at,
        )
    )


async def test_will_invoice_tombstones_stale_authoritative(
    repository: SQLiteRepository,
) -> None:
    stub = _StubPlatform()
    stub.balance_queue.append(
        httpx.Response(
            200,
            json={
                "org_id": "stub-org-1",
                "credit_balance_cents": 5000,
                "pending_debit_balance_cents": 0,
                "will_invoice": True,
            },
        )
    )
    store = AsyncVaultDouble()
    await _seed_ready_pair(store, repository, access_expires_in=3600)
    await _record_authoritative(repository, "10.00")
    caller = _client_for(stub)
    try:
        assert (
            await poll_oauth_balance_snapshot(
                repository,
                secret_store=store,
                http_client=caller,
                platform_base_url="https://platform.test",
                api_base_url="https://api.test",
                now=FIXED_NOW,
            )
            is None
        )
        stored = await repository.latest_quota("parallel")
        assert stored is not None
        assert stored.source is QuotaSource.ESTIMATED
        assert stored.remaining is None
    finally:
        await caller.aclose()


async def test_balance_401_tombstones_stale_authoritative(
    repository: SQLiteRepository,
) -> None:
    stub = _StubPlatform()
    stub.balance_queue.append(httpx.Response(401, json={"error": "denied"}))
    store = AsyncVaultDouble()
    await _seed_ready_pair(store, repository, access_expires_in=3600)
    await _record_authoritative(repository, "10.00")
    caller = _client_for(stub)
    try:
        assert (
            await poll_oauth_balance_snapshot(
                repository,
                secret_store=store,
                http_client=caller,
                platform_base_url="https://platform.test",
                api_base_url="https://api.test",
                now=FIXED_NOW,
            )
            is None
        )
        stored = await repository.latest_quota("parallel")
        assert stored is not None
        assert stored.source is QuotaSource.ESTIMATED
        assert stored.remaining is None
        assert await is_oauth_ready(repository) is False
    finally:
        await caller.aclose()


async def test_disconnect_tombstones_stale_authoritative(
    repository: SQLiteRepository,
) -> None:
    stub = _StubPlatform()
    store = AsyncVaultDouble()
    await _seed_ready_pair(store, repository, access_expires_in=3600)
    await _record_authoritative(repository, "10.00")
    caller = _client_for(stub)
    try:
        await disconnect_oauth(
            secret_store=store,
            repository=repository,
            http_client=caller,
            platform_base_url="https://platform.test",
            api_base_url="https://api.test",
        )
        stored = await repository.latest_quota("parallel")
        assert stored is not None
        assert stored.source is QuotaSource.ESTIMATED
        assert stored.remaining is None
    finally:
        await caller.aclose()


# --- Vault-only AC-5: unbound preflight fails closed before vendor HTTP ------


async def test_unbound_store_resolves_fail_closed() -> None:
    """AC-5: _resolve_secret_store(None) with no seam is the unbound store."""

    from freesearch.services import parallel_oauth as oauth_module

    oauth_module.clear_oauth_test_seams()
    try:
        from pydantic import SecretStr as _SecretStr

        store = oauth_module._resolve_secret_store(None)
        assert type(store).__name__ == "_UnboundSecretStore"
        assert await oauth_module._store_get_secret(store, ACCESS_SECRET_KEY) is None
        with pytest.raises(RuntimeError):
            await oauth_module._store_set_secret(store, ACCESS_SECRET_KEY, _SecretStr("x"))
    finally:
        oauth_module.clear_oauth_test_seams()


async def test_start_device_flow_preflights_writable_store_before_vendor_http(
    repository: SQLiteRepository,
) -> None:
    """AC-5: unbound start_device_flow must fail before any vendor HTTP."""

    from freesearch.services import parallel_oauth as oauth_module

    oauth_module.clear_oauth_test_seams()
    stub = _StubPlatform()
    caller = _client_for(stub)
    try:
        require = getattr(oauth_module, "_require_writable_store", None)
        assert callable(require), (
            "RED (AC-5): parallel_oauth._require_writable_store must exist and be "
            "awaited at start_device_flow entry before vendor HTTP"
        )
        with pytest.raises(RuntimeError):
            await oauth_module.start_device_flow(
                secret_store=None,
                repository=repository,
                http_client=caller,
                platform_base_url="https://platform.test",
                api_base_url="https://api.test",
                now=FIXED_NOW,
            )
        assert stub.requests == [], (
            "RED (AC-5): unbound preflight must run before vendor HTTP; "
            f"got {len(stub.requests)} vendor calls"
        )
    finally:
        await caller.aclose()
        oauth_module.clear_oauth_test_seams()


async def test_clear_vault_deletes_four_slots_with_tombstones(
    repository: SQLiteRepository,
) -> None:
    """AC-5: _clear_vault deletes 4 slots; encrypted stores leave tombstones."""

    from freesearch.services import parallel_oauth as oauth_module

    store = AsyncVaultDouble()
    await store.set(ACCESS_SECRET_KEY, "stub-access-token-1")
    await store.set(REFRESH_SECRET_KEY, "stub-refresh-token-1")
    await store.set(DEVICE_SECRET_KEY, "stub-device-code-1")
    await store.set(oauth_module.CLIENT_SECRET_KEY, "stub-client-secret-1")

    await oauth_module._clear_vault(store, repository)

    assert await store.get(ACCESS_SECRET_KEY) is None
    assert await store.get(REFRESH_SECRET_KEY) is None
    assert await store.get(DEVICE_SECRET_KEY) is None
    assert await store.get(oauth_module.CLIENT_SECRET_KEY) is None


async def test_disconnect_unbound_returns_cleanly_without_vault_writes(
    repository: SQLiteRepository,
) -> None:
    stub = _StubPlatform()
    caller = _client_for(stub)
    try:
        assert (
            await disconnect_oauth(
                secret_store=None,
                repository=repository,
                http_client=caller,
                platform_base_url="https://platform.test",
                api_base_url="https://api.test",
            )
            is None
        )
        assert stub.requests == []
    finally:
        await caller.aclose()
