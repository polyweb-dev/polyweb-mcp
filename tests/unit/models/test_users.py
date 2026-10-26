"""Unit tests for account contracts (P1, PLAN Section 11)."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from pydantic import SecretStr, ValidationError

import freesearch.models.users as users_module
from freesearch.models.users import (
    REFRESH_TOKEN_BYTES,
    REFRESH_TOKEN_LENGTH,
    AuthFamily,
    AuthProvider,
    AuthTokens,
    UserAccount,
    UserAccountCreate,
    UserPrincipal,
    family_is_live,
    normalize_email,
)


def test_auth_provider_values() -> None:
    assert AuthProvider.LOCAL.value == "local"
    assert AuthProvider.WORKOS.value == "workos"
    assert set(AuthProvider) == {AuthProvider.LOCAL, AuthProvider.WORKOS}


def test_user_roles_and_default() -> None:
    # A1 replacement: the legacy admin/developer/agent vocabulary and its
    # registration default are gone from the account contracts.
    assert not hasattr(users_module, "UserRole")
    assert not hasattr(users_module, "DEFAULT_REGISTRATION_ROLE")
    for model in (UserPrincipal, UserAccount, UserAccountCreate):
        assert "role" not in model.model_fields
        assert "is_superuser" not in model.model_fields


@pytest.mark.parametrize("field", ["role", "is_superuser", "account_type", "system_role"])
def test_account_contracts_reject_privilege_fields(field: str) -> None:
    with pytest.raises(ValidationError):
        UserPrincipal.model_validate(
            {
                "id": uuid4(),
                "email": "agent@example.com",
                "session_id": uuid4(),
                "is_active": True,
                "is_verified": False,
                field: "admin",
            }
        )
    with pytest.raises(ValidationError):
        UserAccount.model_validate(
            {
                "id": uuid4(),
                "email": "agent@example.com",
                "is_active": True,
                "is_verified": False,
                field: True,
            }
        )
    with pytest.raises(ValidationError):
        UserAccountCreate.model_validate(
            {"email": "agent@example.com", "hashed_password": "hash", field: "admin"}
        )


def test_user_account_create_hides_password_hash_in_repr() -> None:
    create = UserAccountCreate(email="Agent@Example.com", hashed_password="secret-hash-value")
    assert create.email == "agent@example.com"
    assert "secret-hash-value" not in repr(create)


def test_refresh_constants() -> None:
    assert REFRESH_TOKEN_BYTES == 32
    assert REFRESH_TOKEN_LENGTH == 43


def test_normalize_email_strips_and_casefolds() -> None:
    assert normalize_email("Ops@Example.COM") == "ops@example.com"
    assert normalize_email("  Agent@Example.com  ") == "agent@example.com"


def test_user_principal_carries_session_identity() -> None:
    user_id = uuid4()
    session_id = uuid4()
    principal = UserPrincipal(
        id=user_id,
        email="agent@example.com",
        session_id=session_id,
        is_active=True,
        is_verified=False,
    )
    assert principal.id == user_id
    assert principal.session_id == session_id
    assert "role" not in principal.model_dump()
    assert "is_superuser" not in principal.model_dump()
    assert principal.model_dump()["id"] == user_id


def test_auth_family_live_only_without_revocation_and_future_expiry() -> None:
    now = datetime.now(UTC)
    live = AuthFamily(id=uuid4(), user_id=uuid4(), expires_at=now + timedelta(seconds=60))
    revoked = AuthFamily(
        id=uuid4(),
        user_id=uuid4(),
        expires_at=now + timedelta(seconds=60),
        revoked_at=now,
    )
    expired = AuthFamily(id=uuid4(), user_id=uuid4(), expires_at=now - timedelta(seconds=1))
    assert family_is_live(live, now) is True
    assert family_is_live(revoked, now) is False
    assert family_is_live(expired, now) is False


def test_auth_tokens_mask_secrets_and_require_positive_lifetimes() -> None:
    tokens = AuthTokens(
        access_token=SecretStr("access-123"),
        refresh_token=SecretStr("refresh-123"),
        expires_in=900,
        refresh_expires_in=604800,
    )
    assert tokens.token_type == "bearer"
    assert "access-123" not in repr(tokens)
    assert "refresh-123" not in repr(tokens)
    assert tokens.model_dump()["token_type"] == "bearer"


def test_auth_tokens_reject_non_positive_lifetimes() -> None:
    with pytest.raises(ValidationError):
        AuthTokens(
            access_token=SecretStr("a"),
            refresh_token=SecretStr("r"),
            expires_in=0,
            refresh_expires_in=604800,
        )
    with pytest.raises(ValidationError):
        AuthTokens(
            access_token=SecretStr("a"),
            refresh_token=SecretStr("r"),
            expires_in=900,
            refresh_expires_in=-1,
        )
