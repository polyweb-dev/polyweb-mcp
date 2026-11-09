"""Shared serialized write runner (A4): retries, bounds, rollback, cancellation.

Real temporary SQLite. Lock errors are injected as the exact
``sqlalchemy.exc.OperationalError`` SQLite raises, so the retry predicate is
exercised without timing-dependent lock contention. Every case proves the
operation's write was rolled back (or committed exactly once) by reading the
row back on a fresh session.
"""

from __future__ import annotations

import asyncio
import sqlite3
from collections.abc import AsyncIterator
from pathlib import Path
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from polyweb.models.projects import DEFAULT_INSTALLATION_ACCOUNT_ID
from polyweb.persistence import transactions
from polyweb.persistence.storage import RuntimeSettingRow, SQLiteRepository
from polyweb.persistence.transactions import is_sqlite_lock_error, run_serialized
from polyweb.services.control_access import run_control_write
from polyweb.services.control_errors import ControlStorageUnavailable, ResourceConflict
from tests.fixtures.alpha_fixtures import create_alpha_test_db
from tests.fixtures.api_keys import audit_rows


def _lock_error(message: str = "database is locked") -> OperationalError:
    return OperationalError("BEGIN IMMEDIATE", {}, sqlite3.OperationalError(message))


@pytest_asyncio.fixture
async def repository(tmp_path: Path) -> AsyncIterator[SQLiteRepository]:
    repo = await create_alpha_test_db(tmp_path / "tx.db")
    try:
        yield repo
    finally:
        await repo.close()


