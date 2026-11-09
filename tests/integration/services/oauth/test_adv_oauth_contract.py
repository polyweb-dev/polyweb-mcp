"""Original adversarial cases migrated to A4 credential OAuth.

Case names and parameter matrices retain their origin. Scoped metadata/grants
replace singleton statuses and slots; GET is observational and explicit POST
polls make at most one vendor attempt. Monitoring never polls OAuth implicitly.
"""

import pytest

from polyweb.models.credentials import CredentialOAuthDeviceRead, CredentialOAuthStatusRead
from polyweb.models.schema_enums import OAuthGrantStatus
from tests.fixtures.vault_oauth import vault_oauth_case as vault_oauth_case
from tests.integration.services.oauth.conftest import NON_PARALLEL_IDS
from tests.integration.services.oauth.oauth_stubs import (
    DEVICE_CODE_VALUE,
)


async def test_oauth_routes_registered_for_parallel(vault_oauth_case):
    """Origin test_adv_oauth_contract.py::test_oauth_routes_registered_for_parallel."""
    case = vault_oauth_case
    paths = set(case.client.app.openapi()["paths"])
    base = "/api/v1/account/vault/keys/{key_id}/oauth"
    assert {base, base + "/device", base + "/poll"} <= paths
    assert not any("/providers/" in path and "/oauth" in path for path in paths)


async def test_device_code_shape_exact(vault_oauth_case):
    """Origin test_adv_oauth_contract.py::test_device_code_shape_exact."""
    case = vault_oauth_case
    assert case.client.post(case.path + "/device").status_code == 401
    response = case.client.post(case.path + "/device", headers=case.headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == set(CredentialOAuthDeviceRead.model_fields)
    assert body["user_code"] and body["verification_uri"]
    assert isinstance(body["expires_in"], int) and body["expires_in"] > 0
    assert isinstance(body["interval"], int) and body["interval"] >= 1
    assert DEVICE_CODE_VALUE not in response.text
    await case.assert_no_leaks(response)


async def test_device_code_extra_body_ignored_never_reflected(vault_oauth_case):
    """Origin test_adv_oauth_contract.py::test_device_code_extra_body_ignored_never_reflected."""
    case = vault_oauth_case
    response = case.client.post(
        case.path + "/device", headers=case.headers, json={"smuggled": "token-material"}
    )
    assert response.status_code in (200, 422), response.text
    assert "token-material" not in response.text
    if response.status_code == 200:
        assert set(response.json()) == set(CredentialOAuthDeviceRead.model_fields)
    await case.assert_no_leaks(response)


async def test_device_vendor_failure_leaves_no_partial_state(vault_oauth_case):
    """Origin test_adv_oauth_contract.py::test_device_vendor_failure_leaves_no_partial_state."""
    case = vault_oauth_case
    case.stub.device_status = 500
    response = case.client.post(case.path + "/device", headers=case.headers)
    assert response.status_code == 502
    assert not any((await case.slots()).values())
    assert (await case.status()).status is OAuthGrantStatus.DISCONNECTED
    await case.assert_no_leaks(response)


async def test_status_shape_exact_and_unpaired_when_fresh(vault_oauth_case):
    """Origin test_adv_oauth_contract.py::test_status_shape_exact_and_unpaired_when_fresh."""
    case = vault_oauth_case
    assert case.client.get(case.path).status_code == 401
    response = case.client.get(case.path, headers=case.headers)
    assert response.status_code == 200
    assert set(response.json()) == set(CredentialOAuthStatusRead.model_fields)
    assert response.json()["status"] == "disconnected"
    assert case.stub.poll_calls == case.stub.refresh_calls == case.stub.balance_calls == 0


@pytest.mark.parametrize(
    "outcome,status",
    [("access_denied", "denied"), ("expired_token", "expired"), ("invalid_grant", "expired")],
)
async def test_device_terminal_edges(oauth_case, outcome, status):
    """Origin test_adv_oauth_contract.py::test_device_terminal_edges."""
    case = oauth_case
    case.stub.poll_script = [outcome]
    await case.start()
    response = await case.poll()
    assert response.status is OAuthGrantStatus.DISCONNECTED
    assert response.last_error_code == ("access_denied" if status == "denied" else "expired_token")
    assert (await case.poll()).status is OAuthGrantStatus.DISCONNECTED
    assert case.stub.poll_calls == 1
    assert not any((await case.slots()).values())


@pytest.mark.parametrize("provider_id", NON_PARALLEL_IDS)
async def test_non_parallel_oauth_always_404(oauth_case, provider_id):
    """Origin test_adv_oauth_contract.py::test_non_parallel_oauth_always_404."""
    case = oauth_case
    base = f"/api/v1/providers/{provider_id}/oauth"
    assert case.client.post(base + "/device-code", headers=case.headers).status_code == 404
    assert case.client.get(base + "/status", headers=case.headers).status_code == 404
    assert case.client.delete(base, headers=case.headers).status_code == 404
    assert case.stub.register_calls == 0


async def test_unknown_provider_oauth_404(oauth_case):
    """Origin test_adv_oauth_contract.py::test_unknown_provider_oauth_404."""
    case = oauth_case
    base = "/api/v1/providers/ghost/oauth"
    assert case.client.get(base + "/status").status_code == 401
    for method, suffix in (("post", "/device-code"), ("get", "/status"), ("delete", "")):
        assert getattr(case.client, method)(base + suffix, headers=case.headers).status_code == 404
    assert case.stub.register_calls == case.stub.poll_calls == 0


async def test_status_responses_carry_no_token_fields(vault_oauth_case):
    """Origin test_adv_oauth_contract.py::test_status_responses_carry_no_token_fields."""
    case = vault_oauth_case
    await case.connect()
    response = case.client.get(case.path, headers=case.headers)
    assert response.status_code == 200
    assert set(response.json()) == set(CredentialOAuthStatusRead.model_fields)
    assert "access_token" not in response.text and "refresh_token" not in response.text
    await case.assert_no_leaks(response)
