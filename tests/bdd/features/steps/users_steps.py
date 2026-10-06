"""Offline Behave steps for local accounts, migration, and settings (P1, P6, P8).

Each scenario uses an isolated temporary database and fake provider adapters.
No scenario requires provider credentials, mail, or WorkOS.
Requirement references: R1, R2, R3, R6, R7, R8, AC1, AC2, AC3, AC5, AC6.
"""

from __future__ import annotations

import sqlite3
import tempfile
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import uuid4

from behave import given, then, when  # type: ignore[import-untyped]
from fastapi.testclient import TestClient
from fastapi_users.password import PasswordHelper
from sqlalchemy import select

from freesearch.adapters.base import ProviderAdapter
from freesearch.configuration.config import Settings, require_transport_port
from freesearch.models.contracts import (
    CostEstimate,
    FetchedDocument,
    FetchRequest,
    FetchResponse,
    ProviderCapabilities,
    SearchRequest,
    SearchResponse,
    SearchResult,
    UsageEvent,
    UsageOperation,
)
from freesearch.models.users import AuthProvider, UserRole, normalize_email
from freesearch.persistence.database_migrations import (
    database_status,
    migration_head,
    upgrade_database,
    validate_database_schema,
)
from freesearch.persistence.storage import SQLiteRepository
from freesearch.persistence.users import UserDatabase, UserRow, local_password_hash
from freesearch.routers.api import create_app
from tests.fixtures.auth import configure_bdd_secret

_TEST_PASSWORD = "StrongPass123!x-UsersBDD"


class _UsersStubAdapter(ProviderAdapter):
    """Deterministic stub adapter for the users offline path."""

    def __init__(self, name: str = "stubby") -> None:
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(search=True, fetch=True, cost_estimate=True)

    async def search(self, request: SearchRequest) -> SearchResponse:
        return SearchResponse(
            query=request.query,
            provider=self.name,
            results=[
                SearchResult(
                    title="stub result",
                    url="https://example.com/users",
                    snippet="offline users result",
                )
            ],
            total_results=1,
            usage=UsageEvent(
                provider=self.name,
                operation=UsageOperation.SEARCH,
                units=Decimal("1"),
                observed_at=datetime.now(UTC),
            ),
        )

    async def fetch(self, request: FetchRequest) -> FetchResponse:
        return FetchResponse(
            provider=self.name,
            document=FetchedDocument(
                url=request.url,
                content="offline users document",
                fetched_at=datetime.now(UTC),
            ),
        )

    async def estimate_cost(self, request: SearchRequest | FetchRequest) -> CostEstimate:
        operation = (
            UsageOperation.SEARCH if isinstance(request, SearchRequest) else UsageOperation.FETCH
        )
        return CostEstimate(provider=self.name, operation=operation, units=Decimal("0"))


def _open_users_repository(context: Any) -> None:
    with tempfile.NamedTemporaryFile(
        prefix="freesearch-users-",
        suffix=".db",
        dir=Path.cwd(),
        delete=False,
    ) as temporary_file:
        context.database_path = Path(temporary_file.name)
    context.repository = context.loop.run_until_complete(
        SQLiteRepository.open(context.database_path)
    )


def _create_local_account(context: Any, email: str) -> None:
    async def _insert() -> UserRow:
        async with context.repository.session() as session:
            database = UserDatabase(session, UserRow)
            helper = PasswordHelper()
            hashed = helper.hash(_TEST_PASSWORD)
            created = await database.create({"email": email, "hashed_password": hashed})
            await session.refresh(created)
            context.created_email = created.email
            context.created_role = created.role
            context.created_hash = str(created.hashed_password)
            context.created_id = str(created.id)
            return created

    context.created_user = context.loop.run_until_complete(_insert())


@given("an offline users repository with a temporary database")
def step_given_users_repository(context: Any) -> None:
    _open_users_repository(context)


@when('I create a local account with email "{email}"')
def step_when_create_local_account(context: Any, email: str) -> None:
    _create_local_account(context, email)


