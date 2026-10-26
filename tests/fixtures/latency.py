"""Shared routing-latency helpers for the pytest mixes and the Behave scenarios.

Instant offline adapters, payload builders, repository seeding, cache warming,
background-task draining, the SELECT counter, and the percentile method live
here so ``tests/integration/latency/test_routing_latency.py`` and the Behave
latency steps measure with one implementation. No helper reads a credential.
"""

from __future__ import annotations

import asyncio
import subprocess
from collections.abc import Callable, Iterable, Sequence
from contextlib import suppress
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from pydantic import AnyHttpUrl
from sqlalchemy import event as sa_event

from freesearch.adapters.base import ProviderAdapter
from freesearch.infrastructure.secrets import ProviderName
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
from freesearch.models.provider_limits import AuthMode
from freesearch.persistence.storage import SQLiteRepository
from freesearch.routers.api import _BACKGROUND_TASKS
from freesearch.routers.control import effective_config_for_name, routing_policy

#: Every canonical provider the adapter registry can construct.
CANONICAL_PROVIDERS: tuple[str, ...] = tuple(sorted(provider.value for provider in ProviderName))

REPO_ROOT = Path(__file__).resolve().parents[2]

SEED_AT = datetime(2026, 3, 10, 12, 0, 0, tzinfo=UTC)
SEARCH_QUERY = "routing latency probe"
FETCH_URL = "https://example.com/page"

#: Capability flags of each real adapter in its default (vault-keyed) build.
#: Keenable mirrors its keyless public tier (no quota endpoint without a key).
REAL_CAPABILITIES: dict[str, ProviderCapabilities] = {
    "brave": ProviderCapabilities(search=True, fetch=False, cost_estimate=True),
    "exa": ProviderCapabilities(search=True, fetch=True, quota=True),
    "firecrawl": ProviderCapabilities(search=True, fetch=True, cost_estimate=True, quota=True),
    "keenable": ProviderCapabilities(search=True, fetch=True, cost_estimate=True, quota=False),
    "parallel": ProviderCapabilities(search=True, fetch=True, cost_estimate=True),
    "tavily": ProviderCapabilities(search=True, fetch=True, cost_estimate=True, quota=True),
    "tinyfish": ProviderCapabilities(search=True, fetch=True, cost_estimate=True, quota=False),
    "you": ProviderCapabilities(search=True, fetch=True, cost_estimate=True, quota=True),
}

#: Limit rail of each real adapter in the same default build.
REAL_AUTH_MODES: dict[str, AuthMode] = {"keenable": AuthMode.KEYLESS}


def default_report_dir() -> Path:
    """Return the gitignored repo-root ``test_reports/`` directory."""

    return REPO_ROOT / "test_reports"


def _git(*args: str) -> str | None:
    try:
        proc = subprocess.run(
            ["git", *args],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
            cwd=REPO_ROOT,
        )
    except Exception:
        return None
    return proc.stdout if proc.returncode == 0 else None


def git_commit() -> str:
    """Return the short HEAD commit, ``-dirty`` when the tree has changes."""

    sha = (_git("rev-parse", "--short", "HEAD") or "").strip()
    if not sha:
        return "unknown"
    status = _git("status", "--porcelain")
    return f"{sha}-dirty" if status is None or status.strip() else sha


