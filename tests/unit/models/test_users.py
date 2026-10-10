"""Unit tests for account contracts (P1, PLAN Section 11)."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from pydantic import SecretStr, ValidationError

from freesearch.models.users import (
    DEFAULT_REGISTRATION_ROLE,
    REFRESH_TOKEN_BYTES,
    REFRESH_TOKEN_LENGTH,
    AuthFamily,
    AuthProvider,
    AuthTokens,
    UserPrincipal,
    UserRole,
    family_is_live,
    normalize_email,
)


def test_auth_provider_values() -> None:
    assert AuthProvider.LOCAL.value == "local"
    assert AuthProvider.WORKOS.value == "workos"
    assert set(AuthProvider) == {AuthProvider.LOCAL, AuthProvider.WORKOS}


def test_user_roles_and_default() -> None:
    assert UserRole.ADMIN.value == "admin"
    assert UserRole.DEVELOPER.value == "developer"
    assert UserRole.AGENT.value == "agent"
    assert DEFAULT_REGISTRATION_ROLE is UserRole.AGENT


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
        role=UserRole.AGENT,
        session_id=session_id,
        is_active=True,
        is_superuser=False,
        is_verified=False,
    )
    assert principal.id == user_id
    assert principal.session_id == session_id
    assert principal.role is UserRole.AGENT
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
