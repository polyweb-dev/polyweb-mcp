"""Unit acceptance for the encrypted-DB master key and AES-256-GCM codec.

Covers PLAN.md AC-1 (passphrase mode + KDF), AC-2 (auto-generated key file
with strict perms + atomic write), AC-4 (wrong key fails closed + redacted),
AC-5 (opaque non-deterministic envelopes), and the AC-9 no-silent-regeneration
pin. Fails Red while ``secret_crypto.py`` is unimplemented.
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
    require_secret_crypto,
)


def _crypto():
    """Load the implementation module; fails Red with a clear message until then."""

    return require_secret_crypto()


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
    monkeypatch, tmp_path  # type: ignore[no-untyped-def]
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
    monkeypatch, tmp_path  # type: ignore[no-untyped-def]
) -> None:
    crypto = _crypto()
    key_file = tmp_path / ".secret_key"
    first = _load(crypto, monkeypatch, tmp_path, passphrase=SENTINEL_PASSPHRASE)
    envelope = crypto.SecretCodec(first).encrypt("passphrase-round-trip")

    second = crypto.load_or_create_master_key(key_file=key_file)
    assert crypto.SecretCodec(second).decrypt(envelope).get_secret_value() == (
        "passphrase-round-trip"
    )
    assert not key_file.exists(), "passphrase mode must not persist key material"
    for path in tmp_path.iterdir():
        blob = path.read_bytes()
        assert first.key not in blob, f"key material persisted in {path.name}"
        assert SENTINEL_PASSPHRASE.encode() not in blob, f"passphrase persisted in {path.name}"


def test_master_key_repr_and_errors_reveal_nothing(  # AC-1/AC-5
    monkeypatch, tmp_path  # type: ignore[no-untyped-def]
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
    monkeypatch, tmp_path  # type: ignore[no-untyped-def]
) -> None:
    crypto = _crypto()
    previous_umask = os.umask(0o022)
    try:
        key_file = tmp_path / "sub" / ".secret_key"
        master = crypto.load_or_create_master_key(key_file=key_file)
    finally:
        os.umask(previous_umask)

    assert len(master.key) == 32
    assert stat.S_IMODE(os.stat(key_file).st_mode) == 0o600
    assert stat.S_IMODE(os.stat(key_file.parent).st_mode) == 0o700
    leftovers = [p.name for p in key_file.parent.iterdir() if p != key_file]
    assert leftovers == [], f"atomic-write temp files left behind: {leftovers}"


def test_second_startup_reuses_key_file_unchanged(  # AC-2
    monkeypatch, tmp_path  # type: ignore[no-untyped-def]
) -> None:
    crypto = _crypto()
    key_file = tmp_path / ".secret_key"
    first = _load(crypto, monkeypatch, tmp_path)
    before = (key_file.stat().st_mtime_ns, key_file.read_bytes())

    second = crypto.load_or_create_master_key(key_file=key_file)

    assert second.key == first.key
    assert (key_file.stat().st_mtime_ns, key_file.read_bytes()) == before


def test_two_installations_generate_distinct_keys(  # AC-2
    monkeypatch, tmp_path  # type: ignore[no-untyped-def]
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
    monkeypatch, tmp_path  # type: ignore[no-untyped-def]
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
    monkeypatch, tmp_path  # type: ignore[no-untyped-def]
) -> None:
    crypto = _crypto()
    master = _load(crypto, monkeypatch, tmp_path, passphrase=SENTINEL_PASSPHRASE)
    codec = crypto.SecretCodec(master)

    decrypted = codec.decrypt(codec.encrypt("codec-round-trip-value"))

    assert isinstance(decrypted, SecretStr)
    assert decrypted.get_secret_value() == "codec-round-trip-value"


def test_envelopes_are_opaque_and_nondeterministic(  # AC-5
    monkeypatch, tmp_path  # type: ignore[no-untyped-def]
) -> None:
    crypto = _crypto()
    master = _load(crypto, monkeypatch, tmp_path, passphrase=SENTINEL_PASSPHRASE)
    codec = crypto.SecretCodec(master)
    plaintext = "nondeterministic-plaintext-sentinel"

    first, second = codec.encrypt(plaintext), codec.encrypt(plaintext)

    assert first != second, "fresh 96-bit nonce required per encrypt call"
    assert plaintext not in first
    assert plaintext not in second
    assert codec.decrypt(first).get_secret_value() == plaintext
    assert codec.decrypt(second).get_secret_value() == plaintext


def test_wrong_passphrase_cannot_decrypt_and_error_is_redacted(  # AC-4
    monkeypatch, tmp_path  # type: ignore[no-untyped-def]
) -> None:
    crypto = _crypto()
    right_dir = tmp_path / "right"
    wrong_dir = tmp_path / "wrong"
    right_dir.mkdir()
    wrong_dir.mkdir()
    right = _load(crypto, monkeypatch, right_dir, passphrase=SENTINEL_PASSPHRASE)
    envelope = crypto.SecretCodec(right).encrypt("wrong-key-plaintext-sentinel")

    monkeypatch.setenv("FREESEARCH_ENCRYPTION_KEY", SENTINEL_WRONG_PASSPHRASE)
    wrong = crypto.load_or_create_master_key(key_file=wrong_dir / ".secret_key")

    with pytest.raises(crypto.SecretDecryptError) as exc_info:
        crypto.SecretCodec(wrong).decrypt(envelope)

    message = str(exc_info.value)
    assert "wrong-key-plaintext-sentinel" not in message
    assert wrong.key.hex() not in message
    assert SENTINEL_WRONG_PASSPHRASE not in message


@pytest.mark.parametrize("corrupt", ["", "not-an-envelope", "eyJ2Ijo5OTl9", "a" * 24])
def test_corrupt_envelopes_raise_redacted_error(  # AC-4/AC-5
    monkeypatch, tmp_path, corrupt: str  # type: ignore[no-untyped-def]
) -> None:
    crypto = _crypto()
    master = _load(crypto, monkeypatch, tmp_path, passphrase=SENTINEL_PASSPHRASE)
    codec = crypto.SecretCodec(master)
    envelope = codec.encrypt("corrupt-envelope-plaintext")
    truncated = envelope[: len(envelope) // 2]

    for bad in (corrupt, truncated):
        with pytest.raises(crypto.SecretDecryptError) as exc_info:
            codec.decrypt(bad)
        assert "corrupt-envelope-plaintext" not in str(exc_info.value)


def test_secret_decrypt_error_is_an_exception() -> None:
    crypto = _crypto()
    assert issubclass(crypto.SecretDecryptError, Exception)
