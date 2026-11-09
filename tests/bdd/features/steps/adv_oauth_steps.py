"""Adversarial BDD cases on account-vault OAuth endpoints."""

import json
import logging
from contextlib import suppress
from datetime import timedelta
from decimal import Decimal
from typing import Any
from uuid import uuid4

from behave import given, then, when

from polyweb.models.contracts import QuotaSnapshot, QuotaSource, UnitKind
from polyweb.models.credentials import CredentialOAuthDeviceRead, CredentialOAuthStatusRead
from polyweb.models.schema_enums import OAuthGrantStatus
from polyweb.services.monitoring import refresh_quotas
from polyweb.services.parallel_oauth import ParallelOAuthError
from tests.bdd.features.steps.vault_oauth_support import bdd_vault_oauth_setup
from tests.fixtures.api_keys import database_dump
from tests.integration.services.oauth.oauth_stubs import (
    ACCESS_TOKEN_VALUE,
    CLIENT_SECRET_VALUE,
    DEVICE_CODE_VALUE,
    find_leaked_secrets,
)


def _run(context, value):
    return context.loop.run_until_complete(value)


class _Capture(logging.Handler):
    def __init__(self, sink):
        super().__init__()
        self.sink = sink

    def emit(self, record):
        self.sink.append(self.format(record))


def _setup(context):
    case = bdd_vault_oauth_setup(context)
    context.adv_bodies = []
    context.adv_logs = []
    handler = _Capture(context.adv_logs)
    logging.getLogger().addHandler(handler)
    cleanups = getattr(context, "enc_cleanups", [])
    cleanups.append(lambda: logging.getLogger().removeHandler(handler))
    context.enc_cleanups = cleanups
    return case


def _response(context, response):
    context.adv_response = response
    context.adv_bodies.append(response.text)
    return response


def _balance(context):
    context.adv_snapshot = _run(context, context.oauth_case.balance())


@given("an offline Parallel OAuth API with stubbed vendor")
def step_setup(context: Any) -> None:
    _setup(context)


@given('a stubbed "{outcome}" device poll outcome')
def step_poll_outcome(context: Any, outcome: str) -> None:
    context.oauth_case.stub.poll_script = [outcome]


@given("a connected Parallel OAuth session")
def step_connected(context: Any) -> None:
    if getattr(context, "oauth_case", None) is None:
        _setup(context)
    _run(context, context.oauth_case.connect())


@given("a connected Parallel OAuth session with a poisoned grant")
def step_connected_poisoned(context: Any) -> None:
    if getattr(context, "oauth_case", None) is None:
        _setup(context)
    _run(context, context.oauth_case.connect())
    context.oauth_case.stub.refresh_reject = "invalid_grant"


@given("a stubbed slow_down device poll script with interval {interval:d}")
def step_slow_down(context: Any, interval: int) -> None:
    context.oauth_case.stub.device_interval = interval
    context.oauth_case.stub.poll_script = ["authorization_pending", "slow_down", "success"]


@given("a stubbed vendor balance of {credit:d} credit and {pending:d} pending cents")
def step_balance(context: Any, credit: int, pending: int) -> None:
    context.oauth_case.stub.credit_cents = credit
    context.oauth_case.stub.pending_cents = pending


@given("a stubbed invoiced vendor balance")
def step_invoiced(context: Any) -> None:
    context.oauth_case.stub.balance_will_invoice = True


@given("a seeded and anchored account with live credit {credit:d} pending {pending:d}")
def step_seeded_anchored(context: Any, credit: int, pending: int) -> None:
    context.oauth_case.stub.credit_cents = credit
    context.oauth_case.stub.pending_cents = pending
    _run(
        context,
        context.repository.record_quota(
            QuotaSnapshot(
                provider="parallel",
                source=QuotaSource.ESTIMATED,
                remaining=Decimal("5"),
                limit=Decimal("5"),
                observed_at=context.oauth_case.clock[0],
            )
        ),
    )
    case = context.oauth_case
    manual = case.client.put(
        "/api/v1/providers/parallel/manual-quota",
        headers=case.headers,
        json={
            "billing_start": "2026-09-01",
            "billing_end": "2026-10-01",
            "allowance": "999",
            "current_usage": "0",
        },
    )
    assert manual.status_code == 200


