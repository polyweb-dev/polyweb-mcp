"""A3 AC1 topology: one fenced execution authority for REST and MCP (TASK-000045).

Every case drives the real :class:`ExecutionService` over a temporary SQLite
database with recording fake adapters, composed with the authority the A3 seam
contract expects (``ExecutionService(..., authority=...)``). The durable lease,
fencing tokens, and dispatch rows in ``execution_authority`` are the shared
persistence evidence: REST submits directly and MCP forwards with the original
verified credential, deadline, and trace context.

Cases:

* one authority identity in the durable dispatch ledger for both transports,
  with the verified actor of each transport on every row it produced;
* a second authority instance for a borrowed pool is fenced out before any
  provider dispatch (no direct provider bypass through the execution service);
* an authority outage behind the fence fails closed: typed retriable refusal,
  zero provider calls, zero usage rows, zero new dispatch rows.

Fake providers and temporary databases only; assertions read adapter call
counters and durable rows, never stubbed safety paths.
"""

from __future__ import annotations

import asyncio
from contextlib import suppress
from pathlib import Path
from typing import Any

import pytest

from freesearch.models.credentials import CredentialOperation
from freesearch.models.execution_failures import ExecutionBindingMissing
from freesearch.models.projects import DEFAULT_INSTALLATION_ACCOUNT_ID
from freesearch.models.provider_limits import LimitStoreUnavailable
from freesearch.models.schema_enums import PoolStatus, UpstreamScope
from freesearch.persistence.pools import UpstreamPoolRepository
from freesearch.services.execution import ExecutionService
from freesearch.services.execution_authority import (
    ExecutionAuthority,
    ExecutionAuthorityUnavailable,
)
from tests.fixtures.a3_authority import (
    AUTHORITY_KEY,
    AllocationSpec,
    AuthorityPoolSpec,
    build_authority_world,
)


def weighted_pair(
    *,
    borrow_max: int | None = None,
    a_extra: dict[str, Any] | None = None,
    b_extra: dict[str, Any] | None = None,
) -> tuple[AllocationSpec, AllocationSpec]:
    """The documented 4:6 weighted allocation pair with optional overrides."""

    base_row: dict[str, Any] = dict(borrow_max=borrow_max)
    base_row.update(a_extra or {})
    pair_row: dict[str, Any] = dict(borrow_max=borrow_max)
    pair_row.update(b_extra or {})
    return (
        AllocationSpec(label="A", base_rate=4, weight=4, **base_row),
        AllocationSpec(label="B", base_rate=6, weight=6, **pair_row),
    )


def _refusal_kind(error: BaseException) -> str:
    """Return the exception type name of one refusal for assertion messages."""
    return type(error).__name__


# ---------------------------------------------------------------------------
# AC1 first clause: one authority dispatches all REST and MCP work; the MCP
# forward carries the original verified project API key, deadline and trace
# context (credential evidence: durable rows; deadline/queue-wait and trace
# evidence: the bounded-queue and transport suites).
# ---------------------------------------------------------------------------


