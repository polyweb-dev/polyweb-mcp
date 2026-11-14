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

from polyweb.models.contracts import QuotaSource, UnitKind
from polyweb.models.schema_enums import OAuthGrantStatus
from polyweb.persistence.storage import SQLiteRepository
from polyweb.routers.api import create_app
from polyweb.services.control_errors import ResourceConflict
from polyweb.services.monitoring import refresh_quotas
from polyweb.services.parallel_oauth import (
    BalancePayload,
    DeviceAccessDenied,
    DeviceAuthorizationPending,
    DeviceCodeExpired,
    DeviceSlowDown,
    OAuthUnpaired,
    ParallelOAuthClient,
    ParallelOAuthError,
    balance_to_snapshot,
)
from tests.fixtures.scoped_oauth import open_scoped_oauth
from tests.fixtures.vault_oauth import open_vault_oauth

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


@pytest.fixture(autouse=True)
def _configured_auth(auth_secret):
    """HTTP migrations use the real configured A1 bearer verifier."""
    return auth_secret


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
        await oauth.revoke_token(SecretStr("stub-access-token-1"))
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
        await oauth.revoke_token(SecretStr("stub-refresh-1"))
    finally:
        await caller.aclose()
    register = stub.calls_to("/getServiceKeys/register")[0]
    assert "application/json" in register.headers.get("content-type", "")
    register_body = json.loads(register.content.decode())
    assert register_body["client_name"] == "polyweb"
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


async def test_start_device_flow_persists_only_public_metadata(repository):
    """Origin singleton case: migrated to real A4 credential-scoped behavior."""
    case = await open_scoped_oauth(repository)
    try:
        view = await case.start()
        assert view.user_code and view.expires_in == 1800 and view.interval == 5
        assert "device_code" not in view.model_dump()
        assert await case.token("access") is None
        assert await case.token("refresh") is None
        assert await case.token("device") is not None
        await case.assert_no_leaks(view.model_dump_json())
    finally:
        await case.close()


async def test_status_pending_then_ready_with_bounded_attempts(repository):
    """Origin singleton case: migrated to real A4 credential-scoped behavior."""
    case = await open_scoped_oauth(repository)
    try:
        case.stub.poll_script = ["authorization_pending", "success"]
        await case.start()
        assert (await case.poll()).status is OAuthGrantStatus.PENDING
        assert case.stub.poll_calls == 1
        assert (await case.poll()).status is OAuthGrantStatus.PENDING
        assert case.stub.poll_calls == 1
        case.clock[0] += timedelta(seconds=case.stub.device_interval)
        assert (await case.poll()).status is OAuthGrantStatus.CONNECTED
        assert case.stub.poll_calls == 2
        for _ in range(3):
            assert (await case.status()).status is OAuthGrantStatus.CONNECTED
        assert case.stub.poll_calls == 2
        assert await case.token() is not None and await case.token("device") is None
    finally:
        await case.close()


async def test_status_denied_is_terminal(repository):
    """Origin singleton case: migrated to real A4 credential-scoped behavior."""
    case = await open_scoped_oauth(repository)
    try:
        case.stub.poll_script = ["access_denied"]
        await case.start()
        status = await case.poll()
        assert status.status is OAuthGrantStatus.DISCONNECTED
        assert status.last_error_code == "access_denied"
        for _ in range(3):
            assert (await case.poll()).status is OAuthGrantStatus.DISCONNECTED
        assert case.stub.poll_calls == 1
        assert not any((await case.slots()).values())
    finally:
        await case.close()


async def test_disconnect_revokes_before_deleting_and_is_idempotent(repository):
    """Origin singleton case: migrated to real A4 credential-scoped behavior."""
    case = await open_scoped_oauth(repository)
    try:
        await case.connect()
        old = await case.grant()
        await case.disconnect()
        # A4 fences and tombstones before best-effort revocation, preventing stale resurrection.
        assert case.stub.revoke_calls == 1
        assert not any((await case.slots()).values())
        assert (await case.status()).status is OAuthGrantStatus.DISCONNECTED
        await case.disconnect()
        assert case.stub.revoke_calls == 1
        assert (await case.grant()).token_generation > old.token_generation
    finally:
        await case.close()


