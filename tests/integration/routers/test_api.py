"""Routing latency integration tests: background quota, stale-first, read budget.

Uses real SQLite and offline adapters. Async REST cases use
``httpx.ASGITransport`` so event barriers share one loop.
"""

from __future__ import annotations

import asyncio
from contextlib import suppress
from contextvars import ContextVar
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import event as sa_event

from polyweb.adapters.base import ProviderAdapter
from polyweb.configuration.config import get_settings
from polyweb.infrastructure.encrypted_store import EncryptedDbSecretStore, load_secret_codec
from polyweb.models.contracts import (
    CostEstimate,
    FetchedDocument,
    FetchRequest,
    FetchResponse,
    HealthStatus,
    ProviderCapabilities,
    ProviderHealth,
    QuotaSnapshot,
    QuotaSource,
    SearchRequest,
    SearchResponse,
    SearchResult,
    UsageOperation,
)
from polyweb.models.credentials import CredentialOperation
from polyweb.persistence.storage import SQLiteRepository
from polyweb.routers.api import create_app
from polyweb.services.execution import ExecutionService
from polyweb.services.monitoring import clear_quota_poll_cache
from polyweb.services.provider_runtime import (
    _BACKGROUND_TASKS,
    clear_config_cache,
    effective_config_for_name,
    routing_policy,
)
from tests.fixtures.auth import TEMP_PASSWORD, temp_email
from tests.fixtures.execution import (
    install_adapter_map,
    seed_member_project,
    seed_provider_bindings,
)

FIXED_AT = datetime(2026, 3, 10, 12, 0, 0, tzinfo=UTC)

SEVEN_PROVIDERS = ["exa", "firecrawl", "tavily", "parallel", "you", "brave", "keenable"]


def _execution_store(repository: SQLiteRepository) -> EncryptedDbSecretStore:
    """Return the same encrypted runtime store the app composition builds."""

    return EncryptedDbSecretStore(repository, load_secret_codec(get_settings()))


class _QuotaAdapter(ProviderAdapter):
    """Offline search adapter with controllable quota polling."""

    def __init__(
        self,
        name: str,
        *,
        quota_snapshot: QuotaSnapshot | None = None,
        entered: asyncio.Event | None = None,
        release: asyncio.Event | None = None,
    ) -> None:
        self._name = name
        self._quota_snapshot = quota_snapshot
        self._entered = entered
        self._release = release
        self.search_calls = 0
        self.quota_calls = 0

    @property
    def name(self) -> str:
        return self._name

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(search=True, fetch=True, cost_estimate=True, quota=True)

    async def search(self, request: SearchRequest) -> SearchResponse:
        self.search_calls += 1
        return SearchResponse(
            query=request.query,
            provider=self._name,
            results=[
                SearchResult(
                    title=f"{self._name} hit",
                    url="https://example.com/r",
                    snippet="offline",
                )
            ],
            total_results=1,
        )

    async def fetch(self, request: FetchRequest) -> FetchResponse:
        return FetchResponse(
            provider=self._name,
            document=FetchedDocument(
                url=request.url,
                content=f"{self._name} content",
                fetched_at=datetime.now(UTC),
            ),
        )

    async def estimate_cost(self, request: SearchRequest | FetchRequest) -> CostEstimate:
        operation = (
            UsageOperation.SEARCH if isinstance(request, SearchRequest) else UsageOperation.FETCH
        )
        return CostEstimate(provider=self._name, operation=operation, units=Decimal("0"))

    async def quota(self) -> QuotaSnapshot | None:
        self.quota_calls += 1
        if self._entered is not None:
            self._entered.set()
        if self._release is not None:
            await self._release.wait()
        return self._quota_snapshot

    async def health(self) -> ProviderHealth:
        return ProviderHealth(provider=self._name, status=HealthStatus.UNKNOWN, checked_at=FIXED_AT)