@when('I request a device code for "{provider_id}"')
def step_request_device(context: Any, provider_id: str) -> None:
    case = context.oauth_case
    assert provider_id == "parallel"
    _response(context, case.client.post(case.path + "/device", headers=case.headers))


@when("I request a device code with an extra smuggled field")
def step_request_device_extra(context: Any) -> None:
    case = context.oauth_case
    _response(
        context,
        case.client.post(
            case.path + "/device", headers=case.headers, json={"smuggled": "token-material"}
        ),
    )


@when('I read OAuth status for "{provider_id}"')
def step_read_status(context: Any, provider_id: str) -> None:
    case = context.oauth_case
    assert provider_id == "parallel"
    _response(context, case.client.get(case.path, headers=case.headers))


@when('I disconnect OAuth for "{provider_id}"')
def step_disconnect(context: Any, provider_id: str) -> None:
    case = context.oauth_case
    assert provider_id == "parallel"
    _response(context, case.client.delete(case.path, headers=case.headers))


@when('I create a vault OAuth key for "{provider_id}"')
def step_create_unsupported_key(context: Any, provider_id: str) -> None:
    case = context.oauth_case
    context.unsupported_response = case.client.post(
        "/api/v1/account/vault/keys",
        headers=case.headers,
        json={"provider_type": provider_id, "label": "Unsupported", "auth_mode": "oauth"},
    )


@then("the vault should reject the unsupported OAuth provider without vendor calls")
def step_unsupported_key_rejected(context: Any) -> None:
    assert context.unsupported_response.status_code == 400
    assert context.oauth_case.stub.register_calls == 0


@when("I access OAuth for an unknown vault key")
def step_unknown_key(context: Any) -> None:
    case = context.oauth_case
    path = f"/api/v1/account/vault/keys/{uuid4()}/oauth"
    context.unknown_responses = [
        case.client.post(path + "/device", headers=case.headers),
        case.client.post(path + "/poll", headers=case.headers),
        case.client.get(path, headers=case.headers),
        case.client.delete(path, headers=case.headers),
    ]


@then("every OAuth endpoint should return 404 without vendor calls")
def step_unknown_key_rejected(context: Any) -> None:
    assert [response.status_code for response in context.unknown_responses] == [404] * 4
    assert context.oauth_case.stub.register_calls == 0
    assert context.oauth_case.stub.poll_calls == 0


@when('I disconnect OAuth for "parallel" twice')
def step_disconnect_twice(context: Any) -> None:
    case = context.oauth_case
    context.adv_disconnects = [
        case.client.delete(case.path, headers=case.headers) for _ in range(2)
    ]


@when("I start the device flow and poll status to terminal")
def step_poll_terminal(context: Any) -> None:
    case = context.oauth_case
    response = case.client.post(case.path + "/device", headers=case.headers)
    assert response.status_code == 200, response.text
    context.adv_status = _run(context, case.poll())
    context.adv_bodies.append(context.adv_status.model_dump_json())


@when("I start the device flow and poll status rapidly")
def step_poll_rapid(context: Any) -> None:
    case = context.oauth_case
    start = _run(context, case.start())
    context.adv_initial_interval = start.interval
    context.adv_intervals = []
    for _ in range(3):
        context.adv_status = _run(context, case.poll())
        context.adv_intervals.append(context.adv_status.interval)
        for _ in range(3):
            case.client.get(case.path, headers=case.headers)
        if context.adv_status.status is OAuthGrantStatus.CONNECTED:
            break
        case.clock[0] += timedelta(seconds=context.adv_status.interval)


