"""Provider credential instance contracts (P08).

System-owned credential instances, project-private credential instances, and
explicit per-project grants on system credentials. These are wire/domain DTOs
only: secret material enters through ``SecretStr`` fields and is never part of
any read projection.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import datetime
from enum import StrEnum
from typing import Final
from uuid import UUID

from pydantic import ConfigDict, Field, SecretStr, field_validator, model_validator

from polyweb.models.contracts import ContractModel
from polyweb.models.projects import CredentialOwnerScope
from polyweb.models.schema_enums import OAuthGrantStatus

_PROVIDER_TYPE_PATTERN = re.compile(r"[a-z0-9_-]{1,32}")
_SECRET_MAX_LENGTH: Final[int] = 4096


class CredentialOperation(StrEnum):
    """Operations a grant can permit on a system credential."""

    SEARCH = "search"
    FETCH = "fetch"


class CredentialAuthMode(StrEnum):
    """Authentication modes a credential instance can hold.

    An ``api_key`` credential stores its secret in the generation slot. An
    ``oauth`` credential stores no secret at creation: its tokens arrive
    through the per-credential OAuth device flow.
    """

    API_KEY = "api_key"
    OAUTH = "oauth"


class CredentialStatus(StrEnum):
    """Lifecycle state of a credential instance."""

    ACTIVE = "active"
    DELETED = "deleted"


#: Operations implicitly granted to the owning project of a private credential.
ALL_CREDENTIAL_OPERATIONS: Final[frozenset[CredentialOperation]] = frozenset(CredentialOperation)


def _validate_secret(value: SecretStr) -> SecretStr:
    stripped = value.get_secret_value().strip()
    if not stripped:
        raise ValueError("secret must not be empty")
    if len(stripped) > _SECRET_MAX_LENGTH:
        raise ValueError(f"secret must be at most {_SECRET_MAX_LENGTH} characters")
    return SecretStr(stripped)


class CredentialCreate(ContractModel):
    """Request to create a provider credential instance.

    ``secret`` is required for ``api_key`` credentials and forbidden for
    ``oauth`` credentials, which receive tokens through the device flow.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    provider_type: str
    label: str = Field(min_length=1, max_length=100)
    auth_mode: CredentialAuthMode = CredentialAuthMode.API_KEY
    secret: SecretStr | None = None

    @field_validator("provider_type")
    @classmethod
    def _validate_provider_type(cls, value: str) -> str:
        if not _PROVIDER_TYPE_PATTERN.fullmatch(value):
            raise ValueError(
                "provider_type must be a lowercase identifier of 1-32 characters from [a-z0-9_-]"
            )
        return value

    @field_validator("label")
    @classmethod
    def _validate_label(cls, value: str) -> str:
        if any(unicodedata.category(character).startswith("C") for character in value):
            raise ValueError("label must not contain control characters")
        return value

    @field_validator("secret")
    @classmethod
    def _validate_secret_field(cls, value: SecretStr | None) -> SecretStr | None:
        return None if value is None else _validate_secret(value)

    @model_validator(mode="after")
    def _validate_secret_for_auth_mode(self) -> CredentialCreate:
        if self.auth_mode is CredentialAuthMode.API_KEY and self.secret is None:
            raise ValueError("an api_key credential requires a secret")
        if self.auth_mode is CredentialAuthMode.OAUTH and self.secret is not None:
            raise ValueError("an oauth credential receives its tokens through the device flow")
        return self


class CredentialRotate(ContractModel):
    """Request to rotate a credential to a new generation with a fresh secret."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    expected_generation: int = Field(ge=1)
    secret: SecretStr

    @field_validator("secret")
    @classmethod
    def _validate_secret_field(cls, value: SecretStr) -> SecretStr:
        return _validate_secret(value)


class CredentialGrantUpsert(ContractModel):
    """Request to set the permitted operations of one project grant."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    permitted_operations: frozenset[CredentialOperation] = Field(min_length=1)


class ProjectCredentialRead(ContractModel):
    """The only project-facing projection of a credential instance.

    A project sees its own active private credentials and the active system
    credentials granted to it. Ownership internals (owning project, creator,
    timestamps, other grants, generations of granted system credentials) never
    cross this boundary.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: UUID
    provider_type: str
    owner_scope: CredentialOwnerScope
    label: str
    auth_mode: str
    status: str
    permitted_operations: frozenset[CredentialOperation]
    can_manage: bool
    generation: int | None

    @model_validator(mode="after")
    def _validate_system_projection(self) -> ProjectCredentialRead:
        if self.owner_scope is CredentialOwnerScope.SYSTEM:
            if self.can_manage:
                raise ValueError("a project cannot manage a system credential")
            if self.generation is not None:
                raise ValueError("a system credential projection hides its generation")
        return self


class CredentialOAuthDeviceRead(ContractModel):
    """Public view of a started device flow.

    Only the code the human types and where to type it; the device code, the
    client secret and every token stay in encrypted slots and never appear.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    user_code: str
    verification_uri: str
    interval: int = Field(ge=1)
    expires_in: int = Field(ge=1)


class CredentialOAuthStatusRead(ContractModel):
    """Connection state of one credential's OAuth grant; never token material.

    ``status`` is ``disconnected`` when no flow has ever started. ``interval``
    is set only on a poll response that is still ``pending``: the seconds to
    wait before the next poll.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    credential_id: UUID
    status: OAuthGrantStatus
    scopes: str | None = None
    access_expires_at: datetime | None = None
    connected_at: datetime | None = None
    refreshed_at: datetime | None = None
    disconnected_at: datetime | None = None
    last_error_code: str | None = None
    interval: int | None = Field(default=None, ge=1)


__all__ = [
    "ALL_CREDENTIAL_OPERATIONS",
    "CredentialAuthMode",
    "CredentialCreate",
    "CredentialGrantUpsert",
    "CredentialOAuthDeviceRead",
    "CredentialOAuthStatusRead",
    "CredentialOperation",
    "CredentialRotate",
    "CredentialStatus",
    "ProjectCredentialRead",
]
