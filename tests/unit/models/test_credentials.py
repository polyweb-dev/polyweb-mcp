"""Unit tests for the P08 credential contracts."""

from __future__ import annotations

from uuid import uuid4

import pytest
from pydantic import SecretStr, ValidationError

from polyweb.models.credentials import (
    ALL_CREDENTIAL_OPERATIONS,
    CredentialAuthMode,
    CredentialCreate,
    CredentialGrantUpsert,
    CredentialOperation,
    CredentialRotate,
    ProjectCredentialRead,
)
from polyweb.models.projects import CredentialOwnerScope


def _create(**overrides: object) -> CredentialCreate:
    payload: dict[str, object] = {
        "provider_type": "tavily",
        "label": "primary",
        "secret": "fake-p08-secret-value",
    }
    payload.update(overrides)
    return CredentialCreate.model_validate(payload)


# --- CredentialCreate / CredentialRotate validation ------------------------


def test_empty_and_whitespace_secrets_rejected() -> None:
    with pytest.raises(ValidationError):
        _create(secret="")
    with pytest.raises(ValidationError):
        _create(secret="   \t\n  ")
    with pytest.raises(ValidationError):
        CredentialRotate(expected_generation=1, secret=SecretStr("   "))


def test_secret_is_stripped_on_store() -> None:
    assert _create(secret="  k\n").secret.get_secret_value() == "k"
    rotate = CredentialRotate(expected_generation=1, secret=SecretStr("\tpadded-secret  "))
    assert rotate.secret.get_secret_value() == "padded-secret"


def test_oversized_secret_rejected() -> None:
    with pytest.raises(ValidationError):
        _create(secret="x" * 4097)


def test_empty_whitespace_and_control_labels_rejected() -> None:
    with pytest.raises(ValidationError):
        _create(label="   ")
    with pytest.raises(ValidationError):
        _create(label="bad\x00label")
    with pytest.raises(ValidationError):
        _create(label="bad\nlabel")
    with pytest.raises(ValidationError):
        _create(label="x" * 101)


@pytest.mark.parametrize(
    "provider_type",
    ["", "Tavily", "tavily!", "tavily key", "t" * 33, "exa/tinyfish"],
)
def test_bad_provider_type_format_rejected(provider_type: str) -> None:
    with pytest.raises(ValidationError):
        _create(provider_type=provider_type)


def test_provider_type_format_is_checked_not_membership() -> None:
    """Format validation accepts any lowercase identifier; the service gates membership."""

    created = _create(provider_type="made-up-provider")
    assert created.provider_type == "made-up-provider"


def test_extra_fields_rejected() -> None:
    with pytest.raises(ValidationError):
        CredentialCreate.model_validate(
            {
                "provider_type": "tavily",
                "label": "primary",
                "secret": "fake-p08-secret-value",
                "unexpected": "nope",
            }
        )
    with pytest.raises(ValidationError):
        CredentialRotate.model_validate(
            {"expected_generation": 1, "secret": "fake-p08", "extra": 1}
        )
    with pytest.raises(ValidationError):
        CredentialGrantUpsert.model_validate({"permitted_operations": ["search"], "extra": True})


def test_secret_never_appears_in_repr_str_or_json() -> None:
    secret_value = "fake-p08-super-secret-material"
    created = _create(secret=secret_value)
    for surface in (repr(created), str(created), created.model_dump_json()):
        assert secret_value not in surface
    rotate = CredentialRotate(expected_generation=2, secret=SecretStr(secret_value))
    for surface in (repr(rotate), str(rotate), rotate.model_dump_json()):
        assert secret_value not in surface


def test_rotate_requires_positive_generation() -> None:
    with pytest.raises(ValidationError):
        CredentialRotate(expected_generation=0, secret=SecretStr("fake-p08"))


def test_auth_mode_defaults_to_api_key() -> None:
    assert _create().auth_mode is CredentialAuthMode.API_KEY


# --- CredentialGrantUpsert --------------------------------------------------


def test_grant_requires_at_least_one_operation() -> None:
    with pytest.raises(ValidationError):
        CredentialGrantUpsert(permitted_operations=frozenset())


def test_grant_accepts_only_search_and_fetch() -> None:
    grant = CredentialGrantUpsert(
        permitted_operations=frozenset({CredentialOperation.SEARCH, CredentialOperation.FETCH})
    )
    assert grant.permitted_operations == ALL_CREDENTIAL_OPERATIONS
    with pytest.raises(ValidationError):
        CredentialGrantUpsert.model_validate({"permitted_operations": ["delete"]})
    with pytest.raises(ValidationError):
        CredentialGrantUpsert.model_validate({"permitted_operations": ["admin"]})