class _SimpleAdapter(ProviderAdapter):
    """Quota-less adapter that never blocks the background poll."""

    def __init__(self, name: str) -> None:
        self._name = name
        self.search_calls = 0

    @property
    def name(self) -> str:
        return self._name

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(search=True, fetch=True, cost_estimate=True)

    async def search(self, request: SearchRequest) -> SearchResponse:
        self.search_calls += 1
        return SearchResponse(
            query=request.query,
            provider=self._name,
            results=[
                SearchResult(
                    title=f"{self._name} hit",
                    url="https://example.com/r",
                    snippet="offline",
                )
            ],
            total_results=1,
        )

    async def fetch(self, request: FetchRequest) -> FetchResponse:
        return FetchResponse(
            provider=self._name,
            document=FetchedDocument(
                url=request.url,
                content=f"{self._name} content",
                fetched_at=datetime.now(UTC),
            ),
        )

    async def estimate_cost(self, request: SearchRequest | FetchRequest) -> CostEstimate:
        operation = (
            UsageOperation.SEARCH if isinstance(request, SearchRequest) else UsageOperation.FETCH
        )
        return CostEstimate(provider=self._name, operation=operation, units=Decimal("0"))

    async def quota(self) -> QuotaSnapshot | None:  # keep parity
        return None


async def _drain_background_tasks() -> None:
    for task in list(_BACKGROUND_TASKS):
        with suppress(Exception):
            await asyncio.wait_for(asyncio.shield(task), timeout=5)


async def _authed_headers(client: httpx.AsyncClient, prefix: str) -> dict[str, str]:
    """Register one temp account over async HTTP and return its access header."""

    email = temp_email(prefix)
    registered = await client.post(
        "/auth/register", json={"email": email, "password": TEMP_PASSWORD}
    )
    assert registered.status_code == 201
    logged_in = await client.post(
        "/auth/jwt/login", data={"username": email, "password": TEMP_PASSWORD}
    )
    assert logged_in.status_code == 200
    return {"Authorization": f"Bearer {logged_in.json()['access_token']}"}


async def test_request_does_not_wait_for_quota_poll(
    tmp_path: Path, auth_secret: str, monkeypatch: Any
) -> None:
    """M5: an expired TTL never delays the response; the poll lands afterwards."""
    clear_config_cache()
    clear_quota_poll_cache()
    repository = await SQLiteRepository.open(tmp_path / "no-wait.db")
    store = _execution_store(repository)
    entered = asyncio.Event()
    release = asyncio.Event()
    order: list[str] = []
    try:
        fresh_snapshot = QuotaSnapshot(
            provider="exa",
            source=QuotaSource.AUTHORITATIVE,
            remaining=Decimal("5"),
            limit=Decimal("10"),
            observed_at=FIXED_AT,
        )
        adapter = _QuotaAdapter(
            "exa", quota_snapshot=fresh_snapshot, entered=entered, release=release
        )
        fixture_secrets: dict[str, str] = {}
        install_adapter_map(monkeypatch, [adapter], secrets=fixture_secrets)
        app = create_app([adapter], repository=repository, secret_store=store)
        async with app.router.lifespan_context(app):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                headers = await _authed_headers(client, "no-wait")
                project = await seed_member_project(repository, headers)
                pid = str(project.project_id)
                bindings = await seed_provider_bindings(
                    repository,
                    project_id=project.project_id,
                    actor_id=project.actor_id,
                    store=store,
                    providers=("exa",),
                    secrets=fixture_secrets,
                )
                credential_id = bindings["exa"][0]
                try:
                    request_task = asyncio.create_task(
                        client.post(
                            "/search", json={"project_id": pid, "query": "no wait"}, headers=headers
                        )
                    )
                    await asyncio.wait_for(entered.wait(), timeout=5)
                    order.append("poll_entered")
                    response = await asyncio.wait_for(request_task, timeout=5)
                    order.append("request_done")
                    assert response.status_code == 200
                    assert response.json()["provider"] == "exa"
                    assert adapter.search_calls == 1
                    assert not release.is_set()
                    assert await repository.latest_quota("exa", credential_id=credential_id) is None
                finally:
                    release.set()
                await _drain_background_tasks()
                order.append("poll_done")
                stored = await repository.latest_quota("exa", credential_id=credential_id)
                assert stored is not None
                assert stored.remaining == Decimal("5")
                assert stored.limit == Decimal("10")
                assert await repository.latest_quota("exa") is None
                second = await client.post(
                    "/search", json={"project_id": pid, "query": "after poll"}, headers=headers
                )
                assert second.status_code == 200
                assert second.json()["provider"] == "exa"
            assert order == ["poll_entered", "request_done", "poll_done"]
    finally:
        release.set()
        await _drain_background_tasks()
        clear_config_cache()
        clear_quota_poll_cache()
        await repository.close()


