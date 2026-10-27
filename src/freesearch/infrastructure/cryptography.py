"""Local master-key handling and AES-GCM secret envelopes."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import secrets
from collections.abc import Sequence
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from pydantic import SecretStr

MASTER_KEY_ENV_VAR = "FREESEARCH_ENCRYPTION_KEY"
DEFAULT_KEY_FILE = Path.home() / ".local" / "share" / "freesearch" / ".secret_key"
PBKDF2_ITERATIONS = 300_000
_SALT_BYTES = 16
_KEY_BYTES = 32
_NONCE_BYTES = 12
logger = logging.getLogger(__name__)


@dataclass(frozen=True, repr=False)
class MasterKey:
    """AES-256 key whose representation never exposes its bytes."""

    key: bytes

    def __post_init__(self) -> None:
        if len(self.key) != _KEY_BYTES:
            raise ValueError("invalid master key")

    @property
    def key_id(self) -> str:
        """Stable non-secret identifier of this key (16 hex chars)."""

        return hmac.new(self.key, b"freesearch.master-key-id.v1", hashlib.sha256).hexdigest()[:16]

    def __repr__(self) -> str:
        return f"MasterKey(***, key_id={self.key_id!r})"


class SecretDecryptError(Exception):
    """An encrypted value cannot be safely decrypted."""

    def __init__(self) -> None:
        super().__init__("secret decryption failed")


def _derive_key_from_passphrase(
    passphrase: str, salt: bytes, *, iterations: int = PBKDF2_ITERATIONS
) -> bytes:
    """Derive an AES-256 key with the installation-specific PBKDF2 salt."""

    return hashlib.pbkdf2_hmac("sha256", passphrase.encode(), salt, iterations, dklen=_KEY_BYTES)


def _harden_parent(path: Path) -> None:
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(path, 0o700)


def _read_secret_file(path: Path, size: int, label: str) -> bytes:
    _harden_parent(path.parent)
    data = path.read_bytes()
    if len(data) != size:
        raise ValueError(f"invalid secret {label} file")
    if path.stat().st_mode & 0o777 != 0o600:
        logger.warning("repairing local secret file permissions")
        os.chmod(path, 0o600)
    return data


def _create_secret_file(path: Path, data: bytes) -> bool:
    """Atomically publish a completed 0600 file without overwriting a winner."""

    _harden_parent(path.parent)
    temporary = path.with_name(f".{path.name}.{secrets.token_hex(8)}.tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError:
            return False
        # Opening a directory fd fails on Windows (PermissionError); the file
        # data is already fsynced above, so the directory fsync is best-effort.
        with suppress(OSError):
            directory = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        return True
    finally:
        if temporary.exists():
            temporary.unlink()


def _load_or_create_salt(key_file: Path) -> bytes:
    salt_file = key_file.with_name(".secret_salt")
    if salt_file.exists():
        return _read_secret_file(salt_file, _SALT_BYTES, "salt")
    salt = secrets.token_bytes(_SALT_BYTES)
    if _create_secret_file(salt_file, salt):
        return salt
    return _read_secret_file(salt_file, _SALT_BYTES, "salt")


def load_or_create_master_key(
    *, key_file: Path | None = None, passphrase_env: str | None = None
) -> MasterKey:
    """Load a local key, or derive/create it without exposing key material."""

    path = key_file or DEFAULT_KEY_FILE
    passphrase = (
        passphrase_env if passphrase_env is not None else os.environ.get(MASTER_KEY_ENV_VAR)
    )
    if passphrase:
        return MasterKey(_derive_key_from_passphrase(passphrase, _load_or_create_salt(path)))
    if path.exists():
        return MasterKey(_read_secret_file(path, _KEY_BYTES, "key"))
    key = secrets.token_bytes(_KEY_BYTES)
    if _create_secret_file(path, key):
        return MasterKey(key)
    return MasterKey(_read_secret_file(path, _KEY_BYTES, "key"))


def _read_existing_salt(key_file: Path) -> bytes:
    salt_file = key_file.with_name(".secret_salt")
    if not salt_file.exists():
        raise FileNotFoundError("the master key salt file does not exist")
    return _read_secret_file(salt_file, _SALT_BYTES, "salt")


def load_existing_master_key(
    *, key_file: Path | None = None, passphrase_env: str | None = None
) -> MasterKey:
    """Load the installation key without ever creating key or salt material.

    Same sources as :func:`load_or_create_master_key` (passphrase plus the
    installation salt, or the key file), but a missing file raises
    ``FileNotFoundError`` instead of generating a new key.
    """

    path = key_file or DEFAULT_KEY_FILE
    passphrase = (
        passphrase_env if passphrase_env is not None else os.environ.get(MASTER_KEY_ENV_VAR)
    )
    if passphrase:
        return MasterKey(_derive_key_from_passphrase(passphrase, _read_existing_salt(path)))
    if not path.exists():
        raise FileNotFoundError("the master key file does not exist")
    return MasterKey(_read_secret_file(path, _KEY_BYTES, "key"))


def load_retired_master_keys(
    *,
    key_files: Sequence[Path],
    passphrases: Sequence[str],
    salt_key_file: Path,
    create_salt: bool = True,
) -> list[MasterKey]:
    """Load retired master keys for decrypting pre-rotation envelopes only.

    Retired key files must already exist and be exactly 32 bytes; this function
    never creates key material. Retired passphrases derive through PBKDF2 with
    the installation salt that lives beside the primary key file; with
    ``create_salt=False`` a missing salt raises ``FileNotFoundError``.
    """

    retired: list[MasterKey] = []
    for path in key_files:
        retired.append(MasterKey(_read_secret_file(path, _KEY_BYTES, "key")))
    if passphrases:
        salt = (
            _load_or_create_salt(salt_key_file)
            if create_salt
            else _read_existing_salt(salt_key_file)
        )
        for passphrase in passphrases:
            retired.append(MasterKey(_derive_key_from_passphrase(passphrase, salt)))
    return retired


def _aad(key_id: str, context: str) -> bytes:
    """Associated data binding one ciphertext to its slot and key id."""

    return json.dumps(["freesearch-secret", 2, key_id, context], separators=(",", ":")).encode()


class SecretCodec:
    """Versioned AES-256-GCM envelope codec for text secrets.

    Every envelope written is version 2: it carries the primary key id and is
    bound to its slot ``context`` through AES-GCM associated data, so a copied
    ciphertext never decrypts under a different slot name. Version-1 envelopes
    (no key id, no associated data) decrypt only when the caller opts in with
    ``allow_legacy`` for slots written before context binding existed.
    """

    def __init__(self, master: MasterKey, *, retired: Sequence[MasterKey] = ()) -> None:
        self._primary_key_id = master.key_id
        self._ciphers: dict[str, AESGCM] = {master.key_id: AESGCM(master.key)}
        for key in retired:
            if key.key_id not in self._ciphers:
                self._ciphers[key.key_id] = AESGCM(key.key)

    @property
    def primary_key_id(self) -> str:
        """Return the key id that stamps every newly written envelope."""

        return self._primary_key_id

    def encrypt(self, plaintext: str, *, context: str) -> str:
        """Return a v2 envelope bound to ``context`` under the primary key."""

        if not context:
            raise ValueError("envelope context must not be empty")
        nonce = secrets.token_bytes(_NONCE_BYTES)
        cipher = self._ciphers[self._primary_key_id]
        ciphertext = cipher.encrypt(nonce, plaintext.encode(), _aad(self._primary_key_id, context))
        return json.dumps(
            {
                "v": 2,
                "alg": "AES-256-GCM",
                "kid": self._primary_key_id,
                "nonce": base64.b64encode(nonce).decode(),
                "ct": base64.b64encode(ciphertext).decode(),
            },
            separators=(",", ":"),
        )

    def decrypt(self, envelope: str, *, context: str, allow_legacy: bool = False) -> SecretStr:
        """Decrypt one envelope bound to ``context``; fail closed otherwise."""

        if not context:
            raise ValueError("envelope context must not be empty")
        try:
            payload = json.loads(envelope)
            if not isinstance(payload, dict) or payload.get("alg") != "AES-256-GCM":
                raise ValueError
            version = payload.get("v")
            if version == 2:
                return self._decrypt_v2(payload, context)
            if version == 1:
                if not allow_legacy:
                    raise ValueError
                return self._decrypt_v1(payload)
            raise ValueError
        except (
            InvalidTag,
            KeyError,
            TypeError,
            UnicodeDecodeError,
            ValueError,
            json.JSONDecodeError,
        ):
            raise SecretDecryptError() from None

    def needs_rekey(self, envelope: str) -> bool:
        """Return whether an envelope predates the primary key or context binding."""

        try:
            payload = json.loads(envelope)
            if not isinstance(payload, dict) or payload.get("alg") != "AES-256-GCM":
                raise ValueError
            version = payload.get("v")
            if version == 1:
                return True
            if version != 2 or not isinstance(payload.get("kid"), str):
                raise ValueError
            return bool(payload["kid"] != self._primary_key_id)
        except (TypeError, ValueError, json.JSONDecodeError):
            raise SecretDecryptError() from None

    def _decrypt_v2(self, payload: dict[str, Any], context: str) -> SecretStr:
        kid = payload.get("kid")
        if not isinstance(kid, str):
            raise ValueError
        cipher = self._ciphers.get(kid)
        if cipher is None:
            raise ValueError
        nonce = base64.b64decode(payload["nonce"], validate=True)
        ciphertext = base64.b64decode(payload["ct"], validate=True)
        if len(nonce) != _NONCE_BYTES:
            raise ValueError
        return SecretStr(cipher.decrypt(nonce, ciphertext, _aad(kid, context)).decode())

    def _decrypt_v1(self, payload: dict[str, Any]) -> SecretStr:
        nonce = base64.b64decode(payload["nonce"], validate=True)
        ciphertext = base64.b64decode(payload["ct"], validate=True)
        if len(nonce) != _NONCE_BYTES:
            raise ValueError
        for cipher in self._ciphers.values():
            with suppress(InvalidTag):
                return SecretStr(cipher.decrypt(nonce, ciphertext, None).decode())
        raise InvalidTag