@when("I connect OAuth, run the bounded balance poll, and read the dashboard")
def step_connect_poll_dashboard(context: Any) -> None:
    case = context.oauth_case
    _run(context, case.connect())
    _balance(context)
    _response(context, case.client.get("/dashboard", headers=case.headers))


@when("I read OAuth status repeatedly")
def step_status_repeated(context: Any) -> None:
    case = context.oauth_case
    context.adv_status = _run(context, case.refresh())
    for _ in range(5):
        context.adv_status = _run(context, case.status())
        _run(context, case.refresh())


@when("I run the bounded balance poll repeatedly through failures")
def step_poll_failures(context: Any) -> None:
    case = context.oauth_case
    if _run(context, case.status()).status is not OAuthGrantStatus.CONNECTED:
        _run(context, case.connect())
    case.stub.fail_balance_times = 1
    with suppress(ParallelOAuthError):
        _balance(context)
    for _ in range(5):
        _run(context, refresh_quotas(case.repository, []))
        case.client.get("/dashboard", headers=case.headers)


@when("I drive every OAuth error path")
def step_error_paths(context: Any) -> None:
    case = context.oauth_case
    for outcome in ("access_denied", "expired_token", "invalid_grant"):
        case.stub.poll_script = [outcome]
        _response(context, case.client.post(case.path + "/device", headers=case.headers))
        _response(context, case.client.post(case.path + "/poll", headers=case.headers))
        _response(context, case.client.delete(case.path, headers=case.headers))
    _run(context, case.connect())
    _response(context, case.client.post(case.path + "/device", headers=case.headers))
    case.stub.refresh_reject = "invalid_grant"
    _run(context, case.refresh())
    _response(context, case.client.get("/dashboard", headers=case.headers))


@then("the device code response should carry the strict contract shape")
def step_device_shape(context: Any) -> None:
    response = context.adv_response
    assert response.status_code == 200
    assert set(response.json()) == set(CredentialOAuthDeviceRead.model_fields)
    assert response.json()["user_code"] and response.json()["verification_uri"]
    assert response.json()["expires_in"] > 0 and response.json()["interval"] > 0


@then("the device code response should contain no token fields")
def step_device_no_tokens(context: Any) -> None:
    assert "device_code" not in context.adv_response.json()
    assert DEVICE_CODE_VALUE not in context.adv_response.text
    assert not find_leaked_secrets(context.adv_response.text)


@then("the smuggled value should never surface")
def step_smuggled_never_surfaces(context: Any) -> None:
    assert context.adv_response.status_code in (200, 422)
    assert "token-material" not in context.adv_response.text
    assert "token-material" not in "\n".join(context.adv_logs)
    assert "token-material" not in database_dump(context.repository)
    assert "token-material" not in json.dumps(context.oauth_case.stub.seen_requests)


@then('the OAuth status should become "{status}"')
def step_becomes(context: Any, status: str) -> None:
    view = context.adv_status
    assert view.status is OAuthGrantStatus.DISCONNECTED
    assert view.last_error_code == ("access_denied" if status == "denied" else "expired_token")
    assert not any(_run(context, context.oauth_case.slots()).values())


@then("the disconnect should be accepted with revoke before vault delete")
def step_revoke_order(context: Any) -> None:
    assert context.adv_response.status_code == 204
    assert context.oauth_case.stub.revoke_calls == 1
    assert context.oauth_case.revoke_observations == [(OAuthGrantStatus.CONNECTED.value, True)]
    assert not any(_run(context, context.oauth_case.slots()).values())
    assert _run(context, context.oauth_case.status()).status is OAuthGrantStatus.DISCONNECTED


@then("both disconnects should be accepted and status should be unpaired")
def step_idempotent(context: Any) -> None:
    assert [r.status_code for r in context.adv_disconnects] == [204, 204]
    assert context.oauth_case.stub.revoke_calls == 1
    assert _run(context, context.oauth_case.status()).status is OAuthGrantStatus.DISCONNECTED


