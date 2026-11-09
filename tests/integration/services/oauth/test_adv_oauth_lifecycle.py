"""Original adversarial cases migrated to A4 credential OAuth.

Case names and parameter matrices retain their origin. Scoped metadata/grants
replace singleton statuses and slots; GET is observational and explicit POST
polls make at most one vendor attempt. Monitoring never polls OAuth implicitly.
"""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest

from freesearch.models.schema_enums import OAuthGrantStatus
from freesearch.persistence.oauth_grants import oauth_secret_slot
from freesearch.services.control_errors import UpstreamUnavailable
from freesearch.services.monitoring import refresh_quotas
from freesearch.services.parallel_oauth import (
    OAuthUnpaired,
    ParallelOAuthClient,
    ParallelOAuthError,
)
from tests.fixtures.vault_oauth import vault_oauth_case as vault_oauth_case
from tests.integration.services.oauth.oauth_stubs import (
    ROTATED_ACCESS_TOKEN_VALUE,
)


async def test_revoke_before_delete_ordering(vault_oauth_case, monkeypatch):
    """Origin test_adv_oauth_lifecycle.py::test_revoke_before_delete_ordering."""
    case = vault_oauth_case
    await case.connect()
    old = await case.grant()
    revoke = ParallelOAuthClient.revoke_token_required

    async def checked_revoke(client, token):
        assert (await case.status()).status is OAuthGrantStatus.CONNECTED
        assert await case.token("access") is not None
        assert await case.token("refresh") == token.get_secret_value()
        await revoke(client, token)

    monkeypatch.setattr(ParallelOAuthClient, "revoke_token_required", checked_revoke)
    await case.disconnect()
    assert case.stub.revoke_calls == 1
    for kind in ("access", "refresh", "client", "device"):
        assert (
            await case.store.get(oauth_secret_slot(case.credential.id, kind, old.token_generation))
            is None
        )
    assert (await case.status()).status is OAuthGrantStatus.DISCONNECTED
    await case.assert_no_leaks()


async def test_failed_vault_revoke_retains_grant_for_retry(vault_oauth_case, monkeypatch):
    case = vault_oauth_case
    await case.connect()
    before = await case.slots()

    async def failed_revoke(client, token):
        raise ParallelOAuthError("vendor unavailable")

    with monkeypatch.context() as patch:
        patch.setattr(ParallelOAuthClient, "revoke_token_required", failed_revoke)
        with pytest.raises(UpstreamUnavailable):
            await case.disconnect()
    assert (await case.status()).status is OAuthGrantStatus.CONNECTED
    assert await case.slots() == before
    await case.disconnect()
    assert case.stub.revoke_calls == 1
    assert (await case.status()).status is OAuthGrantStatus.DISCONNECTED
    assert not any((await case.slots()).values())
    await case.assert_no_leaks()


async def test_disconnect_idempotent(vault_oauth_case):
    """Origin test_adv_oauth_lifecycle.py::test_disconnect_idempotent."""
    case = vault_oauth_case
    await case.connect()
    await case.balance()
    assert case.client.delete(case.path, headers=case.headers).status_code == 204
    assert case.client.delete(case.path, headers=case.headers).status_code == 204
    revokes = case.stub.revoke_calls
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(
            pool.map(
                lambda _: case.client.delete(case.path, headers=case.headers).status_code, range(4)
            )
        )
    assert results == [204] * 4
    assert case.stub.revoke_calls == revokes
    assert (await case.status()).status is OAuthGrantStatus.DISCONNECTED
    assert not any((await case.slots()).values())


async def test_refresh_invalid_grant_unpairs_without_hotloop(oauth_case):
    """Origin test_adv_oauth_lifecycle.py::test_refresh_invalid_grant_unpairs_without_hotloop."""
    case = oauth_case
    await case.connect()
    case.stub.refresh_reject = "invalid_grant"
    assert (await case.refresh()).status is OAuthGrantStatus.REFRESH_FAILED
    assert not any((await case.slots()).values())
    for _ in range(4):
        await case.refresh()
        await case.status()
    assert case.stub.refresh_calls == 1


