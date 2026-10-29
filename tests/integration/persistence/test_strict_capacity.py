"""Strict pool/project capacity behavior over the real SQLite store.

The acceptance example is project A ``4/s``, project B ``6/s`` under one shared
pool of ``10/s``: A must stop at four attempts while B is idle, and concurrent
child processes must never over-admit. These tests use short windows only where
the check is synchronous; the cross-process case uses one-hour windows so
process startup time cannot make the result flaky.
"""

from __future__ import annotations

import asyncio
import multiprocessing
from collections.abc import AsyncIterator
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.exc import OperationalError

from freesearch.models.credentials import CredentialOperation
from freesearch.models.observability import ActorType, ExecutionAttribution
from freesearch.models.projects import (
    DEFAULT_INSTALLATION_ACCOUNT_ID,
    CredentialOwnerScope,
)
from freesearch.models.provider_limits import (
    AuthMode,
    LimitAdmission,
    LimitDeniedError,
    LimitOperation,
    LimitStoreUnavailable,
    RateReservation,
    RateWindowName,
)
from freesearch.models.schema_enums import UpstreamScope
from freesearch.persistence.bindings import ProjectBindingRepository
from freesearch.persistence.credentials import CredentialRepository
from freesearch.persistence.limit_repository import (
    LimitRepository,
    StrictAttemptSpec,
    StrictWindowSpec,
)
from freesearch.persistence.limit_rows import LimitAdmissionRow, RateAttemptRow
from freesearch.persistence.pools import (
    PoolAllocationRepository,
    UpstreamPoolRepository,
)
from freesearch.persistence.storage import SQLiteRepository
from tests.fixtures.execution import FIXTURE_ACTOR, seed_execution_project
from tests.integration.persistence import _strict_capacity_worker as worker_module

_SEARCH = CredentialOperation.SEARCH
_KEYED = AuthMode.KEYED
_POOL_LIMIT = 10
_A_LIMIT = 4
_B_LIMIT = 6
_LONG_WINDOW = 3600


@dataclass(frozen=True)
class CapacityWorld:
    repo: SQLiteRepository
    a: ExecutionAttribution
    b: ExecutionAttribution
    credentials: dict[str, UUID]
    bindings: dict[str, UUID]
    pool_id: UUID
    project_a_bucket: str
    project_b_bucket: str
    pool_bucket: str

    def spec(
        self, key: str, *, windows: tuple[StrictWindowSpec, ...] | None = None
    ) -> StrictAttemptSpec:
        project = self.a if key.startswith("a") else self.b
        if windows is None:
            project_limit = _A_LIMIT if key.startswith("a") else _B_LIMIT
            project_bucket = self.project_a_bucket if key.startswith("a") else self.project_b_bucket
            windows = (
                StrictWindowSpec(project_bucket, _LONG_WINDOW, project_limit),
                StrictWindowSpec(self.pool_bucket, _LONG_WINDOW, _POOL_LIMIT),
            )
        return StrictAttemptSpec(
            project_id=project.project_id,
            credential_id=self.credentials[key],
            binding_id=self.bindings[key],
            pool_id=self.pool_id,
            windows=windows,
            actor_type=ActorType.HUMAN,
            actor_id=project.actor_id,
        )


