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
from tests.fixtures.execution import bdd_project_id

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
            json={
                "project_id": bdd_project_id(context, {"Authorization": f"Bearer {token}"}),
                "query": "local accounts",
            },
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


@when("I call Search and Fetch without a token")
def step_when_auth_anonymous_provider_operations(context: Any) -> None:
    with _auth_client(context) as client:
        context.anonymous_search = client.post("/search", json={"query": "public probe"})
        context.anonymous_fetch = client.post("/fetch", json={"url": "https://example.com/public"})


@then("both provider operations should be rejected with 401")
def step_then_auth_anonymous_provider_operations(context: Any) -> None:
    assert context.anonymous_search.status_code == 401
    assert context.anonymous_fetch.status_code == 401


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
            json={
                "project_id": "00000000-0000-4000-8000-0000000000aa",
                "query": "misplaced probe",
            },
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
    from tests.fixtures.auth import create_temp_user

    context.role_pairs = {}
    with _auth_client(context) as client:
        admin_email = f"matrix-admin-{uuid4().hex[:6]}@example.com"
        registered = client.post(
            "/auth/register",
            json={"email": admin_email, "password": _AUTH_PASSWORD, "role": "admin"},
        )
        assert registered.status_code == 201
        assert registered.json()["role"] == "admin"
        logged_in = client.post(
            "/auth/jwt/login", data={"username": admin_email, "password": _AUTH_PASSWORD}
        )
        assert logged_in.status_code == 200
        context.role_pairs["admin"] = logged_in.json()
        for role_name in ("developer", "agent"):
            email = f"matrix-{role_name}-{uuid4().hex[:6]}@example.com"
            context.loop.run_until_complete(
                create_temp_user(
                    context.repository,
                    email,
                    role=UserRole.DEVELOPER if role_name == "developer" else UserRole.AGENT,
                    password=_AUTH_PASSWORD,
                )
            )
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
            json={
                "project_id": bdd_project_id(context, _role_headers(context)),
                "query": "matrix probe",
            },
            headers=_role_headers(context, "agent"),
        )
        assert response.status_code == 200
        assert response.json()["provider"] == "stubby"


_BROWSER_ORIGIN = "http://localhost:5177"
_BROWSER_MARKER = {"Origin": _BROWSER_ORIGIN, "X-FreeSearch-Client": "browser"}


def _configure_browser_origins(context: Any) -> None:
    import os

    from freesearch.configuration.config import get_settings

    previous = os.environ.get("FREESEARCH_AUTH_BROWSER_ORIGINS")
    os.environ["FREESEARCH_AUTH_BROWSER_ORIGINS"] = f'["{_BROWSER_ORIGIN}"]'
    get_settings.cache_clear()

    def _restore() -> None:
        if previous is None:
            os.environ.pop("FREESEARCH_AUTH_BROWSER_ORIGINS", None)
        else:
            os.environ["FREESEARCH_AUTH_BROWSER_ORIGINS"] = previous
        get_settings.cache_clear()

    cleanups: list[Any] = getattr(context, "enc_cleanups", None) or []
    context.enc_cleanups = cleanups
    cleanups.append(_restore)


@given("an offline users API with browser cookie transport")
def step_given_users_browser_api(context: Any) -> None:
    _configure_auth_secret(context)
    _configure_browser_origins(context)
    _open_users_repository(context)
    context.adapters = [_UsersStubAdapter("stubby")]
    context.app = create_app(context.adapters, repository=context.repository)
    context.browser_cookie = None


def _browser_cookie_headers(context: Any) -> dict[str, str]:
    assert context.browser_cookie is not None
    return {
        **_BROWSER_MARKER,
        "Cookie": f"__Secure-freesearch_refresh={context.browser_cookie}",
    }


@when("I log in through the browser")
def step_when_browser_login(context: Any) -> None:
    with _auth_client(context) as client:
        context.browser_login_response = client.post(
            "/auth/jwt/login",
            data={"username": context.auth_email, "password": _AUTH_PASSWORD},
            headers=dict(_BROWSER_MARKER),
        )
        if context.browser_login_response.status_code == 200:
            context.browser_pair = context.browser_login_response.json()


