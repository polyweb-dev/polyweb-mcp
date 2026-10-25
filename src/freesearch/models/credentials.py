"""Provider credential instance contracts (P08).

System-owned credential instances, project-private credential instances, and
explicit per-project grants on system credentials. These are wire/domain DTOs
only: secret material enters through ``SecretStr`` fields and is never part of
any read projection.
"""

from __future__ import annotations

import re
import unicodedata
from enum import StrEnum
from typing import Final
from uuid import UUID

from pydantic import ConfigDict, Field, SecretStr, field_validator, model_validator

from freesearch.models.contracts import ContractModel
from freesearch.models.projects import CredentialOwnerScope

_PROVIDER_TYPE_PATTERN = re.compile(r"[a-z0-9_-]{1,32}")
_SECRET_MAX_LENGTH: Final[int] = 4096


class CredentialOperation(StrEnum):
    """Operations a grant can permit on a system credential."""

    SEARCH = "search"
    FETCH = "fetch"


class CredentialAuthMode(StrEnum):
    """Authentication modes a credential instance can hold."""

    API_KEY = "api_key"


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
    """Request to create a provider credential instance."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    provider_type: str
    label: str = Field(min_length=1, max_length=100)
    auth_mode: CredentialAuthMode = CredentialAuthMode.API_KEY
    secret: SecretStr

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
    def _validate_secret_field(cls, value: SecretStr) -> SecretStr:
        return _validate_secret(value)


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


__all__ = [
    "ALL_CREDENTIAL_OPERATIONS",
    "CredentialAuthMode",
    "CredentialCreate",
    "CredentialGrantUpsert",
    "CredentialOperation",
    "CredentialRotate",
    "CredentialStatus",
    "ProjectCredentialRead",
]
