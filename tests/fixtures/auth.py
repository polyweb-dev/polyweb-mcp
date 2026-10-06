"""Temporary account helpers for explicit auth fixtures (PLAN Section 11).

Every protected HTTP call uses a real verified JWT from ``POST
/auth/jwt/login`` on an isolated temporary database. No helper disables the
guard and no helper installs a global principal override. Each test sets
``FREESEARCH_AUTH_JWT_SECRET`` before the first settings read and clears the
settings cache, so the signing secret never lands in code.
"""

from __future__ import annotations

import secrets
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from fastapi_users.password import PasswordHelper
from httpx import Response
from pydantic import SecretStr

from freesearch.configuration.config import Settings
from freesearch.models.users import UserPrincipal, UserRole
from freesearch.persistence.storage import SQLiteRepository
from freesearch.persistence.users import UserDatabase, UserRow
from freesearch.services.users import AuthService

#: Strong password for temporary fixture accounts only.
TEMP_PASSWORD = "StrongPass123!x-Temp"


def temp_email(prefix: str = "tester") -> str:
    """Return a unique fixture email address."""

    return f"{prefix}-{uuid4().hex[:8]}@example.com"


def temp_token() -> SecretStr:
    """Return an opaque temporary bearer token for fixture wiring.

    This is not a signed JWT. Tests that need a real access JWT must log in
    through ``POST /auth/jwt/login`` or use :func:`test_settings` with an
    :class:`AuthService`. Fixtures use this value as an explicit per-test
    credential only.
    """

    return SecretStr(secrets.token_urlsafe(32))


def auth_headers(token: SecretStr) -> dict[str, str]:
    """Return an explicit Authorization header for one fixture token."""

    return {"Authorization": f"Bearer {token.get_secret_value()}"}


async def create_temp_user(
    repository: SQLiteRepository,
    email: str,
    *,
    role: UserRole = UserRole.AGENT,
    password: str = TEMP_PASSWORD,
) -> UserRow:
    """Create one temporary local account on a test repository."""

    helper = PasswordHelper()
    async with repository.session() as session:
        database = UserDatabase(session, UserRow)
        user = await database.create({"email": email, "hashed_password": helper.hash(password)})
        if role is not UserRole.AGENT:
            await database.set_role(user.id, role)
            await session.commit()
            await session.refresh(user)
        return user


def temp_principal(user: UserRow, *, session_id: UUID | None = None) -> UserPrincipal:
    """Build an explicit principal for one fixture account."""

    return UserPrincipal(
        id=user.id,
        email=user.email,
        role=UserRole(user.role),
        session_id=session_id or uuid4(),
        is_active=bool(user.is_active),
        is_superuser=bool(user.is_superuser),
        is_verified=bool(user.is_verified),
    )


async def temp_account_token(
    repository: SQLiteRepository,
    email: str,
    *,
    role: UserRole = UserRole.AGENT,
) -> tuple[UserPrincipal, SecretStr]:
    """Create one account and return its explicit principal and token."""

    user = await create_temp_user(repository, email, role=role)
    return temp_principal(user), temp_token()


def generate_secret() -> str:
    """Return 32 random bytes as a URL-safe secret for test settings."""

    return secrets.token_urlsafe(32)


def test_settings(**overrides: object) -> Settings:
    """Return test settings with a generated signing secret plus overrides."""

    return Settings(auth_jwt_secret=SecretStr(generate_secret()), **overrides)  # type: ignore[arg-type]


def auth_service_for(repository: SQLiteRepository, settings: Settings | None = None) -> AuthService:
    """Return an explicit auth service bound to one test repository."""

    return AuthService(settings or test_settings(), repository=repository)


def raw_auth_headers(token: str) -> dict[str, str]:
    """Return an explicit Authorization header for one raw token string."""

    return {"Authorization": f"Bearer {token}"}


def install_auth_secret(monkeypatch: pytest.MonkeyPatch) -> str:
    """Point one test at a generated signing secret.

    Set ``FREESEARCH_AUTH_JWT_SECRET`` through the ``monkeypatch`` fixture
    and clear the settings cache, so the app composition reads the secret on
    its next access. The caller restores the environment through
    ``monkeypatch`` and clears the cache again in teardown. Return the raw
    secret for JWT claim checks.
    """

    from freesearch.configuration.config import get_settings

    secret = secrets.token_urlsafe(32)
    monkeypatch.setenv("FREESEARCH_AUTH_JWT_SECRET", secret)
    get_settings.cache_clear()
    return secret


def register_http(client: TestClient, email: str, password: str = TEMP_PASSWORD) -> Response:
    """POST one public registration; return the raw response without asserts."""

    return client.post("/auth/register", json={"email": email, "password": password})


