"""Shared sentinels and Red-gate loaders for the encrypted-DB secrets suites.

Tester-owned: production code must never import this module. Every loader
fails with an explicit ``RED`` assertion while the encrypted-DB slice from
``PLAN.md`` is unimplemented, so the acceptance suites fail cleanly instead
of erroring obscurely at collection time.
"""

from __future__ import annotations

import inspect
from importlib import import_module
from typing import Any

#: Unique greppable provider-key sentinels (AC-3/AC-5). Never real credentials.
SENTINEL_PROVIDER_KEYS: dict[str, str] = {
    "exa": "EXA-SENTINEL-key-9f31c4aab27e",
    "firecrawl": "FIRECRAWL-SENTINEL-key-51bd80c2e913",
    "tavily": "TAVILY-SENTINEL-key-77aa02dfc4b6",
    "parallel": "PARALLEL-SENTINEL-key-2c9e51a8740d",
    "you": "YOU-SENTINEL-key-8d14f6b3a952",
    "brave": "BRAVE-SENTINEL-key-40ce97d15ab8",
    "keenable": "KEENABLE-SENTINEL-key-b6f2d381c4e7",
    "tinyfish": "TINYFISH-SENTINEL-key-8c42b91ea35f",
}

#: Passphrase sentinel for master-key tests (AC-1). Never an AES key itself.
SENTINEL_PASSPHRASE = "correct horse passphrase for acceptance 9f31"

#: Wrong-key passphrase sentinel (AC-4/AC-9). Must differ from the above.
SENTINEL_WRONG_PASSPHRASE = "wrong horse passphrase for acceptance 51bd"

# The legacy-secret census (``migrate_legacy_secrets_to_encrypted_db``) was a
# no-op deleted by A4 (API-11); only the store itself is required now.
_STORE_ATTRS = (
    "ENCRYPTED_SECRET_PREFIX",
    "EncryptedDbSecretStore",
)


def require_cryptography() -> Any:
    """Return the ``cryptography`` module or fail Red while it is missing."""

    try:
        return import_module("freesearch.infrastructure.cryptography")
    except ImportError as exc:
        raise AssertionError(
            "RED (AC-1/AC-2/AC-4): freesearch.infrastructure.cryptography "
            "is not implemented yet (PLAN.md section 2a)"
        ) from exc


def require_encrypted_store_module() -> Any:
    """Return the module hosting the encrypted store or fail Red.

    ``PLAN.md`` prefers a new ``encrypted_store.py`` but allows the symbols
    to live in ``secrets.py``; accept whichever module exposes both.
    """

    for name in (
        "freesearch.infrastructure.encrypted_store",
        "freesearch.infrastructure.secrets",
    ):
        try:
            module = import_module(name)
        except ImportError:
            continue
        if all(hasattr(module, attr) for attr in _STORE_ATTRS):
            return module
    raise AssertionError(
        "RED (AC-3/AC-6): neither freesearch.infrastructure.encrypted_store "
        "nor freesearch.infrastructure.secrets exposes ENCRYPTED_SECRET_PREFIX/"
        "EncryptedDbSecretStore "
        "(PLAN.md section 2b/4)"
    )


async def maybe_await(value: Any) -> Any:
    """Await ``value`` when the implementation chose an async seam.

    ``PLAN.md`` section 5 leaves the sync/async store shape to the Developer;
    the behavioral contracts below hold either way, so tests adapt on the
    mechanism while asserting exact values, precedence, and payloads.
    """

    if inspect.isawaitable(value):
        return await value
    return value


def assert_no_sentinels(haystack: str, sentinels: tuple[str, ...], where: str) -> None:
    """Fail listing every sentinel substring leaked into ``haystack``."""

    leaked = [secret for secret in sentinels if secret and secret in haystack]
    assert not leaked, f"plaintext leak in {where}: {leaked}"