@then("the browser login should issue a strict cookie without a JSON refresh credential")
def step_then_browser_login_cookie(context: Any) -> None:
    from freesearch.infrastructure.browser_auth import (
        REFRESH_COOKIE_NAME,
        REFRESH_COOKIE_PATH,
    )

    response = context.browser_login_response
    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"]
    assert body["expires_in"] == 900
    assert "refresh_token" not in body
    assert "refresh_token" not in response.text
    assert response.headers["cache-control"] == "no-store"
    raw = response.headers.get("set-cookie", "")
    assert raw.startswith(f"{REFRESH_COOKIE_NAME}=")
    assert f"Path={REFRESH_COOKIE_PATH}" in raw
    assert "HttpOnly" in raw
    assert "Secure" in raw
    assert "SameSite=Strict" in raw
    assert "Domain=" not in raw
    context.browser_cookie = raw.split(";", 1)[0].split("=", 1)[1]
    assert context.browser_cookie != ""
    assert context.browser_cookie not in response.text


@then("the programmatic login should set no cookie")
def step_then_programmatic_no_cookie(context: Any) -> None:
    assert "set-cookie" not in context.login_response.headers
    assert context.login_response.json()["refresh_token"]


@when("I refresh through the browser cookie")
def step_when_browser_refresh(context: Any) -> None:
    context.browser_first_cookie = context.browser_cookie
    with _auth_client(context) as client:
        context.browser_refresh_response = client.post(
            "/auth/jwt/refresh", headers=_browser_cookie_headers(context)
        )
        if context.browser_refresh_response.status_code == 200:
            context.browser_rotated = context.browser_refresh_response.json()
            raw = context.browser_refresh_response.headers.get("set-cookie", "")
            context.browser_rotated_cookie = raw.split(";", 1)[0].split("=", 1)[1]


@then("the browser refresh should rotate the cookie once")
def step_then_browser_refresh_rotated(context: Any) -> None:
    response = context.browser_refresh_response
    assert response.status_code == 200
    assert response.json()["access_token"]
    assert "refresh_token" not in response.json()
    assert response.headers["cache-control"] == "no-store"
    assert context.browser_rotated_cookie != context.browser_first_cookie
    assert context.browser_rotated_cookie not in response.text
    context.browser_cookie = context.browser_rotated_cookie


@when("I reuse the consumed browser cookie")
def step_when_browser_reuse(context: Any) -> None:
    with _auth_client(context) as client:
        context.browser_reuse_response = client.post(
            "/auth/jwt/refresh",
            headers={
                **_BROWSER_MARKER,
                "Cookie": f"__Secure-freesearch_refresh={context.browser_first_cookie}",
            },
        )


@then("the consumed browser reuse should fail with HTTP 401 and expire the cookie")
def step_then_browser_reuse_401(context: Any) -> None:
    response = context.browser_reuse_response
    assert response.status_code == 401
    raw = response.headers.get("set-cookie", "")
    assert "Max-Age=0" in raw
    assert "Path=/auth/jwt/refresh" in raw
    assert context.browser_first_cookie not in response.text


@then("the rotated browser credentials should fail at once")
def step_then_browser_rotated_dead(context: Any) -> None:
    with _auth_client(context) as client:
        stale = client.post(
            "/auth/jwt/refresh",
            headers={
                **_BROWSER_MARKER,
                "Cookie": f"__Secure-freesearch_refresh={context.browser_rotated_cookie}",
            },
        )
        assert stale.status_code == 401
        probe = client.get(
            "/users/me",
            headers={"Authorization": f"Bearer {context.browser_rotated['access_token']}"},
        )
        assert probe.status_code == 401


@when("I refresh with an invalid Origin")
def step_when_browser_invalid_origin(context: Any) -> None:
    with _auth_client(context) as client:
        context.browser_forged_response = client.post(
            "/auth/jwt/refresh",
            headers={
                "Origin": "https://evil.example.com",
                "X-FreeSearch-Client": "browser",
                "Cookie": f"__Secure-freesearch_refresh={context.browser_cookie}",
            },
        )