async def test_one_authority_hosts_rest_and_mcp_dispatches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    spec = AuthorityPoolSpec(limit=1000, allocations=weighted_pair())
    world = await build_authority_world(tmp_path, monkeypatch, spec=spec)
    world.park(False)
    key: Any = None
    try:
        straight = await world.service.search(
            world.request("A", tag="rest"),
            attribution=world.projects["A"].attribution,
            context=world.projects["A"].context,
        )
        key, key_ctx = await world.key_context("B")
        forwarded = await world.service.search(
            world.request("B", tag="mcp"),
            attribution=key.attribution,
            context=key_ctx,
        )
        dispatches = await world.dispatch_rows()
        usage_a = await world.usage_rows(project_id=world.projects["A"].project_id)
        usage_b = await world.usage_rows(project_id=world.projects["B"].project_id)
    finally:
        await world.aclose()

    assert straight.provider == "exa", "direct REST submission must execute"
    assert forwarded.provider == "exa", "the forwarded MCP work must execute"
    assert len(dispatches) == 2, dispatches
    assert {row.authority_key for row in dispatches} == {AUTHORITY_KEY}, (
        "one authority ledger identity must mark every transport's dispatch"
    )
    by_project = {row.project_id: row for row in dispatches}
    assert set(by_project) == {
        str(world.projects["A"].project_id),
        str(world.projects["B"].project_id),
    }
    # The forwarded work carries the MCP-verified project API key, not the
    # key's owner and not a server-side substitute identity.
    forwarded_row = by_project[str(world.projects["B"].project_id)]
    assert (forwarded_row.actor_type, forwarded_row.actor_id) == (
        "project_api_key",
        str(key.api_key_id),
    )
    assert forwarded_row.pool_id == str(world.pool.id)
    assert forwarded_row.credential_id == str(world.projects["B"].credential.credential_id)
    assert forwarded_row.binding_id == str(world.projects["B"].credential.binding_id)
    direct_row = by_project[str(world.projects["A"].project_id)]
    assert (direct_row.actor_type, direct_row.actor_id) == (
        "human",
        str(world.projects["A"].attribution.actor_id),
    )
    # Usage attribution repeats the verified actor of each transport.
    assert {(row.actor_type, row.actor_id) for row in usage_a} == {
        ("human", str(world.projects["A"].attribution.actor_id))
    }
    assert {(row.actor_type, row.actor_id) for row in usage_b} == {
        ("project_api_key", str(key.api_key_id))
    }
    assert {row.pool_id for row in usage_a + usage_b} == {str(world.pool.id)}, (
        "usage rows must attribute the shared pool"
    )


# ---------------------------------------------------------------------------
# AC1 last clause: a second authority for a borrowed pool fails before any
# execution (no second fence, no direct provider bypass).
# ---------------------------------------------------------------------------


async def test_second_authority_for_a_borrowed_pool_fails_before_execution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    spec = AuthorityPoolSpec(limit=1000, allocations=weighted_pair())
    world = await build_authority_world(tmp_path, monkeypatch, spec=spec)
    world.park(False)
    second: Any = None
    try:
        held = await world.service.search(
            world.request("A", tag="hold"),
            attribution=world.projects["A"].attribution,
            context=world.projects["A"].context,
        )
        assert held.provider == "exa"

        # A second independent instance reaching for the same fence must be a
        # distinct holder: a stable process-wide holder id would defeat it.
        rival = ExecutionAuthority(
            repository=world.repository,
            secret_store=world.store,
            authority_key=world.authority_key,
            monotonic_fn=world.monotonic.monotonic_fn,
        )
        second = ExecutionService(
            repository=world.repository,
            secret_store=world.store,
            client=object(),
            authority=rival,
        )
        refusal: BaseException | None = None
        try:
            await second.search(
                world.request("B", tag="hijack"),
                attribution=world.projects["B"].attribution,
                context=world.projects["B"].context,
            )
        except BaseException as error:
            refusal = error
        calls_b = world.projects["B"].adapter.search_calls
        calls_a = world.projects["A"].adapter.search_calls
        rows = await world.dispatch_rows()
        usage = await world.usage_rows()
    finally:
        if second is not None:
            with suppress(Exception):
                await second.aclose()
        await world.aclose()

    assert refusal is not None, "the second authority executed a borrowed-pool dispatch"

    assert isinstance(refusal, ExecutionAuthorityUnavailable), (
        f"expected the typed authority refusal, got {type(refusal).__name__}: {refusal} "
        f"(cause {type(refusal.__cause__).__name__ if refusal.__cause__ else None})"
    )
    assert calls_b == 0, (
        f"a second authority for a borrowed pool dispatched ({calls_b} provider calls)"
    )
    assert calls_a == 1
    assert len(rows) == 1 and rows[0].project_id == str(world.projects["A"].project_id)
    assert {row.project_id for row in usage} == {str(world.projects["A"].project_id)}, (
        "the fenced-out second authority left usage rows behind"
    )


