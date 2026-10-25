"""CLI: freesearch-secrets status/rekey against tmp databases and key files."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from freesearch.configuration.config import get_settings
from freesearch.infrastructure.encrypted_store import EncryptedDbSecretStore
from tests.fixtures.alpha_fixtures import create_alpha_test_db


def _settings_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, **extra: str) -> Path:
    key_file = tmp_path / ".secret_key"
    monkeypatch.setenv("FREESEARCH_ENCRYPTION_KEY_FILE", str(key_file))
    for name, value in extra.items():
        monkeypatch.setenv(name, value)
    get_settings.cache_clear()
    return key_file


def test_status_and_rekey_round_trip(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:  # type: ignore[no-untyped-def]
    import asyncio
    import os

    from freesearch.cli.secrets import _run
    from freesearch.infrastructure.cryptography import MasterKey, SecretCodec

    db = tmp_path / "cli-secrets.db"
    retired_file = tmp_path / "retired.key"
    old_key = MasterKey(os.urandom(32))
    retired_file.write_bytes(old_key.key)

    async def _seed() -> None:
        repository = await create_alpha_test_db(db)
        try:
            store = EncryptedDbSecretStore(repository, SecretCodec(old_key))
            await store.set("tavily", "fake-cli-secret-value")
        finally:
            await repository.close()

    asyncio.run(_seed())

    key_file = _settings_env(
        monkeypatch,
        tmp_path,
        FREESEARCH_ENCRYPTION_RETIRED_KEY_FILES=json.dumps([str(retired_file)]),
    )
    # New primary written to a fresh key file (no passphrase -> new random key).
    assert _run(["--database", str(db), "status"]) == 1
    out = capsys.readouterr().out
    assert "fake-cli-secret-value" not in out
    assert old_key.key.hex() not in out
    assert _run(["--database", str(db), "rekey"]) == 0
    assert _run(["--database", str(db), "status"]) == 0
    assert _run(["--database", str(db), "rekey", "--dry-run"]) == 0
    assert "fake-cli-secret-value" not in capsys.readouterr().out
    assert key_file.exists()
    get_settings.cache_clear()
