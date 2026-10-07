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

from pydantic import AwareDatetime, Field, SecretStr

from freesearch.models.contracts import ContractModel


class AuthProvider(StrEnum):
    """Identity provider that owns an account."""

    LOCAL = "local"
    WORKOS = "workos"


class UserRole(StrEnum):
    """Account class that authorizes each control-plane surface."""

    ADMIN = "admin"
    DEVELOPER = "developer"
    AGENT = "agent"


#: Role of a registration that omits the role field.
DEFAULT_REGISTRATION_ROLE: UserRole = UserRole.AGENT

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
    """Verified account identity for one authenticated request.

    ``session_id`` identifies the session family the presented access JWT was
    issued for; the transport uses it for current-family logout and for the
    authoritative family check.
    """

    id: UUID
    email: str
    role: UserRole
    session_id: UUID
    is_active: bool
    is_superuser: bool
    is_verified: bool


class UserAccount(ContractModel):
    """Safe account projection for an Admin route and for the account screen.

    The projection carries the account identity and its authorization flags. It
    carries no password hash and no session family identifier.
    """

    id: UUID
    email: str
    role: UserRole
    is_active: bool
    is_superuser: bool
    is_verified: bool


class AuthFamily(ContractModel):
    """One refresh-token family: an absolute lifetime shared by its tokens.

    Rotation never extends ``expires_at``. ``revoked_at`` records logout, role
    change, reuse detection, or account deactivation.
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
