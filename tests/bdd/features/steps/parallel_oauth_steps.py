"""OAuth BDD scenarios on account-vault lifecycle and primitives."""

from datetime import timedelta
from typing import Any

from behave import given, then, when

from polyweb.models.credentials import CredentialOAuthDeviceRead
from polyweb.models.schema_enums import OAuthGrantStatus
from polyweb.services.parallel_oauth import OAuthUnpaired
from tests.bdd.features.steps.vault_oauth_support import bdd_vault_oauth_setup
from tests.integration.services.oauth.oauth_stubs import DEVICE_CODE_VALUE, TOKEN_SENTINELS


def _run(context, value):
    return context.loop.run_until_complete(value)


def _start(context):
    case = context.oauth_case
    context.device_response = case.client.post(case.path + "/device", headers=case.headers)


def _poll(context):
    case = context.oauth_case
    context.token_calls_before = case.stub.poll_calls
    context.oauth_status = _run(context, case.poll())
    deltas = getattr(context, "token_call_deltas", [])
    deltas.append(case.stub.poll_calls - context.token_calls_before)
    context.token_call_deltas = deltas


def _balance(context):
    case = context.oauth_case
    if _run(context, case.token()) is None:
        context.quota_snapshot = None
        return
    try:
        context.quota_snapshot = _run(context, case.balance())
    except OAuthUnpaired:
        _run(context, case.disconnect())
        context.quota_snapshot = None


@given("an offline Parallel OAuth API with stubbed platform responses")
def step_given_oauth_api(context: Any) -> None:
    bdd_vault_oauth_setup(context)


@given("an offline Parallel OAuth API with a pending device flow")
def step_given_pending_flow(context: Any) -> None:
    bdd_vault_oauth_setup(context)
    context.oauth_case.stub.poll_script = ["authorization_pending"]
    _start(context)


@given("an offline Parallel OAuth API with an expired device code")
def step_given_expired_flow(context: Any) -> None:
    bdd_vault_oauth_setup(context)
    _start(context)
    context.oauth_case.clock[0] += timedelta(hours=1)


@given("an offline Parallel OAuth API with a paired bearer")
def step_given_paired_bearer(context: Any) -> None:
    bdd_vault_oauth_setup(context)
    _run(context, context.oauth_case.connect())


@when("I start the Parallel device flow")
def step_when_start_flow(context: Any) -> None:
    _start(context)


@then("the device code response should carry the user code and verification URIs")
def step_then_device_shape(context: Any) -> None:
    response = context.device_response
    assert response.status_code == 200
    body = response.json()
    assert set(body) == set(CredentialOAuthDeviceRead.model_fields)
    assert body["user_code"] and body["verification_uri"]
    assert body["expires_in"] > 0 and body["interval"] > 0


@then("the device code response should contain no token or device secret")
def step_then_device_no_secrets(context: Any) -> None:
    text = context.device_response.text
    assert DEVICE_CODE_VALUE not in text
    for secret in TOKEN_SENTINELS:
        assert secret not in text
    assert "device_code" not in context.device_response.json()


@when("I check the Parallel OAuth status")
def step_when_check_status(context: Any) -> None:
    _poll(context)


@then("the OAuth status should be pending with a positive expiry")
def step_then_status_pending(context: Any) -> None:
    assert context.oauth_status.status is OAuthGrantStatus.PENDING
    import json

    raw = _run(context, context.oauth_case.token("device"))
    expires = json.loads(raw)["expires_at"]
    from datetime import datetime

    assert datetime.fromisoformat(expires) > context.oauth_case.clock[0]


@when("the poll interval elapses")
def step_when_interval_elapses(context: Any) -> None:
    context.oauth_case.clock[0] += timedelta(seconds=context.oauth_case.stub.device_interval)


@when("the stubbed user approves the device code")
def step_when_approve(context: Any) -> None:
    context.oauth_case.stub.poll_script = ["success"]


@then("the OAuth status should be ready")
def step_then_status_ready(context: Any) -> None:
    assert context.oauth_status.status is OAuthGrantStatus.CONNECTED
    assert context.oauth_status.access_expires_at > context.oauth_case.clock[0]