@then('the stored account should use email "{email}" and role "{role}"')
def step_then_account_email_role(context: Any, email: str, role: str) -> None:
    assert context.created_email == email
    assert context.created_role == role
    assert normalize_email("Ops@Example.COM") == "ops@example.com"


@then("the stored password hash should verify with the password helper")
def step_then_hash_verifies(context: Any) -> None:
    helper = PasswordHelper()
    verified, _ = helper.verify_and_update(_TEST_PASSWORD, context.created_hash)
    assert verified is True
    assert context.created_hash != _TEST_PASSWORD
    assert context.created_hash.startswith("$argon2")


@when("I insert invalid account rows")
def step_when_insert_invalid_rows(context: Any) -> None:
    context.invalid_results = context.loop.run_until_complete(_try_invalid_rows(context))


async def _try_invalid_rows(context: Any) -> list[bool]:
    rejected: list[bool] = []
    shapes: list[dict[str, Any]] = [
        # Local row with a null hash.
        {
            "id": str(uuid4()),
            "email": "null-hash@example.com",
            "hashed_password": None,
            "is_active": True,
            "is_superuser": False,
            "is_verified": False,
            "auth_provider": "local",
            "auth_provider_id": None,
            "role": "agent",
        },
        # Local row with an empty hash.
        {
            "id": str(uuid4()),
            "email": "empty-hash@example.com",
            "hashed_password": "",
            "is_active": True,
            "is_superuser": False,
            "is_verified": False,
            "auth_provider": "local",
            "auth_provider_id": None,
            "role": "agent",
        },
        # WorkOS row with a password hash.
        {
            "id": str(uuid4()),
            "email": "workos-hash@example.com",
            "hashed_password": "some-hash",
            "is_active": True,
            "is_superuser": False,
            "is_verified": False,
            "auth_provider": "workos",
            "auth_provider_id": "ext-1",
            "role": "agent",
        },
        # WorkOS row without an external id.
        {
            "id": str(uuid4()),
            "email": "workos-noid@example.com",
            "hashed_password": None,
            "is_active": True,
            "is_superuser": False,
            "is_verified": False,
            "auth_provider": "workos",
            "auth_provider_id": None,
            "role": "agent",
        },
        # Local row with an external id.
        {
            "id": str(uuid4()),
            "email": "local-extid@example.com",
            "hashed_password": "some-hash",
            "is_active": True,
            "is_superuser": False,
            "is_verified": False,
            "auth_provider": "local",
            "auth_provider_id": "ext-2",
            "role": "agent",
        },
        # Admin role without the superuser flag.
        {
            "id": str(uuid4()),
            "email": "admin-flag@example.com",
            "hashed_password": "some-hash",
            "is_active": True,
            "is_superuser": False,
            "is_verified": False,
            "auth_provider": "local",
            "auth_provider_id": None,
            "role": "admin",
        },
    ]
    async with context.repository.session() as session:
        for shape in shapes:
            try:
                session.add(UserRow(**shape))
                await session.flush()
            except Exception:
                await session.rollback()
                rejected.append(True)
            else:
                await session.rollback()
                rejected.append(False)
    return rejected


@then("the database should reject each invalid account row")
def step_then_invalid_rows_rejected(context: Any) -> None:
    assert context.invalid_results == [True, True, True, True, True, True]


@then("a WorkOS account with a null hash should have no local password hash")
def step_then_workos_null_hash(context: Any) -> None:
    async def _insert() -> UserRow:
        async with context.repository.session() as session:
            row = UserRow(
                id=uuid4(),
                email="workos-null@example.com",
                hashed_password=None,
                is_active=True,
                is_superuser=False,
                is_verified=False,
                auth_provider=AuthProvider.WORKOS.value,
                auth_provider_id="ext-workos-1",
                role=UserRole.AGENT.value,
            )
            session.add(row)
            await session.flush()
            result = local_password_hash(row)
            await session.rollback()
            context.workos_hash_result = result
            return row

    context.loop.run_until_complete(_insert())
    assert context.workos_hash_result is None


