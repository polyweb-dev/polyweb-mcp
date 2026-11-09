"""Targeted A2 execution regressions for the reviewed production defects.

Each case drives the real execution, monitoring, capacity, and persistence
layers with temporary databases, fake adapters, or a real adapter over an
``httpx.MockTransport``. No vendor request leaves the process.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx
import pytest
from pydantic import SecretStr
from sqlalchemy import select

from polyweb.adapters.brave import BraveAdapter
from polyweb.infrastructure.resilience import ProviderOperationError, ResilientRunner
from polyweb.infrastructure.secrets import ProviderName
from polyweb.models.contracts import (
    RoutingMode,
    RoutingPreference,
    UsageOperation,
)
from polyweb.models.credentials import CredentialOperation
from polyweb.models.observability import AttemptBinding
from polyweb.models.projects import ProjectContext
from polyweb.models.provider_limits import (
    AuthMode,
    LimitCallContext,
    LimitDeniedError,
    LimitOperation,
)
from polyweb.persistence.bindings import ProjectBindingRepository
from polyweb.persistence.limit_repository import StrictAttemptSpec, StrictWindowSpec
from polyweb.persistence.limit_rows import LimitAdmissionRow, RateAttemptRow
from polyweb.persistence.storage import SQLiteRepository, UsageEventRow
from polyweb.services.execution import (
    ExecutionBindingMissing,
    ExecutionError,
    _fanout_outcomes,
)
from polyweb.services.monitoring import tracked_call
from polyweb.services.provider_runtime import (
    clear_config_cache,
    effective_config_for_name,
    persist_provider_config,
)
from tests.fixtures.a2_execution import (
    ExecutionWorld,
    PoolSpec,
    build_execution_world,
    fetch_request,
    provider_error,
    search_request,
)
from tests.fixtures.execution import FIXTURE_ACTOR, seed_execution_project


def _binding(world: ExecutionWorld, label: str = "a1") -> AttemptBinding:
    credential = world.credentials[label]
    return AttemptBinding(
        binding_id=credential.binding_id,
        credential_id=credential.credential_id,
        pool_id=world.pool.id if world.pool is not None else None,
    )


def _strict_spec(
    world: ExecutionWorld,
    *,
    label: str = "a1",
    bucket: str,
    window_seconds: int = 3600,
    limit: int = 10,
) -> StrictAttemptSpec:
    credential = world.credentials[label]
    return StrictAttemptSpec(
        project_id=world.project.project_id,
        credential_id=credential.credential_id,
        binding_id=credential.binding_id,
        windows=(StrictWindowSpec(bucket, window_seconds, limit),),
        actor_type=world.project.actor_type,
        actor_id=world.project.actor_id,
    )


def _hooks(world: ExecutionWorld, spec: StrictAttemptSpec, attempt_id: str) -> tuple[Any, Any, Any]:
    async def reserve() -> Any:
        return await world.repository.limits.reserve_strict(
            attempt_id=attempt_id,
            provider="exa",
            operation=LimitOperation.SEARCH,
            auth_mode=AuthMode.KEYED,
            spec=spec,
        )

    async def settle(outcome: str) -> None:
        await world.repository.limits.settle_strict(attempt_id=attempt_id, outcome=outcome)  # type: ignore[arg-type]

    async def release(reservation: Any) -> None:
        await world.repository.limits.release_strict(
            attempt_id=attempt_id, bucket_ids=tuple(reservation.bucket_ids)
        )

    return reserve, settle, release


async def test_real_transport_retry_charges_every_upstream_send(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    world = await build_execution_world(tmp_path, monkeypatch, provider="brave", limits=False)
    bucket = f"a2:retry:{uuid4().hex}"
    attempt_id = f"retry-{uuid4().hex}"
    spec = _strict_spec(world, bucket=bucket)
    reserve, settle, release = _hooks(world, spec, attempt_id)
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(500, json={"message": "upstream failed"})
        return httpx.Response(
            200,
            json={
                "web": {
                    "results": [
                        {
                            "title": "Example",
                            "url": "https://example.com/article",
                            "description": "A result.",
                        }
                    ]
                }
            },
            headers={"X-RateLimit-Remaining": "99"},
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    adapter = BraveAdapter(
        client,
        api_key=SecretStr("fake-brave-key"),
        runner=ResilientRunner(client, base_delay=0, random_source=lambda: 0.0),
    )
    try:
        request = search_request(world)
        await tracked_call(
            world.repository,
            adapter,
            lambda target: target.search(request),
            operation=UsageOperation.SEARCH,
            attribution=world.project,
            request=request,
            binding=_binding(world),
            reserve=reserve,
            settle=settle,
            release=release,
        )
    finally:
        await adapter.aclose()
        await client.aclose()

    async with world.repository.session() as session:
        rows = list(
            (
                await session.execute(
                    select(RateAttemptRow).where(RateAttemptRow.bucket_id == bucket)
                )
            )
            .scalars()
            .all()
        )
    await world.aclose()

    assert len(requests) == 2, "the retrying transport must have sent exactly two requests"
    assert len(rows) == 2, (
        "two real upstream sends consumed one strict unit; each dispatched send must "
        f"carry its own debit (rows={[row.units_text for row in rows]})"
    )
    assert sum(int(row.units_text) for row in rows) == 2


async def test_cancellation_after_dispatch_keeps_the_attempt_debit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    world = await build_execution_world(tmp_path, monkeypatch, limits=False)
    bucket = f"a2:cancel:{uuid4().hex}"
    attempt_id = f"cancel-{uuid4().hex}"
    spec = _strict_spec(world, bucket=bucket)
    reserve, settle, release = _hooks(world, spec, attempt_id)
    adapter = world.adapters["a1"]

    async def hold(_adapter: Any, _request: Any) -> Any:
        await asyncio.sleep(3600)

    adapter.search_handler = hold
    request = search_request(world)
    task = asyncio.ensure_future(
        tracked_call(
            world.repository,
            adapter,
            lambda target: target.search(request),
            operation=UsageOperation.SEARCH,
            attribution=world.project,
            request=request,
            binding=_binding(world),
            reserve=reserve,
            settle=settle,
            release=release,
        )
    )
    await asyncio.wait_for(adapter.search_started.wait(), timeout=5)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    admission = await world.repository.limits.get_admission(attempt_id)
    async with world.repository.session() as session:
        rows = list(
            (
                await session.execute(
                    select(RateAttemptRow).where(RateAttemptRow.attempt_id == attempt_id)
                )
            )
            .scalars()
            .all()
        )
    await world.aclose()

    assert admission is not None, "the cancelled attempt lost its admission record"
    assert admission.state != "released", (
        "a cancellation after the vendor call was dispatched refunded the attempt; "
        "uncertain consumption must stay debited"
    )
    assert len(rows) == 1 and rows[0].units_text == "1"


async def test_pool_concurrency_one_first_call_does_not_deny_itself(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    world = await build_execution_world(
        tmp_path,
        monkeypatch,
        pool=PoolSpec(
            constraints=[],
            max_concurrency=1,
            operations=(CredentialOperation.SEARCH,),
            allocations=(CredentialOperation.SEARCH,),
            base_rate=100,
            rate_window_seconds=3600,
        ),
    )
    adapter = world.adapters["a1"]
    failure: Exception | None = None
    try:
        await world.service.search(
            search_request(world), attribution=world.project, context=world.context
        )
    except Exception as error:
        failure = error

    assert world.pool is not None
    async with world.repository.session() as session:
        reserved = list(
            (
                await session.execute(
                    select(LimitAdmissionRow).where(
                        LimitAdmissionRow.upstream_pool_id == str(world.pool.id),
                        LimitAdmissionRow.state == "reserved",
                    )
                )
            )
            .scalars()
            .all()
        )
    await world.aclose()

    assert failure is None, (
        "the first call under pool max_concurrency=1 denied itself by counting its "
        f"own rails admission ({type(failure).__name__}: {failure}); "
        f"provider calls={adapter.search_calls}, leaked reserved rows={len(reserved)}"
    )
    assert adapter.search_calls == 1
    assert reserved == [], "a denied first call leaked a reserved native admission row"


@pytest.mark.parametrize(
    "constraint",
    [
        {"kind": "rate", "algorithm": "trailing_window", "window": 60, "limit": 1},
        {"algorithm": "rolling_window", "window_seconds": 60, "limit": 1},
    ],
)
async def test_unscoped_pool_window_is_shared_by_search_and_fetch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, constraint
) -> None:
    world = await build_execution_world(
        tmp_path,
        monkeypatch,
        pool=PoolSpec(
            constraints=[constraint],
            operations=(CredentialOperation.SEARCH, CredentialOperation.FETCH),
            allocations=(CredentialOperation.SEARCH, CredentialOperation.FETCH),
            base_rate=1,
            rate_window_seconds=120,
        ),
    )
    adapter = world.adapters["a1"]
    await world.service.search(
        search_request(world), attribution=world.project, context=world.context
    )
    denied = False
    try:
        await world.service.fetch(
            fetch_request(world), attribution=world.project, context=world.context
        )
    except LimitDeniedError:
        denied = True
    fetch_calls = adapter.fetch_calls
    await world.aclose()

    assert denied, (
        "an unscoped shared-pool declaration of 1/minute gave search and fetch "
        f"separate buckets; fetch was admitted (fetch calls={fetch_calls})"
    )
    assert fetch_calls == 0


@pytest.mark.parametrize(
    "constraints",
    [
        {"kind": "rate", "algorithm": "trailing_window", "window": "1m", "limit": 1},
        [
            {
                "kind": "rate",
                "algorithm": "trailing_window",
                "window": "1m",
                "limit": 1,
                "operations": "search",
            }
        ],
        [{"kind": "rate", "algorithm": "token_bucket", "window": "1m", "limit": 1}],
    ],
)
async def test_malformed_or_unsupported_pool_constraints_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, constraints: Any
) -> None:
    world = await build_execution_world(
        tmp_path,
        monkeypatch,
        limits=False,
        pool=PoolSpec(
            constraints=constraints,
            base_rate=1,
            operations=(CredentialOperation.SEARCH,),
            allocations=(CredentialOperation.SEARCH,),
        ),
    )
    adapter = world.adapters["a1"]
    with pytest.raises(ExecutionError):
        await world.service.search(
            search_request(world), attribution=world.project, context=world.context
        )
    calls = adapter.search_calls
    await world.aclose()

    assert calls == 0


def _context(
    world: ExecutionWorld, label: str, *, attempt_id: str, provider: str
) -> LimitCallContext:
    credential = world.credentials[label]
    return LimitCallContext(
        **FIXTURE_ACTOR,
        provider=provider,
        operation=LimitOperation.SEARCH,
        auth_mode=AuthMode.KEYED,
        attempt_id=attempt_id,
        request=search_request(world),
        requested_at=datetime.now(UTC),
        project_id=world.project.project_id,
        credential_id=credential.credential_id,
        binding_id=credential.binding_id,
    )


async def test_terminal_402_on_one_credential_does_not_disable_its_sibling(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    world = await build_execution_world(
        tmp_path, monkeypatch, labels=("a1", "a2"), priorities={"a1": 1, "a2": 100}
    )
    assert world.limits is not None
    first, second = world.adapters["a1"], world.adapters["a2"]

    async def out_of_credits(_adapter: Any, _request: Any) -> Any:
        raise provider_error(
            "exa",
            code="quota_exhausted",
            message="Exa is out of credits.",
            status=402,
            retryable=False,
        )

    first.search_handler = out_of_credits
    request = search_request(world)
    with pytest.raises(ProviderOperationError):
        await tracked_call(
            world.repository,
            first,
            lambda target: target.search(request),
            operation=UsageOperation.SEARCH,
            attribution=world.project,
            request=request,
            limits=world.limits,
            binding=_binding(world, "a1"),
            context=_context(world, "a1", attempt_id=f"402-{uuid4().hex}", provider="exa"),
        )
    assert first.search_calls == 1

    failure: Exception | None = None
    try:
        await tracked_call(
            world.repository,
            second,
            lambda target: target.search(request),
            operation=UsageOperation.SEARCH,
            attribution=world.project,
            request=request,
            limits=world.limits,
            binding=_binding(world, "a2"),
            context=_context(world, "a2", attempt_id=f"402b-{uuid4().hex}", provider="exa"),
        )
    except Exception as error:
        failure = error
    second_calls = second.search_calls
    await world.aclose()

    assert failure is None, (
        "a terminal 402 on credential a1 disabled sibling credential a2 through a "
        f"provider-wide native pool ({type(failure).__name__}: {failure}); "
        f"a2 provider calls={second_calls}"
    )
    assert second_calls == 1


async def test_vendor_429_cooldown_on_one_credential_does_not_block_its_sibling(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    world = await build_execution_world(
        tmp_path,
        monkeypatch,
        provider="firecrawl",
        labels=("a1", "a2"),
        priorities={"a1": 1, "a2": 100},
    )
    assert world.limits is not None
    first, second = world.adapters["a1"], world.adapters["a2"]

    async def rate_limited(_adapter: Any, _request: Any) -> Any:
        raise provider_error(
            "firecrawl",
            code="rate_limited",
            message="rate limit exceeded",
            status=429,
            retryable=True,
            details={"retry_after_seconds": 30},
        )

    first.search_handler = rate_limited
    request = search_request(world)
    with pytest.raises(ProviderOperationError):
        await tracked_call(
            world.repository,
            first,
            lambda target: target.search(request),
            operation=UsageOperation.SEARCH,
            attribution=world.project,
            request=request,
            limits=world.limits,
            binding=_binding(world, "a1"),
            context=_context(world, "a1", attempt_id=f"429-{uuid4().hex}", provider="firecrawl"),
        )

    failure: Exception | None = None
    try:
        await tracked_call(
            world.repository,
            second,
            lambda target: target.search(request),
            operation=UsageOperation.SEARCH,
            attribution=world.project,
            request=request,
            limits=world.limits,
            binding=_binding(world, "a2"),
            context=_context(world, "a2", attempt_id=f"429b-{uuid4().hex}", provider="firecrawl"),
        )
    except Exception as error:
        failure = error
    second_calls = second.search_calls
    await world.aclose()

    assert failure is None, (
        "a vendor 429 on credential a1 contaminated the provider-wide cooldown and "
        f"blocked sibling a2 ({type(failure).__name__}: {failure}); "
        f"a2 provider calls={second_calls}"
    )
    assert second_calls == 1


async def test_same_provider_fanout_uses_both_bindings_and_verified_actor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    world = await build_execution_world(tmp_path, monkeypatch, labels=("a1", "a2"), limits=False)
    other = await seed_execution_project(world.repository, user_id=world.project.actor_id, name="B")
    request = search_request(
        world,
        project_id=other.project_id,
        fanout=True,
        routing=RoutingPreference(mode=RoutingMode.FANOUT),
    )
    response = await world.service.search(request, attribution=world.project, context=world.context)

    async with world.repository.session() as session:
        rows = list(
            (
                await session.execute(
                    select(UsageEventRow).where(
                        UsageEventRow.provider == "exa",
                        UsageEventRow.project_id == str(world.project.project_id),
                    )
                )
            )
            .scalars()
            .all()
        )
    calls = {label: adapter.search_calls for label, adapter in world.adapters.items()}
    await world.aclose()

    assert calls == {"a1": 1, "a2": 1}
    assert response.provider == "aggregated"
    assert len(rows) == 2
    assert {row.binding_id for row in rows} == {
        str(world.credentials["a1"].binding_id),
        str(world.credentials["a2"].binding_id),
    }
    assert {row.project_id for row in rows} == {str(world.project.project_id)}
    assert {row.actor_id for row in rows} == {str(world.project.actor_id)}


async def test_same_provider_require_calls_exactly_one_binding(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    world = await build_execution_world(tmp_path, monkeypatch, labels=("a1", "a2"), limits=False)
    request = search_request(
        world,
        routing=RoutingPreference(
            mode=RoutingMode.REQUIRE, providers=("exa",), allow_fallback=False
        ),
    )
    await world.service.search(request, attribution=world.project, context=world.context)
    calls = {label: adapter.search_calls for label, adapter in world.adapters.items()}
    await world.aclose()

    assert calls == {"a1": 1, "a2": 0}


async def test_chained_fallback_advances_to_the_second_binding(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    world = await build_execution_world(tmp_path, monkeypatch, labels=("a1", "a2"), limits=False)

    async def denied(_adapter: Any, _request: Any) -> Any:
        raise provider_error(
            "exa", code="bot_blocked", message="access denied", status=403, retryable=False
        )

    world.adapters["a1"].search_handler = denied
    response = await world.service.search(
        search_request(world), attribution=world.project, context=world.context
    )
    calls = {label: adapter.search_calls for label, adapter in world.adapters.items()}
    await world.aclose()

    assert calls == {"a1": 1, "a2": 1}
    assert response.provider == "exa"


async def test_chained_fallback_rethrows_the_terminal_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    world = await build_execution_world(tmp_path, monkeypatch, labels=("a1", "a2"), limits=False)

    async def denied(_adapter: Any, _request: Any) -> Any:
        raise provider_error(
            "exa", code="bot_blocked", message="access denied", status=403, retryable=False
        )

    world.adapters["a1"].search_handler = denied
    world.adapters["a2"].search_handler = denied
    with pytest.raises(ProviderOperationError) as failure:
        await world.service.search(
            search_request(world), attribution=world.project, context=world.context
        )
    calls = {label: adapter.search_calls for label, adapter in world.adapters.items()}
    await world.aclose()

    assert calls == {"a1": 1, "a2": 1}
    assert failure.value.error.provider == "exa"


async def test_required_provider_without_binding_makes_zero_calls(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    world = await build_execution_world(tmp_path, monkeypatch, limits=False)
    request = search_request(
        world,
        routing=RoutingPreference(
            mode=RoutingMode.REQUIRE, providers=("ghost",), allow_fallback=False
        ),
    )
    with pytest.raises(ExecutionBindingMissing):
        await world.service.search(request, attribution=world.project, context=world.context)
    calls = sum(adapter.search_calls for adapter in world.adapters.values())
    await world.aclose()

    assert calls == 0


async def test_missing_or_denied_bindings_make_zero_provider_calls(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    world = await build_execution_world(tmp_path, monkeypatch, limits=False)
    adapter = world.adapters["a1"]
    credential = world.credentials["a1"]
    async with world.repository.session() as session:
        binding = await ProjectBindingRepository(session).get(
            project_id=world.project.project_id, binding_id=credential.binding_id
        )
        assert binding is not None
        await ProjectBindingRepository(session).set_enabled_operations(
            project_id=world.project.project_id,
            binding_id=credential.binding_id,
            operations=frozenset(),
            expected_version=binding.version,
        )
        await session.commit()

    with pytest.raises(ExecutionBindingMissing):
        await world.service.search(
            search_request(world), attribution=world.project, context=world.context
        )
    denied_calls = adapter.search_calls

    other = await seed_execution_project(
        world.repository, user_id=world.project.actor_id, name="NoBindings"
    )
    other_context = ProjectContext(
        account_id=world.context.account_id,
        project_id=other.project_id,
        principal=world.context.principal,
        effective_permissions=world.context.effective_permissions,
        policy_revision=1,
    )
    with pytest.raises(ExecutionBindingMissing):
        await world.service.search(
            search_request(world, project_id=other.project_id),
            attribution=world.project,
            context=other_context,
        )
    all_calls = adapter.search_calls
    await world.aclose()

    assert denied_calls == 0
    assert all_calls == 0


async def test_disabled_provider_config_propagates_to_a_second_repository_handle(
    tmp_path: Path,
) -> None:
    database = tmp_path / "cross-handle.db"
    clear_config_cache()
    first = await SQLiteRepository.open(database)
    second = await SQLiteRepository.open(database)
    try:
        before = await effective_config_for_name(second, "exa")
        assert before.allows(UsageOperation.SEARCH)
        await persist_provider_config(
            first,
            ProviderName.EXA,
            before.model_copy(update={"enable_mask": 0}),
        )
        after = await effective_config_for_name(second, "exa")
    finally:
        await first.close()
        await second.close()
        clear_config_cache()

    assert not after.allows(UsageOperation.SEARCH), (
        "the second handle still enabled a provider the first handle disabled"
    )


async def test_parent_fanout_cancellation_cancels_and_awaits_child() -> None:
    cleanup: list[str] = []

    async def slow_child() -> tuple[str, None, int, str, int, str | None]:
        try:
            await asyncio.sleep(3600)
        finally:
            cleanup.append("slow")

    async def terminal_child() -> tuple[str, None, int, str, int, str | None]:
        await asyncio.sleep(0)
        raise provider_error("tavily", message="Tavily is out of Credits.", status=402)

    tasks = [asyncio.ensure_future(slow_child()), asyncio.ensure_future(terminal_child())]
    with pytest.raises(ProviderOperationError):
        await _fanout_outcomes(tasks)

    assert tasks[0].cancelled()
    assert cleanup == ["slow"], "the cancelled fanout child was not awaited to completion"