def login_http(client: TestClient, email: str, password: str = TEMP_PASSWORD) -> Response:
    """POST one public login; return the raw response without asserts."""

    return client.post("/auth/jwt/login", data={"username": email, "password": password})


def register_and_login(
    client: TestClient, email: str, password: str = TEMP_PASSWORD
) -> dict[str, Any]:
    """Register one account and log in; return the verified credential pair."""

    registered = register_http(client, email, password)
    assert registered.status_code == 201
    logged_in = login_http(client, email, password)
    assert logged_in.status_code == 200
    pair = logged_in.json()
    assert pair["token_type"] == "bearer"
    assert pair["access_token"]
    assert pair["refresh_token"]
    return pair


async def promote_account(repository: SQLiteRepository, email: str, role: UserRole) -> None:
    """Assign one explicit role to an account looked up by email."""

    normalized = email.lower()
    async with repository.session() as session:
        database = UserDatabase(session, UserRow)
        account = await database.get_by_email(normalized)
        assert account is not None
        changed = await database.set_role(account.id, role)
        assert changed is True
        await session.commit()


async def register_promote_login(
    client: TestClient,
    repository: SQLiteRepository,
    email: str,
    role: UserRole,
    password: str = TEMP_PASSWORD,
) -> dict[str, Any]:
    """Register, assign one explicit role, then log in; return the pair."""

    registered = register_http(client, email, password)
    assert registered.status_code == 201
    await promote_account(repository, email, role)
    logged_in = login_http(client, email, password)
    assert logged_in.status_code == 200
    return logged_in.json()


async def auth_headers_for(
    client: TestClient,
    repository: SQLiteRepository,
    prefix: str,
    role: UserRole = UserRole.AGENT,
    password: str = TEMP_PASSWORD,
) -> dict[str, str]:
    """Run the full temp-account flow and return one access header."""

    email = temp_email(prefix)
    if role is UserRole.AGENT:
        pair = register_and_login(client, email, password)
    else:
        pair = await register_promote_login(client, repository, email, role, password)
    return raw_auth_headers(pair["access_token"])


def configure_bdd_secret(context: Any) -> str:
    """Point one Behave scenario at a generated secret with cleanup on exit."""

    import os

    from freesearch.configuration.config import get_settings

    previous = os.environ.get("FREESEARCH_AUTH_JWT_SECRET")
    secret = secrets.token_urlsafe(32)
    os.environ["FREESEARCH_AUTH_JWT_SECRET"] = secret
    get_settings.cache_clear()

    def _restore() -> None:
        if previous is None:
            os.environ.pop("FREESEARCH_AUTH_JWT_SECRET", None)
        else:
            os.environ["FREESEARCH_AUTH_JWT_SECRET"] = previous
        get_settings.cache_clear()

    cleanups: list[Any] = getattr(context, "enc_cleanups", None) or []
    context.enc_cleanups = cleanups
    cleanups.append(_restore)
    return secret


async def mcp_account_token(
    repository: SQLiteRepository,
    prefix: str = "mcp",
    role: UserRole = UserRole.AGENT,
    password: str = TEMP_PASSWORD,
) -> tuple[AuthService, SecretStr, str]:
    """Create one temp account and log in through the service.

    Return the service, one access JWT, and the account email. The service
    carries its own generated signing secret, so this helper serves direct MCP
    tool compositions without an HTTP app. Tests beside a REST app must use
    :func:`http_jwt_service` instead, so one JWT spans both transports.
    """

    from fastapi.security import OAuth2PasswordRequestForm

    service = auth_service_for(repository)
    email = temp_email(prefix)
    await create_temp_user(repository, email, role=role, password=password)
    tokens = await service.login(
        OAuth2PasswordRequestForm(username=email, password=password),
        peer_address=f"{prefix}-probe",
    )
    assert tokens is not None
    return service, tokens.access_token, email


def http_jwt_service(repository: SQLiteRepository) -> AuthService:
    """Return a service that verifies the HTTP-issued JWTs of this test.

    It reads the same cached settings as the REST app composition, so one
    access JWT spans the API surface and the MCP surface of one test database.
    The caller sets ``FREESEARCH_AUTH_JWT_SECRET`` first, through the shared
    ``auth_secret`` fixture or :func:`configure_bdd_secret`.
    """

    from freesearch.configuration.config import get_settings

    return AuthService(get_settings(), repository=repository)


def account_id_from_pair(pair: dict[str, Any]) -> UUID:
    """Return the account UUID of one login pair without verifying its signature.

    Tests use this value to seed owned fixture rows for the account that will
    read them. Authorization still comes from the verified JWT on each request.
    """

    import jwt as pyjwt

    claims = pyjwt.decode(pair["access_token"], options={"verify_signature": False})
    return UUID(str(claims["sub"]))
