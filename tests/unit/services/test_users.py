"""Unit tests for account policy without database I/O (P2, P7, PLAN Section 11)."""

import secrets
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi.security import OAuth2PasswordRequestForm
from fastapi_users import exceptions
from fastapi_users.password import PasswordHelper
from pydantic import SecretStr

from freesearch.models.users import AuthFamily, UserPrincipal, UserRole
from freesearch.persistence.users import UserRow
from freesearch.services.users import (
    AUTH_TOKEN_ALGORITHM,
    AUTH_TOKEN_AUDIENCE,
    PASSWORD_RULE_MESSAGE,
    AuthConfigurationError,
    SessionJWTStrategy,
    UserManager,
    get_jwt_strategy,
    has_role,
    refresh_token_digest,
)
from tests.fixtures import auth as auth_fixtures

_HELPER = PasswordHelper()
_STRONG = "StrongPass123!x-Unit"


def _manager(user_db: Any = None) -> UserManager:
    return UserManager(user_db if user_db is not None else AsyncMock())


def _row(**overrides: Any) -> UserRow:
    base: dict[str, Any] = {
        "id": uuid4(),
        "email": "unit@example.com",
        "hashed_password": _HELPER.hash(_STRONG),
        "is_active": True,
        "is_superuser": False,
        "is_verified": False,
        "auth_provider": "local",
        "auth_provider_id": None,
        "role": "agent",
    }
    base.update(overrides)
    return UserRow(**base)


def _credentials(username: str, password: str) -> OAuth2PasswordRequestForm:
    return OAuth2PasswordRequestForm(username=username, password=password)


async def test_validate_password_accepts_rule_shape() -> None:
    await _manager().validate_password(_STRONG, object())  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "password",
    [
        "short1!A",
        "alllowercase123!",
        "ALLUPPERCASE123!",
        "NoDigitsHere!xAa",
        "NoSpecial123Aax",
        "x" * 129,
    ],
)
async def test_validate_password_rejects_each_shape(password: str) -> None:
    with pytest.raises(exceptions.InvalidPasswordException) as error:
        await _manager().validate_password(password, object())  # type: ignore[arg-type]

    assert error.value.reason == PASSWORD_RULE_MESSAGE
    assert password not in str(error.value)


async def test_authenticate_unknown_email_returns_none() -> None:
    user_db = AsyncMock()
    user_db.get_by_email.side_effect = exceptions.UserNotExists()

    assert await _manager(user_db).authenticate(_credentials("ghost@example.com", _STRONG)) is None
    user_db.get_by_email.assert_awaited_once()


async def test_authenticate_workos_row_returns_none() -> None:
    user_db = AsyncMock()
    user_db.get_by_email.return_value = _row(auth_provider="workos", hashed_password=None)

    assert await _manager(user_db).authenticate(_credentials("ext@example.com", _STRONG)) is None


async def test_authenticate_wrong_password_returns_none() -> None:
    user_db = AsyncMock()
    user_db.get_by_email.return_value = _row()

    assert (
        await _manager(user_db).authenticate(_credentials("unit@example.com", "WrongPass123!x-No"))
        is None
    )


async def test_authenticate_unreadable_hash_fails_closed() -> None:
    user_db = AsyncMock()
    user_db.get_by_email.return_value = _row(hashed_password="not-a-hash")

    assert await _manager(user_db).authenticate(_credentials("unit@example.com", _STRONG)) is None


async def test_authenticate_valid_credentials_returns_account() -> None:
    expected = _row()
    user_db = AsyncMock()
    user_db.get_by_email.return_value = expected

    assert (
        await _manager(user_db).authenticate(_credentials("unit@example.com", _STRONG)) is expected
    )


def test_refresh_token_digest_accepts_urlsafe_32_bytes() -> None:
    token = secrets.token_urlsafe(32)

    digest = refresh_token_digest(token)

    assert digest is not None
    assert len(digest) == 64
    assert digest not in token


@pytest.mark.parametrize(
    "token", ["", "short", "x" * 42, "x" * 44, "!" * 43, "space in token" + "x" * 29]
)
def test_refresh_token_digest_rejects_malformed_values(token: str) -> None:
    assert refresh_token_digest(token) is None


def test_has_role_uses_database_row_only() -> None:
    def _principal(role: UserRole, active: bool, superuser: bool) -> UserPrincipal:
        return UserPrincipal(
            id=uuid4(),
            email="unit@example.com",
            role=role,
            session_id=uuid4(),
            is_active=active,
            is_superuser=superuser,
            is_verified=False,
        )

    assert has_role(_principal(UserRole.ADMIN, True, True), frozenset({UserRole.ADMIN})) is True
    assert has_role(_principal(UserRole.AGENT, True, False), frozenset({UserRole.ADMIN})) is False
    assert has_role(_principal(UserRole.ADMIN, False, True), frozenset({UserRole.ADMIN})) is False
    # A superuser flag never widens the decision without the database role.
    assert has_role(_principal(UserRole.AGENT, True, True), frozenset({UserRole.ADMIN})) is False


def test_access_lifetime_caps_at_family_expiry() -> None:
    strategy = SessionJWTStrategy("test-secret", 900, None)  # type: ignore[arg-type]
    now = datetime.now(UTC)
    short = AuthFamily(id=uuid4(), user_id=uuid4(), expires_at=now + timedelta(seconds=100))
    long = AuthFamily(id=uuid4(), user_id=uuid4(), expires_at=now + timedelta(seconds=700000))

    assert strategy.access_lifetime(short, now) == 100
    assert strategy.access_lifetime(long, now) == 900


def test_get_jwt_strategy_shares_api_mcp_vocabulary() -> None:
    strategy = get_jwt_strategy(auth_fixtures.test_settings(), None)  # type: ignore[arg-type]

    assert strategy.algorithm == AUTH_TOKEN_ALGORITHM
    assert strategy.token_audience == [AUTH_TOKEN_AUDIENCE]


def test_get_jwt_strategy_rejects_missing_secret() -> None:
    from freesearch.configuration.config import Settings

    with pytest.raises(AuthConfigurationError):
        get_jwt_strategy(Settings(auth_jwt_secret=None), None)  # type: ignore[arg-type]


def test_auth_token_constants() -> None:
    assert AUTH_TOKEN_AUDIENCE == "freesearch:auth"
    assert AUTH_TOKEN_ALGORITHM == "HS256"
    assert SecretStr("x").get_secret_value() == "x"