@pytest.fixture
def sleeps(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    recorded: list[float] = []

    async def _sleep(delay: float) -> None:
        recorded.append(delay)

    monkeypatch.setattr(transactions.asyncio, "sleep", _sleep)
    return recorded


async def _write(session: AsyncSession, key: str, value: str) -> None:
    session.add(RuntimeSettingRow(key=key, value_json=f'"{value}"'))
    await session.flush()


async def _read(repository: SQLiteRepository, key: str) -> str | None:
    async with repository.session() as session:
        row = await session.get(RuntimeSettingRow, key)
        return None if row is None else row.value_json


def test_lock_predicate_matches_only_lock_and_busy_messages() -> None:
    assert is_sqlite_lock_error(_lock_error("database is locked"))
    assert is_sqlite_lock_error(_lock_error("database table is locked"))
    assert not is_sqlite_lock_error(_lock_error("no such table: x"))
    assert not is_sqlite_lock_error(_lock_error("disk I/O error"))


@pytest.mark.asyncio
async def test_lock_errors_retry_with_backoff_then_commit_once(
    repository: SQLiteRepository, sleeps: list[float]
) -> None:
    key = f"tx-retry-{uuid4().hex}"
    attempts = 0

    async def operation(session: AsyncSession) -> str:
        nonlocal attempts
        attempts += 1
        await _write(session, key, f"attempt-{attempts}")
        if attempts < 3:
            raise _lock_error()
        return "done"

    assert await run_serialized(repository, operation, max_attempts=5) == "done"
    assert attempts == 3
    assert sleeps == [0.02, 0.04]
    # Earlier attempts rolled back: only the committed attempt's value exists.
    assert await _read(repository, key) == '"attempt-3"'


@pytest.mark.asyncio
async def test_lock_retries_are_bounded_and_reraise_the_original(
    repository: SQLiteRepository, sleeps: list[float]
) -> None:
    key = f"tx-bounded-{uuid4().hex}"
    attempts = 0
    raised: list[OperationalError] = []

    async def operation(session: AsyncSession) -> None:
        nonlocal attempts
        attempts += 1
        await _write(session, key, "never")
        error = _lock_error()
        raised.append(error)
        raise error

    with pytest.raises(OperationalError) as excinfo:
        await run_serialized(repository, operation, max_attempts=3)
    assert attempts == 3
    assert excinfo.value is raised[-1]
    assert sleeps == [0.02, 0.04]
    assert await _read(repository, key) is None


@pytest.mark.asyncio
async def test_non_lock_errors_roll_back_without_retry(
    repository: SQLiteRepository, sleeps: list[float]
) -> None:
    for error in (_lock_error("no such table: x"), ValueError("domain rule")):
        key = f"tx-domain-{uuid4().hex}"
        attempts = 0

        async def operation(session: AsyncSession, exc: Exception = error, name: str = key) -> None:
            nonlocal attempts
            attempts += 1
            await _write(session, name, "rolled-back")
            raise exc

        with pytest.raises(type(error)) as excinfo:
            await run_serialized(repository, operation, max_attempts=5)
        assert excinfo.value is error
        assert attempts == 1
        assert await _read(repository, key) is None
    assert sleeps == []


@pytest.mark.asyncio
async def test_cancellation_rolls_back_and_propagates(repository: SQLiteRepository) -> None:
    key = f"tx-cancel-{uuid4().hex}"
    entered = asyncio.Event()
    attempts = 0

    async def operation(session: AsyncSession) -> None:
        nonlocal attempts
        attempts += 1
        await _write(session, key, "cancelled")
        entered.set()
        await asyncio.Event().wait()

    task = asyncio.create_task(run_serialized(repository, operation))
    await asyncio.wait_for(entered.wait(), timeout=10)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert attempts == 1
    assert await _read(repository, key) is None
    # The write lock was released: a following write commits.
    await run_serialized(repository, lambda session: _write(session, key, "after"))
    assert await _read(repository, key) == '"after"'


@pytest.mark.asyncio
async def test_begin_immediate_serializes_concurrent_writers(
    repository: SQLiteRepository,
) -> None:
    """Read-modify-write under the runner never loses an update."""

    key = f"tx-counter-{uuid4().hex}"
    await run_serialized(repository, lambda session: _write(session, key, "0"))

    async def increment(session: AsyncSession) -> None:
        row = await session.get(RuntimeSettingRow, key)
        assert row is not None
        current = int(row.value_json.strip('"'))
        await asyncio.sleep(0)
        row.value_json = f'"{current + 1}"'
        await session.flush()

    await asyncio.gather(*(run_serialized(repository, increment) for _ in range(10)))
    assert await _read(repository, key) == '"10"'


@pytest.mark.asyncio
async def test_control_write_maps_storage_failures(
    repository: SQLiteRepository, sleeps: list[float]
) -> None:
    async def locked(session: AsyncSession) -> None:
        raise _lock_error()

    with pytest.raises(ControlStorageUnavailable):
        await run_control_write(repository, locked, conflict_code="X_CONFLICT", max_attempts=2)

    async def integrity(session: AsyncSession) -> None:
        raise IntegrityError("INSERT", {}, sqlite3.IntegrityError("UNIQUE constraint failed"))

    with pytest.raises(ResourceConflict) as excinfo:
        await run_control_write(repository, integrity, conflict_code="X_CONFLICT")
    assert excinfo.value.code == "X_CONFLICT"


@pytest.mark.asyncio
async def test_audit_append_rolls_back_with_a_failed_mutation(
    repository: SQLiteRepository,
) -> None:
    """An audit row appended inside a mutation that later fails is never committed."""

    from polyweb.services.audit_events import record_project_event, record_system_event
    from tests.fixtures.auth import create_temp_user, temp_email, temp_principal
    from tests.fixtures.execution import seed_execution_project

    user = await create_temp_user(repository, temp_email("tx-audit"))
    project_id = (await seed_execution_project(repository, user_id=user.id)).project_id
    actor = temp_principal(user)
    target = str(uuid4())

    async def operation(session: AsyncSession) -> None:
        await record_system_event(
            session,
            account_id=DEFAULT_INSTALLATION_ACCOUNT_ID,
            actor=actor,
            action="pool.created",
            target_type="pool",
            target_id=target,
        )
        await record_project_event(
            session,
            project_id=project_id,
            actor=actor,
            action="binding.created",
            target_type="binding",
            target_id=target,
        )
        raise ValueError("mutation failed after its audit append")

    with pytest.raises(ValueError):
        await run_serialized(repository, operation)
    for scope in ("system", "project"):
        rows = await audit_rows(repository, scope=scope)
        assert target not in {row["target_id"] for row in rows}


@pytest.mark.asyncio
async def test_binding_mutation_and_its_audit_roll_back_together(
    repository: SQLiteRepository, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failure after the audit append leaves neither the binding nor the audit row."""

    import os

    from polyweb.infrastructure.cryptography import MasterKey, SecretCodec
    from polyweb.infrastructure.encrypted_store import EncryptedDbSecretStore
    from polyweb.models.projects import CredentialOwnerScope
    from polyweb.models.vault import KeyPoolCreate
    from polyweb.persistence.bindings import ProjectBindingRepository
    from polyweb.persistence.credentials import CredentialRepository
    from polyweb.persistence.key_pools import KeyPoolRepository
    from polyweb.services import key_pools
    from polyweb.services.credentials import credential_secret_slot
    from polyweb.services.key_pools import KeyPoolService
    from tests.fixtures.auth import create_temp_user, temp_email, temp_principal
    from tests.fixtures.execution import seed_execution_project

    user = await create_temp_user(repository, temp_email("tx-binding"))
    actor = temp_principal(user)
    project_id = (await seed_execution_project(repository, user_id=user.id)).project_id
    store = EncryptedDbSecretStore(repository, SecretCodec(MasterKey(os.urandom(32))))
    async with repository.session() as session:
        credential = await CredentialRepository(session).insert_credential(
            account_id=DEFAULT_INSTALLATION_ACCOUNT_ID,
            provider_type="exa",
            owner_scope=CredentialOwnerScope.SYSTEM,
            owner_project_id=None,
            owner_user_id=user.id,
            label="tx",
            auth_mode="api_key",
            created_by=user.id,
        )
        await store.create_slot_in_session(
            session, credential_secret_slot(credential.id, 1), "fake-tx-secret"
        )
        await session.commit()
    original = key_pools.record_system_event

    async def audit_then_fail(*args: object, **kwargs: object) -> None:
        await original(*args, **kwargs)  # type: ignore[arg-type]
        raise RuntimeError("fail after the audit append")

    monkeypatch.setattr(key_pools, "record_system_event", audit_then_fail)
    service = KeyPoolService(repository)
    with pytest.raises(RuntimeError):
        await service.create(
            actor,
            credential.id,
            KeyPoolCreate(label="tx", project_id=project_id, operations=frozenset({"search"})),
        )
    async with repository.session() as session:
        assert await KeyPoolRepository(session).list_for_key(credential.id) == []
        bindings = await ProjectBindingRepository(session).list_for_project(project_id=project_id)
        assert all(binding.credential_id != credential.id for binding in bindings)
    rows = await audit_rows(repository, scope="system", action="vault.pool_created")
    assert rows == []


@pytest.mark.asyncio
async def test_concurrent_allocations_on_independent_engines_never_overcommit(
    tmp_path: Path,
) -> None:
    """Two engines racing base rates onto one pool: the sum never exceeds the limit."""

    from polyweb.models.credentials import CredentialOperation
    from polyweb.models.providers import AllocationPut, PoolCreate, RateConstraint
    from polyweb.models.schema_enums import UpstreamScope
    from polyweb.services.control_errors import ResourceConflict as Conflict
    from polyweb.services.pools import PoolService
    from tests.fixtures.alpha_fixtures import bootstrap_fresh_alpha
    from tests.fixtures.auth import temp_principal
    from tests.fixtures.execution import seed_execution_project

    boot = await bootstrap_fresh_alpha(tmp_path / "tx-alloc.db")
    second = await SQLiteRepository.open(boot.database_path)
    try:
        admin = temp_principal(boot.admin_user)
        projects = [(await seed_execution_project(boot.repository)).project_id for _ in range(6)]
        pool = await PoolService(boot.repository).create_pool(
            admin,
            PoolCreate(
                provider_type="tavily",
                upstream_scope=UpstreamScope.ACCOUNT,
                pool_key="race",
                label="race",
                constraints=[
                    RateConstraint(algorithm="fixed_window", window_seconds=60, limit=100)
                ],
            ),
        )
        services = [PoolService(boot.repository), PoolService(second)]

        async def put(index: int, project_id: UUID) -> object:
            try:
                return await services[index % 2].put_allocation(
                    admin,
                    project_id,
                    pool.id,
                    CredentialOperation.SEARCH,
                    AllocationPut(base_rate=40, rate_window_seconds=60),
                )
            except Conflict as error:
                return error

        results = await asyncio.gather(*(put(i, pid) for i, pid in enumerate(projects)))
        accepted = [r for r in results if not isinstance(r, Conflict)]
        refused = [r for r in results if isinstance(r, Conflict)]
        assert len(accepted) == 2
        assert {error.code for error in refused} == {"ALLOCATION_INFEASIBLE"}
        total = 0
        for project_id in projects:
            for allocation in await services[0].list_project_allocations(admin, project_id):
                total += allocation.base_rate
        assert total == 80
    finally:
        await second.close()
        await boot.repository.close()
