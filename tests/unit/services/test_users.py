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

import freesearch.services.users as users_service
from freesearch.models.users import AuthFamily
from freesearch.persistence.users import UserRow
from freesearch.services.users import (
    AUTH_TOKEN_ALGORITHM,
    AUTH_TOKEN_AUDIENCE,
    PASSWORD_RULE_MESSAGE,
    AuthConfigurationError,
    SessionJWTStrategy,
    UserManager,
    get_jwt_strategy,
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
        "is_verified": False,
        "auth_provider": "local",
        "auth_provider_id": None,
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
    """A1 replacement: no role helper exists; the library flag is a constant False.

    The old helper decided authority from a role column and proved a superuser
    flag could not widen it. Now no role or flag exists at all: authority is
    resolved from live scoped assignments (see the integration suites).
    """

    for removed in ("has_role", "_stored_role", "AuthUnsupportedRole", "change_role"):
        assert not hasattr(users_service, removed)
    assert not hasattr(users_service.AuthService, "change_role")
    row = _row()
    assert row.is_superuser is False
    with pytest.raises(AttributeError):
        row.is_superuser = True  # type: ignore[misc]


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


@pytest.mark.parametrize("field,value", [("role", "admin"), ("is_superuser", True)])
def test_stored_role_never_raises_for_a_database_row_value(field: str, value: object) -> None:
    """A1 replacement: the account row refuses a role or privilege flag outright."""

    with pytest.raises((TypeError, AttributeError)):
        _row(**{field: value})


async def test_provision_account_uses_safe_manager_and_returns_projection() -> None:
    """T2-PROVISION: provision_account creates with safe=True and returns the read."""

    from contextlib import asynccontextmanager

    from freesearch.models.users import UserAccount
    from freesearch.services.users import AuthService

    created_id = uuid4()
    created_row = _row()
    created_row.id = created_id
    expected = UserAccount(
        id=created_id,
        email="unit@example.com",
        is_active=True,
        is_verified=False,
    )
    seen: dict[str, object] = {}

    @asynccontextmanager
    async def _manager_ctx(**kwargs: object):  # type: ignore[no-untyped-def]
        manager = AsyncMock()

        async def _create(payload: object, safe: bool = False) -> object:
            seen["payload"] = payload
            seen["safe"] = safe
            return created_row

        manager.create.side_effect = _create
        yield manager

    service = AuthService(auth_fixtures.test_settings(), repository=AsyncMock())
    service.user_manager = _manager_ctx  # type: ignore[method-assign]
    service.get_account = AsyncMock(return_value=expected)  # type: ignore[method-assign]

    result = await service.provision_account("unit@example.com", SecretStr(_STRONG))

    assert result == expected
    assert seen["safe"] is True
    payload = seen["payload"]
    # The created account asks for no privilege; the library's own flags stay off.
    assert getattr(payload, "is_superuser", False) is False
    assert not hasattr(payload, "role")
    assert "role" not in result.model_dump()
    service.get_account.assert_awaited_once_with(created_id)  # type: ignore[attr-defined]


async def test_provision_account_maps_storage_failure() -> None:
    """T2-PROVISION: an unreadable created account becomes storage-unavailable."""

    from contextlib import asynccontextmanager

    from freesearch.services.users import AuthService, AuthStorageUnavailable

    @asynccontextmanager
    async def _manager_ctx(**kwargs: object):  # type: ignore[no-untyped-def]
        manager = AsyncMock()
        manager.create.return_value = _row()
        yield manager

    service = AuthService(auth_fixtures.test_settings(), repository=AsyncMock())
    service.user_manager = _manager_ctx  # type: ignore[method-assign]
    service.get_account = AsyncMock(return_value=None)  # type: ignore[method-assign]

    with pytest.raises(AuthStorageUnavailable):
        await service.provision_account("unit@example.com", SecretStr(_STRONG))


async def test_provision_account_propagates_library_errors() -> None:
    """T2-PROVISION: duplicate and password errors reach the router mapping."""

    from contextlib import asynccontextmanager

    from freesearch.services.users import AuthService

    for failure in (
        exceptions.UserAlreadyExists(),
        exceptions.InvalidPasswordException(reason="bad password"),
    ):

        def _make_ctx(current: object):  # type: ignore[no-untyped-def]
            @asynccontextmanager
            async def _failing_ctx(**kwargs: object):  # type: ignore[no-untyped-def]
                manager = AsyncMock()
                manager.create.side_effect = current
                yield manager

            return _failing_ctx

        service = AuthService(auth_fixtures.test_settings(), repository=AsyncMock())
        service.user_manager = _make_ctx(failure)  # type: ignore[method-assign]

        with pytest.raises(type(failure)):
            await service.provision_account("unit@example.com", SecretStr(_STRONG))
