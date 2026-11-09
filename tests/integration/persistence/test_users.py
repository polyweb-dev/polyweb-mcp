"""Integration tests for account rows and the library adapter (P1, PLAN T1/T6/T8)."""

import asyncio
from pathlib import Path
from uuid import uuid4

import pytest
import pytest_asyncio
from fastapi_users import exceptions
from fastapi_users.password import PasswordHelper
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from polyweb.models.projects import DEFAULT_INSTALLATION_ACCOUNT_ID, BuiltinRole
from polyweb.models.users import AuthProvider, normalize_email
from polyweb.persistence.projects import ProjectRepository, SystemRoleAssignmentRow
from polyweb.persistence.storage import SQLiteRepository
from polyweb.persistence.users import (
    LoginThrottleRow,
    UserDatabase,
    UserRow,
    local_password_hash,
)
from tests.fixtures.auth import (
    TEMP_PASSWORD,
    auth_headers,
    create_temp_user,
    grant_system_admin,
    temp_email,
    temp_principal,
    temp_token,
)

_HELPER = PasswordHelper()


@pytest_asyncio.fixture
async def repository(tmp_path: Path) -> SQLiteRepository:
    repo = await SQLiteRepository.open(tmp_path / "users.db")
    yield repo
    await repo.close()


async def _system_roles(repository: SQLiteRepository, user_id: object) -> set[str]:
    """Return the durable system role keys of one account (the only authority source)."""

    async with repository.session() as session:
        rows = (
            await session.execute(
                select(SystemRoleAssignmentRow.role_key).where(
                    SystemRoleAssignmentRow.user_id == str(user_id)
                )
            )
        ).scalars()
        return set(rows)


async def _create(
    repository: SQLiteRepository, email: str, password: str = TEMP_PASSWORD
) -> UserRow:
    async with repository.session() as session:
        database = UserDatabase(session, UserRow)
        return await database.create({"email": email, "hashed_password": _HELPER.hash(password)})


async def test_create_normalizes_email_and_defaults_to_agent(
    repository: SQLiteRepository,
) -> None:
    user = await _create(repository, "Ops@Example.COM")

    assert user.email == "ops@example.com"
    assert not hasattr(user, "role")
    assert await _system_roles(repository, user.id) == set()
    assert user.auth_provider == AuthProvider.LOCAL.value
    assert user.auth_provider_id is None
    assert user.is_active is True
    assert user.is_superuser is False
    verified, _ = _HELPER.verify_and_update(TEMP_PASSWORD, str(user.hashed_password))
    assert verified is True


async def test_create_enforces_ordinary_human_defaults_and_privilege_requires_set_role(
    repository: SQLiteRepository,
) -> None:
    """T2-SIGNUP (A1): create makes an ordinary human; only a trusted grant adds authority."""

    for requested in ("admin", "developer", "agent", "system_admin"):
        async with repository.session() as session:
            database = UserDatabase(session, UserRow)
            user = await database.create(
                {
                    "email": temp_email(f"persist-{requested}"),
                    "hashed_password": _HELPER.hash(TEMP_PASSWORD),
                    "role": requested,
                }
            )
        assert await _system_roles(repository, user.id) == set()
        assert user.is_superuser is False
        assert user.is_active is True
        assert user.is_verified is False

    # Only the trusted bootstrap/operator path creates system authority.
    async with repository.session() as session:
        database = UserDatabase(session, UserRow)
        admin_user = await database.create(
            {
                "email": temp_email("promoted-admin"),
                "hashed_password": _HELPER.hash(TEMP_PASSWORD),
            }
        )
    await grant_system_admin(repository, admin_user.id)

    assert await _system_roles(repository, admin_user.id) == {BuiltinRole.SYSTEM_ADMIN.value}
    async with repository.session() as session:
        reloaded = await session.get(UserRow, admin_user.id)
        assert reloaded is not None
        # The library flag never mirrors the assignment.
        assert reloaded.is_superuser is False


async def test_create_ignores_privilege_flags_and_bad_roles(
    repository: SQLiteRepository,
) -> None:
    """T2-SIGNUP (A1): client status/privilege/provider fields never reach the row."""

    async with repository.session() as session:
        database = UserDatabase(session, UserRow)
        flagged = await database.create(
            {
                "email": temp_email("flagged"),
                "hashed_password": _HELPER.hash(TEMP_PASSWORD),
                "role": "admin",
                "is_superuser": True,
                "is_active": False,
                "is_verified": True,
                "auth_provider": "workos",
                "auth_provider_id": "forged",
                "system_role_assignments": ["system_admin"],
            }
        )
    assert flagged.is_superuser is False
    assert flagged.is_active is True
    assert flagged.is_verified is False
    assert flagged.auth_provider == AuthProvider.LOCAL.value
    assert flagged.auth_provider_id is None
    assert await _system_roles(repository, flagged.id) == set()

    for bad in ("superadmin", "ADMIN", None):
        async with repository.session() as session:
            database = UserDatabase(session, UserRow)
            fallback = await database.create(
                {
                    "email": temp_email("fallback"),
                    "hashed_password": _HELPER.hash(TEMP_PASSWORD),
                    "role": bad,
                }
            )
        assert await _system_roles(repository, fallback.id) == set()
        assert fallback.is_superuser is False