# ---------------------------------------------------------------------------
# AC1 authority outage + 7.6 fail closed: the capacity store behind the fence
# is down, so the execution refuses predictably instead of bypassing.
# ---------------------------------------------------------------------------


async def test_authority_outage_fails_closed_without_provider_calls(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    spec = AuthorityPoolSpec(limit=1000, allocations=weighted_pair())
    world = await build_authority_world(tmp_path, monkeypatch, spec=spec)
    world.park(False)
    try:
        before = await world.service.search(
            world.request("A", tag="baseline"),
            attribution=world.projects["A"].attribution,
            context=world.projects["A"].context,
        )
        assert before.provider == "exa"

        async def store_down(*_args: Any, **_kwargs: Any) -> Any:
            raise LimitStoreUnavailable("capacity store unavailable")

        # The real capacity-store seam every execution goes through is the
        # attempt reservation of the limit repository (both the native rails
        # and the strict pool/project windows land in ``reserve_attempt``),
        # because a fixture with live limits never routes through the old
        # strict-only ``reserve_strict`` shim.
        monkeypatch.setattr(world.repository.limits, "reserve_attempt", store_down)
        try:
            refusal: BaseException | None = None
            broke: Any = None
            try:
                broke = await world.service.search(
                    world.request("A", tag="during-outage"),
                    attribution=world.projects["A"].attribution,
                    context=world.projects["A"].context,
                )
            except BaseException as error:
                refusal = error
            calls = world.projects["A"].adapter.search_calls
            rows = await world.dispatch_rows()
            usage = await world.usage_rows()
        finally:
            monkeypatch.undo()
    finally:
        await world.aclose()

    assert broke is None, "an outaged authority must not dispatch"
    assert refusal is not None and isinstance(refusal, ExecutionAuthorityUnavailable), (
        f"expected typed ExecutionAuthorityUnavailable, got {type(refusal).__name__}: {refusal}"
    )
    assert calls == 1, "the outage path made a provider bypass"
    assert len(rows) == 1, "the outage path wrote a dispatch row without the fence"
    assert {row.project_id for row in usage} == {str(world.projects["A"].project_id)}, (
        "the outage path wrote usage rows"
    )
    # The outage consumed nothing: no rate attempt beyond the baseline send.
    attempts = await world.pool_attempts()
    assert len(attempts) == 1, f"the outage path charged a rate attempt: {attempts}"


# ---------------------------------------------------------------------------
# P6: the final dispatch check must revalidate the complete dispatch-relevant
# snapshot. A queued call whose pool or binding changed while it waited must
# fail closed instead of dispatching a stale plan.
# ---------------------------------------------------------------------------


def _p6_spec() -> AuthorityPoolSpec:
    """The bounded pair other queued cases use, with a caller-tight pool."""

    return AuthorityPoolSpec(
        limit=1000,
        allocations=(
            AllocationSpec(label="A", base_rate=4, borrow_max=10, weight=4, max_concurrency=1),
            AllocationSpec(label="B", base_rate=6, borrow_max=10, weight=6, max_concurrency=1),
        ),
    )


async def test_pool_disabled_while_queued_never_dispatches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    spec = _p6_spec()
    world = await build_authority_world(tmp_path, monkeypatch, spec=spec)
    second: list[asyncio.Task[Any]] = []
    try:
        first = world.submit("A", "first")
        await world.wait_starts(1)
        second = world.submit("A", "second")
        await world.wait_queued("A", 1)

        # The pool goes disabled while the second call waits for its grant.
        async with world.repository.session() as session:
            pools = UpstreamPoolRepository(session)
            paused = await pools.update_pool(
                account_id=DEFAULT_INSTALLATION_ACCOUNT_ID,
                pool_id=world.pool.id,
                upstream_scope=UpstreamScope.ACCOUNT,
                pool_key=world.pool.pool_key,
                label=world.pool.label,
                constraints=spec.constraints,
                max_concurrency=world.pool.max_concurrency,
                max_queued_requests=world.pool.max_queued_requests,
                status=PoolStatus.DISABLED,
            )
            assert paused is not None
            await session.commit()

        world.release()
        drain_deadline = asyncio.get_running_loop().time() + 15.0
        while not all(task.done() for task in first + second):
            world.release()
            if asyncio.get_running_loop().time() > drain_deadline:
                pytest.fail("the queued call never settled after the pool went disabled")
            await asyncio.sleep(0.002)
        outcomes, failures = await world.gather(first + second)
        calls = world.projects["A"].adapter.search_calls
        rows = await world.dispatch_rows(project_id=world.projects["A"].project_id)
        usage = await world.usage_rows(project_id=world.projects["A"].project_id)
        attempts = await world.project_attempts("A")
    finally:
        await world.aclose()

        # The queued call must fail closed on the stale snapshot, without a send,
        # without a durable dispatch of its own, and without a rate debit.
        assert len(failures) == 1, (
            f"the disabled-pool queued call resolved {[type(o).__name__ for o in outcomes]}"
        )
        assert calls == 1, f"the disabled-pool dispatch reached the provider ({calls} calls)"
        assert len(rows) == 1, "the disabled-pool dispatch wrote its own dispatch row"
        assert len(usage) == 1, "the disabled-pool dispatch produced usage"
        assert len(attempts) == 1, f"the disabled-pool dispatch charged an attempt: {attempts}"


async def test_binding_disabled_while_queued_never_dispatches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    spec = _p6_spec()
    world = await build_authority_world(tmp_path, monkeypatch, spec=spec)
    try:
        first = world.submit("A", "first")
        await world.wait_starts(1)
        second = world.submit("A", "second")
        await world.wait_queued("A", 1)

        # The binding loses its search operation while the call is queued.
        from freesearch.persistence.bindings import ProjectBindingRepository

        async with world.repository.session() as session:
            binding = ProjectBindingRepository(session)
            rows = await binding.list_for_project(project_id=world.projects["A"].project_id)
            assert rows, "the fixture binding exists"
            binding_row = rows[0]
            disabled = await binding.set_enabled_operations(
                project_id=world.projects["A"].project_id,
                binding_id=binding_row.id,
                operations=frozenset({CredentialOperation.FETCH}),
                expected_version=binding_row.version,
            )
            assert disabled is not None
            await session.commit()

        world.release()
        drain_deadline = asyncio.get_running_loop().time() + 15.0
        while not all(task.done() for task in first + second):
            world.release()
            if asyncio.get_running_loop().time() > drain_deadline:
                pytest.fail("the queued call never settled after the binding changed")
            await asyncio.sleep(0.002)
        outcomes, failures = await world.gather(first + second)
        calls = world.projects["A"].adapter.search_calls
        rows = await world.dispatch_rows(project_id=world.projects["A"].project_id)
        usage = await world.usage_rows(project_id=world.projects["A"].project_id)
        attempts = await world.project_attempts("A")
    finally:
        await world.aclose()

    assert len(failures) == 1, (
        f"the changed-binding queued call resolved {[type(o).__name__ for o in outcomes]}"
    )
    assert all(isinstance(error, ExecutionBindingMissing) for error in failures), [
        type(error).__name__ for error in failures
    ]
    assert calls == 1, f"the stale-binding dispatch reached the provider ({calls} calls)"
    assert len(rows) == 1, "the changed-binding dispatch wrote its own dispatch row"
    assert len(usage) == 1, "the changed-binding dispatch produced usage"
    assert len(attempts) == 1, f"the stale-binding dispatch charged an attempt: {attempts}"