class OfflineAdapter(ProviderAdapter):
    """Offline stub: instant search/fetch, no quota poll delay.

    Without explicit ``capabilities`` the stub supports search, fetch, and
    cost estimates (the historical pytest mix shape); :func:`fake_adapter_for`
    mirrors a real adapter's flags instead.
    """

    def __init__(
        self,
        name: str,
        *,
        capabilities: ProviderCapabilities | None = None,
        limit_auth_mode: AuthMode = AuthMode.KEYED,
    ) -> None:
        self._name = name
        self._capabilities = capabilities or ProviderCapabilities(
            search=True, fetch=True, cost_estimate=True
        )
        self._limit_auth_mode = limit_auth_mode

    @property
    def name(self) -> str:
        return self._name

    @property
    def capabilities(self) -> ProviderCapabilities:
        return self._capabilities

    @property
    def limit_auth_mode(self) -> AuthMode:
        return self._limit_auth_mode

    async def search(self, request: SearchRequest) -> SearchResponse:
        return SearchResponse(
            query=request.query,
            provider=self._name,
            results=[
                SearchResult(
                    title=f"{self._name} hit",
                    url=AnyHttpUrl("https://example.com/r"),
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
        return None

    async def health(self) -> ProviderHealth:
        return ProviderHealth(
            provider=self._name, status=HealthStatus.UNKNOWN, checked_at=datetime.now(UTC)
        )


def fake_adapter_for(name: str) -> OfflineAdapter:
    """Return an instant offline adapter mirroring the real adapter's flags."""

    return OfflineAdapter(
        name,
        capabilities=REAL_CAPABILITIES[name],
        limit_auth_mode=REAL_AUTH_MODES.get(name, AuthMode.KEYED),
    )


def supports_operation(adapter: ProviderAdapter, operation: str) -> bool:
    """Return whether ``adapter`` advertises ``operation`` (search or fetch)."""

    capabilities = adapter.capabilities
    return capabilities.search if operation == "search" else capabilities.fetch


async def seed_repository(
    repository: SQLiteRepository,
    providers: Iterable[str],
    *,
    observed_at: datetime = SEED_AT,
) -> None:
    """Record a positive authoritative quota and a healthy status per provider."""

    for name in providers:
        await repository.record_quota(
            QuotaSnapshot(
                provider=name,
                source=QuotaSource.AUTHORITATIVE,
                remaining=Decimal("10"),
                limit=Decimal("10"),
                observed_at=observed_at,
            )
        )
        await repository.record_health(
            ProviderHealth(provider=name, status=HealthStatus.HEALTHY, checked_at=observed_at)
        )


async def warm_route_caches(repository: SQLiteRepository, providers: Iterable[str]) -> None:
    """Pre-load the per-provider effective config and the routing policy caches."""

    for provider_name in providers:
        await effective_config_for_name(repository, provider_name)
    await routing_policy(repository)


async def drain_background_tasks() -> None:
    """Await the out-of-band quota refresh tasks owned by the running loop."""

    loop = asyncio.get_running_loop()
    for task in list(_BACKGROUND_TASKS):
        if task.get_loop() is not loop:
            continue
        with suppress(Exception):
            await asyncio.wait_for(asyncio.shield(task), timeout=5)


def attach_select_counter(
    repository: SQLiteRepository,
    selects: list[int],
    unavailable_reasons: list[str] | None = None,
) -> Callable[[], None] | None:
    """Count foreground SELECTs; return a detach callable or None with a reason."""

    reasons = unavailable_reasons if unavailable_reasons is not None else []
    engine = getattr(repository, "_engine", None)
    sync_engine = getattr(engine, "sync_engine", None)
    if sync_engine is None:
        reasons.append("no sync_engine exposed by repository engine")
        return None

    def _before_cursor(
        conn: Any, cursor: Any, statement: str, params: Any, ctx: Any, many: Any
    ) -> None:
        if isinstance(statement, str) and statement.lstrip().upper().startswith("SELECT"):
            selects[0] += 1

    try:
        sa_event.listen(sync_engine, "before_cursor_execute", _before_cursor)
    except Exception as exc:
        reasons.append(f"select listener attach failed: {exc}")
        return None

    def _detach() -> None:
        with suppress(Exception):
            sa_event.remove(sync_engine, "before_cursor_execute", _before_cursor)

    return _detach


def search_payload(
    mode: str,
    providers: Sequence[str] | None,
    fanout: bool = False,
    project_id: str | None = None,
) -> dict[str, Any]:
    """Build one search request body; ``auto`` mode omits the routing block."""

    payload: dict[str, Any] = {"query": SEARCH_QUERY}
    if project_id is not None:
        payload["project_id"] = project_id
    if mode != "auto":
        payload["routing"] = {"mode": mode, "providers": list(providers or [])}
    if fanout:
        payload["fanout"] = True
    return payload


def fetch_payload(
    mode: str, providers: Sequence[str] | None, project_id: str | None = None
) -> dict[str, Any]:
    """Build one fetch request body; ``auto`` mode omits the routing block."""

    payload: dict[str, Any] = {"url": FETCH_URL}
    if project_id is not None:
        payload["project_id"] = project_id
    if mode != "auto":
        payload["routing"] = {"mode": mode, "providers": list(providers or [])}
    return payload


def percentile(sorted_values: Sequence[float], pct: float) -> float:
    """Linear interpolation between closest ranks; empty input reports 0.0."""

    if not sorted_values:
        return 0.0
    if len(sorted_values) == 1:
        return sorted_values[0]
    rank = (len(sorted_values) - 1) * (pct / 100.0)
    low = int(rank)
    high = min(low + 1, len(sorted_values) - 1)
    return sorted_values[low] + (sorted_values[high] - sorted_values[low]) * (rank - low)