@then("the Agent account should not carry the superuser flag")
def step_then_agent_not_superuser(context: Any) -> None:
    async def _read() -> bool:
        async with context.repository.session() as session:
            database = UserDatabase(session, UserRow)
            found = await database.get_by_email("agent@example.com")
            assert found is not None
            return bool(found.is_superuser)

    assert context.loop.run_until_complete(_read()) is False


@given("a pre-Alembic users database with historical usage rows")
def step_given_prealembic_users_db(context: Any) -> None:
    context.temp_directory = tempfile.TemporaryDirectory(prefix="users-migration-bdd-")
    database = Path(context.temp_directory.name) / "freesearch.db"
    database.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(database) as connection:
        connection.executescript(
            """
            CREATE TABLE usage_events (
                id INTEGER PRIMARY KEY,
                provider TEXT NOT NULL,
                operation TEXT NOT NULL,
                units TEXT NOT NULL,
                observed_at TEXT NOT NULL,
                request_id TEXT,
                metadata TEXT NOT NULL
            );
            """
        )
        connection.execute(
            """
            INSERT INTO usage_events
                (id, provider, operation, units, observed_at, request_id, metadata)
            VALUES (1, 'legacy', 'search', '1.00',
                    '2026-01-01T00:00:00+00:00', NULL, '{}')
            """
        )
    context.database_path = str(database)
    with sqlite3.connect(database) as connection:
        context.rows_before = connection.execute(
            "SELECT id, provider, operation, units FROM usage_events ORDER BY id"
        ).fetchall()


@when("I run the users database migration")
def step_when_users_migration(context: Any) -> None:
    context.migration_result = upgrade_database(Path(str(context.database_path)))


@then('the users database should be at head "{revision}" with a valid schema')
def step_then_users_db_at_head(context: Any, revision: str) -> None:
    status = database_status(Path(str(context.database_path)))
    assert status.current_revision == revision
    assert status.current_revision == migration_head()
    assert status.schema_valid is True
    validate_database_schema(Path(str(context.database_path)))


@then("the historical usage rows should remain unchanged")
def step_then_users_history_unchanged(context: Any) -> None:
    with sqlite3.connect(str(context.database_path)) as connection:
        rows = connection.execute(
            "SELECT id, provider, operation, units FROM usage_events ORDER BY id"
        ).fetchall()
    assert rows == context.rows_before