async def seed_capacity_world(repo: SQLiteRepository) -> CapacityWorld:
    """Seed project A, project B, three credentials, one pool, two allocations."""

    a = await seed_execution_project(repo, name="A")
    b = await seed_execution_project(repo, user_id=a.actor_id, name="B")
    credentials: dict[str, UUID] = {}
    bindings: dict[str, UUID] = {}
    async with repo.session() as session:
        credentials_repo = CredentialRepository(session)
        bindings_repo = ProjectBindingRepository(session)
        for key, project, label in (
            ("a1", a, "fake-a1"),
            ("a2", a, "fake-a2"),
            ("b1", b, "fake-b1"),
        ):
            credential = await credentials_repo.insert_credential(
                account_id=DEFAULT_INSTALLATION_ACCOUNT_ID,
                provider_type="exa",
                owner_scope=CredentialOwnerScope.PROJECT,
                owner_project_id=project.project_id,
                label=label,
                auth_mode="api_key",
                created_by=project.actor_id,
            )
            binding = await bindings_repo.create(
                project_id=project.project_id,
                credential_id=credential.id,
                credential_scope=CredentialOwnerScope.PROJECT,
                route_label=label,
                created_by=project.actor_id,
            )
            enabled = await bindings_repo.set_enabled_operations(
                project_id=project.project_id,
                binding_id=binding.id,
                operations=frozenset({_SEARCH}),
                expected_version=binding.version,
            )
            assert enabled is not None
            credentials[key] = credential.id
            bindings[key] = binding.id

        pool = await UpstreamPoolRepository(session).create_pool(
            account_id=DEFAULT_INSTALLATION_ACCOUNT_ID,
            provider_type="exa",
            upstream_scope=UpstreamScope.ACCOUNT,
            pool_key=f"capacity-{uuid4().hex[:10]}",
            label="capacity pool",
            constraints=[
                {
                    "kind": "rate",
                    "algorithm": "trailing_window",
                    "window": _LONG_WINDOW,
                    "limit": _POOL_LIMIT,
                }
            ],
        )
        pools = UpstreamPoolRepository(session)
        for credential_id in credentials.values():
            await pools.link_credential(
                credential_id=credential_id,
                operation=_SEARCH,
                pool_id=pool.id,
                provider_type="exa",
            )
        allocations = PoolAllocationRepository(session)
        await allocations.create(
            project_id=a.project_id,
            pool_id=pool.id,
            operation=_SEARCH,
            base_rate=_A_LIMIT,
            rate_window_seconds=_LONG_WINDOW,
            granted_by=a.actor_id,
        )
        await allocations.create(
            project_id=b.project_id,
            pool_id=pool.id,
            operation=_SEARCH,
            base_rate=_B_LIMIT,
            rate_window_seconds=_LONG_WINDOW,
            granted_by=b.actor_id,
        )
        await session.commit()

    return CapacityWorld(
        repo=repo,
        a=a,
        b=b,
        credentials=credentials,
        bindings=bindings,
        pool_id=pool.id,
        project_a_bucket=f"project:{a.project_id}:{pool.id}:search",
        project_b_bucket=f"project:{b.project_id}:{pool.id}:search",
        pool_bucket=f"pool:{pool.id}:search:{_LONG_WINDOW}",
    )


@pytest_asyncio.fixture
async def world(tmp_path: Path) -> AsyncIterator[CapacityWorld]:
    repo = await SQLiteRepository.open(tmp_path / "capacity.db")
    try:
        yield await seed_capacity_world(repo)
    finally:
        await repo.close()


async def _reserve(
    repo: SQLiteRepository,
    *,
    attempt_id: str,
    spec: StrictAttemptSpec,
    created_at: datetime | None = None,
) -> object:
    return await repo.limits.reserve_strict(
        attempt_id=attempt_id,
        provider="exa",
        operation=LimitOperation.SEARCH,
        auth_mode=_KEYED,
        spec=spec,
        created_at=created_at,
    )


async def _attempt_units(repo: SQLiteRepository, bucket: str) -> Decimal:
    rows = await _attempt_rows(repo, bucket)
    return sum((Decimal(row.units_text) for row in rows), Decimal("0"))


async def _attempt_rows(repo: SQLiteRepository, bucket: str) -> list[RateAttemptRow]:
    async with repo.session() as session:
        return list(
            (
                await session.execute(
                    select(RateAttemptRow).where(RateAttemptRow.bucket_id == bucket)
                )
            )
            .scalars()
            .all()
        )


async def test_limit_one_per_second_denies_the_second_attempt(world: CapacityWorld) -> None:
    bucket = "a2:limit-one"
    spec = world.spec("a1", windows=(StrictWindowSpec(bucket, 1, 1),))
    await _reserve(world.repo, attempt_id="one-first", spec=spec)

    with pytest.raises(LimitDeniedError) as denial:
        await _reserve(world.repo, attempt_id="one-second", spec=spec)

    assert bucket in denial.value.reasons
    assert len(await _attempt_rows(world.repo, bucket)) == 1