async def test_stale_first_snapshot_then_new_snapshot(
    tmp_path: Path, auth_secret: str, monkeypatch: Any
) -> None:
    """E1: first expired-TTL request uses the old snapshot; later request excludes."""
    clear_config_cache()
    clear_quota_poll_cache()
    repository = await SQLiteRepository.open(tmp_path / "stale-first.db")
    store = _execution_store(repository)
    entered = asyncio.Event()
    release = asyncio.Event()
    planned_quotas: list[list[Decimal | None]] = []
    original_quota = ExecutionService._leg_quota

    async def capture_plan(self: ExecutionService, leg: Any) -> Any:
        snapshot = await original_quota(self, leg)
        planned_quotas.append([] if snapshot is None else [snapshot.remaining])
        return snapshot

    monkeypatch.setattr(ExecutionService, "_leg_quota", capture_plan)
    try:
        positive = QuotaSnapshot(
            provider="exa",
            source=QuotaSource.AUTHORITATIVE,
            remaining=Decimal("10"),
            limit=Decimal("10"),
            observed_at=FIXED_AT,
        )
        await repository.record_quota(positive)
        clear_quota_poll_cache()
        zero = QuotaSnapshot(
            provider="exa",
            source=QuotaSource.AUTHORITATIVE,
            remaining=Decimal("0"),
            limit=Decimal("10"),
            observed_at=datetime(2026, 3, 10, 12, 5, 0, tzinfo=UTC),
        )
        adapter = _QuotaAdapter("exa", quota_snapshot=zero, entered=entered, release=release)
        fixture_secrets: dict[str, str] = {}
        install_adapter_map(monkeypatch, [adapter], secrets=fixture_secrets)
        app = create_app([adapter], repository=repository, secret_store=store)
        async with app.router.lifespan_context(app):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                headers = await _authed_headers(client, "stale-first")
                project = await seed_member_project(repository, headers)
                pid = str(project.project_id)
                bindings = await seed_provider_bindings(
                    repository,
                    project_id=project.project_id,
                    actor_id=project.actor_id,
                    store=store,
                    providers=("exa",),
                    operations=frozenset({CredentialOperation.SEARCH}),
                    secrets=fixture_secrets,
                )
                credential_id = bindings["exa"][0]
                await repository.record_quota(positive, credential_id=credential_id)
                try:
                    first_task = asyncio.create_task(
                        client.post(
                            "/search",
                            json={
                                "project_id": pid,
                                "query": "stale first",
                                "routing": {"mode": "require", "providers": ["exa"]},
                            },
                            headers=headers,
                        )
                    )
                    await asyncio.wait_for(entered.wait(), timeout=5)
                    first = await asyncio.wait_for(first_task, timeout=5)
                    assert first.status_code == 200
                    assert first.json()["provider"] == "exa"
                    assert planned_quotas == [[Decimal("10")]]
                    assert not release.is_set()
                    stale = await repository.latest_quota("exa", credential_id=credential_id)
                    assert stale is not None and stale.remaining == Decimal("10")
                finally:
                    release.set()
                await _drain_background_tasks()
                stored = await repository.latest_quota("exa", credential_id=credential_id)
                assert stored is not None
                assert stored.remaining == Decimal("0")
                assert stored.limit == Decimal("10")
                unrelated = await repository.latest_quota("exa")
                assert unrelated is not None and unrelated.remaining == Decimal("10")
                clear_quota_poll_cache()
                second = await client.post(
                    "/search",
                    json={
                        "project_id": pid,
                        "query": "after exhaustion",
                        "routing": {"mode": "require", "providers": ["exa"]},
                    },
                    headers=headers,
                )
                assert second.status_code == 503
                assert "no required provider is eligible" in second.json()["detail"]
                assert adapter.search_calls == 1
                assert planned_quotas == [[Decimal("10")], [Decimal("0")]]
    finally:
        release.set()
        await _drain_background_tasks()
        clear_config_cache()
        clear_quota_poll_cache()
        await repository.close()


