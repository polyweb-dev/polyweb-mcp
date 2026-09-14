"""Encrypted runtime-settings secret store and one-shot legacy import."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from dotenv import dotenv_values

from freesearch.infrastructure.secret_crypto import SecretCodec, SecretDecryptError
from freesearch.infrastructure.secrets import PROVIDER_ENV_VARS, ProviderName, SecretStore
from freesearch.persistence.storage import SQLiteRepository

ENCRYPTED_SECRET_PREFIX = "secret.enc:"
logger = logging.getLogger(__name__)


class EncryptedDbSecretStore:
    """Keep ciphertext envelopes in ``runtime_settings`` only."""

    def __init__(self, repository: SQLiteRepository, codec: SecretCodec) -> None:
        self._repository = repository
        self._codec = codec

    @staticmethod
    def _key(name: str) -> str:
        return ENCRYPTED_SECRET_PREFIX + name

    async def get(self, name: str) -> str | None:
        value = await self._repository.get_runtime_setting(self._key(name))
        if not isinstance(value, str):
            return None
        try:
            return self._codec.decrypt(value).get_secret_value()
        except SecretDecryptError:
            logger.warning("encrypted secret could not be decrypted")
            return None

    async def set(self, name: str, value: str) -> None:
        if not value:
            raise ValueError("secret must not be empty")
        await self._repository.set_runtime_setting(self._key(name), self._codec.encrypt(value))

    async def delete(self, name: str) -> None:
        await self._repository.set_runtime_setting(self._key(name), None)


@dataclass(frozen=True)
class MigrationReport:
    """Value-free migration counters suitable for safe operational logs."""

    migrated: int = 0
    skipped_existing: int = 0
    absent: int = 0


def _dotenv_value(env_var: str) -> str | None:
    try:
        value = dotenv_values(".env").get(env_var)
    except (OSError, UnicodeDecodeError):
        return None
    return value if isinstance(value, str) and value else None


def _legacy_value(store: SecretStore, name: str) -> str | None:
    try:
        return store.get(name)
    except Exception:
        return None


def _provider_legacy_value(
    provider: ProviderName, legacy_store: SecretStore, environ: dict[str, str]
) -> str | None:
    env_var = PROVIDER_ENV_VARS[provider]
    return (
        environ.get(env_var)
        or _dotenv_value(env_var)
        or _legacy_value(legacy_store, provider.value)
    )


async def migrate_legacy_secrets_to_encrypted_db(
    *,
    repository: SQLiteRepository,
    encrypted_store: EncryptedDbSecretStore,
    legacy_store: SecretStore,
    environ_snapshot: dict[str, str],
) -> MigrationReport:
    """Import the eleven legacy slots once without deleting or overwriting them."""

    from freesearch.services.parallel_oauth import (
        ACCESS_SECRET_KEY,
        CLIENT_SECRET_KEY,
        DEVICE_SECRET_KEY,
        REFRESH_SECRET_KEY,
    )

    migrated = skipped_existing = absent = 0
    providers = (
        (item.value, _provider_legacy_value(item, legacy_store, environ_snapshot))
        for item in ProviderName
    )
    oauth_slots = (ACCESS_SECRET_KEY, REFRESH_SECRET_KEY, DEVICE_SECRET_KEY, CLIENT_SECRET_KEY)
    candidates = list(providers) + [
        (slot, _legacy_value(legacy_store, slot)) for slot in oauth_slots
    ]
    for name, legacy_value in candidates:
        existing = await repository.get_runtime_setting(ENCRYPTED_SECRET_PREFIX + name)
        if existing is not None:
            skipped_existing += 1
        elif legacy_value:
            await encrypted_store.set(name, legacy_value)
            migrated += 1
        else:
            absent += 1
    return MigrationReport(migrated, skipped_existing, absent)
