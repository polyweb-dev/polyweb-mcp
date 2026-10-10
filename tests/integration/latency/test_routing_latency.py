"""Direct routing-latency measurements over in-process REST and MCP APIs.

Harness: REST mixes drive the FastAPI app through ``httpx.ASGITransport``
(in-process, not network); MCP mixes call ``server.call_tool`` in-process.
A real temporary SQLite repository and seven offline stub adapters back
every mix. Each request records wall time via ``time.perf_counter()`` and
a foreground SELECT count. Reports land in repo-root ``test_reports/``.
"""

from __future__ import annotations

import asyncio
import csv
import platform
import sqlite3
import subprocess
import sys
import time
from collections.abc import Awaitable, Callable, Mapping, Sequence
from contextlib import suppress
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx
import pytest
from sqlalchemy import event as sa_event

from freesearch.adapters.base import ProviderAdapter
from freesearch.mcp.server import create_server
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

SEVEN_PROVIDERS = ["exa", "firecrawl", "tavily", "parallel", "you", "brave", "keenable"]

SEED_AT = datetime(2026, 3, 10, 12, 0, 0, tzinfo=UTC)
SEARCH_QUERY = "routing latency probe"
FETCH_URL = "https://example.com/page"

_CSV_COLUMNS = (
    "commit",
    "transport",
    "operation",
    "routing_mode",
    "providers",
    "adapter_mode",
    "cache_state",
    "phase",
    "request_index",
    "wall_time_ms",
    "route_plan_reads",
    "trace_id",
    "status",
    "error",
)

_WARMUP_PER_MIX = 10
_MEASURED_PER_MIX = 30
_EXPECTED_TOTAL_ROWS = 328  # 8 mixes x (1 cold + 10 warmup + 30 measured)

_MIX_ORDER: tuple[tuple[str, str, str, str], ...] = (
    ("rest-inprocess", "search", "require", "exa"),
    ("rest-inprocess", "search", "auto", "all"),
    ("rest-inprocess", "search", "fanout", "exa+tavily"),
    ("mcp-inprocess", "search", "require", "exa"),
    ("mcp-inprocess", "search", "auto", "all"),
    ("mcp-inprocess", "search", "fanout", "exa+tavily"),
    ("mcp-inprocess", "fetch", "require", "exa"),
    ("mcp-inprocess", "fetch", "auto", "all"),
)

_REPRO_COMMAND = (
    "uv run --with matplotlib pytest tests/integration/latency/test_routing_latency.py -q"
)

_READS_UNAVAILABLE_REASONS: list[str] = []


class _OfflineAdapter(ProviderAdapter):
    """Offline stub: instant search/fetch, no quota poll delay."""

    def __init__(self, name: str) -> None:
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(search=True, fetch=True, cost_estimate=True)

    async def search(self, request: SearchRequest) -> SearchResponse:
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
        return None

    async def health(self) -> ProviderHealth:
        return ProviderHealth(
            provider=self._name, status=HealthStatus.UNKNOWN, checked_at=datetime.now(UTC)
        )


async def _drain_background_tasks() -> None:
    for task in list(_BACKGROUND_TASKS):
        with suppress(Exception):
            await asyncio.wait_for(asyncio.shield(task), timeout=5)


def _git_commit() -> str:
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
            cwd=Path(__file__).resolve().parents[3],
        )
        sha = proc.stdout.strip()
        return sha if sha else "unknown"
    except Exception:
        return "unknown"


def _default_output_dir() -> Path:
    return Path(__file__).resolve().parents[3] / "test_reports"


async def _seed_repository(repository: SQLiteRepository) -> None:
    for name in SEVEN_PROVIDERS:
        await repository.record_quota(
            QuotaSnapshot(
                provider=name,
                source=QuotaSource.AUTHORITATIVE,
                remaining=Decimal("10"),
                limit=Decimal("10"),
                observed_at=SEED_AT,
            )
        )
        await repository.record_health(
            ProviderHealth(provider=name, status=HealthStatus.HEALTHY, checked_at=SEED_AT)
        )


