"""Original encrypted OAuth security cases on A4 generation-scoped slots.

All original encryption, deletion, revocation, refresh and no-leak assertions
now address the credential's actual slots. No provider-wide vault is involved.
"""

from polyweb.models.schema_enums import OAuthGrantStatus
from polyweb.persistence.oauth_grants import oauth_secret_slot
from tests.integration.services.oauth.oauth_stubs import (
    ACCESS_TOKEN_VALUE,
    CLIENT_SECRET_VALUE,
    DEVICE_CODE_VALUE,
    REFRESH_TOKEN_VALUE,
    ROTATED_ACCESS_TOKEN_VALUE,
    find_leaked_secrets,
)


async def test_device_flow_to_ready_keeps_all_slots_ciphertext_only(oauth_case):
    case = oauth_case
    device = await case.start()
    pending = await case.grant()
    slot = oauth_secret_slot(case.credential.id, "device", pending.token_generation)
    ciphertext = await case.repository.get_runtime_setting("secret.enc:" + slot)
    assert isinstance(ciphertext, str) and DEVICE_CODE_VALUE not in ciphertext
    assert DEVICE_CODE_VALUE in (await case.token("device"))
    assert DEVICE_CODE_VALUE not in device.model_dump_json()
    case.stub.poll_script = ["success"]
    status = await case.poll()
    assert status.status is OAuthGrantStatus.CONNECTED
    assert await case.token() == ACCESS_TOKEN_VALUE
    assert await case.token("refresh") == REFRESH_TOKEN_VALUE
    assert await case.token("client") == CLIENT_SECRET_VALUE
    assert await case.token("device") is None
    current = await case.grant()
    for kind in ("access", "refresh", "client"):
        key = oauth_secret_slot(case.credential.id, kind, current.token_generation)
        raw = await case.repository.get_runtime_setting("secret.enc:" + key)
        assert isinstance(raw, str) and not find_leaked_secrets(raw)
    await case.assert_no_leaks(device.model_dump_json(), status.model_dump_json())


async def test_refresh_rotates_ciphertext_and_disconnect_revokes_then_clears(oauth_case):
    case = oauth_case
    await case.connect()
    old = await case.grant()
    old_slot = oauth_secret_slot(case.credential.id, "access", old.token_generation)
    old_cipher = await case.repository.get_runtime_setting("secret.enc:" + old_slot)
    await case.expire_access()
    status = await case.refresh()
    assert status.status is OAuthGrantStatus.CONNECTED
    current = await case.grant()
    assert current.token_generation > old.token_generation
    assert await case.token() == ROTATED_ACCESS_TOKEN_VALUE
    current_slot = oauth_secret_slot(case.credential.id, "access", current.token_generation)
    new_cipher = await case.repository.get_runtime_setting("secret.enc:" + current_slot)
    assert old_cipher != new_cipher
    assert await case.store.get(old_slot) is None
    assert await case.repository.get_runtime_setting("secret.enc:" + old_slot) is None
    await case.disconnect()
    assert case.stub.revoke_calls == 1
    for kind in ("access", "refresh", "device", "client"):
        slot = oauth_secret_slot(case.credential.id, kind, current.token_generation)
        assert await case.store.get(slot) is None
        assert await case.repository.get_runtime_setting("secret.enc:" + slot) is None
        assert await case.repository.get_runtime_setting("secret.deleted:" + slot) == {"v": 1}
    await case.disconnect()
    assert case.stub.revoke_calls == 1
    assert (await case.status()).status is OAuthGrantStatus.DISCONNECTED
    await case.assert_no_leaks()
