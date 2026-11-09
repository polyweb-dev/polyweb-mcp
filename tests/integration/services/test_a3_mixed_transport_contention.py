"""A3 AC6 tail: mixed REST and MCP contention over one authoritative pool.

Continuous demand arrives from both transports in the same window: a REST
human session and an MCP project-API-key session compete for one shared pool
through the single execution authority. Isolation and pool limits must hold:
every durable row (dispatch, attempt, usage) keeps the verified transport
actor, one authority ledger identity covers both transports, and the pool's
rate envelope is never exceeded. Separate queue timing per transport is
exercised through the injected queue clock.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from freesearch.models.execution_failures import (
    ExecutionAuthorityUnavailable,
    ExecutionQueueExpired,
    ExecutionQueueSaturated,
)
from tests.fixtures.a3_authority import (
    AUTHORITY_KEY,
    AllocationSpec,
    AuthorityPoolSpec,
    build_authority_world,
    stored_dispatch_rows,
    usage_event_rows,
)


def contention_pool() -> AuthorityPoolSpec:
    """A tight envelope: exactly the ten dispatches the pair can borrow."""
    return AuthorityPoolSpec(
        limit=10,
        window_seconds=3600,
        max_concurrency=None,
        allocations=(
            AllocationSpec(
                label="A",
                base_rate=4,
                weight=4,
                borrow_max=10,
                max_concurrency=1,
                max_queue_wait_ms=15_000,
            ),
            AllocationSpec(
                label="B",
                base_rate=6,
                weight=6,
                borrow_max=10,
                max_concurrency=1,
                max_queue_wait_ms=15_000,
            ),
        ),
    )


async def test_mixed_transports_hold_isolation_and_pool_limits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    world = await build_authority_world(tmp_path, monkeypatch, spec=contention_pool())
    key: Any = None
    try:
        # The MCP side forwards with the project API key of project A; the
        # REST side executes through project B's human session directly.
        key, key_ctx = await world.key_context("A")
        mcp_tasks = [
            asyncio.create_task(
                world.service.search(
                    world.request("A", tag=f"mcp{index}"),
                    attribution=key.attribution,
                    context=key_ctx,
                )
            )
            for index in range(5)
        ]
        rest_tasks = world.submit("B", *(f"rest{index}" for index in range(5)))
        tasks = list(mcp_tasks) + list(rest_tasks)
        loop = asyncio.get_running_loop()
        deadline = loop.time() + 30.0
        while not all(task.done() for task in tasks):
            world.release()
            if loop.time() > deadline:
                pytest.fail(
                    f"mixed contention never resolved ({sum(1 for t in tasks if t.done())}/"
                    f"{len(tasks)}; starts={len(world.starts)})"
                )
            await asyncio.sleep(0.002)
            world.release()
        successes, failures = await world.gather(tasks)
        dispatches = await stored_dispatch_rows(world)
        usage_a = await usage_event_rows(world, project_id=world.projects["A"].project_id)
        usage_b = await usage_event_rows(world, project_id=world.projects["B"].project_id)
        pool_attempts = await world.pool_attempts()
        projections = [(row.project_id, row.actor_type, row.actor_id) for row in usage_a] + [
            (row.project_id, row.actor_type, row.actor_id) for row in usage_b
        ]
    finally:
        await world.aclose()

    unusual = [
        failure
        for failure in failures
        if not isinstance(failure, (ExecutionQueueExpired, ExecutionAuthorityUnavailable))
    ]
    assert not unusual, [f"{type(f).__name__}: {f}" for f in unusual]
    assert len(successes) + len(unusual) <= 10
    # One authority ledger identity covers both transports.
    assert {row.authority_key for row in dispatches} == {AUTHORITY_KEY}
    assert {row.pool_id for row in dispatches} == {str(world.pool.id)}
    # The pool envelope holds even under mixed contention.
    assert len(pool_attempts) <= 10, (
        f"mixed transports exceeded the pool envelope ({len(pool_attempts)} attempts)"
    )
    # Isolation: every usage row keeps the verified actor of its transport.
    expected_a = {
        (
            str(world.projects["A"].project_id),
            "project_api_key",
            str(key.attribution.actor_id),
        )
    }
    expected_b = {
        (
            str(world.projects["B"].project_id),
            "human",
            str(world.projects["B"].attribution.actor_id),
        )
    }
    assert set(projections) <= expected_a | expected_b, set(projections)
    assert all(row.actor_type == "project_api_key" for row in usage_a)
    assert all(row.actor_type == "human" for row in usage_b)


async def test_mixed_transports_share_one_queue_budget(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The pool's total queue budget applies across REST and MCP together."""
    spec = contention_pool()
    spec = AuthorityPoolSpec(
        limit=100,
        window_seconds=3600,
        max_queued_requests=1,
        allocations=(
            AllocationSpec(
                label="A",
                base_rate=4,
                weight=4,
                borrow_max=10,
                max_concurrency=1,
            ),
            AllocationSpec(
                label="B",
                base_rate=6,
                weight=6,
                borrow_max=10,
                max_concurrency=1,
            ),
        ),
    )
    world = await build_authority_world(tmp_path, monkeypatch, spec=spec)
    key: object = None
    try:
        key, key_ctx = await world.key_context("A")
        mcp_tasks = [
            asyncio.create_task(
                world.service.search(
                    world.request("A", tag=f"mcp{index}"),
                    attribution=key.attribution,
                    context=key_ctx,
                )
            )
            for index in range(2)
        ]
        rest_tasks = world.submit("B", "rest0", "rest1", "rest2")
        tasks = list(mcp_tasks) + list(rest_tasks)
        loop = asyncio.get_running_loop()
        deadline = loop.time() + 20.0
        while not all(task.done() for task in tasks):
            world.release()
            if loop.time() > deadline:
                pytest.fail("the shared queue budget never resolved")
            await asyncio.sleep(0.002)
        successes, failures = await world.gather(tasks)
    finally:
        await world.aclose()

    assert failures, "the shared total queue bound must saturate at least one request"
    assert all(isinstance(item, ExecutionQueueSaturated) for item in failures), [
        type(item).__name__ for item in failures
    ]
    assert len(successes) + len(failures) == len(tasks)
