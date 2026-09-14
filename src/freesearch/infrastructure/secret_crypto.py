"""Local master-key handling and AES-GCM secret envelopes."""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import secrets
from dataclasses import dataclass
from pathlib import Path

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

    def __repr__(self) -> str:
        return "MasterKey(***)"


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


class SecretCodec:
    """Versioned AES-256-GCM envelope codec for text secrets."""

    def __init__(self, master: MasterKey) -> None:
        self._cipher = AESGCM(master.key)

    def encrypt(self, plaintext: str) -> str:
        nonce = secrets.token_bytes(_NONCE_BYTES)
        ciphertext = self._cipher.encrypt(nonce, plaintext.encode(), None)
        return json.dumps(
            {
                "v": 1,
                "alg": "AES-256-GCM",
                "nonce": base64.b64encode(nonce).decode(),
                "ct": base64.b64encode(ciphertext).decode(),
            },
            separators=(",", ":"),
        )

    def decrypt(self, envelope: str) -> SecretStr:
        try:
            payload = json.loads(envelope)
            if (
                not isinstance(payload, dict)
                or payload.get("v") != 1
                or payload.get("alg") != "AES-256-GCM"
            ):
                raise ValueError
            nonce = base64.b64decode(payload["nonce"], validate=True)
            ciphertext = base64.b64decode(payload["ct"], validate=True)
            if len(nonce) != _NONCE_BYTES:
                raise ValueError
            return SecretStr(self._cipher.decrypt(nonce, ciphertext, None).decode())
        except (
            InvalidTag,
            KeyError,
            TypeError,
            UnicodeDecodeError,
            ValueError,
            json.JSONDecodeError,
        ):
            raise SecretDecryptError() from None
