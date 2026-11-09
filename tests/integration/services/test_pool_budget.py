"""Pool budget admission against independent real SQLite sessions."""

import asyncio
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from freesearch.models.contracts import (
    FallbackPolicy,
    RoutingConfigResponse,
    SearchResponse,
    UnitKind,
    UsageEvent,
    UsageOperation,
)
from freesearch.models.projects import DEFAULT_INSTALLATION_ACCOUNT_ID, CredentialOwnerScope
from freesearch.models.provider_limits import AuthMode, LimitStoreUnavailable
from freesearch.persistence.credentials import CredentialRepository
from freesearch.persistence.key_pools import KeyPoolRepository, KeyPoolValues
from freesearch.persistence.settings import ProjectSettingsRepository
from freesearch.services.credentials import credential_secret_slot
from freesearch.services.execution import _AttemptSeam
from freesearch.services.pool_budget import pool_budget_used_micros, release, reserve, settle_actual
from freesearch.services.pool_materializer import materialize_pools
from freesearch.services.provider_runtime import initialize_provider_configs, persist_routing_config
from tests.fixtures.a2_execution import RecordingAdapter, build_execution_world, search_request


@pytest_asyncio.fixture
async def budget_store(tmp_path: Path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{(tmp_path / 'budget.db').as_posix()}")
    async with engine.begin() as connection:
        await connection.execute(
            text(
                "CREATE TABLE key_pools (id TEXT PRIMARY KEY, budget_limit INTEGER, "
                "budget_window_seconds INTEGER)"
            )
        )
        await connection.execute(
            text(
                "CREATE TABLE pool_budget_usage (pool_id TEXT, window_start TEXT, "
                "spent_micros INTEGER NOT NULL, updated_at TEXT NOT NULL, "
                "PRIMARY KEY (pool_id, window_start))"
            )
        )
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


@pytest.mark.asyncio
async def test_reserve_deny_release_and_rollover(budget_store) -> None:
    pool_id = uuid4()
    jan = datetime(2024, 1, 31, 23, tzinfo=UTC)
    feb = datetime(2024, 2, 1, tzinfo=UTC)
    async with budget_store() as session:
        await session.execute(
            text("INSERT INTO key_pools VALUES (:id, 100, 2592000)"), {"id": str(pool_id)}
        )
        await session.commit()
    async with budget_store() as session:
        assert await reserve(session, pool_id, 60, now=jan)
        assert await reserve(session, pool_id, 40, now=jan)
        assert not await reserve(session, pool_id, 1, now=jan)
        assert await pool_budget_used_micros(session, pool_id, now=jan) == 100
        await release(session, pool_id, 40, window_start="2024-01-01")
        assert await pool_budget_used_micros(session, pool_id, now=jan) == 60
        assert await reserve(session, pool_id, 100, now=feb)
        assert await pool_budget_used_micros(session, pool_id, now=feb) == 100
        await session.commit()


@pytest.mark.asyncio
async def test_unlimited_pool_does_not_write(budget_store) -> None:
    pool_id = uuid4()
    async with budget_store() as session:
        await session.execute(
            text("INSERT INTO key_pools VALUES (:id, NULL, 2592000)"), {"id": str(pool_id)}
        )
        await session.commit()
        assert await reserve(session, pool_id, 999)
        assert (await session.execute(text("SELECT COUNT(*) FROM pool_budget_usage"))).scalar() == 0


@pytest.mark.asyncio
async def test_uncapped_admission_checks_live_cap_once(budget_store) -> None:
    pool_id = uuid4()
    statements = []
    async with budget_store() as session:
        await session.execute(
            text("INSERT INTO key_pools VALUES (:id, NULL, 2592000)"), {"id": str(pool_id)}
        )
        await session.commit()
        connection = await session.connection()

        def record(_conn, _cursor, statement, _parameters, _context, _many):
            statements.append(statement)

        event.listen(connection.sync_connection, "before_cursor_execute", record)
        try:
            assert await reserve(session, pool_id, 999)
        finally:
            event.remove(connection.sync_connection, "before_cursor_execute", record)
        assert len(statements) == 1
        assert statements[0].lstrip().upper().startswith("SELECT")


@pytest.mark.asyncio
async def test_settlement_adjusts_original_window_even_above_cap(budget_store) -> None:
    pool_id = uuid4()
    jan = datetime(2024, 1, 31, tzinfo=UTC)
    async with budget_store() as session:
        await session.execute(
            text("INSERT INTO key_pools VALUES (:id, 100, 2592000)"), {"id": str(pool_id)}
        )
        assert await reserve(session, pool_id, 60, now=jan)
        await settle_actual(session, pool_id, 60, 120, window_start="2024-01-01")
        assert await pool_budget_used_micros(session, pool_id, now=jan) == 120
        assert not await reserve(session, pool_id, 1, now=jan)


@pytest.mark.asyncio
async def test_concurrent_reservations_never_exceed_cap(budget_store) -> None:
    pool_id = uuid4()
    async with budget_store() as session:
        await session.execute(
            text("INSERT INTO key_pools VALUES (:id, 100, 86400)"), {"id": str(pool_id)}
        )
        await session.commit()

    async def attempt() -> bool:
        async with budget_store() as session:
            accepted = await reserve(session, pool_id, 10)
            await session.commit()
            return accepted

    assert sum(await asyncio.gather(*(attempt() for _ in range(25)))) == 10
    async with budget_store() as session:
        assert await pool_budget_used_micros(session, pool_id) == 100


async def _routing_world(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    cap: int,
    *,
    primary: str = "exa",
    auth_mode: AuthMode = AuthMode.KEYED,
):
    world = await build_execution_world(tmp_path, monkeypatch, labels=(), limits=False)
    pools = {}
    async with world.repository.session() as session:
        for provider, limit in ((primary, cap), ("brave", None)):
            credential = await CredentialRepository(session).insert_credential(
                account_id=DEFAULT_INSTALLATION_ACCOUNT_ID,
                provider_type=provider,
                owner_scope=CredentialOwnerScope.SYSTEM,
                owner_project_id=None,
                owner_user_id=world.project.actor_id,
                label=provider,
                auth_mode="api_key",
                created_by=world.project.actor_id,
            )
            secret = f"budget-{provider}"
            await world.store.create_slot_in_session(
                session, credential_secret_slot(credential.id, 1), secret
            )
            pool = await KeyPoolRepository(session).create(
                credential_id=credential.id,
                project_id=world.project.project_id,
                provider_type=provider,
                created_by=world.project.actor_id,
                values=KeyPoolValues(
                    label=provider, operations=frozenset({"search"}), budget_limit=limit
                ),
            )
            pools[provider] = pool.id
            world.adapters_by_secret[secret] = RecordingAdapter(
                provider, auth_mode=auth_mode if provider == primary else AuthMode.KEYED
            )
        await materialize_pools(session, project_id=world.project.project_id)
        await session.commit()
    monkeypatch.setattr(
        "freesearch.services.execution.adapter_factory",
        lambda name: (
            (lambda _client, api_key=None: world.adapters_by_secret[api_key.get_secret_value()])
            if name in pools
            else None
        ),
    )
    await initialize_provider_configs(world.repository)
    await persist_routing_config(
        world.repository, RoutingConfigResponse(fallback_policy=FallbackPolicy.CHAINED)
    )
    async with world.repository.session() as session:
        settings = ProjectSettingsRepository(session)
        revision = await settings.revision(
            project_id=world.project.project_id, namespace="provider_order"
        )
        assert await settings.compare_and_set(
            project_id=world.project.project_id,
            namespace="provider_order",
            schema_version=1,
            overrides={"search": {"strategy": "custom", "custom_order": [primary, "brave"]}},
            expected_revision=revision,
        )
        await session.commit()
    return world, pools


@pytest.mark.asyncio
async def test_exhausted_pool_falls_through_project_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    world, pools = await _routing_world(tmp_path, monkeypatch, 0)
    try:
        response = await world.service.search(
            search_request(world), attribution=world.project, context=world.context
        )
        assert response.provider == "brave"
        assert world.adapters_by_secret["budget-exa"].search_calls == 0
        assert world.adapters_by_secret["budget-brave"].search_calls == 1
        async with world.repository.session() as session:
            assert await pool_budget_used_micros(session, pools["exa"]) == 0
    finally:
        await world.aclose()


@pytest.mark.asyncio
async def test_advanced_request_uses_its_price_before_send(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    world, pools = await _routing_world(tmp_path, monkeypatch, 10_000)
    try:
        response = await world.service.search(
            search_request(world, limit=100), attribution=world.project, context=world.context
        )
        assert response.provider == "brave"
        assert world.adapters_by_secret["budget-exa"].search_calls == 0
        async with world.repository.session() as session:
            assert await pool_budget_used_micros(session, pools["exa"]) == 0
    finally:
        await world.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mode,cap,expected",
    [
        (AuthMode.KEYED, 8_000, "brave"),
        (AuthMode.KEYLESS, 0, "tavily"),
    ],
)
async def test_tavily_advanced_keyed_and_keyless_budget(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: AuthMode, cap: int, expected: str
) -> None:
    world, pools = await _routing_world(
        tmp_path, monkeypatch, cap, primary="tavily", auth_mode=mode
    )
    try:
        response = await world.service.search(
            search_request(world, mode="advanced"), attribution=world.project, context=world.context
        )
        assert response.provider == expected
        assert world.adapters_by_secret["budget-tavily"].search_calls == (expected == "tavily")
        async with world.repository.session() as session:
            assert await pool_budget_used_micros(session, pools["tavily"]) == 0
    finally:
        await world.aclose()


@pytest.mark.asyncio
async def test_successful_send_charges_catalog_price(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    world, pools = await _routing_world(tmp_path, monkeypatch, 7000)
    try:
        first = await world.service.search(
            search_request(world), attribution=world.project, context=world.context
        )
        assert first.provider == "exa"
        async with world.repository.session() as session:
            assert await pool_budget_used_micros(session, pools["exa"]) == 7000
        second = await world.service.search(
            search_request(world), attribution=world.project, context=world.context
        )
        assert second.provider == "brave"
        assert world.adapters_by_secret["budget-exa"].search_calls == 1
    finally:
        await world.aclose()


@pytest.mark.asyncio
async def test_successful_send_settles_reported_cost(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    world, pools = await _routing_world(tmp_path, monkeypatch, 50_000)

    async def charged(_adapter, request):
        return SearchResponse(
            query=request.query,
            provider="exa",
            results=[],
            usage=UsageEvent(
                provider="exa",
                operation=UsageOperation.SEARCH,
                units=Decimal("0.023"),
                unit_kind=UnitKind.USD,
                observed_at=datetime.now(UTC),
            ),
        )

    world.adapters_by_secret["budget-exa"].search_handler = charged
    try:
        await world.service.search(
            search_request(world), attribution=world.project, context=world.context
        )
        async with world.repository.session() as session:
            assert await pool_budget_used_micros(session, pools["exa"]) == 23_000
    finally:
        await world.aclose()


@pytest.mark.asyncio
async def test_unknown_cost_is_admitted_without_writing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    world, pools = await _routing_world(tmp_path, monkeypatch, 0)
    monkeypatch.setattr("freesearch.services.execution.request_price", lambda *_: None)
    try:
        response = await world.service.search(
            search_request(world), attribution=world.project, context=world.context
        )
        assert response.provider == "exa"
        async with world.repository.session() as session:
            assert (
                await session.execute(
                    text("SELECT COUNT(*) FROM pool_budget_usage WHERE pool_id=:pool"),
                    {"pool": str(pools["exa"])},
                )
            ).scalar() == 0
    finally:
        await world.aclose()


@pytest.mark.asyncio
async def test_unsent_dispatch_refunds_budget(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    world, pools = await _routing_world(tmp_path, monkeypatch, 10000)

    async def fail_record(*_args, **_kwargs):
        raise RuntimeError("dispatch record failed")

    monkeypatch.setattr("freesearch.services.execution._AttemptSeam._record_dispatch", fail_record)
    try:
        with pytest.raises(LimitStoreUnavailable, match="limit store is unavailable"):
            await world.service.search(
                search_request(world), attribution=world.project, context=world.context
            )
        assert world.adapters_by_secret["budget-exa"].search_calls == 0
        async with world.repository.session() as session:
            assert await pool_budget_used_micros(session, pools["exa"]) == 0
    finally:
        await world.aclose()


@pytest.mark.asyncio
async def test_cancellation_during_budget_commit_refunds_unsent_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    world, pools = await _routing_world(tmp_path, monkeypatch, 10000)
    committed, resume = asyncio.Event(), asyncio.Event()
    original = _AttemptSeam._commit_budget

    async def delayed_commit(self, pool_id, cost):
        result = await original(self, pool_id, cost)
        committed.set()
        await resume.wait()
        return result

    monkeypatch.setattr(_AttemptSeam, "_commit_budget", delayed_commit)
    call = asyncio.create_task(
        world.service.search(
            search_request(world), attribution=world.project, context=world.context
        )
    )
    try:
        await asyncio.wait_for(committed.wait(), 10)
        call.cancel()
        resume.set()
        with pytest.raises(asyncio.CancelledError):
            await call
        assert world.adapters_by_secret["budget-exa"].search_calls == 0
        async with world.repository.session() as session:
            assert await pool_budget_used_micros(session, pools["exa"]) == 0
    finally:
        resume.set()
        if not call.done():
            call.cancel()
            await asyncio.gather(call, return_exceptions=True)
        await world.aclose()
