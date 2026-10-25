"""Unit acceptance for the encrypted-DB master key and AES-256-GCM codec.

Covers vault-only AC-3 (passphrase via FREESEARCH_ENCRYPTION_KEY with
PBKDF2+salt, file fallback via Settings.encryption_key_file, strict perms).
Focused: PBKDF2/env-vs-file, wrong-key None, nondeterministic envelopes.
"""

from __future__ import annotations

import os
import stat
from hashlib import sha256
from pathlib import Path

import pytest
from pydantic import SecretStr

from tests.encrypted_secrets_helpers import (
    SENTINEL_PASSPHRASE,
    SENTINEL_WRONG_PASSPHRASE,
    require_cryptography,
)


def _crypto():
    """Load the implementation module; fails Red with a clear message until then."""

    return require_cryptography()


def _load(crypto, monkeypatch, tmp_path, *, passphrase=None):  # type: ignore[no-untyped-def]
    if passphrase is not None:
        monkeypatch.setenv("FREESEARCH_ENCRYPTION_KEY", passphrase)
    else:
        monkeypatch.delenv("FREESEARCH_ENCRYPTION_KEY", raising=False)
    return crypto.load_or_create_master_key(key_file=tmp_path / ".secret_key")


# --- AC-1: passphrase mode -------------------------------------------------


def test_master_key_env_var_name() -> None:
    crypto = _crypto()
    assert crypto.MASTER_KEY_ENV_VAR == "FREESEARCH_ENCRYPTION_KEY"


def test_passphrase_derives_32_byte_key_via_kdf_not_raw(  # AC-1
    monkeypatch,
    tmp_path,  # type: ignore[no-untyped-def]
) -> None:
    crypto = _crypto()
    master = _load(crypto, monkeypatch, tmp_path, passphrase=SENTINEL_PASSPHRASE)

    assert isinstance(master.key, bytes)
    assert len(master.key) == 32
    raw_padded = SENTINEL_PASSPHRASE.encode("utf-8").ljust(32, b"\0")[:32]
    assert master.key != raw_padded, "raw env string must never be the AES key"
    assert master.key != sha256(SENTINEL_PASSPHRASE.encode("utf-8")).digest(), (
        "a single hash pass is not a KDF; PBKDF2-HMAC-SHA256 with stored salt is required"
    )


def test_passphrase_mode_decrypts_across_reloads_without_key_file(  # AC-1
    monkeypatch,
    tmp_path,  # type: ignore[no-untyped-def]
) -> None:
    crypto = _crypto()
    key_file = tmp_path / ".secret_key"
    first = _load(crypto, monkeypatch, tmp_path, passphrase=SENTINEL_PASSPHRASE)
    envelope = crypto.SecretCodec(first).encrypt("passphrase-round-trip", context="tavily")

    second = crypto.load_or_create_master_key(key_file=key_file)
    assert crypto.SecretCodec(second).decrypt(envelope, context="tavily").get_secret_value() == (
        "passphrase-round-trip"
    )
    assert not key_file.exists(), "passphrase mode must not persist key material"
    for path in tmp_path.iterdir():
        blob = path.read_bytes()
        assert first.key not in blob, f"key material persisted in {path.name}"
        assert SENTINEL_PASSPHRASE.encode() not in blob, f"passphrase persisted in {path.name}"


def test_master_key_repr_and_errors_reveal_nothing(  # AC-1/AC-5
    monkeypatch,
    tmp_path,  # type: ignore[no-untyped-def]
) -> None:
    crypto = _crypto()
    master = _load(crypto, monkeypatch, tmp_path, passphrase=SENTINEL_PASSPHRASE)

    redacted = repr(master)
    assert SENTINEL_PASSPHRASE not in redacted
    assert master.key.hex() not in redacted
    assert "***" in redacted


def test_default_key_file_is_local_dev_not_docker_data() -> None:
    crypto = _crypto()
    assert isinstance(crypto.DEFAULT_KEY_FILE, Path)
    assert str(crypto.DEFAULT_KEY_FILE) != "/data/.secret_key"


# --- AC-2: auto-generate mode ----------------------------------------------


def test_auto_generate_creates_strict_perm_key_file_despite_umask(  # AC-2
    monkeypatch,
    tmp_path,  # type: ignore[no-untyped-def]
) -> None:
    crypto = _crypto()
    previous_umask = os.umask(0o022)
    try:
        key_file = tmp_path / "sub" / ".secret_key"
        master = crypto.load_or_create_master_key(key_file=key_file)
    finally:
        os.umask(previous_umask)

    assert len(master.key) == 32
    if os.name != "posix":
        pytest.skip("POSIX-only 0600/0700 mode assert; reuse covered below on all platforms")
    assert stat.S_IMODE(os.stat(key_file).st_mode) == 0o600
    assert stat.S_IMODE(os.stat(key_file.parent).st_mode) == 0o700
    leftovers = [p.name for p in key_file.parent.iterdir() if p != key_file]
    assert leftovers == [], f"atomic-write temp files left behind: {leftovers}"


