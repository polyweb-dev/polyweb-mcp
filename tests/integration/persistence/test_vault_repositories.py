"""Vault repositories against an isolated 0002 database with unregistered schema."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import Column, Integer, String, create_engine, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from freesearch.models.project_permissions import PROVIDER_OWNER_BIT
from freesearch.models.projects import DEFAULT_INSTALLATION_ACCOUNT_ID, CredentialOwnerScope
from freesearch.persistence.credentials import CredentialRepository
from freesearch.persistence.database_migrations import _config, migration_head
from freesearch.persistence.key_pools import KeyPoolRepository, KeyPoolValues
from freesearch.persistence.migrations.vault_rbac_schema import (
    add_vault_schema,
    finalize_vault_schema,
)
from freesearch.persistence.projects import ProjectRepository


@asynccontextmanager
async def world(
    path: Path, *, finalized: bool = False
) -> AsyncIterator[tuple[AsyncSession, UUID, UUID, UUID, UUID]]:
    command.upgrade(_config(path), "0002_capacity_actor")
    first, second, project, other_project = (uuid4() for _ in range(4))
    sync_engine = create_engine(f"sqlite:///{path.as_posix()}")
    with sync_engine.begin() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
        operations = Operations(MigrationContext.configure(connection))
        add_vault_schema(operations)
        if finalized:
            finalize_vault_schema(operations)
        for column in (
            Column("capacity_rate", Integer),
            Column("capacity_rate_window_seconds", Integer),
            Column("capacity_budget_micros", Integer),
            Column("capacity_budget_window", String(5)),
        ):
            operations.add_column("provider_credentials", column)
        for user in (first, second):
            connection.execute(
                text(
                    "INSERT INTO user (id,email,hashed_password,is_active,is_verified) "
                    "VALUES (:u,:email,'hash',1,1)"
                ),
                {"u": str(user), "email": f"{user}@example.test"},
            )
        for index, proj in enumerate((project, other_project)):
            connection.execute(
                text(
                    "INSERT INTO projects (id,account_id,name,slug,created_by,created_at) "
                    "VALUES (:p,:account,:name,:name,:u,'now')"
                ),
                {
                    "p": str(proj),
                    "account": str(DEFAULT_INSTALLATION_ACCOUNT_ID),
                    "name": f"project{index}",
                    "u": str(first),
                },
            )
            for user in (first, second):
                connection.execute(
                    text("INSERT INTO project_memberships (project_id,user_id) VALUES (:p,:u)"),
                    {"p": str(proj), "u": str(user)},
                )
                connection.execute(
                    text(
                        "INSERT INTO project_role_assignments "
                        "(project_id,user_id,role_key,granted_by) "
                        "VALUES (:p,:u,'project_admin',:u)"
                    ),
                    {"p": str(proj), "u": str(user)},
                )
    sync_engine.dispose()
    engine = create_async_engine(f"sqlite+aiosqlite:///{path.as_posix()}")
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            await session.execute(text("PRAGMA foreign_keys=ON"))
            yield session, first, second, project, other_project
    finally:
        await engine.dispose()


async def _credential(
    session: AsyncSession, owner: UUID, label: str = "key", provider_type: str = "tavily"
) -> UUID:
    credential = await CredentialRepository(session).insert_credential(
        account_id=DEFAULT_INSTALLATION_ACCOUNT_ID,
        provider_type=provider_type,
        owner_scope=CredentialOwnerScope.SYSTEM,
        owner_project_id=None,
        label=label,
        auth_mode="api_key",
        created_by=owner,
        owner_user_id=owner,
    )
    return credential.id


@pytest.mark.asyncio
async def test_vault_credential_ownership_and_policy(tmp_path: Path) -> None:
    async with world(tmp_path / "vault.db") as (session, first, second, _, _):
        repo = CredentialRepository(session)
        key = await _credential(session, first)
        assert len(await repo.list_for_owner(first)) == 1
        assert await repo.list_for_owner(second) == []
        assert await repo.get_owned(second, key) is None
        assert (
            await repo.update_policy(second, key, overcommit=False, contention_mode="ratio") is None
        )
        updated = await repo.update_policy(first, key, overcommit=False, contention_mode="ratio")
        assert updated is not None and not updated.overcommit and updated.contention_mode == "ratio"


@pytest.mark.asyncio
async def test_finalized_labels_are_unique_per_owner(tmp_path: Path) -> None:
    async with world(tmp_path / "vault.db", finalized=True) as (session, first, second, _, _):
        await _credential(session, first)
        await _credential(session, second)
        with pytest.raises(IntegrityError):
            async with session.begin_nested():
                await _credential(session, first)
        assert len(await CredentialRepository(session).list_for_owner(first)) == 1


@pytest.mark.asyncio
async def test_pool_crud_copy_lookup_and_unassign(tmp_path: Path) -> None:
    async with world(tmp_path / "vault.db") as (session, first, _, project, other):
        key = await _credential(session, first)
        repo = KeyPoolRepository(session)
        values = KeyPoolValues(
            label="primary",
            operations=frozenset({"search", "fetch"}),
            rate_limit=100,
            budget_limit=1234567,
            operation_limits={"search": {"rate_limit": 12}},
        )
        pool = await repo.create(
            credential_id=key,
            project_id=project,
            provider_type="tavily",
            created_by=first,
            values=values,
        )
        assert pool.budget_window_seconds == 2592000
        assert (await repo.get_for_project_provider(project, "tavily")) == pool
        assert len(await repo.list_for_key(key)) == len(await repo.list_for_project(project)) == 1
        copy = await repo.duplicate_to_project(pool.id, other, "copy", first)
        assert copy is not None and copy.operation_limits == values.operation_limits
        assert copy.budget_limit == 1234567
        changed = await repo.update(pool.id, values.model_copy(update={"rate_limit": 50}))
        assert changed is not None and changed.rate_limit == 50 and changed.version == 2
        assert await repo.unassign_owner_pools(project, first) == [pool.id]
        assert (await repo.get(pool.id)).project_id is None  # type: ignore[union-attr]
        assigned = await repo.assign(pool.id, project)
        assert assigned is not None and assigned.project_id == project
        assert (await repo.unassign(pool.id)).project_id is None  # type: ignore[union-attr]
        assert await repo.delete(pool.id)
        assert not await repo.delete(pool.id)


@pytest.mark.asyncio
async def test_pool_explicit_null_budget_window_round_trips(tmp_path: Path) -> None:
    async with world(tmp_path / "vault.db") as (session, first, _, _, _):
        key = await _credential(session, first)
        repo = KeyPoolRepository(session)
        pool = await repo.create(
            credential_id=key,
            project_id=None,
            provider_type="tavily",
            created_by=first,
            values=KeyPoolValues(
                label="none", operations=frozenset({"search"}), budget_window_seconds=None
            ),
        )
        assert pool.budget_window_seconds is None
        stored = await repo.get(pool.id)
        assert stored is not None and stored.budget_window_seconds is None


@pytest.mark.asyncio
async def test_unassign_owner_pools_does_not_touch_other_vaults(tmp_path: Path) -> None:
    async with world(tmp_path / "vault.db") as (session, first, second, project, _):
        first_key = await _credential(session, first)
        second_key = await _credential(session, second, provider_type="brave")
        repo = KeyPoolRepository(session)
        values = KeyPoolValues(label="pool", operations=frozenset({"search"}))
        first_pool = await repo.create(
            credential_id=first_key,
            project_id=project,
            provider_type="tavily",
            created_by=first,
            values=values,
        )
        second_pool = await repo.create(
            credential_id=second_key,
            project_id=project,
            provider_type="brave",
            created_by=second,
            values=values,
        )
        assert await repo.unassign_owner_pools(project, first) == [first_pool.id]
        remaining = await repo.list_for_project(project)
        assert [pool.id for pool in remaining] == [second_pool.id]


@pytest.mark.asyncio
async def test_pool_uniqueness_and_empty_operations(tmp_path: Path) -> None:
    async with world(tmp_path / "vault.db") as (session, first, _, project, _):
        key = await _credential(session, first)
        repo = KeyPoolRepository(session)
        values = KeyPoolValues(label="one", operations=frozenset({"search"}))
        await repo.create(
            credential_id=key,
            project_id=project,
            provider_type="tavily",
            created_by=first,
            values=values,
        )
        with pytest.raises(IntegrityError):
            async with session.begin_nested():
                await repo.create(
                    credential_id=key,
                    project_id=project,
                    provider_type="tavily",
                    created_by=first,
                    values=values.model_copy(update={"label": "two"}),
                )
        with pytest.raises(ValueError):
            KeyPoolValues(label="bad", operations=frozenset())


@pytest.mark.asyncio
async def test_permissions_transfer_claim_and_clear(tmp_path: Path) -> None:
    async with world(tmp_path / "vault.db") as (session, first, second, project, _):
        repo = ProjectRepository(session)
        assert await repo.transfer_provider_owner(project, None, first)
        assert await repo.set_member_permissions(project, first, 15)
        assert await repo.get_member_permissions(project, first) == PROVIDER_OWNER_BIT | 15
        assert not await repo.transfer_provider_owner(project, None, second)
        assert await repo.transfer_provider_owner(project, first, second)
        assert await repo.get_provider_owner(project) == second
        assert await repo.list_provider_owner_projects(second) == [project]
        assert await repo.clear_provider_owner_for_user(second) == [project]
        assert await repo.transfer_provider_owner(project, None, first)
        with pytest.raises(ValueError):
            await repo.set_member_permissions(project, second, PROVIDER_OWNER_BIT)


@pytest.mark.asyncio
async def test_concurrent_claims_have_one_winner(tmp_path: Path) -> None:
    async with world(tmp_path / "vault.db") as (session, first, second, project, _):
        await session.commit()
        engine = session.bind
        assert isinstance(engine, AsyncEngine)

        async def claim(user: UUID) -> bool:
            async with (
                async_sessionmaker(engine, expire_on_commit=False)() as contender,
                contender.begin(),
            ):
                return await ProjectRepository(contender).transfer_provider_owner(
                    project, None, user
                )

        assert sorted(await asyncio.gather(claim(first), claim(second))) == [False, True]
        assert await ProjectRepository(session).get_provider_owner(project) in (first, second)


@pytest.mark.asyncio
async def test_transfer_rolls_back_with_caller_transaction(tmp_path: Path) -> None:
    async with world(tmp_path / "vault.db") as (session, first, second, project, _):
        repo = ProjectRepository(session)
        assert await repo.transfer_provider_owner(project, None, first)
        await session.commit()
        assert await repo.transfer_provider_owner(project, first, second)
        await session.rollback()
        assert await repo.get_provider_owner(project) == first


@pytest.mark.asyncio
async def test_reject_non_admin_and_duplicate_owner(tmp_path: Path) -> None:
    async with world(tmp_path / "vault.db") as (session, first, second, project, _):
        repo = ProjectRepository(session)
        await session.execute(
            text("DELETE FROM project_role_assignments WHERE project_id=:p AND user_id=:u"),
            {"p": str(project), "u": str(second)},
        )
        assert not await repo.transfer_provider_owner(project, None, second)
        assert await repo.transfer_provider_owner(project, None, first)
        with pytest.raises(IntegrityError):
            async with session.begin_nested():
                await session.execute(
                    text(
                        "UPDATE project_memberships SET permissions=:owner "
                        "WHERE project_id=:p AND user_id=:u"
                    ),
                    {"owner": PROVIDER_OWNER_BIT, "p": str(project), "u": str(second)},
                )
        assert await repo.get_provider_owner(project) == first


@pytest.mark.asyncio
async def test_vault_credential_insert_works_on_migrated_head(tmp_path: Path) -> None:
    path = tmp_path / "migrated.db"
    command.upgrade(_config(path), migration_head())
    user = uuid4()
    engine = create_async_engine(f"sqlite+aiosqlite:///{path.as_posix()}")
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            await session.execute(
                text(
                    "INSERT INTO user (id,email,hashed_password,is_active,is_verified) "
                    "VALUES (:u,'legacy@example.test','hash',1,1)"
                ),
                {"u": str(user)},
            )
            repo = CredentialRepository(session)
            key = await repo.insert_credential(
                account_id=DEFAULT_INSTALLATION_ACCOUNT_ID,
                provider_type="tavily",
                owner_scope=CredentialOwnerScope.SYSTEM,
                owner_project_id=None,
                label="old",
                auth_mode="api_key",
                created_by=user,
                owner_user_id=user,
            )
            assert await repo.get_owned(user, key.id) is not None
            assert (
                await repo.get_system_credential(
                    account_id=DEFAULT_INSTALLATION_ACCOUNT_ID, credential_id=key.id
                )
                is None
            )
    finally:
        await engine.dispose()