async def test_reverse_timestamp_order_never_admits_both(world: CapacityWorld) -> None:
    bucket = "a2:reverse-clock"
    spec = world.spec("a1", windows=(StrictWindowSpec(bucket, 1, 1),))
    later = datetime.now(UTC) + timedelta(milliseconds=250)

    await _reserve(world.repo, attempt_id="reverse-late", spec=spec, created_at=later)
    with pytest.raises(LimitDeniedError) as denial:
        await _reserve(world.repo, attempt_id="reverse-early", spec=spec)

    assert bucket in denial.value.reasons
    assert len(await _attempt_rows(world.repo, bucket)) == 1


async def test_same_attempt_id_debits_once_and_changed_spec_is_refused(
    world: CapacityWorld,
) -> None:
    bucket = "a2:idempotent"
    spec = world.spec("a1", windows=(StrictWindowSpec(bucket, 10, 10),))
    first = await _reserve(world.repo, attempt_id="same-id", spec=spec)
    replay = await _reserve(world.repo, attempt_id="same-id", spec=spec)

    assert replay.idempotent is True
    assert len(await _attempt_rows(world.repo, bucket)) == 1
    assert await _attempt_units(world.repo, bucket) == Decimal("1")
    assert first.state == "reserved"

    changed = replace(spec, windows=(StrictWindowSpec("a2:idempotent-other", 10, 10),))
    with pytest.raises(LimitDeniedError) as denial:
        await _reserve(world.repo, attempt_id="same-id", spec=changed)
    assert "attempt_spec_conflict" in denial.value.reasons
    assert len(await _attempt_rows(world.repo, bucket)) == 1


async def test_settle_then_release_keeps_the_debit(world: CapacityWorld) -> None:
    bucket = "a2:settled-release"
    spec = world.spec("a1", windows=(StrictWindowSpec(bucket, 10, 10),))
    await _reserve(world.repo, attempt_id="settled", spec=spec)

    assert await world.repo.limits.settle_strict(attempt_id="settled", outcome="completed") is True
    assert (
        await world.repo.limits.release_strict(attempt_id="settled", bucket_ids=[bucket]) is False
    )

    admission = await world.repo.limits.get_admission("settled")
    assert admission is not None
    assert admission.state != "released"
    assert len(await _attempt_rows(world.repo, bucket)) == 1
    assert await _attempt_units(world.repo, bucket) == Decimal("1")

    limited = world.spec("a1", windows=(StrictWindowSpec(bucket, 10, 1),))
    with pytest.raises(LimitDeniedError) as denial:
        await _reserve(world.repo, attempt_id="after-settle", spec=limited)
    assert bucket in denial.value.reasons


async def test_released_attempt_replay_is_refused(world: CapacityWorld) -> None:
    bucket = "a2:released-replay"
    spec = world.spec("a1", windows=(StrictWindowSpec(bucket, 10, 10),))
    await _reserve(world.repo, attempt_id="released", spec=spec)
    assert (
        await world.repo.limits.release_strict(attempt_id="released", bucket_ids=[bucket]) is True
    )

    with pytest.raises(LimitDeniedError) as denial:
        await _reserve(world.repo, attempt_id="released", spec=spec)
    assert "attempt_already_settled" in denial.value.reasons
    assert await _attempt_rows(world.repo, bucket) == []


def _native_admission(attempt_id: str) -> LimitAdmission:
    created = datetime.now(UTC)
    return LimitAdmission(
        **FIXTURE_ACTOR,
        attempt_id=attempt_id,
        provider="exa",
        operation=LimitOperation.SEARCH,
        auth_mode=_KEYED,
        pool_id=None,
        reserved_crd=Decimal("0"),
        reserved_native=None,
        state="reserved",
        created_at=created,
        expires_at=created + timedelta(seconds=60),
        rate_reservations=[
            RateReservation(
                bucket_id="exa:keyed:1m",
                window=RateWindowName.MINUTE,
                units=Decimal("1"),
            )
        ],
    )


