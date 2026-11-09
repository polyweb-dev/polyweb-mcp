"""Account contracts shared by persistence, services, and transports.

Pure data plus two pure helpers. No OpenTelemetry, database, HTTP, or
fastapi-users import belongs here, so every layer can depend on this module
without creating a cycle.

Credentials stay outside :class:`UserPrincipal`: a principal carries the
verified account identity and its session family, never a token, digest, or
password hash. :class:`AuthTokens` holds the raw credential pair and is the only
contract allowed to carry secret material, and its fields are ``SecretStr`` so a
repr or an ordinary dump cannot reveal them.
"""

from datetime import datetime
from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, ConfigDict, Field, SecretStr, field_validator, model_validator

from polyweb.models.contracts import ContractModel


class AuthProvider(StrEnum):
    """Identity provider that owns an account."""

    LOCAL = "local"
    WORKOS = "workos"


#: Refresh credentials are URL-safe base64 of 32 random bytes.
REFRESH_TOKEN_BYTES: int = 32
REFRESH_TOKEN_LENGTH: int = 43


def normalize_email(email: str) -> str:
    """Return the canonical storage form of an email address.

    Local account creation and lookup both use this helper, so the
    case-insensitive unique index can never be bypassed by a different casing.
    """

    return email.strip().casefold()


class UserPrincipal(ContractModel):
    """Verified human identity for one authenticated request.

    ``session_id`` identifies the session family the presented access JWT was
    issued for; the transport uses it for current-family logout and for the
    authoritative family check. The principal carries no role or privilege
    flag: authority always comes from live scoped role assignments.
    """

    id: UUID
    email: str
    session_id: UUID
    is_active: bool
    is_verified: bool


def _require_provider_identity(
    auth_provider: AuthProvider, auth_provider_id: str | None, hashed_password: str | None
) -> None:
    """Enforce the local/WorkOS identity invariants shared by the account contracts."""

    if auth_provider is AuthProvider.LOCAL and auth_provider_id is not None:
        raise ValueError("Local user must not have auth_provider_id")
    if auth_provider is AuthProvider.WORKOS:
        if hashed_password is not None:
            raise ValueError("WorkOS user must not have hashed_password")
        if not auth_provider_id or not auth_provider_id.strip():
            raise ValueError("WorkOS user requires a non-empty auth_provider_id")


class UserAccountCreate(ContractModel):
    """Trusted creation contract of one ordinary human account.

    A local account needs a password hash and no provider id; a WorkOS account
    needs a provider id and no password hash. There is no role, account-type or
    privilege field: system authority is granted only through an explicit
    system role assignment.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    email: str
    auth_provider: AuthProvider = AuthProvider.LOCAL
    auth_provider_id: str | None = None
    hashed_password: str | None = Field(default=None, repr=False)
    is_active: bool = True
    is_verified: bool = False
    username: str | None = Field(default=None, min_length=1, max_length=64)
    first_name: str | None = Field(default=None, min_length=1, max_length=100)
    last_name: str | None = Field(default=None, min_length=1, max_length=100)

    @field_validator("email")
    @classmethod
    def _normalize_email(cls, email: str) -> str:
        return normalize_email(email)

    @model_validator(mode="after")
    def _validate_provider_invariants(self) -> "UserAccountCreate":
        if self.auth_provider is AuthProvider.LOCAL and (
            not self.hashed_password or not self.hashed_password.strip()
        ):
            raise ValueError("Local user requires a non-empty hashed_password")
        _require_provider_identity(self.auth_provider, self.auth_provider_id, self.hashed_password)
        return self


class UserAccount(ContractModel):
    """The one safe projection of a human account.

    Registration, ``GET /users/me``, account provisioning and deactivation all
    return this shape. It carries identity, provider, profile and status
    fields, and no password hash, session family, role or privilege flag.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", from_attributes=True)

    id: UUID
    email: str
    auth_provider: AuthProvider = AuthProvider.LOCAL
    auth_provider_id: str | None = None
    username: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    is_active: bool
    is_verified: bool

    @field_validator("email")
    @classmethod
    def _normalize_email(cls, email: str) -> str:
        return normalize_email(email)

    @model_validator(mode="after")
    def _validate_provider_invariants(self) -> "UserAccount":
        _require_provider_identity(self.auth_provider, self.auth_provider_id, None)
        return self


class AuthFamily(ContractModel):
    """One refresh-token family: an absolute lifetime shared by its tokens.

    Rotation never extends ``expires_at``. ``revoked_at`` records logout, system
    role revocation, reuse detection, or account deactivation.
    """

    id: UUID
    user_id: UUID
    expires_at: AwareDatetime
    revoked_at: AwareDatetime | None = None


class AuthTokens(ContractModel):
    """Credential pair returned by login and by protected refresh.

    The access token is a JWT for the API and MCP surfaces. The refresh token is
    an opaque rotating credential accepted only by ``POST /auth/jwt/refresh``.
    """

    access_token: SecretStr = Field(repr=False)
    refresh_token: SecretStr = Field(repr=False)
    token_type: Literal["bearer"] = "bearer"
    expires_in: int = Field(gt=0)
    refresh_expires_in: int = Field(gt=0)


def family_is_live(family: AuthFamily, now: datetime) -> bool:
    """Return whether a family can still authorize a credential."""

    return family.revoked_at is None and family.expires_at > now