@then("the invalid Origin refresh should fail with HTTP 403 without cookie deletion")
def step_then_browser_forged_403(context: Any) -> None:
    response = context.browser_forged_response
    assert response.status_code == 403
    assert "set-cookie" not in response.headers
    assert context.browser_cookie not in response.text
    with _auth_client(context) as client:
        live = client.post("/auth/jwt/refresh", headers=_browser_cookie_headers(context))
        assert live.status_code == 200
        raw = live.headers.get("set-cookie", "")
        context.browser_cookie = raw.split(";", 1)[0].split("=", 1)[1]


@when("I log out through the browser cookie")
def step_when_browser_logout(context: Any) -> None:
    with _auth_client(context) as client:
        context.browser_logout_response = client.request(
            "DELETE", "/auth/jwt/refresh", headers=_browser_cookie_headers(context)
        )


@then("the browser logout should revoke the family and expire the cookie")
def step_then_browser_logout_ok(context: Any) -> None:
    response = context.browser_logout_response
    assert response.status_code == 204
    assert response.headers["cache-control"] == "no-store"
    raw = response.headers.get("set-cookie", "")
    assert "Max-Age=0" in raw
    assert "Path=/auth/jwt/refresh" in raw
    with _auth_client(context) as client:
        assert (
            client.post("/auth/jwt/refresh", headers=_browser_cookie_headers(context)).status_code
            == 401
        )


def _role_account_id(context: Any, role: str) -> str:
    with _auth_client(context) as client:
        me = client.get("/users/me", headers=_role_headers(context, role))
        assert me.status_code == 200
        return str(me.json()["id"])


@when('I register with role "{role}" as "{email}"')
def step_when_register_with_role(context: Any, role: str, email: str) -> None:
    context.auth_email = email
    context.auth_role = role
    with _auth_client(context) as client:
        context.register_response = client.post(
            "/auth/register", json={"email": email, "password": _AUTH_PASSWORD, "role": role}
        )


@then('the role signup should create "{role}" without tokens')
def step_then_role_signup_ok(context: Any, role: str) -> None:
    response = context.register_response
    assert response.status_code == 201
    body = response.json()
    assert body["email"] == context.auth_email.lower()
    assert body["role"] == role
    assert body["is_active"] is True
    assert body["is_superuser"] is (role == "admin")
    assert "access_token" not in body
    assert "refresh_token" not in body
    assert "hashed_password" not in body


@when('I log in with role "{role}" as "{email}"')
def step_when_login_with_role(context: Any, role: str, email: str) -> None:
    context.auth_email = email
    with _auth_client(context) as client:
        context.login_response = client.post(
            "/auth/jwt/login", data={"username": email, "password": _AUTH_PASSWORD}
        )
        if context.login_response.status_code == 200:
            context.auth_pair = context.login_response.json()


@then('the role login should report "{role}" with a 900-second access token')
def step_then_role_login_ok(context: Any, role: str) -> None:
    assert context.login_response.status_code == 200
    assert context.login_response.json()["access_token"]
    with _auth_client(context) as client:
        me = client.get(
            "/users/me",
            headers={"Authorization": f"Bearer {context.auth_pair['access_token']}"},
        )
    assert me.status_code == 200
    assert me.json()["role"] == role


@when('the Admin provisions an "{role}" account')
@when('the Admin provisions a "{role}" account')
def step_when_admin_provisions(context: Any, role: str) -> None:
    email = f"provision-{role}-{uuid4().hex[:6]}@example.com"
    context.provision_email = email
    context.provision_role = role
    with _auth_client(context) as client:
        context.provision_response = client.post(
            "/api/v1/users",
            json={"email": email, "password": _AUTH_PASSWORD, "role": role},
            headers=_role_headers(context, "admin"),
        )