async def test_auto_route_plan_read_budget(
    tmp_path: Path, auth_secret: str, monkeypatch: Any
) -> None:
    """M6: AUTO batches health once and reads quota only for prepared legs.

    The leg chain prepares the first leg and, while it runs, the next one, so
    a successful AUTO request reads exactly two scoped quotas.

    The warm SELECT count is printed as a diagnostic report, never asserted:
    routing latency (not a fixed read count) is the acceptance measure.
    """
    clear_config_cache()
    clear_quota_poll_cache()
    repository = await SQLiteRepository.open(tmp_path / "read-budget.db")
    store = _execution_store(repository)
    release = asyncio.Event()
    entered = asyncio.Event()
    try:
        for name in SEVEN_PROVIDERS:
            await repository.record_quota(
                QuotaSnapshot(
                    provider=name,
                    source=QuotaSource.AUTHORITATIVE,
                    remaining=Decimal("10"),
                    limit=Decimal("10"),
                    observed_at=FIXED_AT,
                )
            )
            await repository.record_health(
                ProviderHealth(provider=name, status=HealthStatus.HEALTHY, checked_at=FIXED_AT)
            )
        adapters: list[ProviderAdapter] = [
            _QuotaAdapter(
                name,
                quota_snapshot=QuotaSnapshot(
                    provider=name,
                    source=QuotaSource.AUTHORITATIVE,
                    remaining=Decimal("10"),
                    limit=Decimal("10"),
                    observed_at=FIXED_AT,
                ),
                entered=entered if name == SEVEN_PROVIDERS[0] else None,
                release=release if name == SEVEN_PROVIDERS[0] else None,
            )
            for name in SEVEN_PROVIDERS
        ]
        for adapter in adapters:
            assert isinstance(adapter, _QuotaAdapter)
            adapter._entered = entered if adapter.name == SEVEN_PROVIDERS[0] else None
            adapter._release = release if adapter.name == SEVEN_PROVIDERS[0] else None
        fixture_secrets: dict[str, str] = {}
        install_adapter_map(monkeypatch, adapters, secrets=fixture_secrets)
        app = create_app(adapters, repository=repository, secret_store=store)

        for name in SEVEN_PROVIDERS:
            await effective_config_for_name(repository, name)
        await routing_policy(repository)

        health_calls: list[list[str]] = []
        quota_calls: list[tuple[str, Any, Any]] = []
        quota_batch_calls: list[list[str]] = []
        in_plan: ContextVar[bool] = ContextVar("in_plan", default=False)
        orig_health = SQLiteRepository.latest_health_batch
        orig_quota = SQLiteRepository.latest_quota
        orig_quota_batch = SQLiteRepository.latest_quota_batch
        orig_plan = ExecutionService._leg_quota

        async def _count_health(self: SQLiteRepository, providers: Any) -> Any:
            health_calls.append(list(providers))
            return await orig_health(self, providers)

        async def _count_quota(self: SQLiteRepository, provider: str, **kwargs: Any) -> Any:
            if in_plan.get():
                quota_calls.append((provider, kwargs.get("credential_id"), kwargs.get("pool_id")))
            return await orig_quota(self, provider, **kwargs)

        async def _count_quota_batch(self: SQLiteRepository, providers: Any) -> Any:
            if in_plan.get():
                quota_batch_calls.append(list(providers))
            return await orig_quota_batch(self, providers)

        async def _count_plan(self: ExecutionService, leg: Any) -> Any:
            token = in_plan.set(True)
            try:
                return await orig_plan(self, leg)
            finally:
                in_plan.reset(token)

        SQLiteRepository.latest_health_batch = _count_health  # type: ignore[method-assign]
        SQLiteRepository.latest_quota = _count_quota  # type: ignore[method-assign]
        SQLiteRepository.latest_quota_batch = _count_quota_batch  # type: ignore[method-assign]
        ExecutionService._leg_quota = _count_plan  # type: ignore[method-assign]
        select_counts: list[int] = [0]

        def _before_cursor(
            conn: Any, cursor: Any, statement: str, params: Any, ctx: Any, many: Any
        ) -> None:
            if statement.lstrip().upper().startswith("SELECT"):
                select_counts[0] += 1

        sync_engine = getattr(repository._engine, "sync_engine", None)
        listened = False
        if sync_engine is not None:
            sa_event.listen(sync_engine, "before_cursor_execute", _before_cursor)
            listened = True
        try:
            clear_quota_poll_cache()
            health_calls.clear()
            quota_calls.clear()
            select_counts[0] = 0
            cold_health = 0
            clear_config_cache()
            async with app.router.lifespan_context(app):
                transport = httpx.ASGITransport(app=app)
                async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                    headers = await _authed_headers(client, "read-budget")
                    project = await seed_member_project(repository, headers)
                    pid = str(project.project_id)
                    bindings = await seed_provider_bindings(
                        repository,
                        project_id=project.project_id,
                        actor_id=project.actor_id,
                        store=store,
                        providers=tuple(SEVEN_PROVIDERS),
                        secrets=fixture_secrets,
                    )
                    try:
                        first_task = asyncio.create_task(
                            client.post(
                                "/search",
                                json={"project_id": pid, "query": "cold plan"},
                                headers=headers,
                            )
                        )
                        with suppress(asyncio.TimeoutError, TimeoutError):
                            await asyncio.wait_for(entered.wait(), timeout=5)
                        cold_resp = await asyncio.wait_for(first_task, timeout=5)
                        assert cold_resp.status_code == 200
                    finally:
                        release.set()
                    await _drain_background_tasks()
                    cold_selects = select_counts[0]
                    cold_health = len(health_calls)
                    cold_quota = list(quota_calls)
                    assert not quota_batch_calls

                    for name in SEVEN_PROVIDERS:
                        await effective_config_for_name(repository, name)
                    await routing_policy(repository)
                    clear_quota_poll_cache()
                    entered.clear()
                    release.clear()

                    for adapter in adapters:
                        if (
                            isinstance(adapter, _QuotaAdapter)
                            and adapter.name == SEVEN_PROVIDERS[0]
                        ):
                            adapter._entered = entered
                            adapter._release = release
                    health_calls.clear()
                    quota_calls.clear()
                    select_counts[0] = 0
                    warm_task = asyncio.create_task(
                        client.post(
                            "/search",
                            json={"project_id": pid, "query": "warm plan"},
                            headers=headers,
                        )
                    )
                    with suppress(asyncio.TimeoutError, TimeoutError):
                        await asyncio.wait_for(entered.wait(), timeout=5)
                    warm_resp = await asyncio.wait_for(warm_task, timeout=5)
                    assert warm_resp.status_code == 200
                    release.set()
                    await _drain_background_tasks()
                    warm_selects = select_counts[0]
                    # Diagnostic report only: database reads per request are not
                    # pass/fail (the routing-latency acceptance owns the gate).
                    # The count includes the access-JWT account/session reads.
                    print(
                        f"route-plan reads report: cold-cache SELECTs={cold_selects} "
                        f"warm SELECTs={warm_selects} health-batches={len(health_calls)} "
                        f"cold scoped-quota-reads={len(cold_quota)}"
                    )
                    assert len(health_calls) == 1, f"expected one health batch, got {health_calls}"
                    assert set(health_calls[0]) == set(SEVEN_PROVIDERS)
                    expected_reads = {(name, bindings[name][0], None) for name in SEVEN_PROVIDERS}
                    assert not quota_batch_calls
                    assert len(quota_calls) == 2
                    assert set(quota_calls) <= expected_reads
                    assert cold_health >= 1
                    assert len(cold_quota) == 2
                    assert set(cold_quota) <= expected_reads
        finally:
            SQLiteRepository.latest_health_batch = orig_health  # type: ignore[method-assign]
            SQLiteRepository.latest_quota = orig_quota  # type: ignore[method-assign]
            SQLiteRepository.latest_quota_batch = orig_quota_batch  # type: ignore[method-assign]
            ExecutionService._leg_quota = orig_plan  # type: ignore[method-assign]
            if listened and sync_engine is not None:
                with suppress(Exception):
                    sa_event.remove(sync_engine, "before_cursor_execute", _before_cursor)
    finally:
        release.set()
        await _drain_background_tasks()
        clear_config_cache()
        clear_quota_poll_cache()
        await repository.close()
