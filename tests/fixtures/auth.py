"""Temporary account helpers for explicit auth fixtures (PLAN Section 11, A1).

Every protected HTTP call uses a real verified JWT from ``POST
/auth/jwt/login`` on an isolated temporary database. No helper disables the
guard and no helper installs a global principal override. Each test sets
``FREESEARCH_AUTH_JWT_SECRET`` before the first settings read and clears the
settings cache, so the signing secret never lands in code.

Authority follows the A1 model (TASK-000041): every account starts ordinary.
System authority exists only through an explicit trusted ``system_admin``
assignment (:func:`grant_system_admin`), and project authority only through
project membership. A test asks for system authority explicitly, and only when
it exercises a system-scoped operation.
"""

from __future__ import annotations

import secrets
from collections.abc import Callable
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from fastapi_users.password import PasswordHelper
from httpx import Response
from pydantic import SecretStr

from freesearch.configuration.config import Settings
from freesearch.models.users import UserPrincipal
from freesearch.persistence.projects import bootstrap_fresh_installation
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


async def grant_system_admin(repository: SQLiteRepository, user_id: UUID) -> None:
    """Grant ``system_admin`` to one account through the trusted bootstrap path.

    This is the operator path (``bootstrap_fresh_installation``), never a
    request field, so tests exercise the same authority source as production.
    """

    async with repository.session() as session:
        await bootstrap_fresh_installation(session, user_id)
        await session.commit()


async def create_temp_user(
    repository: SQLiteRepository,
    email: str,
    *,
    system_admin: bool = False,
    password: str = TEMP_PASSWORD,
) -> UserRow:
    """Create one ordinary local account; grant ``system_admin`` only when asked."""

    helper = PasswordHelper()
    async with repository.session() as session:
        database = UserDatabase(session, UserRow)
        user = await database.create({"email": email, "hashed_password": helper.hash(password)})
    if system_admin:
        await grant_system_admin(repository, user.id)
    return user


def temp_principal(user: UserRow, *, session_id: UUID | None = None) -> UserPrincipal:
    """Build an explicit principal for one fixture account (no role, no privilege flag)."""

    return UserPrincipal(
        id=user.id,
        email=user.email,
        session_id=session_id or uuid4(),
        is_active=bool(user.is_active),
        is_verified=bool(user.is_verified),
    )


async def temp_account_token(
    repository: SQLiteRepository,
    email: str,
    *,
    system_admin: bool = False,
) -> tuple[UserPrincipal, SecretStr]:
    """Create one account and return its explicit principal and token."""

    user = await create_temp_user(repository, email, system_admin=system_admin)
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


async def promote_to_system_admin(repository: SQLiteRepository, email: str) -> UUID:
    """Grant ``system_admin`` to an account looked up by email; return its id."""

    async with repository.session() as session:
        account = await UserDatabase(session, UserRow).get_by_email(email)
        assert account is not None
        user_id = account.id
    await grant_system_admin(repository, user_id)
    return user_id


async def register_system_admin_login(
    client: TestClient,
    repository: SQLiteRepository,
    email: str,
    password: str = TEMP_PASSWORD,
) -> dict[str, Any]:
    """Register an ordinary account, grant it ``system_admin`` (trusted), then log in."""

    registered = register_http(client, email, password)
    assert registered.status_code == 201
    await promote_to_system_admin(repository, email)
    logged_in = login_http(client, email, password)
    assert logged_in.status_code == 200
    return logged_in.json()


async def auth_headers_for(
    client: TestClient,
    repository: SQLiteRepository,
    prefix: str,
    *,
    system_admin: bool = False,
    password: str = TEMP_PASSWORD,
) -> dict[str, str]:
    """Run the full temp-account flow and return one access header."""

    email = temp_email(prefix)
    if system_admin:
        pair = await register_system_admin_login(client, repository, email, password)
    else:
        pair = register_and_login(client, email, password)
    return raw_auth_headers(pair["access_token"])


def install_process_auth_secret() -> tuple[str, Callable[[], None]]:
    """Set a generated ``FREESEARCH_AUTH_JWT_SECRET`` in the process env.

    Clear the settings cache so the next composition reads it, and return the
    secret plus a restore callable that puts back the previous value (or
    removes the variable) and clears the cache again.
    """

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

    return secret, _restore


def configure_bdd_secret(context: Any) -> str:
    """Point one Behave scenario at a generated secret with cleanup on exit."""

    secret, restore = install_process_auth_secret()
    cleanups: list[Any] = getattr(context, "enc_cleanups", None) or []
    context.enc_cleanups = cleanups
    cleanups.append(restore)
    return secret


async def login_service(
    service: AuthService, email: str, password: str = TEMP_PASSWORD
) -> SecretStr:
    """Log one existing account in through the service; return its access JWT."""

    from fastapi.security import OAuth2PasswordRequestForm

    tokens = await service.login(
        OAuth2PasswordRequestForm(username=email, password=password),
        peer_address="fixture-probe",
    )
    assert tokens is not None
    return tokens.access_token


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