def _attach_select_counter(
    repository: SQLiteRepository, selects: list[int]
) -> Callable[[], None] | None:
    """Count foreground SELECTs; return a detach callable or None with a reason."""
    engine = getattr(repository, "_engine", None)
    sync_engine = getattr(engine, "sync_engine", None)
    if sync_engine is None:
        _READS_UNAVAILABLE_REASONS.append("no sync_engine exposed by repository engine")
        return None

    def _before_cursor(
        conn: Any, cursor: Any, statement: str, params: Any, ctx: Any, many: Any
    ) -> None:
        if isinstance(statement, str) and statement.lstrip().upper().startswith("SELECT"):
            selects[0] += 1

    try:
        sa_event.listen(sync_engine, "before_cursor_execute", _before_cursor)
    except Exception as exc:
        _READS_UNAVAILABLE_REASONS.append(f"select listener attach failed: {exc}")
        return None

    def _detach() -> None:
        with suppress(Exception):
            sa_event.remove(sync_engine, "before_cursor_execute", _before_cursor)

    return _detach


def _search_payload(mode: str, providers: list[str] | None, fanout: bool = False) -> dict[str, Any]:
    payload: dict[str, Any] = {"query": SEARCH_QUERY}
    if mode != "auto":
        payload["routing"] = {"mode": mode, "providers": providers or []}
    if fanout:
        payload["fanout"] = True
    return payload


def _fetch_payload(mode: str, providers: list[str] | None) -> dict[str, Any]:
    payload: dict[str, Any] = {"url": FETCH_URL}
    if mode != "auto":
        payload["routing"] = {"mode": mode, "providers": providers or []}
    return payload


async def _record_request(
    rows: list[dict[str, Any]],
    *,
    commit: str,
    transport: str,
    operation: str,
    routing_mode: str,
    providers: str,
    cache_state: str,
    phase: str,
    request_index: int,
    selects: list[int] | None,
    call: Callable[[], Awaitable[Any]],
) -> None:
    if selects is not None:
        selects[0] = 0
    start = time.perf_counter()
    try:
        await call()
    except Exception as exc:  # per-request isolation: never fail the mix on one sample
        status = f"error:{type(exc).__name__}"
        error = str(exc)
    else:
        status = "ok"
        error = ""
    elapsed_ms = (time.perf_counter() - start) * 1000.0
    reads: int | str = selects[0] if selects is not None else ""
    await _drain_background_tasks()
    rows.append(
        {
            "commit": commit,
            "transport": transport,
            "operation": operation,
            "routing_mode": routing_mode,
            "providers": providers,
            "adapter_mode": "offline",
            "cache_state": cache_state,
            "phase": phase,
            "request_index": request_index,
            "wall_time_ms": f"{elapsed_ms:.6f}",
            "route_plan_reads": reads,
            "trace_id": "",
            "status": status,
            "error": error,
        }
    )


async def _run_mix(
    rows: list[dict[str, Any]],
    *,
    commit: str,
    transport: str,
    operation: str,
    routing_mode: str,
    providers: str,
    repository: SQLiteRepository,
    selects: list[int] | None,
    call: Callable[[], Awaitable[Any]],
) -> None:
    clear_config_cache()
    clear_quota_poll_cache()
    await _record_request(
        rows,
        commit=commit,
        transport=transport,
        operation=operation,
        routing_mode=routing_mode,
        providers=providers,
        cache_state="cold",
        phase="cold",
        request_index=0,
        selects=selects,
        call=call,
    )
    for provider_name in SEVEN_PROVIDERS:
        await effective_config_for_name(repository, provider_name)
    await routing_policy(repository)
    for index in range(_WARMUP_PER_MIX):
        await _record_request(
            rows,
            commit=commit,
            transport=transport,
            operation=operation,
            routing_mode=routing_mode,
            providers=providers,
            cache_state="warm",
            phase="warmup",
            request_index=index,
            selects=selects,
            call=call,
        )
    for index in range(_MEASURED_PER_MIX):
        await _record_request(
            rows,
            commit=commit,
            transport=transport,
            operation=operation,
            routing_mode=routing_mode,
            providers=providers,
            cache_state="warm",
            phase="measured",
            request_index=index,
            selects=selects,
            call=call,
        )


def _percentile(sorted_values: list[float], pct: float) -> float:
    """Linear interpolation between closest ranks; document the method in the MD."""
    if not sorted_values:
        return 0.0
    if len(sorted_values) == 1:
        return sorted_values[0]
    rank = (len(sorted_values) - 1) * (pct / 100.0)
    low = int(rank)
    high = min(low + 1, len(sorted_values) - 1)
    return sorted_values[low] + (sorted_values[high] - sorted_values[low]) * (rank - low)