async def test_balance_401_unpairs_and_backs_off(oauth_case):
    """Origin test_adv_oauth_lifecycle.py::test_balance_401_unpairs_and_backs_off."""
    case = oauth_case
    await case.connect()
    case.stub.balance_status = 401
    with pytest.raises(OAuthUnpaired):
        await case.balance()
    await case.disconnect()
    for _ in range(4):
        await case.status()
        await refresh_quotas(case.repository, [])
    assert case.stub.balance_calls == 1
    assert not any((await case.slots()).values())


async def test_device_interval_and_slow_down_honored(oauth_case):
    """Origin test_adv_oauth_lifecycle.py::test_device_interval_and_slow_down_honored."""
    case = oauth_case
    case.stub.poll_script = ["authorization_pending", "slow_down", "success"]
    start = await case.start()
    assert start.interval == case.stub.device_interval
    assert (await case.poll()).status is OAuthGrantStatus.PENDING
    assert (await case.poll()).status is OAuthGrantStatus.PENDING
    assert case.stub.poll_calls == 1
    case.clock[0] += timedelta(seconds=start.interval)
    slow = await case.poll()
    assert slow.status is OAuthGrantStatus.PENDING
    assert slow.interval == start.interval + 5
    for _ in range(4):
        await case.status()
    assert case.stub.poll_calls == 2
    assert (await case.poll()).status is OAuthGrantStatus.PENDING
    assert case.stub.poll_calls == 2
    case.clock[0] += timedelta(seconds=slow.interval)
    assert (await case.poll()).status is OAuthGrantStatus.CONNECTED
    assert case.stub.poll_calls == 3


async def test_balance_poll_single_flight(oauth_case):
    """Origin test_adv_oauth_lifecycle.py::test_balance_poll_single_flight."""
    case = oauth_case
    await case.connect()
    await asyncio.gather(*(refresh_quotas(case.repository, []) for _ in range(6)))
    assert case.stub.balance_calls == 0
    # Explicit primitive invocation sends once; the fixture never adds a hidden retry.
    assert await case.balance() is not None
    assert case.stub.balance_calls == 1


async def test_refresh_single_flight_and_skew(oauth_case):
    """Origin test_adv_oauth_lifecycle.py::test_refresh_single_flight_and_skew."""
    case = oauth_case
    await case.connect()
    old = await case.grant()
    for _ in range(4):
        await case.status()
    assert case.stub.refresh_calls == 0
    await case.expire_access()
    await asyncio.gather(case.refresh(), case.refresh())
    assert (await case.grant()).token_generation > old.token_generation
    assert await case.token() == ROTATED_ACCESS_TOKEN_VALUE
    await case.disconnect()
    await case.refresh()
    assert (await case.status()).status is OAuthGrantStatus.DISCONNECTED
    assert not any((await case.slots()).values())


async def test_restart_while_paired_returns_409_without_touching_pairing(vault_oauth_case):
    """Origin singleton restart-conflict case: pairing survives a denied restart."""
    case = vault_oauth_case
    await case.connect()
    old = await case.token()
    response = case.client.post(case.path + "/device", headers=case.headers)
    assert response.status_code == 409
    assert await case.token() == old
    assert case.stub.register_calls == case.stub.device_calls == 1
    await case.assert_no_leaks(response)


async def test_refresh_quotas_path_also_polls_oauth(oauth_case):
    """Origin test_adv_oauth_lifecycle.py::test_refresh_quotas_path_also_polls_oauth."""
    case = oauth_case
    await case.connect()
    await refresh_quotas(case.repository, [])
    assert case.stub.balance_calls == 0
    assert await case.repository.latest_quota("parallel") is None
    assert (await case.status()).status is OAuthGrantStatus.CONNECTED
