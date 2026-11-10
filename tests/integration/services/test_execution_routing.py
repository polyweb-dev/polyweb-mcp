"""Preserve the former router's dispatch and tolerant snapshot contracts in A2."""

import asyncio
from pathlib import Path
from typing import Any

import pytest

from polyweb.infrastructure.resilience import ProviderOperationError
from polyweb.models.contracts import FallbackPolicy, RoutingConfigResponse, RoutingPreference
from polyweb.services.provider_runtime import persist_routing_config
from tests.fixtures.a2_execution import (
    PoolSpec,
    build_execution_world,
    fetch_request,
    provider_error,
    search_request,
)


async def test_ranked_candidates_project_reads_do_not_scale_with_bindings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One planning snapshot must not re-read the project for every owned binding."""
    import re

    from sqlalchemy import event

    from polyweb.models.contracts import UsageOperation
    from polyweb.persistence.bindings import ProjectBindingRepository
    from polyweb.services.provider_runtime import routing_policy
    from tests.fixtures.a2_execution import RecordingAdapter
    from tests.fixtures.execution import install_adapter_map
    from tests.fixtures.latency import seed_latency_pools, warm_route_caches

    all_providers = ("exa", "firecrawl", "tavily", "parallel", "you", "brave", "keenable")
    project_reads = [0]
    reads_by_bindings: dict[int, int] = {}

    def count_project_selects(
        conn: Any, cursor: Any, statement: str, params: Any, ctx: Any, many: Any
    ) -> None:
        if statement.lstrip().upper().startswith("SELECT") and re.search(
            r"\bFROM\s+projects\b", statement, re.IGNORECASE
        ):
            project_reads[0] += 1

    for binding_count in (1, 7):
        world = await build_execution_world(tmp_path, monkeypatch, labels=(), limits=False)
        try:
            providers = all_providers[:binding_count]
            adapters = [RecordingAdapter(provider) for provider in providers]
            secrets: dict[str, str] = {}
            await seed_latency_pools(
                world.repository,
                project_id=world.project.project_id,
                actor_id=world.project.actor_id,
                store=world.store,
                providers=providers,
                secrets=secrets,
            )
            install_adapter_map(monkeypatch, adapters, secrets=secrets)
            await warm_route_caches(world.repository, providers)
            policy = await routing_policy(world.repository)
            async with world.repository.session() as session:
                bindings = await ProjectBindingRepository(session).list_for_project(
                    project_id=world.project.project_id
                )
            assert len(bindings) == binding_count
            request = search_request(world)
            engine = world.repository._engine.sync_engine
            project_reads[0] = 0
            event.listen(engine, "before_cursor_execute", count_project_selects)
            try:
                context, _, candidates = await world.service._ranked_candidates(
                    world.context, request, UsageOperation.SEARCH, policy
                )
            finally:
                event.remove(engine, "before_cursor_execute", count_project_selects)
            reads_by_bindings[binding_count] = project_reads[0]
            assert context.account_id == world.context.account_id
            assert context.project_id == world.project.project_id
            assert len(candidates) == binding_count
            assert {candidate.provider for candidate in candidates} == set(providers)
            assert {candidate.binding.id for candidate in candidates} == {
                binding.id for binding in bindings
            }
            assert {candidate.credential_id for candidate in candidates} == {
                binding.credential_id for binding in bindings
            }
        finally:
            await world.aclose()

    assert reads_by_bindings[1] > 0
    assert reads_by_bindings[7] == reads_by_bindings[1], reads_by_bindings


@pytest.mark.parametrize(
    ("fallback_policy", "allow_fallback", "operation"),
    [
        (FallbackPolicy.CHAINED, True, "search"),
        (FallbackPolicy.FIRST_ONLY, True, "search"),
        (FallbackPolicy.CHAINED, False, "search"),
        (FallbackPolicy.CHAINED, True, "fetch"),
        (FallbackPolicy.FIRST_ONLY, True, "fetch"),
        (FallbackPolicy.CHAINED, False, "fetch"),
    ],
)
async def test_dispatch_uses_one_candidate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fallback_policy: FallbackPolicy,
    allow_fallback: bool,
    operation: str,
) -> None:
    world = await build_execution_world(tmp_path, monkeypatch, labels=("a1", "a2"), limits=False)
    try:
        await persist_routing_config(
            world.repository, RoutingConfigResponse(fallback_policy=fallback_policy)
        )
        failure = RuntimeError("unexpected primary failure")

        async def crash(_adapter: Any, _request: Any) -> Any:
            raise failure

        world.adapters["a1"].search_handler = crash
        world.adapters["a1"].fetch_handler = crash
        request = (search_request if operation == "search" else fetch_request)(
            world, routing=RoutingPreference(allow_fallback=allow_fallback)
        )
        with pytest.raises(RuntimeError) as caught:
            await getattr(world.service, operation)(
                request, attribution=world.project, context=world.context
            )
        assert caught.value is failure
        assert getattr(world.adapters["a1"], f"{operation}_calls") == 1
        assert getattr(world.adapters["a2"], f"{operation}_calls") == 0
    finally:
        await world.aclose()


async def test_cancelling_parent_execution_awaits_both_fanout_children(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sqlalchemy import select

    from polyweb.persistence.limit_rows import LimitAdmissionRow, RateAttemptRow

    world = await build_execution_world(
        tmp_path,
        monkeypatch,
        labels=("a1", "a2"),
        limits=False,
        pool=PoolSpec(constraints=[], max_concurrency=2),
    )
    cleaned: list[str] = []
    parent: asyncio.Task[Any] | None = None
    try:
        for label, adapter in world.adapters.items():

            async def hang(_adapter: Any, _request: Any, label: str = label) -> Any:
                try:
                    await asyncio.Event().wait()
                finally:
                    # Async cleanup must finish before the parent returns cancellation.
                    await asyncio.sleep(0)
                    cleaned.append(label)

            adapter.search_handler = hang
        parent = asyncio.create_task(
            world.service.search(
                search_request(world, fanout=True),
                attribution=world.project,
                context=world.context,
            )
        )
        await asyncio.wait_for(
            asyncio.gather(*(adapter.search_started.wait() for adapter in world.adapters.values())),
            timeout=5,
        )
        parent.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(parent, timeout=5)
        assert sorted(cleaned) == ["a1", "a2"]
        assert [adapter.search_calls for adapter in world.adapters.values()] == [1, 1]
        async with world.repository.session() as session:
            admissions = list((await session.scalars(select(LimitAdmissionRow))).all())
            attempts = list((await session.scalars(select(RateAttemptRow))).all())
        assert len(admissions) == 2 and len(attempts) == 2
        for row in [*admissions, *attempts]:
            assert row.project_id == str(world.project.project_id)
            assert row.actor_id == str(world.project.actor_id)
            assert row.actor_type == world.project.actor_type.value
        assert all(row.state != "released" for row in admissions)
    finally:
        if parent is not None and not parent.done():
            parent.cancel()
            await asyncio.gather(parent, return_exceptions=True)
        await world.aclose()


@pytest.mark.parametrize("all_fail", [False, True])
async def test_fetch_chained_fallback_preserves_success_and_terminal_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, all_fail: bool
) -> None:
    world = await build_execution_world(tmp_path, monkeypatch, labels=("a1", "a2"), limits=False)
    try:
        await persist_routing_config(
            world.repository, RoutingConfigResponse(fallback_policy=FallbackPolicy.CHAINED)
        )
        first = provider_error("exa", code="bot_blocked", status=403)
        terminal = provider_error("exa", code="upstream_error", status=502)

        async def denied(_adapter: Any, _request: Any) -> Any:
            raise first

        async def failed(_adapter: Any, _request: Any) -> Any:
            raise terminal

        world.adapters["a1"].fetch_handler = denied
        if all_fail:
            world.adapters["a2"].fetch_handler = failed
            with pytest.raises(ProviderOperationError) as caught:
                await world.service.fetch(
                    fetch_request(world), attribution=world.project, context=world.context
                )
            assert caught.value is terminal
        else:
            response = await world.service.fetch(
                fetch_request(world), attribution=world.project, context=world.context
            )
            assert response.provider == "exa"
            assert response.document.content == "fake document"
        assert [adapter.fetch_calls for adapter in world.adapters.values()] == [1, 1]
    finally:
        await world.aclose()


@pytest.mark.parametrize("batch_mode", ["absent", "failed"])
async def test_batchless_repository_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, batch_mode: str
) -> None:
    world = await build_execution_world(tmp_path, monkeypatch, limits=False)
    try:
        real_health = world.repository.latest_health
        real_quota = world.repository.latest_quota
        calls: list[str] = []

        async def failed_batch(_providers: Any) -> Any:
            calls.append("batch")
            raise RuntimeError("snapshot batch unavailable")

        async def failed_health(*_args: Any, **_kwargs: Any) -> Any:
            calls.append("health")
            raise RuntimeError("health snapshot unavailable")

        async def failed_quota(*_args: Any, **_kwargs: Any) -> Any:
            calls.append("quota")
            raise RuntimeError("quota snapshot unavailable")

        monkeypatch.setattr(
            world.repository,
            "latest_health_batch",
            None if batch_mode == "absent" else failed_batch,
        )
        monkeypatch.setattr(world.repository, "latest_health", failed_health)
        monkeypatch.setattr(world.repository, "latest_quota", failed_quota)
        response = await world.service.search(
            search_request(world), attribution=world.project, context=world.context
        )
        assert response.provider == "exa"
        assert world.adapters["a1"].search_calls == 1
        assert calls == (["batch"] if batch_mode == "failed" else []) + ["health", "quota"]
        # Stash origin also read real per-provider snapshots without a batch API,
        # and returned empty snapshots for an empty roster.
        from datetime import UTC, datetime
        from decimal import Decimal

        from polyweb.models.contracts import QuotaSnapshot, QuotaSource

        monkeypatch.setattr(world.repository, "latest_health_batch", None)
        monkeypatch.setattr(world.repository, "latest_health", real_health)
        monkeypatch.setattr(world.repository, "latest_quota", real_quota)
        snapshot = QuotaSnapshot(
            provider="exa",
            source=QuotaSource.AUTHORITATIVE,
            remaining=Decimal("5"),
            limit=Decimal("100"),
            observed_at=datetime.now(UTC),
        )
        credential_id = world.credentials["a1"].credential_id
        await world.repository.record_quota(snapshot, credential_id=credential_id)
        from polyweb.models.credentials import CredentialOperation

        legs = await world.service._usable_legs(world.context, CredentialOperation.SEARCH)
        try:
            health, quota = await world.service._health_and_quota(legs)
            assert set(health) == set(quota) == {legs[0].binding_id}
            assert health[legs[0].binding_id].provider == "exa"
            assert quota[legs[0].binding_id] == snapshot
            assert await world.service._health_and_quota([]) == ({}, {})
        finally:
            for leg in legs:
                leg.lease.release()
    finally:
        await world.aclose()


@pytest.mark.parametrize("operation", ["search", "fetch"])
async def test_require_filters_before_state_reads(tmp_path, monkeypatch, operation):
    """Origin tests/unit/routers/test_api.py: REQUIRE limits every state read."""
    import polyweb.services.execution as execution
    from polyweb.models.contracts import RoutingMode
    from polyweb.services.execution import ExecutionBindingMissing
    from tests.fixtures.a2_execution import RecordingAdapter
    from tests.fixtures.execution import install_adapter_map, seed_provider_bindings

    world = await build_execution_world(tmp_path, monkeypatch, limits=False)
    extra = [RecordingAdapter("brave"), RecordingAdapter("firecrawl")]
    secrets = {"exa": world.credentials["a1"].secret}
    await seed_provider_bindings(
        world.repository,
        project_id=world.project.project_id,
        actor_id=world.project.actor_id,
        store=world.store,
        providers=("brave", "firecrawl"),
        secrets=secrets,
    )
    install_adapter_map(monkeypatch, [world.adapters["a1"], *extra], secrets=secrets)
    required = ("exa",) if operation == "search" else ("exa", "firecrawl")
    names = []
    reads = []
    real_config = execution.effective_config_for_name
    real_health = world.repository.latest_health
    real_quota = world.repository.latest_quota
    real_batch = world.repository.latest_health_batch

    async def config(repo, name, **kwargs):
        names.append(name)
        return await real_config(repo, name, **kwargs)

    async def health(provider, **kwargs):
        reads.append(("health", provider))
        return await real_health(provider, **kwargs)

    async def quota(provider, **kwargs):
        reads.append(("quota", provider))
        return await real_quota(provider, **kwargs)

    async def batch(providers):
        reads.append(("batch", tuple(providers)))
        return await real_batch(providers)

    monkeypatch.setattr(execution, "effective_config_for_name", config)
    monkeypatch.setattr(world.repository, "latest_health", health)
    monkeypatch.setattr(world.repository, "latest_quota", quota)
    monkeypatch.setattr(world.repository, "latest_health_batch", batch)
    try:
        # A corrupt unrelated configuration must never be inspected by REQUIRE.
        await world.repository.set_runtime_setting("provider.brave", {"config": {"priority": 0}})
        request = (search_request if operation == "search" else fetch_request)(
            world, routing=RoutingPreference(mode=RoutingMode.REQUIRE, providers=required)
        )
        await getattr(world.service, operation)(
            request, attribution=world.project, context=world.context
        )
        assert names and set(names) == set(required)
        assert reads[0] == ("batch", required)
        assert sorted(reads[1:]) == sorted(
            (kind, name) for name in required for kind in ("health", "quota")
        )
        assert extra[0].search_calls == extra[0].fetch_calls == 0
        names.clear()
        reads.clear()
        missing = request.model_copy(
            update={"routing": RoutingPreference(mode=RoutingMode.REQUIRE, providers=("ghost",))}
        )
        with pytest.raises(ExecutionBindingMissing):
            await getattr(world.service, operation)(
                missing, attribution=world.project, context=world.context
            )
        assert names == [] and reads == []
    finally:
        await world.aclose()


@pytest.mark.parametrize("operation", ["search", "fetch"])
async def test_dispatch_chained_fallback_on_provider_error_succeeds_second(
    tmp_path, monkeypatch, operation
):
    """Origin tests/unit/routers/test_api.py: second credential returns success."""
    world = await build_execution_world(tmp_path, monkeypatch, labels=("a1", "a2"), limits=False)

    async def denied(_adapter, _request):
        raise provider_error("exa", code="bot_blocked", status=403)

    try:
        setattr(world.adapters["a1"], f"{operation}_handler", denied)
        response = await getattr(world.service, operation)(
            (search_request if operation == "search" else fetch_request)(world),
            attribution=world.project,
            context=world.context,
        )
        assert response.provider == "exa"
        assert [getattr(a, f"{operation}_calls") for a in world.adapters.values()] == [1, 1]
        assert (
            response.document.content == "fake document"
            if operation == "fetch"
            else response.total_results == 1
        )
    finally:
        await world.aclose()


@pytest.mark.parametrize("operation", ["search", "fetch"])
async def test_dispatch_chained_fallback_on_provider_error_all_fail(
    tmp_path, monkeypatch, operation
):
    """Origin tests/unit/routers/test_api.py: retain the final provider error."""
    world = await build_execution_world(tmp_path, monkeypatch, labels=("a1", "a2"), limits=False)
    errors = [
        provider_error("exa", code="bot_blocked", status=403),
        provider_error("exa", code="upstream_error", status=502),
    ]
    try:
        for adapter, error in zip(world.adapters.values(), errors, strict=True):

            async def denied(_adapter, _request, error=error):
                raise error

            setattr(adapter, f"{operation}_handler", denied)
        with pytest.raises(ProviderOperationError) as caught:
            await getattr(world.service, operation)(
                (search_request if operation == "search" else fetch_request)(world),
                attribution=world.project,
                context=world.context,
            )
        assert caught.value is errors[-1]
        assert [getattr(a, f"{operation}_calls") for a in world.adapters.values()] == [1, 1]
    finally:
        await world.aclose()


@pytest.mark.parametrize("refusal", ["required_provider", "binding", "capacity"])
async def test_denied_requests_never_schedule_vendor_quota_io(tmp_path, monkeypatch, refusal):
    """AC7 includes request-triggered observers, not only search/fetch wire calls."""
    from uuid import uuid4

    from polyweb.models.contracts import ProviderCapabilities, RoutingMode
    from polyweb.models.provider_limits import AuthMode, LimitDeniedError, LimitOperation
    from polyweb.persistence.bindings import ProjectBindingRepository
    from polyweb.persistence.limit_repository import StrictAttemptSpec, StrictWindowSpec
    from polyweb.services.execution import ExecutionBindingMissing
    from tests.fixtures.a2_execution import RecordingAdapter

    pool = PoolSpec(constraints=[{"window": 60, "limit": 1}], base_rate=1)
    world = await build_execution_world(
        tmp_path, monkeypatch, limits=False, pool=pool if refusal == "capacity" else None
    )
    polls = []

    async def quota(_adapter):
        polls.append("vendor quota")
        return None

    monkeypatch.setattr(
        RecordingAdapter,
        "capabilities",
        property(lambda self: ProviderCapabilities(search=True, fetch=True, quota=True)),
    )
    monkeypatch.setattr(RecordingAdapter, "quota", quota)
    try:
        if refusal == "capacity":
            assert world.pool is not None
            credential = world.credentials["a1"]
            attempt_id = f"preconsume-{uuid4().hex}"
            await world.repository.limits.reserve_strict(
                attempt_id=attempt_id,
                provider="exa",
                operation=LimitOperation.SEARCH,
                auth_mode=AuthMode.KEYED,
                spec=StrictAttemptSpec(
                    project_id=world.project.project_id,
                    credential_id=credential.credential_id,
                    binding_id=credential.binding_id,
                    pool_id=world.pool.id,
                    windows=(StrictWindowSpec(f"pool:{world.pool.id}:60", 60, 1),),
                    actor_type=world.project.actor_type,
                    actor_id=world.project.actor_id,
                ),
            )
            await world.repository.limits.settle_strict(attempt_id=attempt_id, outcome="completed")
        request = search_request(world)
        if refusal == "required_provider":
            request = search_request(
                world, routing=RoutingPreference(mode=RoutingMode.REQUIRE, providers=("ghost",))
            )
        if refusal == "binding":
            credential = world.credentials["a1"]
            async with world.repository.session() as session:
                repo = ProjectBindingRepository(session)
                binding = await repo.get(
                    project_id=world.project.project_id, binding_id=credential.binding_id
                )
                await repo.set_enabled_operations(
                    project_id=world.project.project_id,
                    binding_id=binding.id,
                    operations=frozenset(),
                    expected_version=binding.version,
                )
                await session.commit()
        with pytest.raises((ExecutionBindingMissing, LimitDeniedError)):
            await world.service.search(request, attribution=world.project, context=world.context)
        await asyncio.sleep(0)
        assert world.adapters["a1"].search_calls == 0
        assert polls == [] and not world.service._quota_tasks
    finally:
        await world.aclose()


_CHAIN_LABELS = ("a1", "a2", "a3", "a4")


@pytest.mark.parametrize("operation", ["search", "fetch"])
@pytest.mark.parametrize("max_attempts", [1, 2, 3, 4, 5])
async def test_chained_fallback_attempts_at_most_the_hop_limit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, max_attempts: int, operation: str
) -> None:
    """Every failing leg falls through until ``max_attempts`` distinct legs ran."""
    world = await build_execution_world(tmp_path, monkeypatch, labels=_CHAIN_LABELS, limits=False)
    errors = [
        provider_error("exa", code="bot_blocked", status=403, message=f"leg {index}")
        for index in range(len(_CHAIN_LABELS))
    ]
    try:
        await persist_routing_config(
            world.repository,
            RoutingConfigResponse(
                fallback_policy=FallbackPolicy.CHAINED, max_attempts=max_attempts
            ),
        )
        for label, error in zip(_CHAIN_LABELS, errors, strict=True):

            async def denied(_adapter: Any, _request: Any, error: Any = error) -> Any:
                raise error

            setattr(world.adapters[label], f"{operation}_handler", denied)
        with pytest.raises(ProviderOperationError) as caught:
            await getattr(world.service, operation)(
                (search_request if operation == "search" else fetch_request)(world),
                attribution=world.project,
                context=world.context,
            )
        attempted = min(max_attempts, len(_CHAIN_LABELS))
        calls = [getattr(world.adapters[label], f"{operation}_calls") for label in _CHAIN_LABELS]
        assert calls == [1] * attempted + [0] * (len(_CHAIN_LABELS) - attempted)
        assert caught.value is errors[attempted - 1]
    finally:
        await world.aclose()


@pytest.mark.parametrize("max_attempts", [1, 2, 3, 4])
@pytest.mark.parametrize("succeeds_at", [1, 2, 3, 4])
async def test_chained_fallback_returns_the_first_success_inside_the_hop_limit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, max_attempts: int, succeeds_at: int
) -> None:
    """A success at leg N returns when N fits the limit; later legs never run."""
    world = await build_execution_world(tmp_path, monkeypatch, labels=_CHAIN_LABELS, limits=False)
    try:
        await persist_routing_config(
            world.repository, RoutingConfigResponse(max_attempts=max_attempts)
        )
        for label in _CHAIN_LABELS[: succeeds_at - 1]:

            async def denied(_adapter: Any, _request: Any, label: str = label) -> Any:
                raise provider_error("exa", code="bot_blocked", status=403, message=label)

            world.adapters[label].search_handler = denied
        call = world.service.search(
            search_request(world), attribution=world.project, context=world.context
        )
        if succeeds_at <= max_attempts:
            response = await call
            assert response.provider == "exa"
            expected = [1] * succeeds_at + [0] * (len(_CHAIN_LABELS) - succeeds_at)
        else:
            with pytest.raises(ProviderOperationError):
                await call
            expected = [1] * max_attempts + [0] * (len(_CHAIN_LABELS) - max_attempts)
        assert [world.adapters[label].search_calls for label in _CHAIN_LABELS] == expected
    finally:
        await world.aclose()


async def test_leg_chain_prepares_only_the_next_leg_while_one_runs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Daisy chain: the next leg resolves during an attempt, never two ahead."""
    from polyweb.services.execution import ExecutionService

    world = await build_execution_world(tmp_path, monkeypatch, labels=_CHAIN_LABELS, limits=False)
    events: list[str] = []
    labels_by_binding = {item.binding_id: label for label, item in world.credentials.items()}
    real_resolve = ExecutionService._resolve_leg

    async def recording_resolve(self: Any, context: Any, binding: Any, *args: Any, **kwargs: Any):
        leg = await real_resolve(self, context, binding, *args, **kwargs)
        events.append(f"resolved:{labels_by_binding[binding.id]}")
        return leg

    monkeypatch.setattr(ExecutionService, "_resolve_leg", recording_resolve)
    try:
        await persist_routing_config(
            world.repository, RoutingConfigResponse(max_attempts=len(_CHAIN_LABELS))
        )
        for label in _CHAIN_LABELS[:2]:

            async def denied(_adapter: Any, _request: Any, label: str = label) -> Any:
                events.append(f"called:{label}")
                # Hold the attempt until the next leg is ready (bounded).
                index = _CHAIN_LABELS.index(label)
                for _ in range(500):
                    if f"resolved:{_CHAIN_LABELS[index + 1]}" in events:
                        break
                    await asyncio.sleep(0.01)
                raise provider_error("exa", code="bot_blocked", status=403, message=label)

            world.adapters[label].search_handler = denied

        response = await world.service.search(
            search_request(world), attribution=world.project, context=world.context
        )
        assert response.provider == "exa"
        assert [world.adapters[label].search_calls for label in _CHAIN_LABELS] == [1, 1, 1, 0]
        assert events.index("resolved:a2") < events.index("called:a2")
        assert events.index("called:a1") < events.index("resolved:a3")
        assert events.count("resolved:a4") == 1, "the success leg's successor is prepared once"
        for position, event in enumerate(events):
            if event.startswith("called:"):
                attempted = sum(1 for item in events[: position + 1] if item.startswith("called:"))
                resolved = sum(1 for item in events[:position] if item.startswith("resolved:"))
                assert resolved <= attempted + 1, f"more than one leg ahead at {events}"
    finally:
        await world.aclose()