async def test_refresh_skew_avoids_network_when_fresh(repository):
    """Origin singleton case: migrated to real A4 credential-scoped behavior."""
    case = await open_scoped_oauth(repository)
    try:
        await case.connect()
        for _ in range(5):
            assert (await case.status()).status is OAuthGrantStatus.CONNECTED
        assert case.stub.refresh_calls == 0
        assert case.stub.balance_calls == 0
    finally:
        await case.close()


async def test_refresh_skew_triggers_one_refresh_at_boundary(repository):
    """Origin singleton case: migrated to real A4 credential-scoped behavior."""
    case = await open_scoped_oauth(repository)
    try:
        await case.connect()
        await case.expire_access()
        status = await case.refresh()
        assert status.status is OAuthGrantStatus.CONNECTED
        assert case.stub.refresh_calls == 1
        assert await case.token() == "adv-access-TOKEN-0003"
    finally:
        await case.close()


async def test_concurrent_refresh_is_single_flight(repository):
    """Origin singleton case: migrated to real A4 credential-scoped behavior."""
    case = await open_scoped_oauth(repository)
    try:
        await case.connect()
        old = await case.grant()
        await case.expire_access()
        # Scoped A4 uses generation CAS rather than a process-global refresh lock.
        await asyncio.gather(case.refresh(), case.refresh())
        new = await case.grant()
        assert new.token_generation > old.token_generation
        assert await case.token() == "adv-access-TOKEN-0003"
        assert (await case.status()).status is OAuthGrantStatus.CONNECTED
        await case.assert_no_leaks()
    finally:
        await case.close()


async def test_refresh_invalid_grant_unpairs_vault(repository):
    """Origin singleton case: migrated to real A4 credential-scoped behavior."""
    case = await open_scoped_oauth(repository)
    try:
        await case.connect()
        case.stub.refresh_reject = "invalid_grant"
        assert (await case.refresh()).status is OAuthGrantStatus.REFRESH_FAILED
        assert not any((await case.slots()).values())
        await case.refresh()
        assert case.stub.refresh_calls == 1
    finally:
        await case.close()


async def test_balance_poll_records_authoritative_snapshot(repository):
    """Origin singleton case: migrated to real A4 credential-scoped behavior."""
    case = await open_scoped_oauth(repository)
    try:
        await case.connect()
        snapshot = await case.balance()
        assert snapshot.source is QuotaSource.AUTHORITATIVE
        assert snapshot.remaining == Decimal("10.00") and snapshot.limit is None
        assert snapshot.unit_kind is UnitKind.USD
        stored = await case.repository.latest_quota("parallel", credential_id=case.credential.id)
        assert stored == snapshot
        assert await case.repository.latest_quota("parallel") is None
    finally:
        await case.close()


async def test_balance_poll_accepts_float_cents_from_wire(repository):
    """Origin singleton case: migrated to real A4 credential-scoped behavior."""
    case = await open_scoped_oauth(repository)
    try:
        await case.connect()
        case.stub.balance_body_override = {
            "org_id": "fake",
            "credit_balance_cents": 1250.0,
            "pending_debit_balance_cents": 250.0,
            "will_invoice": False,
        }
        snapshot = await case.balance()
        assert snapshot.remaining == Decimal("10.00")
        assert isinstance(snapshot.remaining, Decimal)
    finally:
        await case.close()


async def test_balance_poll_transient_failure_backs_off(repository):
    """Origin singleton case: migrated to real A4 credential-scoped behavior."""
    case = await open_scoped_oauth(repository)
    try:
        await case.connect()
        case.stub.fail_balance_times = 1
        with pytest.raises(ParallelOAuthError):
            await case.balance()
        for _ in range(3):
            await case.status()
        assert case.stub.balance_calls == 1
        assert (await case.status()).status is OAuthGrantStatus.CONNECTED
        assert (
            await case.repository.latest_quota("parallel", credential_id=case.credential.id) is None
        )
    finally:
        await case.close()


async def test_balance_poll_skips_without_network_when_unpaired(repository):
    """Origin singleton case: migrated to real A4 credential-scoped behavior."""
    case = await open_scoped_oauth(repository)
    try:
        assert (await case.status()).status is OAuthGrantStatus.DISCONNECTED
        assert await case.token() is None
        assert case.stub.balance_calls == case.stub.poll_calls == case.stub.refresh_calls == 0
    finally:
        await case.close()