async def test_get_by_email_is_case_insensitive(repository: SQLiteRepository) -> None:
    await _create(repository, "Agent@Example.com")

    async with repository.session() as session:
        database = UserDatabase(session, UserRow)
        found = await database.get_by_email("AGENT@example.COM")

    assert found is not None
    assert found.email == "agent@example.com"


async def test_duplicate_email_raises_library_error(repository: SQLiteRepository) -> None:
    await _create(repository, "dup@example.com")

    async with repository.session() as session:
        database = UserDatabase(session, UserRow)
        with pytest.raises(exceptions.UserAlreadyExists):
            await database.create(
                {"email": "DUP@example.com", "hashed_password": _HELPER.hash(TEMP_PASSWORD)}
            )


async def test_concurrent_registrations_allow_only_one(
    repository: SQLiteRepository,
) -> None:
    email = temp_email("race")

    async def _attempt() -> bool:
        async with repository.session() as session:
            database = UserDatabase(session, UserRow)
            try:
                await database.create(
                    {"email": email, "hashed_password": _HELPER.hash(TEMP_PASSWORD)}
                )
            except exceptions.UserAlreadyExists:
                return False
            return True

    results = await asyncio.gather(*(_attempt() for _ in range(5)))

    assert sum(results) == 1


async def test_local_password_hash_branches(repository: SQLiteRepository) -> None:
    user = await create_temp_user(repository, temp_email("local"))

    async with repository.session() as session:
        database = UserDatabase(session, UserRow)
        found = await database.get_by_email(user.email)
        assert found is not None
        assert local_password_hash(found) == str(found.hashed_password)

    workos = UserRow(
        id=uuid4(),
        email=temp_email("workos"),
        hashed_password=None,
        is_active=True,
        is_verified=False,
        auth_provider=AuthProvider.WORKOS.value,
        auth_provider_id="ext-1",
    )
    assert local_password_hash(workos) is None


async def test_database_rejects_invalid_provider_shapes(repository: SQLiteRepository) -> None:
    base = {
        "id": uuid4(),
        "email": "shape@example.com",
        "is_active": True,
        "is_verified": False,
    }
    shapes = [
        {
            **base,
            "hashed_password": None,
            "auth_provider": "local",
            "auth_provider_id": None,
            "email": "s1@example.com",
            "id": uuid4(),
        },
        {
            **base,
            "hashed_password": "",
            "auth_provider": "local",
            "auth_provider_id": None,
            "email": "s2@example.com",
            "id": uuid4(),
        },
        {
            **base,
            "hashed_password": "h",
            "auth_provider": "workos",
            "auth_provider_id": "ext-1",
            "email": "s3@example.com",
            "id": uuid4(),
        },
        {
            **base,
            "hashed_password": None,
            "auth_provider": "workos",
            "auth_provider_id": None,
            "email": "s4@example.com",
            "id": uuid4(),
        },
        {
            **base,
            "hashed_password": "h",
            "auth_provider": "local",
            "auth_provider_id": "ext-2",
            "email": "s5@example.com",
            "id": uuid4(),
        },
        {
            # RC-1: a foreign provider passes every other check, so only the
            # provider value constraint can reject it.
            **base,
            "hashed_password": None,
            "auth_provider": "github",
            "auth_provider_id": None,
            "email": "s7@example.com",
            "id": uuid4(),
        },
    ]
    async with repository.session() as session:
        for shape in shapes:
            session.add(UserRow(**shape))
            with pytest.raises(IntegrityError):
                await session.flush()
            await session.rollback()