@then('the provisioning should create "{role}" without credentials and keep the caller live')
def step_then_provision_ok(context: Any, role: str) -> None:
    response = context.provision_response
    assert response.status_code == 201
    body = response.json()
    assert body["email"] == context.provision_email.lower()
    assert body["role"] == role
    assert set(body.keys()) == {"id", "email", "role", "is_active", "is_superuser", "is_verified"}
    assert "access_token" not in body
    assert "refresh_token" not in body
    assert "hashed_password" not in body
    assert "set-cookie" not in response.headers
    with _auth_client(context) as client:
        assert client.get("/users/me", headers=_role_headers(context, "admin")).status_code == 200
        logged_in = client.post(
            "/auth/jwt/login",
            data={"username": context.provision_email, "password": _AUTH_PASSWORD},
        )
        assert logged_in.status_code == 200
        me = client.get(
            "/users/me",
            headers={"Authorization": f"Bearer {logged_in.json()['access_token']}"},
        )
        assert me.status_code == 200
        assert me.json()["role"] == role


@then("a Developer provisioning should fail with HTTP 403")
def step_then_developer_provision_403(context: Any) -> None:
    with _auth_client(context) as client:
        denied = client.post(
            "/api/v1/users",
            json={
                "email": f"blocked-dev-{uuid4().hex[:6]}@example.com",
                "password": _AUTH_PASSWORD,
                "role": "agent",
            },
            headers=_role_headers(context, "developer"),
        )
        assert denied.status_code == 403
        assert (
            client.get("/users/me", headers=_role_headers(context, "developer")).status_code == 200
        )


@then("an Agent provisioning should fail with HTTP 403")
def step_then_agent_provision_403(context: Any) -> None:
    with _auth_client(context) as client:
        denied = client.post(
            "/api/v1/users",
            json={
                "email": f"blocked-agent-{uuid4().hex[:6]}@example.com",
                "password": _AUTH_PASSWORD,
                "role": "agent",
            },
            headers=_role_headers(context, "agent"),
        )
        assert denied.status_code == 403
        assert client.get("/users/me", headers=_role_headers(context, "agent")).status_code == 200


@then("an anonymous provisioning should fail with HTTP 401")
def step_then_anonymous_provision_401(context: Any) -> None:
    with _auth_client(context) as client:
        assert (
            client.post(
                "/api/v1/users",
                json={
                    "email": f"blocked-anon-{uuid4().hex[:6]}@example.com",
                    "password": _AUTH_PASSWORD,
                    "role": "agent",
                },
            ).status_code
            == 401
        )


@then("legacy account routes should deny every role with HTTP 403 and keep sessions live")
def step_then_legacy_deny_all(context: Any) -> None:
    denied_detail = "account management is not available before project association"
    with _auth_client(context) as client:
        me = client.get("/users/me", headers=_role_headers(context, "agent"))
        assert me.status_code == 200
        target = str(me.json()["id"])
        unknown = str(uuid4())
        for role in ("admin", "developer", "agent"):
            headers = _role_headers(context, role)
            for path in (
                f"/api/v1/users/{target}",
                f"/api/v1/users/{unknown}",
                "/api/v1/users/not-a-uuid",
            ):
                denied = client.get(path, headers=headers)
                assert denied.status_code == 403
                assert denied.json() == {"detail": denied_detail}
            for path in (f"/api/v1/users/{target}/role", f"/api/v1/users/{unknown}/role"):
                denied = client.patch(path, json={"role": "agent"}, headers=headers)
                assert denied.status_code == 403
                assert denied.json() == {"detail": denied_detail}
        # No denial changed a role and no denial revoked a family.
        check = client.get("/users/me", headers=_role_headers(context, "agent"))
        assert check.status_code == 200
        assert check.json()["role"] == "agent"
        for role in ("admin", "developer", "agent"):
            assert client.get("/users/me", headers=_role_headers(context, role)).status_code == 200