async def test_seed_ledger_suppressed_while_oauth_ready(repository):
    """Origin singleton case: migrated to real A4 credential-scoped behavior."""
    case = await open_scoped_oauth(repository)
    try:
        await case.connect()
        from polyweb.models.contracts import QuotaSnapshot

        await case.repository.record_quota(
            QuotaSnapshot(
                provider="parallel",
                source=QuotaSource.ESTIMATED,
                remaining=Decimal("999"),
                observed_at=case.clock[0],
            )
        )
        snapshot = await case.balance()
        assert snapshot.remaining == Decimal("10")
        assert (
            await case.repository.latest_quota("parallel", credential_id=case.credential.id)
        ).remaining == Decimal("10")
        assert (await case.repository.latest_quota("parallel")).remaining == Decimal("999")
    finally:
        await case.close()


async def test_oauth_balance_flows_through_refresh_quotas(repository):
    """Origin singleton case: migrated to real A4 credential-scoped behavior."""
    case = await open_scoped_oauth(repository)
    try:
        await case.connect()
        # Hidden singleton OAuth polling was removed: ordinary monitoring has no grant authority.
        assert await refresh_quotas(case.repository, []) == []
        assert case.stub.balance_calls == 0
        snapshot = await case.balance()
        assert snapshot.remaining == Decimal("10")
        await case.assert_no_leaks(snapshot.model_dump_json())
    finally:
        await case.close()


async def test_control_device_code_shape_and_presence(repository):
    """Origin singleton case: migrated to real A4 credential-scoped behavior."""
    case = await open_vault_oauth(repository)
    try:
        response = case.client.post(case.path + "/device", headers=case.headers)
        assert response.status_code == 200
        from polyweb.models.credentials import CredentialOAuthDeviceRead

        assert set(response.json()) == set(CredentialOAuthDeviceRead.model_fields)
        await case.assert_no_leaks(response)
    finally:
        await case.close()


async def test_control_status_shape_and_terminal_views(repository):
    """Origin singleton case: migrated to real A4 credential-scoped behavior."""
    case = await open_vault_oauth(repository)
    try:
        response = case.client.get(case.path, headers=case.headers)
        assert response.status_code == 200
        from polyweb.models.credentials import CredentialOAuthStatusRead

        assert set(response.json()) == set(CredentialOAuthStatusRead.model_fields)
        assert response.json()["status"] == "disconnected"
        await case.assert_no_leaks(response)
    finally:
        await case.close()


async def test_control_rejects_other_and_unknown_providers(repository):
    """Origin singleton case: migrated to real A4 credential-scoped behavior."""
    case = await open_scoped_oauth(repository)
    try:
        for provider in ("exa", "tavily", "unknown"):
            for method, suffix in (("post", "/device-code"), ("get", "/status"), ("delete", "")):
                response = getattr(case.client, method)(
                    f"/api/v1/providers/{provider}/oauth" + suffix, headers=case.headers
                )
                assert response.status_code == 404
        assert case.stub.register_calls == case.stub.poll_calls == 0
    finally:
        await case.close()


async def test_control_disconnect_is_idempotent_204(repository):
    """Origin singleton case: migrated to real A4 credential-scoped behavior."""
    case = await open_vault_oauth(repository)
    try:
        await case.connect()
        for _ in range(2):
            response = case.client.delete(case.path, headers=case.headers)
            assert response.status_code == 204
        assert case.stub.revoke_calls == 1
        assert not any((await case.slots()).values())
    finally:
        await case.close()


async def test_start_device_flow_conflicts_when_paired(repository):
    """Origin singleton case: migrated to real A4 credential-scoped behavior."""
    case = await open_scoped_oauth(repository)
    try:
        await case.connect()
        old = await case.token()
        with pytest.raises(ResourceConflict):
            await case.start()
        assert await case.token() == old
        assert case.stub.register_calls == 1
    finally:
        await case.close()


async def test_control_device_code_409_when_paired(repository):
    """Origin singleton case: migrated to real A4 credential-scoped behavior."""
    case = await open_vault_oauth(repository)
    try:
        await case.connect()
        response = case.client.post(case.path + "/device", headers=case.headers)
        assert response.status_code == 409
        assert response.json()["detail"]["code"] == "OAUTH_ALREADY_CONNECTED"
        assert case.stub.register_calls == 1
        await case.assert_no_leaks(response)
    finally:
        await case.close()