async def test_strict_and_native_reservations_share_one_attempt_namespace(
    world: CapacityWorld,
) -> None:
    spec = world.spec("a1", windows=(StrictWindowSpec("a2:collision", 10, 10),))
    await _reserve(world.repo, attempt_id="strict-first", spec=spec)
    with pytest.raises(LimitDeniedError) as strict_denial:
        await world.repo.limits.reserve(_native_admission("strict-first"))
    assert "attempt_identity_conflict" in strict_denial.value.reasons

    await world.repo.limits.reserve(_native_admission("native-first"))
    with pytest.raises(LimitDeniedError) as native_denial:
        await _reserve(world.repo, attempt_id="native-first", spec=spec)
    assert "attempt_identity_conflict" in native_denial.value.reasons


async def test_two_credentials_of_one_project_share_one_allowance(
    world: CapacityWorld,
) -> None:
    spec_a1 = world.spec("a1")
    spec_a2 = world.spec("a2")

    admitted = 0
    for index in range(2):
        await _reserve(world.repo, attempt_id=f"share-a1-{index}", spec=spec_a1)
        admitted += 1
        await _reserve(world.repo, attempt_id=f"share-a2-{index}", spec=spec_a2)
        admitted += 1

    with pytest.raises(LimitDeniedError) as denial:
        await _reserve(world.repo, attempt_id="share-a2-over", spec=spec_a2)

    assert admitted == _A_LIMIT
    assert world.project_a_bucket in denial.value.reasons
    assert await _attempt_units(world.repo, world.project_a_bucket) == Decimal(str(_A_LIMIT))


async def test_durable_capacity_rows_carry_the_verified_actor(world: CapacityWorld) -> None:
    spec = world.spec("a1", windows=(StrictWindowSpec("a2:actor", 10, 10),))
    await _reserve(world.repo, attempt_id="actor-attempt", spec=spec)

    async with world.repo.session() as session:
        admission = await session.get(LimitAdmissionRow, "actor-attempt")
        attempts = list(
            (
                await session.execute(
                    select(RateAttemptRow).where(RateAttemptRow.attempt_id == "actor-attempt")
                )
            )
            .scalars()
            .all()
        )
    assert admission is not None
    assert attempts

    admission_columns = set(LimitAdmissionRow.__table__.columns.keys())
    attempt_columns = set(RateAttemptRow.__table__.columns.keys())
    missing_admission = {"actor_type", "actor_id"} - admission_columns
    missing_attempts = {"actor_type", "actor_id"} - attempt_columns
    assert not missing_admission, (
        "strict admission rows do not persist the verified actor; "
        f"columns are {sorted(admission_columns)}"
    )
    assert not missing_attempts, (
        "strict rate-attempt rows do not persist the verified actor; "
        f"columns are {sorted(attempt_columns)}"
    )
    assert admission.actor_type == ActorType.HUMAN.value
    assert admission.actor_id == str(world.a.actor_id)
    assert attempts[0].actor_type == ActorType.HUMAN.value
    assert attempts[0].actor_id == str(world.a.actor_id)


def _flaky_factory(real_factory: Any, seam: str) -> Any:
    class FlakySession:
        def __init__(self, session: Any) -> None:
            self._session = session

        async def __aenter__(self) -> FlakySession:
            await self._session.__aenter__()
            return self

        async def __aexit__(self, *exc: object) -> object:
            return await self._session.__aexit__(*exc)

        async def execute(self, statement: object, *args: object, **kwargs: object) -> object:
            if seam == "begin" and str(statement) == "BEGIN IMMEDIATE":
                raise OperationalError("BEGIN IMMEDIATE", {}, Exception("store unavailable"))
            return await self._session.execute(statement, *args, **kwargs)

        async def commit(self) -> None:
            if seam == "commit":
                raise OperationalError("COMMIT", {}, Exception("store unavailable"))
            await self._session.commit()

        def __getattr__(self, name: str) -> object:
            return getattr(self._session, name)

    def factory(*args: object, **kwargs: object) -> FlakySession:
        return FlakySession(real_factory(*args, **kwargs))

    return factory


