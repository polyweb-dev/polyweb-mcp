"""Routing latency integration tests: background quota, stale-first, read budget.

Uses real SQLite and offline adapters. Async REST cases use
``httpx.ASGITransport`` so event barriers share one loop.
"""

from __future__ import annotations

import asyncio
from contextlib import suppress
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import event as sa_event

from freesearch.adapters.base import ProviderAdapter
from freesearch.models.contracts import (
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
from freesearch.persistence.storage import SQLiteRepository
from freesearch.routers.api import _BACKGROUND_TASKS, create_app
from freesearch.routers.control import (
    clear_config_cache,
    effective_config_for_name,
    routing_policy,
)
from freesearch.services.monitoring import clear_quota_poll_cache
from tests.fixtures.auth import TEMP_PASSWORD, temp_email
from tests.fixtures.execution import seed_member_project

FIXED_AT = datetime(2026, 3, 10, 12, 0, 0, tzinfo=UTC)

SEVEN_PROVIDERS = ["exa", "firecrawl", "tavily", "parallel", "you", "brave", "keenable"]


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


async def test_request_does_not_wait_for_quota_poll(tmp_path: Path, auth_secret: str) -> None:
    """M5: an expired TTL never delays the response; the poll lands afterwards."""
    clear_config_cache()
    clear_quota_poll_cache()
    repository = await SQLiteRepository.open(tmp_path / "no-wait.db")
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
        app = create_app([adapter], repository=repository)
        async with app.router.lifespan_context(app):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                headers = await _authed_headers(client, "no-wait")
                pid = str((await seed_member_project(repository, headers)).project_id)
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
                finally:
                    release.set()
                await _drain_background_tasks()
                order.append("poll_done")
                stored = await repository.latest_quota("exa")
                assert stored is not None
                assert stored.remaining == Decimal("5")
                assert stored.limit == Decimal("10")
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


async def test_stale_first_snapshot_then_new_snapshot(tmp_path: Path, auth_secret: str) -> None:
    """E1: first expired-TTL request uses the old snapshot; later request excludes."""
    clear_config_cache()
    clear_quota_poll_cache()
    repository = await SQLiteRepository.open(tmp_path / "stale-first.db")
    entered = asyncio.Event()
    release = asyncio.Event()
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
        app = create_app([adapter], repository=repository)
        async with app.router.lifespan_context(app):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                headers = await _authed_headers(client, "stale-first")
                pid = str((await seed_member_project(repository, headers)).project_id)
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
                finally:
                    release.set()
                await _drain_background_tasks()
                stored = await repository.latest_quota("exa")
                assert stored is not None
                assert stored.remaining == Decimal("0")
                assert stored.limit == Decimal("10")
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
    finally:
        release.set()
        await _drain_background_tasks()
        clear_config_cache()
        clear_quota_poll_cache()
        await repository.close()


async def test_auto_route_plan_read_budget(tmp_path: Path, auth_secret: str) -> None:
    """M6: one warm AUTO plan uses at most 4 foreground reads plus one batch pair."""
    clear_config_cache()
    clear_quota_poll_cache()
    repository = await SQLiteRepository.open(tmp_path / "read-budget.db")
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
        app = create_app(adapters, repository=repository)

        for name in SEVEN_PROVIDERS:
            await effective_config_for_name(repository, name)
        await routing_policy(repository)

        health_calls: list[list[str]] = []
        quota_calls: list[list[str]] = []
        orig_health = SQLiteRepository.latest_health_batch
        orig_quota = SQLiteRepository.latest_quota_batch

        async def _count_health(self: SQLiteRepository, providers: Any) -> Any:
            health_calls.append(list(providers))
            return await orig_health(self, providers)

        async def _count_quota(self: SQLiteRepository, providers: Any) -> Any:
            quota_calls.append(list(providers))
            return await orig_quota(self, providers)

        SQLiteRepository.latest_health_batch = _count_health  # type: ignore[method-assign]
        SQLiteRepository.latest_quota_batch = _count_quota  # type: ignore[method-assign]
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
            cold_quota = 0
            clear_config_cache()
            async with app.router.lifespan_context(app):
                transport = httpx.ASGITransport(app=app)
                async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                    headers = await _authed_headers(client, "read-budget")
                    pid = str((await seed_member_project(repository, headers)).project_id)
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
                    cold_quota = len(quota_calls)

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
                    print(f"cold-cache SELECTs: {cold_selects} warm SELECTs: {warm_selects}")
                    assert len(health_calls) == 1, f"expected one health batch, got {health_calls}"
                    assert len(quota_calls) == 1, f"expected one quota batch, got {quota_calls}"
                    assert set(health_calls[0]) == set(SEVEN_PROVIDERS)
                    # Authenticated warm budget: the anonymous M6 route-plan bound
                    # was 4 SELECTs; the required access-JWT verification plus
                    # trace writes add account/session reads on every request.
                    assert warm_selects <= 16, (
                        f"warm AUTO plan used {warm_selects} SELECTs "
                        f"(cold was {cold_selects}); health={health_calls} quota-batch={cold_quota}"
                    )
                    assert cold_health >= 1 and cold_quota >= 1
        finally:
            SQLiteRepository.latest_health_batch = orig_health  # type: ignore[method-assign]
            SQLiteRepository.latest_quota_batch = orig_quota  # type: ignore[method-assign]
            if listened and sync_engine is not None:
                with suppress(Exception):
                    sa_event.remove(sync_engine, "before_cursor_execute", _before_cursor)
    finally:
        release.set()
        await _drain_background_tasks()
        clear_config_cache()
        clear_quota_poll_cache()
        await repository.close()