# --- ProjectCredentialRead --------------------------------------------------


def _project_read(**overrides: object) -> ProjectCredentialRead:
    payload: dict[str, object] = {
        "id": uuid4(),
        "provider_type": "tavily",
        "owner_scope": CredentialOwnerScope.SYSTEM,
        "label": "shared",
        "auth_mode": "api_key",
        "status": "active",
        "permitted_operations": frozenset({CredentialOperation.SEARCH}),
        "can_manage": False,
        "generation": None,
    }
    payload.update(overrides)
    return ProjectCredentialRead.model_validate(payload)


def test_project_read_is_the_only_projection_shape() -> None:
    read = _project_read()
    assert set(read.model_dump()) == {
        "id",
        "provider_type",
        "owner_scope",
        "label",
        "auth_mode",
        "status",
        "permitted_operations",
        "can_manage",
        "generation",
    }


def test_system_projection_rejects_can_manage() -> None:
    with pytest.raises(ValidationError):
        _project_read(can_manage=True)


def test_system_projection_rejects_generation() -> None:
    with pytest.raises(ValidationError):
        _project_read(generation=3)


def test_project_projection_allows_manage_and_generation() -> None:
    read = _project_read(
        owner_scope=CredentialOwnerScope.PROJECT,
        can_manage=True,
        generation=2,
    )
    assert read.can_manage is True
    assert read.generation == 2


# --- Owned keyless contract (TASK-000065) ------------------------------------
#
# A fresh signup can create an owned keyless/free-tier credential without an
# API key and then assign a pool for it. Keyed/OAuth guards below stay green
# through that change.


def test_keyless_auth_mode_is_supported() -> None:
    assert CredentialAuthMode("keyless") is CredentialAuthMode.KEYLESS


def test_keyless_credential_create_needs_no_secret() -> None:
    created = CredentialCreate.model_validate(
        {
            "provider_type": "keenable",
            "label": "free-tier",
            "auth_mode": "keyless",
        }
    )
    assert created.auth_mode is CredentialAuthMode.KEYLESS
    assert created.secret is None


def test_keyless_vault_key_create_needs_no_secret() -> None:
    from polyweb.models.vault import VaultKeyCreate

    created = VaultKeyCreate.model_validate(
        {
            "provider_type": "keenable",
            "label": "free-tier",
            "auth_mode": "keyless",
        }
    )
    assert created.auth_mode is CredentialAuthMode.KEYLESS
    assert created.secret is None


def test_api_key_credential_still_requires_secret() -> None:
    with pytest.raises(ValidationError):
        CredentialCreate.model_validate(
            {
                "provider_type": "tavily",
                "label": "keyed",
                "auth_mode": "api_key",
            }
        )


def test_oauth_credential_still_forbids_secret() -> None:
    with pytest.raises(ValidationError):
        CredentialCreate.model_validate(
            {
                "provider_type": "tavily",
                "label": "oauth",
                "auth_mode": "oauth",
                "secret": "fake-p08-secret-value",
            }
        )


def test_oauth_credential_without_secret_still_valid() -> None:
    created = CredentialCreate.model_validate(
        {
            "provider_type": "tavily",
            "label": "oauth",
            "auth_mode": "oauth",
        }
    )
    assert created.auth_mode is CredentialAuthMode.OAUTH
    assert created.secret is None


def test_keyless_credential_forbids_secret() -> None:
    with pytest.raises(ValidationError):
        CredentialCreate.model_validate(
            {
                "provider_type": "keenable",
                "label": "free-tier",
                "auth_mode": "keyless",
                "secret": "fake-p08-secret-value",
            }
        )


def test_keyless_create_validation_rejects_unsupported_provider() -> None:
    from polyweb.services.credentials import CredentialService, CredentialValidationError

    with pytest.raises(CredentialValidationError, match="does not support keyless"):
        CredentialService._validate_create(
            CredentialCreate.model_validate(
                {
                    "provider_type": "exa",
                    "label": "free-tier",
                    "auth_mode": "keyless",
                }
            )
        )


def test_keyless_create_validation_accepts_supported_providers() -> None:
    from polyweb.services.credentials import CredentialService

    for provider in ("keenable", "tavily"):
        CredentialService._validate_create(
            CredentialCreate.model_validate(
                {
                    "provider_type": provider,
                    "label": "free-tier",
                    "auth_mode": "keyless",
                }
            )
        )