@when("I delete the disconnected OAuth vault key after revocation")
def step_delete_revoked_key(context: Any) -> None:
    case = context.oauth_case
    assert case.stub.revoke_calls == 1
    assert _run(context, case.status()).status is OAuthGrantStatus.DISCONNECTED
    response = case.client.delete(case.path.removesuffix("/oauth"), headers=case.headers)
    assert response.status_code == 200, response.text
    assert case.stub.revoke_calls == 1
    keys = case.client.get("/api/v1/account/vault/keys", headers=case.headers)
    assert keys.status_code == 200
    assert str(case.credential.id) not in {key["id"] for key in keys.json()}


@then("the OAuth status should be unpaired without a vendor hot-loop")
def step_unpaired_bounded(context: Any) -> None:
    assert context.adv_status.status is OAuthGrantStatus.REFRESH_FAILED
    assert context.oauth_case.stub.refresh_calls == 1
    assert not any(_run(context, context.oauth_case.slots()).values())


@then("the flow should reach ready with bounded vendor polls")
def step_ready_bounded(context: Any) -> None:
    assert context.adv_status.status is OAuthGrantStatus.CONNECTED
    assert context.oauth_case.stub.poll_calls == 3
    assert context.adv_intervals[1] == context.adv_initial_interval + 5


@then('the Parallel quota should be authoritative USD "{usd}" with no limit')
def step_quota_usd(context: Any, usd: str) -> None:
    snapshot = context.adv_snapshot
    assert snapshot.source is QuotaSource.AUTHORITATIVE
    assert snapshot.remaining == Decimal(usd) and snapshot.limit is None
    assert snapshot.unit_kind is UnitKind.USD and snapshot.display_unit == "USD"
    assert (
        _run(
            context,
            context.repository.latest_quota(
                "parallel", credential_id=context.oauth_case.credential.id
            ),
        )
        == snapshot
    )


@then("the Parallel quota entry should be missing")
def step_missing(context: Any) -> None:
    assert context.adv_snapshot is None
    assert (
        _run(
            context,
            context.repository.latest_quota(
                "parallel", credential_id=context.oauth_case.credential.id
            ),
        )
        is None
    )
    assert _run(context, context.repository.latest_quota("parallel")) is None


@then('the live balance should win as authoritative USD "{usd}"')
def step_precedence(context: Any, usd: str) -> None:
    assert context.adv_snapshot.source is QuotaSource.AUTHORITATIVE
    assert context.adv_snapshot.remaining == Decimal(usd)
    assert (
        _run(
            context,
            context.repository.latest_quota(
                "parallel", credential_id=context.oauth_case.credential.id
            ),
        )
        == context.adv_snapshot
    )
    assert _run(context, context.repository.latest_quota("parallel")).remaining == Decimal("5")


@then("vendor balance polls should stay bounded")
def step_bounded(context: Any) -> None:
    assert context.oauth_case.stub.balance_calls == 1


@then("no log record or response body should contain token material")
def step_no_leak(context: Any) -> None:
    for body in context.adv_bodies:
        assert not find_leaked_secrets(body)
    assert not find_leaked_secrets("\n".join(context.adv_logs))
    _run(context, context.oauth_case.assert_no_leaks(*context.adv_bodies))


@then("the vault should hold the bearer while the database holds none")
def step_vault_not_db(context: Any) -> None:
    case = context.oauth_case
    assert _run(context, case.token()) == ACCESS_TOKEN_VALUE
    assert _run(context, case.token("client")) == CLIENT_SECRET_VALUE
    assert _run(context, case.token("device")) is None
    _run(context, case.assert_no_leaks())


@then("the status should be fingerprint-only")
def step_fingerprint(context: Any) -> None:
    case = context.oauth_case
    probe = case.client.get(case.path, headers=case.headers)
    assert probe.status_code == 200
    assert set(probe.json()) == set(CredentialOAuthStatusRead.model_fields)
    assert "access_token" not in probe.text and "refresh_token" not in probe.text
    _run(context, case.assert_no_leaks(probe))