@when("I prepare one Admin account")
def step_when_prepare_one_admin(context: Any) -> None:
    context.role_pairs = {}
    email = f"matrix-admin-{uuid4().hex[:6]}@example.com"
    with _auth_client(context) as client:
        registered = client.post(
            "/auth/register", json={"email": email, "password": _AUTH_PASSWORD, "role": "admin"}
        )
        assert registered.status_code == 201
        logged_in = client.post(
            "/auth/jwt/login", data={"username": email, "password": _AUTH_PASSWORD}
        )
        assert logged_in.status_code == 200
        context.role_pairs["admin"] = logged_in.json()


@when("I consume the shared creation limit")
def step_when_consume_shared_limit(context: Any) -> None:
    with _auth_client(context) as client:
        for index in range(4):
            email = f"limit-share-{index}-{uuid4().hex[:4]}@example.com"
            if index < 2:
                response = client.post(
                    "/auth/register", json={"email": email, "password": _AUTH_PASSWORD}
                )
            else:
                response = client.post(
                    "/api/v1/users",
                    json={"email": email, "password": _AUTH_PASSWORD, "role": "agent"},
                    headers=_role_headers(context, "admin"),
                )
            assert response.status_code == 201
        context.limit_email = f"limit-share-5-{uuid4().hex[:4]}@example.com"
        context.limit_response = client.post(
            "/api/v1/users",
            json={"email": context.limit_email, "password": _AUTH_PASSWORD, "role": "agent"},
            headers=_role_headers(context, "admin"),
        )


@then("the sixth creation should fail with HTTP 429 and a retry delay")
def step_then_shared_limit_429(context: Any) -> None:
    response = context.limit_response
    assert response.status_code == 429
    assert response.headers.get("retry-after")
    assert _AUTH_PASSWORD not in response.text


@then("invalid creation roles should fail with safe HTTP 422")
def step_then_invalid_creation_roles_422(context: Any) -> None:
    with _auth_client(context) as client:
        for bad in ("superadmin", "ADMIN", None):
            rejected = client.post(
                "/api/v1/users",
                json={
                    "email": f"bad-{uuid4().hex[:4]}@example.com",
                    "password": _AUTH_PASSWORD,
                    "role": bad,
                },
                headers=_role_headers(context, "admin"),
            )
            assert rejected.status_code == 422
            assert rejected.json() == {"detail": "invalid authentication request"}


@then("privileged creation fields should fail with safe HTTP 422")
def step_then_privileged_fields_422(context: Any) -> None:
    with _auth_client(context) as client:
        rejected = client.post(
            "/api/v1/users",
            json={
                "email": f"widen-{uuid4().hex[:4]}@example.com",
                "password": _AUTH_PASSWORD,
                "role": "agent",
                "extra": "agent",
            },
            headers=_role_headers(context, "admin"),
        )
        assert rejected.status_code == 422
        assert rejected.json() == {"detail": "invalid authentication request"}
        flagged = client.post(
            "/api/v1/users",
            json={
                "email": f"flag-{uuid4().hex[:4]}@example.com",
                "password": _AUTH_PASSWORD,
                "role": "agent",
                "is_superuser": True,
            },
            headers=_role_headers(context, "admin"),
        )
        assert flagged.status_code == 201
        assert flagged.json()["role"] == "agent"
        assert flagged.json()["is_superuser"] is False


@then("weak provisioned passwords and duplicate email should fail safely")
def step_then_weak_and_duplicate_safe(context: Any) -> None:
    with _auth_client(context) as client:
        weak = client.post(
            "/api/v1/users",
            json={
                "email": f"weak-{uuid4().hex[:4]}@example.com",
                "password": "short",
                "role": "agent",
            },
            headers=_role_headers(context, "admin"),
        )
        assert weak.status_code == 400
        assert "short" not in weak.text
        email = f"dup-bdd-{uuid4().hex[:6]}@example.com"
        first = client.post(
            "/api/v1/users",
            json={"email": email, "password": _AUTH_PASSWORD, "role": "agent"},
            headers=_role_headers(context, "admin"),
        )
        assert first.status_code == 201
        second = client.post(
            "/api/v1/users",
            json={"email": email, "password": _AUTH_PASSWORD, "role": "agent"},
            headers=_role_headers(context, "admin"),
        )
        assert second.status_code == 400