async def test_device_invalid_grant_fails_closed_to_expired(repository):
    """Origin singleton case: migrated to real A4 credential-scoped behavior."""
    case = await open_scoped_oauth(repository)
    try:
        case.stub.poll_script = ["invalid_grant"]
        await case.start()
        response = await case.poll()
        assert response.status is OAuthGrantStatus.DISCONNECTED
        assert response.last_error_code == "expired_token"
        assert not any((await case.slots()).values())
        await case.poll()
        assert case.stub.poll_calls == 1
    finally:
        await case.close()


async def test_will_invoice_tombstones_stale_authoritative(repository):
    """Origin singleton case: migrated to real A4 credential-scoped behavior."""
    case = await open_scoped_oauth(repository)
    try:
        await case.connect()
        first = await case.balance()
        case.stub.balance_will_invoice = True
        assert await case.balance() is None
        # Historical credential funds never become an unrelated provider balance.
        assert await case.repository.latest_quota("parallel") is None
        assert (
            await case.repository.latest_quota("parallel", credential_id=case.credential.id)
        ) == first
    finally:
        await case.close()


async def test_balance_401_tombstones_stale_authoritative(repository):
    """Origin singleton case: migrated to real A4 credential-scoped behavior."""
    case = await open_scoped_oauth(repository)
    try:
        await case.connect()
        await case.balance()
        case.stub.balance_status = 401
        with pytest.raises(OAuthUnpaired):
            await case.balance()
        await case.disconnect()
        assert (await case.status()).status is OAuthGrantStatus.DISCONNECTED
        assert await case.token() is None
        assert await case.repository.latest_quota("parallel") is None
    finally:
        await case.close()


async def test_disconnect_tombstones_stale_authoritative(repository):
    """Origin singleton case: migrated to real A4 credential-scoped behavior."""
    case = await open_scoped_oauth(repository)
    try:
        await case.connect()
        await case.balance()
        await case.disconnect()
        assert (await case.status()).status is OAuthGrantStatus.DISCONNECTED
        assert await case.token() is None
        assert await case.repository.latest_quota("parallel") is None
    finally:
        await case.close()


async def test_unbound_store_resolves_fail_closed():
    from fastapi import FastAPI, HTTPException
    from starlette.requests import Request

    from polyweb.routers.control_errors import control_secret_store

    app = FastAPI()
    app.state.secret_store = None
    with pytest.raises(HTTPException) as caught:
        control_secret_store(Request({"type": "http", "app": app, "headers": []}))
    assert caught.value.status_code == 503


async def test_start_device_flow_preflights_writable_store_before_vendor_http(repository):
    """Origin singleton case: migrated to real A4 credential-scoped behavior."""
    case = await open_vault_oauth(repository)
    try:
        app = create_app([], repository=case.repository, secret_store=AsyncVaultDouble())
        with TestClient(app) as client:
            response = client.post(case.path + "/device", headers=case.headers)
        assert response.status_code == 503
        assert case.stub.register_calls == case.stub.device_calls == 0
        assert not any((await case.slots()).values())
    finally:
        await case.close()


async def test_clear_vault_deletes_four_slots_with_tombstones(repository):
    """Origin singleton case: migrated to real A4 credential-scoped behavior."""
    case = await open_scoped_oauth(repository)
    try:
        await case.connect()
        old = await case.grant()
        await case.disconnect()
        from polyweb.persistence.oauth_grants import oauth_secret_slot

        for kind in ("access", "refresh", "device", "client"):
            slot = oauth_secret_slot(case.credential.id, kind, old.token_generation)
            assert await case.store.get(slot) is None
            assert await case.repository.get_runtime_setting("secret.enc:" + slot) is None
            assert await case.repository.get_runtime_setting("secret.deleted:" + slot) == {"v": 1}
    finally:
        await case.close()


async def test_disconnect_unbound_returns_cleanly_without_vault_writes(repository):
    """Origin singleton case: migrated to real A4 credential-scoped behavior."""
    case = await open_scoped_oauth(repository)
    try:
        await case.disconnect()
        assert case.stub.revoke_calls == 0
        assert not any((await case.slots()).values())
        assert (await case.status()).status is OAuthGrantStatus.DISCONNECTED
    finally:
        await case.close()