def _wall_value(row: Mapping[str, Any]) -> float:
    try:
        return float(row.get("wall_time_ms") or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _reads_value(row: Mapping[str, Any]) -> float | None:
    value = row.get("route_plan_reads")
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _mix_key(row: Mapping[str, Any]) -> tuple[str, str, str, str]:
    return (
        str(row.get("transport")),
        str(row.get("operation")),
        str(row.get("routing_mode")),
        str(row.get("providers")),
    )


def _group_label(transport: str, operation: str, mode: str, providers: str) -> str:
    short = "rest" if transport.startswith("rest") else "mcp"
    return f"{short}\n{operation} {mode}\n{providers}"


def _write_latency_report(rows: Sequence[dict[str, Any]], output_dir: Path) -> None:
    """Write routing_latency.csv, both PNG charts, and routing_latency.md."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    resolved = Path(output_dir)
    if not resolved.is_absolute():
        resolved = Path(__file__).resolve().parents[3] / resolved
    resolved.mkdir(parents=True, exist_ok=True)

    csv_path = resolved / "routing_latency.csv"
    wall_path = resolved / "routing_latency_wall_time.png"
    reads_path = resolved / "routing_latency_route_reads.png"
    md_path = resolved / "routing_latency.md"

    with open(csv_path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(_CSV_COLUMNS))
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {key: ("" if row.get(key) is None else row.get(key)) for key in _CSV_COLUMNS}
            )

    measured = [row for row in rows if row.get("phase") == "measured"]
    cold = [row for row in rows if row.get("phase") == "cold"]
    warmup = [row for row in rows if row.get("phase") == "warmup"]
    commit = str(rows[0].get("commit")) if rows else _git_commit()

    table: list[dict[str, Any]] = []
    for transport, operation, mode, providers in _MIX_ORDER:
        group = [r for r in measured if _mix_key(r) == (transport, operation, mode, providers)]
        ok_rows = [r for r in group if r.get("status") == "ok"]
        walls = sorted(_wall_value(r) for r in ok_rows)
        reads: list[float] = []
        for item in ok_rows:
            value = _reads_value(item)
            if value is not None:
                reads.append(value)
        reads.sort()
        table.append(
            {
                "transport": transport,
                "operation": operation,
                "mode": mode,
                "providers": providers,
                "n": len(group),
                "failures": len(group) - len(ok_rows),
                "median_ms": _percentile(walls, 50.0),
                "p95_ms": _percentile(walls, 95.0),
                "max_ms": max(walls) if walls else 0.0,
                "median_reads": _percentile(reads, 50.0) if reads else None,
            }
        )

    labels = [
        _group_label(e["transport"], e["operation"], e["mode"], e["providers"]) for e in table
    ]

    wall_fig, wall_ax = plt.subplots(figsize=(12, 5))
    wall_ax.bar(range(len(labels)), [e["median_ms"] for e in table])
    wall_ax.set_xticks(range(len(labels)), labels, rotation=30, ha="right")
    wall_ax.set_ylabel("median wall time (ms)")
    wall_ax.set_title("Routing latency: median wall ms per measured mix (in-process)")
    wall_fig.tight_layout()
    wall_fig.savefig(wall_path)
    plt.close(wall_fig)

    reads_fig, reads_ax = plt.subplots(figsize=(12, 5))
    reads_values = [e["median_reads"] if e["median_reads"] is not None else 0.0 for e in table]
    reads_ax.bar(range(len(labels)), reads_values)
    top = max(reads_values) if reads_values and max(reads_values) > 0 else 1.0
    for index, entry in enumerate(table):
        if entry["median_reads"] is None:
            reads_ax.text(index, top * 0.05, "unavailable", ha="center", rotation=90)
    reads_ax.set_xticks(range(len(labels)), labels, rotation=30, ha="right")
    reads_ax.set_ylabel("median route-plan reads")
    reads_ax.set_title("Route-plan reads: median SELECTs per measured mix")
    reads_fig.tight_layout()
    reads_fig.savefig(reads_path)
    plt.close(reads_fig)

    if _READS_UNAVAILABLE_REASONS:
        reads_note = "Unavailable: " + "; ".join(_READS_UNAVAILABLE_REASONS)
    else:
        missing = [e for e in table if e["median_reads"] is None]
        if missing:
            names = ", ".join(f"{e['transport']} {e['operation']} {e['mode']}" for e in missing)
            reads_note = f"Groups without numeric reads (chart shows unavailable): {names}."
        else:
            reads_note = "Route-plan read counts are available for every measured group."

    lines = [
        "# Routing latency report",
        "",
        "## Method",
        "Direct latency measurement. Each sample wraps one complete API request with",
        "time.perf_counter(): an in-process REST POST via httpx.ASGITransport or an",
        "in-process MCP server.call_tool call. Route-plan reads count foreground",
        "SELECT statements observed on the repository engine during the request.",
        "Telemetry and provider writes are INSERTs, so SELECTs isolate the plan.",
        "",
        "## Harness",
        "In-process harness, NOT network latency. REST uses httpx.ASGITransport",
        "against the FastAPI app; MCP uses create_server plus server.call_tool.",
        "Wall times exclude TCP/TLS/HTTP wire cost and must not be read as",
        "production network latency.",
        "",
        "## Commit",
        commit,
        "",
        "## Environment",
        f"- python: {sys.version.replace(chr(10), ' ')}",
        f"- platform: {platform.platform()}",
        f"- sqlite: {sqlite3.sqlite_version}",
        "",
        "## Request mixes",
        "| transport | operation | routing_mode | providers | payload |",
        "|---|---|---|---|---|",
    ]
    payloads = {
        ("rest-inprocess", "search", "require", "exa"): (
            'POST /search {"query", "routing": {"mode": "require", "providers": ["exa"]}}'
        ),
        ("rest-inprocess", "search", "auto", "all"): 'POST /search {"query"}',
        ("rest-inprocess", "search", "fanout", "exa+tavily"): (
            'POST /search {"query", "fanout": true, "routing": {"mode": "fanout", '
            '"providers": ["exa", "tavily"]}}'
        ),
        ("mcp-inprocess", "search", "require", "exa"): (
            'call_tool search {"query", "routing": {"mode": "require", "providers": ["exa"]}}'
        ),
        ("mcp-inprocess", "search", "auto", "all"): 'call_tool search {"query"}',
        ("mcp-inprocess", "search", "fanout", "exa+tavily"): (
            'call_tool search {"query", "fanout": true, "routing": {"mode": "fanout", '
            '"providers": ["exa", "tavily"]}}'
        ),
        ("mcp-inprocess", "fetch", "require", "exa"): (
            'call_tool fetch {"url", "routing": {"mode": "require", "providers": ["exa"]}}'
        ),
        ("mcp-inprocess", "fetch", "auto", "all"): 'call_tool fetch {"url"}',
    }
    for transport, operation, mode, providers in _MIX_ORDER:
        lines.append(
            f"| {transport} | {operation} | {mode} | {providers} | "
            f"{payloads[(transport, operation, mode, providers)]} |"
        )
    lines += [
        "",
        "## Cache preparation",
        "Before each mix both caches are cleared (clear_config_cache and",
        "clear_quota_poll_cache); one cold probe runs first (cache_state cold).",
        "Then each of the seven providers is pre-warmed via",
        "effective_config_for_name plus routing_policy; ten warmup rows follow",
        "(cache_state warm, phase warmup); thirty measured rows follow",
        "(cache_state warm, phase measured). After every request the tasks in",
        "_BACKGROUND_TASKS are drained so samples stay serial and isolated.",
        "",
        "## Fixtures and policy",
        "- Real temporary SQLiteRepository per test function, seeded per provider",
        "  with AUTHORITATIVE remaining 10 / limit 10 quota and HEALTHY status.",
        "- Seven offline stub adapters (quota() returns None so no poll delay;",
        "  health UNKNOWN). adapter_mode is offline for every row.",
        "- Default routing policy; concurrency is serial on one event loop.",
        "",
        "## Sample counts",
        f"- cold probes: {len(cold)} (one per mix)",
        f"- warmup rows: {len(warmup)} (ten per mix)",
        f"- measured rows: {len(measured)} (thirty per mix)",
        f"- total data rows: {len(rows)}",
        "",
        "## Measured results",
        "Statistics cover successful (status ok) measured rows only; failures are",
        "counted separately.",
        "| mix | measured | failures | median ms | p95 ms | max ms | median reads |",
        "|---|---|---|---|---|---|---|",
    ]
    for entry in table:
        reads_cell = (
            f"{entry['median_reads']:.3f}" if entry["median_reads"] is not None else ("unavailable")
        )
        lines.append(
            f"| {entry['transport']} {entry['operation']} {entry['mode']} "
            f"{entry['providers']} | {entry['n']} | {entry['failures']} | "
            f"{entry['median_ms']:.3f} | {entry['p95_ms']:.3f} | "
            f"{entry['max_ms']:.3f} | {reads_cell} |"
        )
    lines += [
        "",
        "## Percentile method",
        "Median is the 50th percentile; p95 is the 95th percentile. Percentiles",
        "use linear interpolation between closest ranks: rank = (n - 1) * p, then",
        "value = lower + (upper - lower) * fraction. Single-sample groups use the",
        "sample; empty groups report 0.0.",
        "",
        "## Reproduction",
        f"`{_REPRO_COMMAND}`",
        "",
        "## Limitations",
        "- Expired-TTL probes were not collected in this run.",
        "- trace_id is empty: the in-process harness has no distributed trace.",
        "- In-process wall time is not network latency.",
        "- No before/after speedup is claimed from these samples.",
        f"- {reads_note}",
        "",
        "## Charts",
        "![API wall time](routing_latency_wall_time.png)",
        "![Route-plan reads](routing_latency_route_reads.png)",
        "",
    ]
    md_path.write_text("\n".join(lines), encoding="utf-8")


def _assert_report(rows: Sequence[dict[str, Any]], output_dir: Path) -> None:
    """Shared report assertions: structure per mix, positive walls, artifacts."""
    csv_path = output_dir / "routing_latency.csv"
    md_path = output_dir / "routing_latency.md"
    wall_png = output_dir / "routing_latency_wall_time.png"
    reads_png = output_dir / "routing_latency_route_reads.png"
    assert csv_path.exists()
    with open(csv_path, newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        assert reader.fieldnames == list(_CSV_COLUMNS)
        data_rows = list(reader)
    assert len(data_rows) == len(rows)
    if len(rows) == _EXPECTED_TOTAL_ROWS:
        assert len(data_rows) == 328
    for key in {_mix_key(row) for row in rows}:
        subset = [row for row in data_rows if _mix_key(row) == key]
        assert sum(1 for row in subset if row["phase"] == "cold") == 1
        assert sum(1 for row in subset if row["phase"] == "warmup") == _WARMUP_PER_MIX
        assert sum(1 for row in subset if row["phase"] == "measured") == _MEASURED_PER_MIX
    measured = [row for row in data_rows if row["phase"] == "measured"]
    assert measured
    for row in measured:
        assert float(row["wall_time_ms"]) > 0
    md_text = md_path.read_text(encoding="utf-8")
    assert "![API wall time](routing_latency_wall_time.png)" in md_text
    assert "![Route-plan reads](routing_latency_route_reads.png)" in md_text
    assert wall_png.exists() and wall_png.stat().st_size > 0
    assert reads_png.exists() and reads_png.stat().st_size > 0


@pytest.fixture(scope="session")
def latency_rows() -> list[dict[str, Any]]:
    """Session-owned sample collection shared by the three latency tests."""
    return []


async def test_rest_search_latency(tmp_path: Path, latency_rows: list[dict[str, Any]]) -> None:
    clear_config_cache()
    clear_quota_poll_cache()
    repository = await SQLiteRepository.open(tmp_path / "rest-latency.db")
    selects: list[int] = [0]
    detach: Callable[[], None] | None = None
    try:
        await _seed_repository(repository)
        detach = _attach_select_counter(repository, selects)
        measured_selects = selects if detach is not None else None
        adapters = [_OfflineAdapter(name) for name in SEVEN_PROVIDERS]
        app = create_app(adapters, repository=repository)
        commit = _git_commit()
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:

            async def _require_search() -> None:
                response = await client.post("/search", json=_search_payload("require", ["exa"]))
                response.raise_for_status()

            async def _auto_search() -> None:
                response = await client.post("/search", json=_search_payload("auto", None))
                response.raise_for_status()

            async def _fanout_search() -> None:
                response = await client.post(
                    "/search",
                    json=_search_payload("fanout", ["exa", "tavily"], fanout=True),
                )
                response.raise_for_status()

            await _run_mix(
                latency_rows,
                commit=commit,
                transport="rest-inprocess",
                operation="search",
                routing_mode="require",
                providers="exa",
                repository=repository,
                selects=measured_selects,
                call=_require_search,
            )
            await _run_mix(
                latency_rows,
                commit=commit,
                transport="rest-inprocess",
                operation="search",
                routing_mode="auto",
                providers="all",
                repository=repository,
                selects=measured_selects,
                call=_auto_search,
            )
            await _run_mix(
                latency_rows,
                commit=commit,
                transport="rest-inprocess",
                operation="search",
                routing_mode="fanout",
                providers="exa+tavily",
                repository=repository,
                selects=measured_selects,
                call=_fanout_search,
            )
        _write_latency_report(latency_rows, _default_output_dir())
        _assert_report(latency_rows, _default_output_dir())
    finally:
        if detach is not None:
            detach()
        await _drain_background_tasks()
        clear_config_cache()
        clear_quota_poll_cache()
        await repository.close()


async def test_mcp_search_latency(tmp_path: Path, latency_rows: list[dict[str, Any]]) -> None:
    clear_config_cache()
    clear_quota_poll_cache()
    repository = await SQLiteRepository.open(tmp_path / "mcp-search-latency.db")
    selects: list[int] = [0]
    detach: Callable[[], None] | None = None
    try:
        await _seed_repository(repository)
        detach = _attach_select_counter(repository, selects)
        measured_selects = selects if detach is not None else None
        adapters = [_OfflineAdapter(name) for name in SEVEN_PROVIDERS]
        server = create_server(adapters, repository=repository)
        commit = _git_commit()

        async def _require_search() -> None:
            await server.call_tool("search", {"request": _search_payload("require", ["exa"])})

        async def _auto_search() -> None:
            await server.call_tool("search", {"request": _search_payload("auto", None)})

        async def _fanout_search() -> None:
            await server.call_tool(
                "search",
                {"request": _search_payload("fanout", ["exa", "tavily"], fanout=True)},
            )

        await _run_mix(
            latency_rows,
            commit=commit,
            transport="mcp-inprocess",
            operation="search",
            routing_mode="require",
            providers="exa",
            repository=repository,
            selects=measured_selects,
            call=_require_search,
        )
        await _run_mix(
            latency_rows,
            commit=commit,
            transport="mcp-inprocess",
            operation="search",
            routing_mode="auto",
            providers="all",
            repository=repository,
            selects=measured_selects,
            call=_auto_search,
        )
        await _run_mix(
            latency_rows,
            commit=commit,
            transport="mcp-inprocess",
            operation="search",
            routing_mode="fanout",
            providers="exa+tavily",
            repository=repository,
            selects=measured_selects,
            call=_fanout_search,
        )
        _write_latency_report(latency_rows, _default_output_dir())
        _assert_report(latency_rows, _default_output_dir())
    finally:
        if detach is not None:
            detach()
        await _drain_background_tasks()
        clear_config_cache()
        clear_quota_poll_cache()
        await repository.close()


async def test_mcp_fetch_latency(tmp_path: Path, latency_rows: list[dict[str, Any]]) -> None:
    clear_config_cache()
    clear_quota_poll_cache()
    repository = await SQLiteRepository.open(tmp_path / "mcp-fetch-latency.db")
    selects: list[int] = [0]
    detach: Callable[[], None] | None = None
    try:
        await _seed_repository(repository)
        detach = _attach_select_counter(repository, selects)
        measured_selects = selects if detach is not None else None
        adapters = [_OfflineAdapter(name) for name in SEVEN_PROVIDERS]
        server = create_server(adapters, repository=repository)
        commit = _git_commit()

        async def _require_fetch() -> None:
            await server.call_tool("fetch", {"request": _fetch_payload("require", ["exa"])})

        async def _auto_fetch() -> None:
            await server.call_tool("fetch", {"request": _fetch_payload("auto", None)})

        await _run_mix(
            latency_rows,
            commit=commit,
            transport="mcp-inprocess",
            operation="fetch",
            routing_mode="require",
            providers="exa",
            repository=repository,
            selects=measured_selects,
            call=_require_fetch,
        )
        await _run_mix(
            latency_rows,
            commit=commit,
            transport="mcp-inprocess",
            operation="fetch",
            routing_mode="auto",
            providers="all",
            repository=repository,
            selects=measured_selects,
            call=_auto_fetch,
        )
        _write_latency_report(latency_rows, _default_output_dir())
        _assert_report(latency_rows, _default_output_dir())
    finally:
        if detach is not None:
            detach()
        await _drain_background_tasks()
        clear_config_cache()
        clear_quota_poll_cache()
        await repository.close()