@then("the migration should create the account tables and trace ownership column")
def step_then_users_migration_objects(context: Any) -> None:
    with sqlite3.connect(str(context.database_path)) as connection:
        tables = {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        trace_columns = {
            str(row[1]) for row in connection.execute('PRAGMA table_info("trace_spans")')
        }
        backup_check = connection.execute("PRAGMA integrity_check").fetchone()
    assert {"user", "login_throttle", "auth_sessions", "refresh_tokens"} <= tables
    assert "user_id" in trace_columns
    assert backup_check == ("ok",)
    assert context.migration_result.backup is not None


@when("I check the users settings contracts")
def step_when_users_settings(context: Any) -> None:
    context.settings_missing_rejected = False
    try:
        Settings(auth_jwt_secret=None).require_auth_secret()
    except ValueError:
        context.settings_missing_rejected = True
    context.settings_repr = repr(Settings(auth_jwt_secret="x" * 32))
    context.port_missing_rejected = False
    try:
        require_transport_port(Settings(api_port=None, mcp_port=None), transport="api")
    except ValueError:
        context.port_missing_rejected = True


@then("a missing signing secret should block authentication")
def step_then_missing_secret_blocked(context: Any) -> None:
    assert context.settings_missing_rejected is True
    assert context.port_missing_rejected is True


@then("settings representations should contain no secret material")
def step_then_settings_no_secrets(context: Any) -> None:
    assert "x" * 32 not in context.settings_repr
    assert "FREESEARCH_AUTH_JWT_SECRET" not in context.settings_repr


@given("an offline users API with stub adapters and a temporary database")
def step_given_users_api(context: Any) -> None:
    _configure_auth_secret(context)
    _open_users_repository(context)
    context.adapters = [_UsersStubAdapter("stubby")]
    context.app = create_app(context.adapters, repository=context.repository)


@when("I submit an offline users search")
def step_when_users_search(context: Any) -> None:
    with TestClient(context.app) as client:
        registered = client.post(
            "/auth/register",
            json={"email": "users-search@example.com", "password": _TEST_PASSWORD},
        )
        assert registered.status_code == 201
        logged_in = client.post(
            "/auth/jwt/login",
            data={"username": "users-search@example.com", "password": _TEST_PASSWORD},
        )
        assert logged_in.status_code == 200
        token = logged_in.json()["access_token"]
        context.search_response = client.post(
            "/search",
            json={"query": "local accounts"},
            headers={"Authorization": f"Bearer {token}"},
        )


@then("the offline users search should succeed with the stub provider")
def step_then_users_search_ok(context: Any) -> None:
    assert context.search_response.status_code == 200
    assert context.search_response.json()["provider"] == "stubby"


@then("the stored account can be found by a case-insensitive lookup")
def step_then_case_insensitive_lookup(context: Any) -> None:
    async def _lookup() -> str:
        async with context.repository.session() as session:
            database = UserDatabase(session, UserRow)
            found = await database.get_by_email("OPS@example.com")
            assert found is not None
            statement = select(UserRow).where(UserRow.email == found.email)
            row = (await session.execute(statement)).scalar_one()
            return str(row.email)

    assert context.loop.run_until_complete(_lookup()) == "ops@example.com"


_AUTH_PASSWORD = "StrongPass123!x-AuthBDD"


def _configure_auth_secret(context: Any) -> None:
    """Point this scenario at a generated signing secret, restored on cleanup."""

    configure_bdd_secret(context)


@given("an offline users API with account auth and stub adapters")
def step_given_users_auth_api(context: Any) -> None:
    _configure_auth_secret(context)
    _open_users_repository(context)
    context.adapters = [_UsersStubAdapter("stubby")]
    context.app = create_app(context.adapters, repository=context.repository)


def _auth_client(context: Any) -> TestClient:
    return TestClient(context.app)


@when('I register account "{email}"')
def step_when_auth_register(context: Any, email: str) -> None:
    context.auth_email = email
    with _auth_client(context) as client:
        context.register_response = client.post(
            "/auth/register", json={"email": email, "password": _AUTH_PASSWORD}
        )


@then("the registration should create an Agent account without tokens")
def step_then_auth_register_ok(context: Any) -> None:
    response = context.register_response
    assert response.status_code == 201
    body = response.json()
    assert body["email"] == context.auth_email.lower()
    assert body["role"] == "agent"
    assert body["is_active"] is True
    assert "access_token" not in body
    assert "refresh_token" not in body
    assert "hashed_password" not in body


@when("I log in as the registered account")
def step_when_auth_login(context: Any) -> None:
    with _auth_client(context) as client:
        context.login_response = client.post(
            "/auth/jwt/login",
            data={"username": context.auth_email, "password": _AUTH_PASSWORD},
        )
        if context.login_response.status_code == 200:
            context.auth_pair = context.login_response.json()


@then("the login should return a Bearer pair with a 900-second access token")
def step_then_auth_login_ok(context: Any) -> None:
    response = context.login_response
    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["expires_in"] == 900
    assert body["refresh_expires_in"] == 604800
    assert body["access_token"]
    assert body["refresh_token"]
    assert response.headers["cache-control"] == "no-store"


@when("I read my account with the access token")
def step_when_auth_read_me(context: Any) -> None:
    token = context.auth_pair["access_token"]
    with _auth_client(context) as client:
        context.me_response = client.get("/users/me", headers={"Authorization": f"Bearer {token}"})


@then("the account read should return my record without a hash")
def step_then_auth_me_ok(context: Any) -> None:
    assert context.me_response.status_code == 200
    body = context.me_response.json()
    assert body["email"] == context.auth_email.lower()
    assert body["role"] == "agent"
    assert "hashed_password" not in body


@when("I log in with a wrong password")
def step_when_auth_wrong_password(context: Any) -> None:
    with _auth_client(context) as client:
        context.bad_login_response = client.post(
            "/auth/jwt/login",
            data={"username": context.auth_email, "password": "WrongPass123!x-No"},
        )


@then("the login should fail with bad credentials")
def step_then_auth_bad_login(context: Any) -> None:
    assert context.bad_login_response.status_code == 400
    assert "WrongPass123" not in context.bad_login_response.text


@when("I read my account without a token")
def step_when_auth_me_anonymous(context: Any) -> None:
    with _auth_client(context) as client:
        context.me_response = client.get("/users/me")


@when("I read my account with a malformed token")
def step_when_auth_me_malformed(context: Any) -> None:
    with _auth_client(context) as client:
        context.me_response = client.get(
            "/users/me", headers={"Authorization": "Bearer not-a-token"}
        )


@then("the account read should fail with HTTP 401")
def step_then_auth_me_401(context: Any) -> None:
    assert context.me_response.status_code == 401
    assert context.me_response.headers["www-authenticate"] == "Bearer"


@when('I register with weak password "{password}"')
def step_when_auth_weak_password(context: Any, password: str) -> None:
    with _auth_client(context) as client:
        context.register_response = client.post(
            "/auth/register",
            json={"email": f"weak-{uuid4().hex[:8]}@example.com", "password": password},
        )


@then("the registration should fail with the password rule")
def step_then_auth_weak_rejected(context: Any) -> None:
    assert context.register_response.status_code == 400
    assert "password must have" in context.register_response.text


@when("I fail login five times and then once more")
def step_when_auth_login_limit(context: Any) -> None:
    with _auth_client(context) as client:
        for _ in range(5):
            probe = client.post(
                "/auth/jwt/login",
                data={"username": context.auth_email, "password": "WrongPass123!x-No"},
            )
            assert probe.status_code == 400
        context.limit_response = client.post(
            "/auth/jwt/login",
            data={"username": context.auth_email, "password": "WrongPass123!x-No"},
        )


@then("the sixth login should fail with HTTP 429 and a retry delay")
def step_then_auth_login_429(context: Any) -> None:
    assert context.limit_response.status_code == 429
    assert int(context.limit_response.headers["retry-after"]) >= 1


@when("I register five accounts and then one more")
def step_when_auth_registration_limit(context: Any) -> None:
    with _auth_client(context) as client:
        for index in range(5):
            probe = client.post(
                "/auth/register",
                json={
                    "email": f"capped-{index}-{uuid4().hex[:6]}@example.com",
                    "password": _AUTH_PASSWORD,
                },
            )
            assert probe.status_code == 201
        context.limit_response = client.post(
            "/auth/register",
            json={
                "email": f"capped-last-{uuid4().hex[:6]}@example.com",
                "password": _AUTH_PASSWORD,
            },
        )


@then("the sixth registration should fail with HTTP 429 and a retry delay")
def step_then_auth_registration_429(context: Any) -> None:
    assert context.limit_response.status_code == 429
    assert int(context.limit_response.headers["retry-after"]) >= 1


@when("I refresh with the refresh token")
def step_when_auth_refresh(context: Any) -> None:
    token = context.auth_pair["refresh_token"]
    with _auth_client(context) as client:
        context.refresh_response = client.post(
            "/auth/jwt/refresh", headers={"Authorization": f"Bearer {token}"}
        )
        if context.refresh_response.status_code == 200:
            context.refresh_pair = context.refresh_response.json()


@then("the refresh should return one successor pair")
def step_then_auth_refresh_ok(context: Any) -> None:
    assert context.refresh_response.status_code == 200
    body = context.refresh_response.json()
    assert body["token_type"] == "bearer"
    assert body["expires_in"] == 900
    # The refresh credential is always new. The access JWT can match the old
    # string when the clock has not advanced past the same second.
    assert body["refresh_token"] != context.auth_pair["refresh_token"]
    assert body["refresh_expires_in"] <= context.auth_pair["refresh_expires_in"]
    assert context.refresh_response.headers["cache-control"] == "no-store"


@when("I reuse the consumed refresh token")
def step_when_auth_reuse(context: Any) -> None:
    token = context.auth_pair["refresh_token"]
    with _auth_client(context) as client:
        context.reuse_response = client.post(
            "/auth/jwt/refresh", headers={"Authorization": f"Bearer {token}"}
        )


@then("the reuse should fail with HTTP 401")
def step_then_auth_reuse_401(context: Any) -> None:
    assert context.reuse_response.status_code == 401


@then("the successor credentials should fail at once")
def step_then_auth_successor_dead(context: Any) -> None:
    with _auth_client(context) as client:
        probe = client.get(
            "/users/me",
            headers={"Authorization": f"Bearer {context.refresh_pair['access_token']}"},
        )
        assert probe.status_code == 401
        stale = client.post(
            "/auth/jwt/refresh",
            headers={"Authorization": f"Bearer {context.refresh_pair['refresh_token']}"},
        )
        assert stale.status_code == 401


@when("I log out with the successor access token")
def step_when_auth_logout(context: Any) -> None:
    token = context.refresh_pair["access_token"]
    with _auth_client(context) as client:
        context.logout_response = client.post(
            "/auth/jwt/logout", headers={"Authorization": f"Bearer {token}"}
        )


@then("the logout should revoke the family at once")
def step_then_auth_logout_ok(context: Any) -> None:
    assert context.logout_response.status_code == 204
    with _auth_client(context) as client:
        for token in (context.auth_pair["access_token"], context.refresh_pair["access_token"]):
            probe = client.get("/users/me", headers={"Authorization": f"Bearer {token}"})
            assert probe.status_code == 401
        stale = client.post(
            "/auth/jwt/refresh",
            headers={"Authorization": f"Bearer {context.refresh_pair['refresh_token']}"},
        )
        assert stale.status_code == 401


@when("I fail login four times")
def step_when_auth_login_fail_four(context: Any) -> None:
    with _auth_client(context) as client:
        for _ in range(4):
            probe = client.post(
                "/auth/jwt/login",
                data={"username": context.auth_email, "password": "WrongPass123!x-No"},
            )
            assert probe.status_code == 400


_OVERSIZE_PAD = "A" * 4097


@when("I register with a 4097-byte body")
def step_when_auth_register_oversize(context: Any) -> None:
    with _auth_client(context) as client:
        context.oversize_response = client.post(
            "/auth/register",
            json={
                "email": "oversize@example.com",
                "password": _AUTH_PASSWORD,
                "pad": _OVERSIZE_PAD,
            },
        )


@when("I log in with a 4097-byte body")
def step_when_auth_login_oversize(context: Any) -> None:
    with _auth_client(context) as client:
        context.oversize_response = client.post(
            "/auth/jwt/login",
            data={"username": _OVERSIZE_PAD, "password": _OVERSIZE_PAD},
        )


@then("the oversize auth call should fail with HTTP 413 and no credential content")
def step_then_auth_oversize_413(context: Any) -> None:
    response = context.oversize_response
    assert response.status_code == 413
    assert response.json() == {"detail": "request body is too large"}
    assert _OVERSIZE_PAD not in response.text


@when('I call "{method} {path}" without a token')
def step_when_auth_anonymous_call(context: Any, method: str, path: str) -> None:
    payload: dict[str, str] = {}
    if method == "POST" and path == "/search":
        payload = {"query": "anonymous probe"}
    elif method == "POST" and path == "/fetch":
        payload = {"url": "https://example.com/page"}
    with _auth_client(context) as client:
        if method == "POST":
            context.anonymous_response = client.post(path, json=payload)
        else:
            context.anonymous_response = client.get(path)


@then("the call should fail with HTTP 401 and a Bearer challenge")
def step_then_auth_anonymous_401(context: Any) -> None:
    assert context.anonymous_response.status_code == 401
    assert context.anonymous_response.headers["www-authenticate"] == "Bearer"


@when("I use the refresh token on search and the access token on refresh")
def step_when_auth_misplaced_credentials(context: Any) -> None:
    pair = context.auth_pair
    with _auth_client(context) as client:
        context.misplaced_search = client.post(
            "/search",
            json={"query": "misplaced probe"},
            headers={"Authorization": f"Bearer {pair['refresh_token']}"},
        )
        context.misplaced_refresh = client.post(
            "/auth/jwt/refresh",
            headers={"Authorization": f"Bearer {pair['access_token']}"},
        )


@then("both misplaced credentials should fail with HTTP 401")
def step_then_auth_misplaced_401(context: Any) -> None:
    assert context.misplaced_search.status_code == 401
    assert context.misplaced_refresh.status_code == 401


@when("I prepare Admin, Developer, and Agent accounts")
def step_when_auth_prepare_roles(context: Any) -> None:
    context.role_pairs = {}
    with _auth_client(context) as client:
        for role_name, role in (
            ("admin", UserRole.ADMIN),
            ("developer", UserRole.DEVELOPER),
            ("agent", UserRole.AGENT),
        ):
            email = f"matrix-{role_name}-{uuid4().hex[:6]}@example.com"
            registered = client.post(
                "/auth/register", json={"email": email, "password": _AUTH_PASSWORD}
            )
            assert registered.status_code == 201

            async def _promote(target_email: str = email, target_role: UserRole = role) -> None:
                async with context.repository.session() as session:
                    database = UserDatabase(session, UserRow)
                    account = await database.get_by_email(target_email)
                    assert account is not None
                    await database.set_role(account.id, target_role)
                    await session.commit()

            if role is not UserRole.AGENT:
                context.loop.run_until_complete(_promote())
            logged_in = client.post(
                "/auth/jwt/login", data={"username": email, "password": _AUTH_PASSWORD}
            )
            assert logged_in.status_code == 200
            context.role_pairs[role_name] = logged_in.json()


def _role_headers(context: Any, role: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {context.role_pairs[role]['access_token']}"}


@then("anonymous control calls should fail with HTTP 401")
def step_then_matrix_anonymous_401(context: Any) -> None:
    with _auth_client(context) as client:
        assert client.get("/api/v1/providers").status_code == 401
        assert client.patch("/api/v1/providers/tavily", json={"enabled": False}).status_code == 401


@then("provider reads should allow Admin and Developer but deny Agent")
def step_then_matrix_reads(context: Any) -> None:
    with _auth_client(context) as client:
        for role in ("admin", "developer"):
            response = client.get("/api/v1/providers", headers=_role_headers(context, role))
            assert response.status_code == 200
            assert isinstance(response.json(), list)
        denied = client.get("/api/v1/providers", headers=_role_headers(context, "agent"))
        assert denied.status_code == 403


@then("provider mutations should allow Admin but deny Developer and Agent")
def step_then_matrix_mutations(context: Any) -> None:
    with _auth_client(context) as client:
        for role in ("developer", "agent"):
            response = client.patch(
                "/api/v1/providers/tavily",
                json={"enabled": False},
                headers=_role_headers(context, role),
            )
            assert response.status_code == 403
        allowed = client.patch(
            "/api/v1/providers/tavily",
            json={"enabled": False},
            headers=_role_headers(context, "admin"),
        )
        assert allowed.status_code == 200
        assert allowed.json()["provider_id"] == "tavily"


@then("Agent search should succeed")
def step_then_matrix_agent_search(context: Any) -> None:
    with _auth_client(context) as client:
        response = client.post(
            "/search",
            json={"query": "matrix probe"},
            headers=_role_headers(context, "agent"),
        )
        assert response.status_code == 200
        assert response.json()["provider"] == "stubby"
