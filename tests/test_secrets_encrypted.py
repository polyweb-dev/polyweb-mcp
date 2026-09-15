"""Unit tests for encrypted secrets, master key management, and EncryptedDatabaseSecretStore."""

import sqlite3
from pathlib import Path

import pytest
from cryptography.fernet import Fernet

from freesearch.secrets import (
    EncryptedDatabaseSecretStore,
    KeyringSecretStore,
    MemorySecretStore,
    ProviderName,
    ProviderSecretResolver,
    decrypt_secret,
    encrypt_secret,
    get_or_create_master_key,
    resolve_default_secret_store,
)


def test_master_key_generation_and_persistence(tmp_path: Path) -> None:
    key_file = tmp_path / ".secret_key"
    assert not key_file.exists()

    key1 = get_or_create_master_key(tmp_path)
    assert key_file.is_file()
    assert len(key1) == 44  # Standard base64-encoded 32-byte Fernet key

    # Re-reading should return identical key
    key2 = get_or_create_master_key(tmp_path)
    assert key1 == key2


def test_master_key_explicit_key_and_passphrase(tmp_path: Path) -> None:
    # Explicit valid Fernet key
    valid_fernet = Fernet.generate_key().decode()
    key = get_or_create_master_key(tmp_path, explicit_key=valid_fernet)
    assert key == valid_fernet.encode()

    # Explicit arbitrary passphrase derives a 44-byte Fernet key
    passphrase_key = get_or_create_master_key(tmp_path, explicit_key="simple-passphrase-123")
    assert len(passphrase_key) == 44
    Fernet(passphrase_key)  # Validates key is usable by Fernet


def test_encrypt_decrypt_round_trip() -> None:
    master_key = Fernet.generate_key()
    plaintext = "super-secret-api-key-12345"

    ciphertext = encrypt_secret(master_key, plaintext)
    assert ciphertext != plaintext
    assert plaintext not in ciphertext

    decrypted = decrypt_secret(master_key, ciphertext)
    assert decrypted == plaintext


def test_decrypt_with_invalid_key_or_corrupted_ciphertext() -> None:
    key1 = Fernet.generate_key()
    key2 = Fernet.generate_key()

    ciphertext = encrypt_secret(key1, "secret-data")

    # Decrypting with wrong key raises ValueError
    with pytest.raises(ValueError, match="failed to decrypt"):
        decrypt_secret(key2, ciphertext)

    # Decrypting corrupted ciphertext raises ValueError
    with pytest.raises(ValueError, match="failed to decrypt"):
        decrypt_secret(key1, "corrupted_payload_data")


def test_encrypted_database_secret_store_lifecycle(tmp_path: Path) -> None:
    db_path = tmp_path / "test_freesearch.db"
    master_key = Fernet.generate_key()
    store = EncryptedDatabaseSecretStore(
        database_path=db_path,
        master_key=master_key,
        data_dir=tmp_path,
    )

    # Initial get returns None
    assert store.get("brave") is None

    # Set secret
    raw_key = "BSA_live_secret_key_abcdef"
    store.set("brave", raw_key)

    # Verify directly in SQLite that the stored value is ciphertext, NEVER plaintext
    with sqlite3.connect(str(db_path)) as conn:
        cursor = conn.execute(
            "SELECT value_json FROM runtime_settings WHERE key = 'secret.brave.encrypted'"
        )
        row = cursor.fetchone()
        assert row is not None
        assert raw_key not in row[0]
        assert "ciphertext" in row[0]

    # Get secret decrypts correctly
    assert store.get("brave") == raw_key

    # Update secret
    new_key = "BSA_live_updated_key_99999"
    store.set("brave", new_key)
    assert store.get("brave") == new_key

    # Delete secret
    store.delete("brave")
    assert store.get("brave") is None

    # Delete is idempotent
    store.delete("brave")
    assert store.get("brave") is None


def test_encrypted_database_secret_store_empty_value_rejected(tmp_path: Path) -> None:
    db_path = tmp_path / "test.db"
    store = EncryptedDatabaseSecretStore(database_path=db_path, data_dir=tmp_path)
    with pytest.raises(ValueError, match="must not be empty"):
        store.set("tavily", "")


def test_resolve_default_secret_store_selection(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Explicit memory backend
    monkeypatch.setenv("FREESEARCH_SECRET_STORE", "memory")
    store_mem = resolve_default_secret_store(tmp_path / "db.sqlite")
    assert isinstance(store_mem, MemorySecretStore)

    # Explicit keyring backend
    monkeypatch.setenv("FREESEARCH_SECRET_STORE", "keyring")
    store_keyring = resolve_default_secret_store(tmp_path / "db.sqlite")
    assert isinstance(store_keyring, KeyringSecretStore)

    # Explicit database backend
    monkeypatch.setenv("FREESEARCH_SECRET_STORE", "database")
    store_db = resolve_default_secret_store(tmp_path / "db.sqlite")
    assert isinstance(store_db, EncryptedDatabaseSecretStore)


def test_resolver_with_encrypted_database_store(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    db_path = tmp_path / "resolver_test.db"
    store = EncryptedDatabaseSecretStore(database_path=db_path, data_dir=tmp_path)
    store.set("tavily", "db-tavily-key")

    # 1. Database store returns key when no env var is present
    resolver = ProviderSecretResolver(store=store, environ={})
    assert resolver.get(ProviderName.TAVILY).get_secret_value() == "db-tavily-key"

    # 2. Environment variable overrides database secret
    resolver_with_env = ProviderSecretResolver(
        store=store,
        environ={"FREESEARCH_TAVILY_API_KEY": "env-override-key"},
    )
    assert resolver_with_env.get(ProviderName.TAVILY).get_secret_value() == "env-override-key"