def test_second_startup_reuses_key_file_unchanged(  # AC-2
    monkeypatch,
    tmp_path,  # type: ignore[no-untyped-def]
) -> None:
    crypto = _crypto()
    key_file = tmp_path / ".secret_key"
    first = _load(crypto, monkeypatch, tmp_path)
    before = (key_file.stat().st_mtime_ns, key_file.read_bytes())

    second = crypto.load_or_create_master_key(key_file=key_file)

    assert second.key == first.key
    assert (key_file.stat().st_mtime_ns, key_file.read_bytes()) == before


def test_two_installations_generate_distinct_keys(  # AC-2
    monkeypatch,
    tmp_path,  # type: ignore[no-untyped-def]
) -> None:
    crypto = _crypto()
    first_dir = tmp_path / "a"
    second_dir = tmp_path / "b"
    first_dir.mkdir()
    second_dir.mkdir()
    monkeypatch.delenv("FREESEARCH_ENCRYPTION_KEY", raising=False)

    first = crypto.load_or_create_master_key(key_file=first_dir / ".secret_key")
    second = crypto.load_or_create_master_key(key_file=second_dir / ".secret_key")

    assert first.key != second.key


def test_corrupt_key_file_fails_closed_without_regeneration(  # AC-9
    monkeypatch,
    tmp_path,  # type: ignore[no-untyped-def]
) -> None:
    crypto = _crypto()
    key_file = tmp_path / ".secret_key"
    key_file.write_bytes(b"too-short")
    monkeypatch.delenv("FREESEARCH_ENCRYPTION_KEY", raising=False)

    with pytest.raises(Exception) as exc_info:
        crypto.load_or_create_master_key(key_file=key_file)

    assert key_file.read_bytes() == b"too-short", "never regenerate over an existing file"
    assert "too-short" not in str(exc_info.value)


# --- Codec: round-trip, opacity, wrong key (AC-4/AC-5) ----------------------


def test_codec_round_trip_returns_secret_str(  # AC-3
    monkeypatch,
    tmp_path,  # type: ignore[no-untyped-def]
) -> None:
    crypto = _crypto()
    master = _load(crypto, monkeypatch, tmp_path, passphrase=SENTINEL_PASSPHRASE)
    codec = crypto.SecretCodec(master)

    decrypted = codec.decrypt(
        codec.encrypt("codec-round-trip-value", context="tavily"), context="tavily"
    )

    assert isinstance(decrypted, SecretStr)
    assert decrypted.get_secret_value() == "codec-round-trip-value"


def test_envelopes_are_opaque_and_nondeterministic(  # AC-5
    monkeypatch,
    tmp_path,  # type: ignore[no-untyped-def]
) -> None:
    crypto = _crypto()
    master = _load(crypto, monkeypatch, tmp_path, passphrase=SENTINEL_PASSPHRASE)
    codec = crypto.SecretCodec(master)
    plaintext = "nondeterministic-plaintext-sentinel"

    first, second = (
        codec.encrypt(plaintext, context="tavily"),
        codec.encrypt(plaintext, context="tavily"),
    )

    assert first != second, "fresh 96-bit nonce required per encrypt call"
    assert plaintext not in first
    assert plaintext not in second
    assert codec.decrypt(first, context="tavily").get_secret_value() == plaintext
    assert codec.decrypt(second, context="tavily").get_secret_value() == plaintext


def test_wrong_passphrase_cannot_decrypt_and_error_is_redacted(  # AC-4
    monkeypatch,
    tmp_path,  # type: ignore[no-untyped-def]
) -> None:
    crypto = _crypto()
    right_dir = tmp_path / "right"
    wrong_dir = tmp_path / "wrong"
    right_dir.mkdir()
    wrong_dir.mkdir()
    right = _load(crypto, monkeypatch, right_dir, passphrase=SENTINEL_PASSPHRASE)
    envelope = crypto.SecretCodec(right).encrypt("wrong-key-plaintext-sentinel", context="tavily")

    monkeypatch.setenv("FREESEARCH_ENCRYPTION_KEY", SENTINEL_WRONG_PASSPHRASE)
    wrong = crypto.load_or_create_master_key(key_file=wrong_dir / ".secret_key")

    with pytest.raises(crypto.SecretDecryptError) as exc_info:
        crypto.SecretCodec(wrong).decrypt(envelope, context="tavily")

    message = str(exc_info.value)
    assert "wrong-key-plaintext-sentinel" not in message
    assert wrong.key.hex() not in message
    assert SENTINEL_WRONG_PASSPHRASE not in message