@then("each status check should have attempted at most one token call")
def step_then_bounded_poll(context: Any) -> None:
    assert all(delta <= 1 for delta in context.token_call_deltas)


@when("I check the Parallel OAuth status twice in quick succession")
def step_when_check_status_twice(context: Any) -> None:
    _poll(context)
    _poll(context)


@then("the token endpoint should have been called exactly once")
def step_then_token_called_once(context: Any) -> None:
    assert context.oauth_case.stub.poll_calls == 1


@when("the stubbed user denies the device code")
def step_when_deny(context: Any) -> None:
    context.oauth_case.stub.poll_script = ["access_denied"]


@then("the OAuth status should be denied")
def step_then_status_denied(context: Any) -> None:
    assert context.oauth_status.status is OAuthGrantStatus.DISCONNECTED
    assert context.oauth_status.last_error_code == "access_denied"


@when("I check the Parallel OAuth status again")
def step_when_check_status_again(context: Any) -> None:
    _poll(context)


@then("the OAuth status should still be denied with no extra token call")
def step_then_denied_terminal(context: Any) -> None:
    assert context.oauth_status.status is OAuthGrantStatus.DISCONNECTED
    assert context.oauth_status.last_error_code == "access_denied"
    assert context.oauth_case.stub.poll_calls - context.token_calls_before == 0


@then("the OAuth status should be expired")
def step_then_status_expired(context: Any) -> None:
    assert context.oauth_status.status is OAuthGrantStatus.DISCONNECTED
    assert context.oauth_status.last_error_code == "expired_token"
    assert _run(context, context.oauth_case.token("device")) is None


@when("the bounded quota poll runs with a rejected bearer")
def step_when_rejected_bearer(context: Any) -> None:
    context.oauth_case.stub.balance_status = 401
    _balance(context)
    context.balance_calls_before = context.oauth_case.stub.balance_calls


@then("the OAuth status should be unpaired")
def step_then_status_unpaired(context: Any) -> None:
    assert _run(context, context.oauth_case.status()).status is OAuthGrantStatus.DISCONNECTED
    assert not any(_run(context, context.oauth_case.slots()).values())


@when("the bounded quota poll runs again immediately")
def step_when_poll_again(context: Any) -> None:
    _balance(context)


@then("no extra balance call should have been made")
def step_then_no_extra_balance_call(context: Any) -> None:
    assert context.oauth_case.stub.balance_calls == context.balance_calls_before


@when("I start the Parallel device flow again")
def step_when_start_flow_again(context: Any) -> None:
    context.bearer_before = _run(context, context.oauth_case.token())
    _start(context)


@then("the device flow should conflict with 409 and the bearer should survive")
def step_then_conflict(context: Any) -> None:
    assert context.device_response.status_code == 409
    assert _run(context, context.oauth_case.token()) == context.bearer_before
    assert context.oauth_case.stub.register_calls == 1


@when("I disconnect the Parallel OAuth pairing")
def step_when_disconnect(context: Any) -> None:
    case = context.oauth_case
    context.disconnect_response = case.client.delete(case.path, headers=case.headers)


@then("the revocation should precede the deletion and the status should be unpaired")
def step_then_revoke_before_delete(context: Any) -> None:
    assert context.disconnect_response.status_code == 204
    assert context.oauth_case.stub.revoke_calls == 1
    assert context.oauth_case.revoke_observations == [(OAuthGrantStatus.CONNECTED.value, True)]
    assert _run(context, context.oauth_case.status()).status is OAuthGrantStatus.DISCONNECTED
    assert not any(_run(context, context.oauth_case.slots()).values())


@when("I disconnect the Parallel OAuth pairing again")
def step_when_disconnect_again(context: Any) -> None:
    case = context.oauth_case
    context.disconnect_response = case.client.delete(case.path, headers=case.headers)


@then("the disconnect should still return 204")
def step_then_disconnect_idempotent(context: Any) -> None:
    assert context.disconnect_response.status_code == 204
    assert context.oauth_case.stub.revoke_calls == 1