@pytest.mark.parametrize("seam", ["begin", "commit"])
async def test_store_failure_fails_closed_without_partial_rows(
    world: CapacityWorld, seam: str
) -> None:
    failing = LimitRepository(_flaky_factory(world.repo._session_factory, seam))
    spec = world.spec("a1", windows=(StrictWindowSpec("a2:store-failure", 10, 10),))
    attempt_id = f"store-failure-{seam}"

    with pytest.raises(LimitStoreUnavailable):
        await failing.reserve_strict(
            attempt_id=attempt_id,
            provider="exa",
            operation=LimitOperation.SEARCH,
            auth_mode=_KEYED,
            spec=spec,
        )

    assert await world.repo.limits.get_admission(attempt_id) is None
    assert await _attempt_rows(world.repo, "a2:store-failure") == []


def test_a4_b6_pool10_child_processes_never_over_admit(tmp_path: Path) -> None:
    db_path = tmp_path / "capacity-process.db"
    identity: dict[str, str] = {}

    async def seed() -> None:
        repo = await SQLiteRepository.open(db_path)
        try:
            world = await seed_capacity_world(repo)
            identity.update(
                {
                    "project_a": str(world.a.project_id),
                    "project_b": str(world.b.project_id),
                    "credential_a": str(world.credentials["a1"]),
                    "binding_a": str(world.bindings["a1"]),
                    "credential_b": str(world.credentials["b1"]),
                    "binding_b": str(world.bindings["b1"]),
                    "project_a_bucket": world.project_a_bucket,
                    "project_b_bucket": world.project_b_bucket,
                    "pool_bucket": world.pool_bucket,
                }
            )
        finally:
            await repo.close()

    asyncio.run(seed())

    context = multiprocessing.get_context("spawn")
    barrier = context.Barrier(4)
    results_queue = context.Queue()
    tasks = [
        (
            str(db_path),
            identity["project_a"],
            identity["credential_a"],
            identity["binding_a"],
            identity["project_a_bucket"],
            identity["pool_bucket"],
            _A_LIMIT,
            "A",
            barrier,
        ),
        (
            str(db_path),
            identity["project_a"],
            identity["credential_a"],
            identity["binding_a"],
            identity["project_a_bucket"],
            identity["pool_bucket"],
            _A_LIMIT,
            "A",
            barrier,
        ),
        (
            str(db_path),
            identity["project_b"],
            identity["credential_b"],
            identity["binding_b"],
            identity["project_b_bucket"],
            identity["pool_bucket"],
            _B_LIMIT,
            "B",
            barrier,
        ),
        (
            str(db_path),
            identity["project_b"],
            identity["credential_b"],
            identity["binding_b"],
            identity["project_b_bucket"],
            identity["pool_bucket"],
            _B_LIMIT,
            "B",
            barrier,
        ),
    ]
    processes = [
        context.Process(target=worker_module.run_worker, args=(*task, results_queue))
        for task in tasks
    ]
    for process in processes:
        process.start()
    for process in processes:
        process.join(timeout=120)
    assert all(not process.is_alive() for process in processes), (
        "a spawned capacity worker did not exit within 120 seconds"
    )
    assert all(process.exitcode == 0 for process in processes), (
        f"a spawned capacity worker crashed: {[process.exitcode for process in processes]}"
    )
    results = [results_queue.get(timeout=30) for _ in processes]
    results_queue.close()

    admitted_a = sum(result["admitted"] for result in results if result["project"] == "A")
    admitted_b = sum(result["admitted"] for result in results if result["project"] == "B")
    denied = sum(result["denied"] for result in results)
    errors = [error for result in results for error in result["errors"]]

    assert errors == []
    assert admitted_a == _A_LIMIT
    assert admitted_b == _B_LIMIT
    assert admitted_a + admitted_b == _POOL_LIMIT
    assert denied == 6

    async def counts() -> tuple[Decimal, Decimal, Decimal]:
        repo = await SQLiteRepository.open(db_path)
        try:
            return (
                await _attempt_units(repo, identity["pool_bucket"]),
                await _attempt_units(repo, identity["project_a_bucket"]),
                await _attempt_units(repo, identity["project_b_bucket"]),
            )
        finally:
            await repo.close()

    pool_units, a_units, b_units = asyncio.run(counts())
    assert pool_units == Decimal(str(_POOL_LIMIT))
    assert a_units == Decimal(str(_A_LIMIT))
    assert b_units == Decimal(str(_B_LIMIT))