@pytest.mark.parametrize("corrupt", ["", "not-an-envelope", "eyJ2Ijo5OTl9", "a" * 24])
def test_corrupt_envelopes_raise_redacted_error(  # AC-4/AC-5
    monkeypatch,
    tmp_path,
    corrupt: str,  # type: ignore[no-untyped-def]
) -> None:
    crypto = _crypto()
    master = _load(crypto, monkeypatch, tmp_path, passphrase=SENTINEL_PASSPHRASE)
    codec = crypto.SecretCodec(master)
    envelope = codec.encrypt("corrupt-envelope-plaintext", context="tavily")
    truncated = envelope[: len(envelope) // 2]

    for bad in (corrupt, truncated):
        with pytest.raises(crypto.SecretDecryptError) as exc_info:
            codec.decrypt(bad, context="tavily")
        assert "corrupt-envelope-plaintext" not in str(exc_info.value)


def test_secret_decrypt_error_is_an_exception() -> None:
    crypto = _crypto()
    assert issubclass(crypto.SecretDecryptError, Exception)


def test_explicit_passphrase_env_param_wins_over_process_env(
    monkeypatch,
    tmp_path,  # type: ignore[no-untyped-def]
) -> None:
    """AC-3: explicit passphrase_env beats FREESEARCH_ENCRYPTION_KEY."""

    crypto = _crypto()
    monkeypatch.setenv("FREESEARCH_ENCRYPTION_KEY", SENTINEL_WRONG_PASSPHRASE)
    key_file = tmp_path / ".secret_key"

    explicit = crypto.load_or_create_master_key(
        key_file=key_file, passphrase_env=SENTINEL_PASSPHRASE
    )
    envelope = crypto.SecretCodec(explicit).encrypt("explicit-param-wins", context="tavily")

    monkeypatch.delenv("FREESEARCH_ENCRYPTION_KEY", raising=False)
    reloaded = crypto.load_or_create_master_key(
        key_file=key_file, passphrase_env=SENTINEL_PASSPHRASE
    )
    assert crypto.SecretCodec(reloaded).decrypt(envelope, context="tavily").get_secret_value() == (
        "explicit-param-wins"
    )


def test_settings_encryption_key_file_overrides_default(
    monkeypatch,
    tmp_path,  # type: ignore[no-untyped-def]
) -> None:
    """AC-3: Settings.encryption_key_file overrides DEFAULT_KEY_FILE (/data mount)."""

    from freesearch.configuration.config import get_settings

    monkeypatch.chdir(tmp_path)
    get_settings.cache_clear()
    try:
        monkeypatch.setenv("FREESEARCH_ENCRYPTION_KEY_FILE", "/data/.secret_key")
        assert get_settings().encryption_key_file == Path("/data/.secret_key")
    finally:
        monkeypatch.delenv("FREESEARCH_ENCRYPTION_KEY_FILE", raising=False)
        get_settings.cache_clear()
    assert get_settings().encryption_key_file != Path("/data/.secret_key")
    get_settings.cache_clear()


# --- v2 envelopes: key ids, context binding, retired keys -------------------

_CTX = "tavily"


def _master() -> object:
    crypto = _crypto()
    return crypto.MasterKey(os.urandom(32))


def test_key_id_is_stable_short_and_hides_key_bytes() -> None:
    crypto = _crypto()
    first = crypto.MasterKey(os.urandom(32))
    second = crypto.MasterKey(os.urandom(32))
    assert first.key_id == first.key_id
    assert len(first.key_id) == 16
    assert int(first.key_id, 16) >= 0
    assert first.key_id != second.key_id
    rendered = repr(first)
    assert first.key.hex() not in rendered


def test_v2_envelope_round_trip_with_kid() -> None:
    crypto = _crypto()
    master = crypto.MasterKey(os.urandom(32))
    codec = crypto.SecretCodec(master)
    envelope = codec.encrypt("v2-secret-value", context=_CTX)
    import json as _json

    payload = _json.loads(envelope)
    assert payload["v"] == 2
    assert payload["kid"] == master.key_id
    assert codec.decrypt(envelope, context=_CTX).get_secret_value() == "v2-secret-value"


def test_decrypt_with_different_context_fails() -> None:
    crypto = _crypto()
    codec = crypto.SecretCodec(crypto.MasterKey(os.urandom(32)))
    envelope = codec.encrypt("ctx-bound", context="credential.a.g1")
    with pytest.raises(crypto.SecretDecryptError):
        codec.decrypt(envelope, context="credential.b.g1")


def test_tampered_kid_or_ciphertext_fails() -> None:
    import json as _json

    crypto = _crypto()
    codec = crypto.SecretCodec(crypto.MasterKey(os.urandom(32)))
    envelope = codec.encrypt("tamper", context=_CTX)
    payload = _json.loads(envelope)
    payload["kid"] = "0" * 16
    with pytest.raises(crypto.SecretDecryptError):
        codec.decrypt(_json.dumps(payload), context=_CTX)
    payload = _json.loads(envelope)
    payload["ct"] = payload["ct"][:-4] + "AAAA"
    with pytest.raises(crypto.SecretDecryptError):
        codec.decrypt(_json.dumps(payload), context=_CTX)


def test_retired_key_decrypts_old_v2_and_duplicate_is_ignored() -> None:
    crypto = _crypto()
    old = crypto.MasterKey(os.urandom(32))
    new = crypto.MasterKey(os.urandom(32))
    envelope = crypto.SecretCodec(old).encrypt("rotated-away", context=_CTX)
    codec = crypto.SecretCodec(new, retired=[old, new])
    assert codec.decrypt(envelope, context=_CTX).get_secret_value() == "rotated-away"
    assert codec.primary_key_id == new.key_id
    with pytest.raises(crypto.SecretDecryptError):
        crypto.SecretCodec(new).decrypt(envelope, context=_CTX)


def test_v1_envelope_decrypts_only_with_allow_legacy() -> None:
    import base64 as _b64
    import json as _json

    crypto = _crypto()
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    old = crypto.MasterKey(os.urandom(32))
    nonce = os.urandom(12)
    ct = AESGCM(old.key).encrypt(nonce, b"legacy-value", None)
    envelope = _json.dumps(
        {
            "v": 1,
            "alg": "AES-256-GCM",
            "nonce": _b64.b64encode(nonce).decode(),
            "ct": _b64.b64encode(ct).decode(),
        }
    )
    codec = crypto.SecretCodec(crypto.MasterKey(os.urandom(32)), retired=[old])
    with pytest.raises(crypto.SecretDecryptError):
        codec.decrypt(envelope, context=_CTX)
    assert (
        codec.decrypt(envelope, context=_CTX, allow_legacy=True).get_secret_value()
        == "legacy-value"
    )


def test_needs_rekey_cases() -> None:
    crypto = _crypto()
    primary = crypto.MasterKey(os.urandom(32))
    retired = crypto.MasterKey(os.urandom(32))
    codec = crypto.SecretCodec(primary, retired=[retired])
    assert codec.needs_rekey(codec.encrypt("x", context=_CTX)) is False
    assert codec.needs_rekey(crypto.SecretCodec(retired).encrypt("x", context=_CTX)) is True
    with pytest.raises(crypto.SecretDecryptError):
        codec.needs_rekey("not-an-envelope")


def test_empty_context_rejected() -> None:
    crypto = _crypto()
    codec = crypto.SecretCodec(crypto.MasterKey(os.urandom(32)))
    with pytest.raises(ValueError):
        codec.encrypt("x", context="")
    with pytest.raises(ValueError):
        codec.decrypt(codec.encrypt("x", context=_CTX), context="")


def test_load_retired_master_keys(tmp_path) -> None:  # type: ignore[no-untyped-def]
    crypto = _crypto()
    missing = tmp_path / "missing.key"
    with pytest.raises(OSError):
        crypto.load_retired_master_keys(
            key_files=[missing], passphrases=[], salt_key_file=tmp_path / "salt.key"
        )
    assert not missing.exists()
    wrong = tmp_path / "wrong.key"
    wrong.write_bytes(b"short")
    with pytest.raises(ValueError):
        crypto.load_retired_master_keys(
            key_files=[wrong], passphrases=[], salt_key_file=tmp_path / "salt.key"
        )
    good = tmp_path / "good.key"
    key_bytes = os.urandom(32)
    good.write_bytes(key_bytes)
    retired = crypto.load_retired_master_keys(
        key_files=[good], passphrases=[], salt_key_file=tmp_path / "salt.key"
    )
    assert len(retired) == 1
    assert retired[0].key == key_bytes
    # Passphrase-derived retired key equals the passphrase-derived primary (same salt).
    primary_salt_file = tmp_path / ".secret_key"
    derived_primary = crypto.load_or_create_master_key(
        key_file=primary_salt_file, passphrase_env="p08-pass"
    )
    derived_retired = crypto.load_retired_master_keys(
        key_files=[], passphrases=["p08-pass"], salt_key_file=primary_salt_file
    )
    assert derived_retired[0].key == derived_primary.key