async def test_set_role_updates_privilege_without_commit(
    repository: SQLiteRepository,
) -> None:
    """A1: the system role repository flushes in the caller's transaction, never commits."""

    user = await create_temp_user(repository, temp_email("role"))
    await create_temp_user(repository, temp_email("installation-seed"), system_admin=True)

    async with repository.session() as session:
        projects = ProjectRepository(session)
        await projects.assign_system_role(
            account_id=DEFAULT_INSTALLATION_ACCOUNT_ID,
            user_id=user.id,
            role_key=BuiltinRole.SYSTEM_ADMIN.value,
            granted_by=user.id,
        )
        await session.rollback()
    assert await _system_roles(repository, user.id) == set()

    async with repository.session() as session:
        projects = ProjectRepository(session)
        await projects.assign_system_role(
            account_id=DEFAULT_INSTALLATION_ACCOUNT_ID,
            user_id=user.id,
            role_key=BuiltinRole.SYSTEM_ADMIN.value,
            granted_by=user.id,
        )
        await session.commit()
    assert await _system_roles(repository, user.id) == {BuiltinRole.SYSTEM_ADMIN.value}

    async with repository.session() as session:
        projects = ProjectRepository(session)
        assert (
            await projects.delete_system_role(
                account_id=DEFAULT_INSTALLATION_ACCOUNT_ID,
                user_id=user.id,
                role_key=BuiltinRole.SYSTEM_ADMIN.value,
            )
            is True
        )
        await session.rollback()
    assert await _system_roles(repository, user.id) == {BuiltinRole.SYSTEM_ADMIN.value}

    async with repository.session() as session:
        assert (
            await ProjectRepository(session).delete_system_role(
                account_id=DEFAULT_INSTALLATION_ACCOUNT_ID,
                user_id=uuid4(),
                role_key=BuiltinRole.SYSTEM_ADMIN.value,
            )
            is False
        )


async def test_login_throttle_row_persists_digest_key(repository: SQLiteRepository) -> None:
    async with repository.session() as session:
        session.add(
            LoginThrottleRow(key="a" * 64, attempts=1, expires_at="2026-01-01T00:00:00+00:00")
        )
        await session.commit()

    async with repository.session() as session:
        row = await session.get(LoginThrottleRow, "a" * 64)
        assert row is not None
        assert row.attempts == 1


async def test_storage_session_rolls_back_on_error(repository: SQLiteRepository) -> None:
    key = "b" * 64
    with pytest.raises(RuntimeError, match="boom"):
        async with repository.session() as session:
            session.add(
                LoginThrottleRow(key=key, attempts=1, expires_at="2026-01-01T00:00:00+00:00")
            )
            await session.flush()
            raise RuntimeError("boom")

    async with repository.session() as session:
        assert await session.get(LoginThrottleRow, key) is None


async def test_temp_fixture_helpers_use_explicit_accounts(
    repository: SQLiteRepository,
) -> None:
    email = temp_email("fixture")
    user = await create_temp_user(repository, email)
    principal = temp_principal(user)
    token = temp_token()

    assert principal.email == normalize_email(email)
    assert "role" not in principal.model_dump()
    assert await _system_roles(repository, user.id) == set()
    headers = auth_headers(token)
    assert headers["Authorization"].startswith("Bearer ")
    assert token.get_secret_value() not in repr(token)
    assert "Authorization" in headers


async def test_two_explicit_accounts_stay_distinct(repository: SQLiteRepository) -> None:
    first = await create_temp_user(repository, temp_email("first"))
    second = await create_temp_user(repository, temp_email("second"))

    assert first.id != second.id
    assert first.email != second.email

    async with repository.session() as session:
        rows = (await session.execute(select(UserRow))).scalars().all()
        emails = {str(row.email) for row in rows}
    assert str(first.email) in emails
    assert str(second.email) in emails


async def test_user_row_privilege_fails_closed_across_unloaded_and_rollback(
    repository: SQLiteRepository,
) -> None:
    """Authority derives strictly from durable assignments; constructor and rollback fail closed."""

    with pytest.raises(TypeError):
        UserRow(email=temp_email("fake-admin"), role="admin")
    with pytest.raises((TypeError, AttributeError)):
        UserRow(email=temp_email("fake-admin"), is_superuser=True)
    plain = UserRow(email=temp_email("plain"))
    assert plain.is_superuser is False
    with pytest.raises(AttributeError):
        plain.is_superuser = True  # type: ignore[misc]

    await create_temp_user(repository, temp_email("installation-seed"), system_admin=True)
    user = await _create(repository, temp_email("rollback-priv"))
    async with repository.session() as session:
        await ProjectRepository(session).assign_system_role(
            account_id=DEFAULT_INSTALLATION_ACCOUNT_ID,
            user_id=user.id,
            role_key=BuiltinRole.SYSTEM_ADMIN.value,
            granted_by=user.id,
        )
        loaded = await session.get(UserRow, user.id)
        assert loaded is not None
        assert loaded.is_superuser is False
        await session.rollback()

    assert await _system_roles(repository, user.id) == set()
    async with repository.session() as session:
        fresh = await session.get(UserRow, user.id)
        assert fresh is not None
        assert fresh.is_superuser is False
