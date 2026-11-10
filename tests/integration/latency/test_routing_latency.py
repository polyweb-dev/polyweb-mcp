"""Direct routing-latency measurements over in-process REST and MCP APIs.

Harness: REST mixes drive the FastAPI app through ``httpx.ASGITransport``
(in-process, not network); MCP mixes call ``server.call_tool`` in-process.
A real temporary SQLite repository and seven offline stub adapters back
every mix. Each request records wall time via ``time.perf_counter()`` and
a foreground SELECT count. Reports land in repo-root ``test_reports/a2-takeover/latency/``.

The offline adapter, payloads, seeding, cache warming, draining, SELECT
counter, and percentile method are shared with the Behave routing-latency
scenarios through :mod:`tests.fixtures.latency`.
"""

from __future__ import annotations

import csv
import platform
import sqlite3
import sys
import time
from collections.abc import Awaitable, Callable, Mapping, Sequence
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx
import pytest
from pydantic import SecretStr

from polyweb.configuration.config import get_settings
from polyweb.infrastructure.encrypted_store import EncryptedDbSecretStore, load_secret_codec
from polyweb.mcp.server import create_server
from polyweb.persistence.storage import SQLiteRepository
from polyweb.routers.api import create_app
from polyweb.services.monitoring import clear_quota_poll_cache
from polyweb.services.provider_runtime import clear_config_cache
from tests.fixtures.api_keys import mcp_project_key
from tests.fixtures.auth import TEMP_PASSWORD, temp_email
from tests.fixtures.execution import (
    install_adapter_map,
    seed_member_project,
)
from tests.fixtures.latency import (
    REPO_ROOT,
    OfflineAdapter,
    attach_select_counter,
    drain_background_tasks,
    fetch_payload,
    git_commit,
    percentile,
    search_payload,
    seed_latency_pools,
    seed_repository,
    warm_route_caches,
)
from tests.fixtures.latency_servers import ProviderClock, lift_repository_rate_windows

SEVEN_PROVIDERS = ["exa", "firecrawl", "tavily", "parallel", "you", "brave", "keenable"]

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
    "provider_time_ms",
    "added_time_ms",
    "provider_calls",
    "route_plan_reads",
    "trace_id",
    "status",
    "error",
)

_WARMUP_PER_MIX = 10
_MEASURED_PER_MIX = 30
_EXPECTED_TOTAL_ROWS = 410  # 10 mixes x (1 cold + 10 warmup + 30 measured)

_MIX_ORDER: tuple[tuple[str, str, str, str], ...] = (
    ("rest-inprocess", "search", "require", "exa"),
    ("rest-inprocess", "search", "auto", "all"),
    ("rest-inprocess", "search", "fanout", "exa+tavily"),
    ("rest-inprocess", "fetch", "require", "exa"),
    ("rest-inprocess", "fetch", "auto", "all"),
    ("mcp-inprocess", "search", "require", "exa"),
    ("mcp-inprocess", "search", "auto", "all"),
    ("mcp-inprocess", "search", "fanout", "exa+tavily"),
    ("mcp-inprocess", "fetch", "require", "exa"),
    ("mcp-inprocess", "fetch", "auto", "all"),
)

_REPRO_COMMAND = "uv run --with matplotlib pytest tests/integration/latency -q -rs"

_READS_UNAVAILABLE_REASONS: list[str] = []
_PROVIDER_CLOCK = ProviderClock()


def _latency_store(repository: SQLiteRepository) -> EncryptedDbSecretStore:
    """Return the encrypted runtime store both transports build for this database."""

    return EncryptedDbSecretStore(repository, load_secret_codec(get_settings()))


async def _bind_seven_providers(
    repository: SQLiteRepository,
    store: EncryptedDbSecretStore,
    monkeypatch: pytest.MonkeyPatch,
    adapters: Sequence[Any],
    *,
    project_id: Any,
    actor_id: Any,
) -> None:
    """Assign owned provider pools for all seven keyed fakes.

    Without bindings every sample is a fast 503, so the mix would measure the
    refusal path instead of routing.
    """

    secrets: dict[str, str] = {}
    for adapter in adapters:
        _PROVIDER_CLOCK.instrument(adapter)
    install_adapter_map(monkeypatch, adapters, secrets=secrets)
    await seed_latency_pools(
        repository,
        project_id=project_id,
        actor_id=actor_id,
        store=store,
        providers=tuple(SEVEN_PROVIDERS),
        secrets=secrets,
    )


def _assert_measured_samples_succeeded(
    rows: Sequence[dict[str, Any]], *, transport: str, operation: str
) -> None:
    """Every measured sample of these mixes must be a real, successful request."""

    failures = [
        (row["routing_mode"], row["status"], row["error"])
        for row in rows
        if row["transport"] == transport
        and row["operation"] == operation
        and row["phase"] == "measured"
        and row["status"] != "ok"
    ]
    assert failures == [], f"latency samples measured failures, not routing: {failures[:3]}"


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
    _PROVIDER_CLOCK.reset()
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
    provider_ms, provider_calls = _PROVIDER_CLOCK.snapshot()
    reads: int | str = selects[0] if selects is not None else ""
    await drain_background_tasks()
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
            "provider_time_ms": f"{provider_ms:.6f}",
            "added_time_ms": f"{elapsed_ms - provider_ms:.6f}",
            "provider_calls": provider_calls,
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
    await warm_route_caches(repository, SEVEN_PROVIDERS)
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


def _write_latency_report(rows: Sequence[dict[str, Any]], output_dir: Path) -> bool:
    """Write routing_latency.csv, routing_latency.md, and PNG charts when possible.

    The numeric report (CSV + Markdown + gate inputs) always runs. The PNG
    charts need matplotlib, which the CI image may not install: when the
    import is unavailable the report is written without chart embeds and this
    returns False instead of skipping the benchmark. Returns True when both
    charts were written.
    """
    resolved = Path(output_dir)
    if not resolved.is_absolute():
        resolved = REPO_ROOT / resolved
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
    commit = str(rows[0].get("commit")) if rows else git_commit()

    table: list[dict[str, Any]] = []
    for transport, operation, mode, providers in _MIX_ORDER:
        group = [r for r in measured if _mix_key(r) == (transport, operation, mode, providers)]
        ok_rows = [r for r in group if r.get("status") == "ok"]
        walls = sorted(_wall_value(r) for r in ok_rows)
        provider_times = sorted(float(r["provider_time_ms"]) for r in ok_rows)
        added_times = sorted(float(r["added_time_ms"]) for r in ok_rows)
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
                "median_ms": percentile(walls, 50.0),
                "p95_ms": percentile(walls, 95.0),
                "provider_p95_ms": percentile(provider_times, 95.0),
                "added_p95_ms": percentile(added_times, 95.0),
                "max_ms": max(walls) if walls else 0.0,
                "median_reads": percentile(reads, 50.0) if reads else None,
            }
        )

    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        plotted = False
    else:
        plotted = True

    labels = [
        _group_label(e["transport"], e["operation"], e["mode"], e["providers"]) for e in table
    ]

    if plotted:
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
        "in-process MCP server.call_tool call. The legacy route_plan_reads field",
        "counts all SELECTs on the repository engine during the request window.",
        "Each adapter instance uses ProviderClock around search/fetch. Each row",
        "records its summed fake-provider duration and added_time_ms = wall_time_ms",
        "minus provider_time_ms. Added p95 uses the per-request differences, not",
        "a difference between percentiles. Fanout sums both fake calls.",
        "These counts include authorization, binding, and capacity reads. Any",
        "background SELECT during that window also contributes. They are a",
        "diagnostic, not a pure route-planner count or a pass/fail limit.",
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
        ("rest-inprocess", "fetch", "require", "exa"): (
            'POST /fetch {"url", "routing": {"mode": "require", "providers": ["exa"]}}'
        ),
        ("rest-inprocess", "fetch", "auto", "all"): 'POST /fetch {"url"}',
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
        "| mix | measured | failures | median total ms | total p95 ms | provider p95 ms | "
        "added p95 ms | max total ms | median reads |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for entry in table:
        reads_cell = (
            f"{entry['median_reads']:.3f}" if entry["median_reads"] is not None else ("unavailable")
        )
        lines.append(
            f"| {entry['transport']} {entry['operation']} {entry['mode']} "
            f"{entry['providers']} | {entry['n']} | {entry['failures']} | "
            f"{entry['median_ms']:.3f} | {entry['p95_ms']:.3f} | "
            f"{entry['provider_p95_ms']:.3f} | {entry['added_p95_ms']:.3f} | "
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
        "- The baseline is fake-adapter call time in the same request, not an earlier commit.",
        "- Added time includes the in-process client/tool stack outside the fake adapter.",
        "- The user deferred the 80 ms target. This measurement imposes no new ceiling.",
        "- No before/after speedup is claimed from these samples.",
        f"- {reads_note}",
        "",
        "## Charts",
    ]
    if plotted:
        lines += [
            "![API wall time](routing_latency_wall_time.png)",
            "![Route-plan reads](routing_latency_route_reads.png)",
            "",
        ]
    else:
        lines += [
            "Charts were not rendered: matplotlib is not installed in this environment.",
            "The CSV and the tables above carry the full numeric report; the gate",
            "inputs do not depend on the charts.",
            "",
        ]
    md_path.write_text(chr(10).join(lines), encoding="utf-8")
    return plotted


def _assert_report(rows: Sequence[dict[str, Any]], output_dir: Path, *, plotted: bool) -> None:
    """Shared report assertions: structure per mix, positive walls, artifacts.

    PNG chart artifacts are asserted only when the report writer produced
    them; a missing matplotlib must never fail the numeric benchmark.
    """
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
        assert len(data_rows) == 410
    for key in {_mix_key(row) for row in rows}:
        subset = [row for row in data_rows if _mix_key(row) == key]
        assert sum(1 for row in subset if row["phase"] == "cold") == 1
        assert sum(1 for row in subset if row["phase"] == "warmup") == _WARMUP_PER_MIX
        assert sum(1 for row in subset if row["phase"] == "measured") == _MEASURED_PER_MIX
    measured = [row for row in data_rows if row["phase"] == "measured"]
    assert measured
    for row in measured:
        assert float(row["wall_time_ms"]) > 0
        assert float(row["provider_time_ms"]) > 0
        assert int(row["provider_calls"]) == (2 if row["routing_mode"] == "fanout" else 1)
        assert float(row["added_time_ms"]) == pytest.approx(
            float(row["wall_time_ms"]) - float(row["provider_time_ms"]), abs=0.000002
        )
    md_text = md_path.read_text(encoding="utf-8")
    if plotted:
        assert "![API wall time](routing_latency_wall_time.png)" in md_text
        assert "![Route-plan reads](routing_latency_route_reads.png)" in md_text
        assert wall_png.exists() and wall_png.stat().st_size > 0
        assert reads_png.exists() and reads_png.stat().st_size > 0
    else:
        assert "Charts were not rendered" in md_text
        assert "![API wall time](routing_latency_wall_time.png)" not in md_text


@pytest.fixture(scope="session")
def latency_rows() -> list[dict[str, Any]]:
    """Session-owned sample collection shared by the four latency tests."""
    return []


async def test_rest_search_latency(
    tmp_path: Path,
    latency_rows: list[dict[str, Any]],
    auth_secret: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clear_config_cache()
    clear_quota_poll_cache()
    repository = await SQLiteRepository.open(tmp_path / "rest-latency.db")
    selects: list[int] = [0]
    detach: Callable[[], None] | None = None
    try:
        await seed_repository(repository, SEVEN_PROVIDERS)
        await lift_repository_rate_windows(repository, SEVEN_PROVIDERS)
        detach = attach_select_counter(repository, selects, _READS_UNAVAILABLE_REASONS)
        measured_selects = selects if detach is not None else None
        adapters = [OfflineAdapter(name) for name in SEVEN_PROVIDERS]
        store = _latency_store(repository)
        app = create_app(adapters, repository=repository, secret_store=store)
        commit = git_commit()
        transport = httpx.ASGITransport(app=app)
        # A2: the shared execution service is composed by the app lifespan;
        # without it every request fails closed with 503 before routing.
        async with (
            app.router.lifespan_context(app),
            httpx.AsyncClient(transport=transport, base_url="http://test") as client,
        ):
            email = temp_email("latency-rest")
            registered = await client.post(
                "/auth/register",
                json={
                    "email": email,
                    "password": TEMP_PASSWORD,
                    "username": f"tester-{uuid4().hex[:8]}",
                    "first_name": "Test",
                    "last_name": "User",
                },
            )
            assert registered.status_code == 201
            logged_in = await client.post(
                "/auth/jwt/login", data={"username": email, "password": TEMP_PASSWORD}
            )
            assert logged_in.status_code == 200
            headers = {"Authorization": f"Bearer {logged_in.json()['access_token']}"}
            project = await seed_member_project(repository, headers)
            pid = str(project.project_id)
            await _bind_seven_providers(
                repository,
                store,
                monkeypatch,
                adapters,
                project_id=project.project_id,
                actor_id=project.actor_id,
            )

            async def _require_search() -> None:
                response = await client.post(
                    "/search",
                    json=search_payload("require", ["exa"], project_id=pid),
                    headers=headers,
                )
                response.raise_for_status()

            async def _auto_search() -> None:
                response = await client.post(
                    "/search",
                    json=search_payload("auto", None, project_id=pid),
                    headers=headers,
                )
                response.raise_for_status()

            async def _fanout_search() -> None:
                response = await client.post(
                    "/search",
                    json=search_payload("fanout", ["exa", "tavily"], fanout=True, project_id=pid),
                    headers=headers,
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
        _assert_measured_samples_succeeded(
            latency_rows, transport="rest-inprocess", operation="search"
        )
        report_dir = REPO_ROOT / "test_reports" / "a2-takeover" / "latency"
        plotted = _write_latency_report(latency_rows, report_dir)
        _assert_report(latency_rows, report_dir, plotted=plotted)
    finally:
        if detach is not None:
            detach()
        await drain_background_tasks()
        clear_config_cache()
        clear_quota_poll_cache()
        await repository.close()


async def test_rest_fetch_latency(
    tmp_path: Path,
    latency_rows: list[dict[str, Any]],
    auth_secret: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clear_config_cache()
    clear_quota_poll_cache()
    repository = await SQLiteRepository.open(tmp_path / "rest-fetch-latency.db")
    selects: list[int] = [0]
    detach: Callable[[], None] | None = None
    try:
        await seed_repository(repository, SEVEN_PROVIDERS)
        await lift_repository_rate_windows(repository, SEVEN_PROVIDERS)
        detach = attach_select_counter(repository, selects, _READS_UNAVAILABLE_REASONS)
        measured_selects = selects if detach is not None else None
        adapters = [OfflineAdapter(name) for name in SEVEN_PROVIDERS]
        store = _latency_store(repository)
        app = create_app(adapters, repository=repository, secret_store=store)
        commit = git_commit()
        transport = httpx.ASGITransport(app=app)
        # A2: the shared execution service is composed by the app lifespan;
        # without it every request fails closed with 503 before routing.
        async with (
            app.router.lifespan_context(app),
            httpx.AsyncClient(transport=transport, base_url="http://test") as client,
        ):
            email = temp_email("latency-rest-fetch")
            registered = await client.post(
                "/auth/register",
                json={
                    "email": email,
                    "password": TEMP_PASSWORD,
                    "username": f"tester-{uuid4().hex[:8]}",
                    "first_name": "Test",
                    "last_name": "User",
                },
            )
            assert registered.status_code == 201
            logged_in = await client.post(
                "/auth/jwt/login", data={"username": email, "password": TEMP_PASSWORD}
            )
            assert logged_in.status_code == 200
            headers = {"Authorization": f"Bearer {logged_in.json()['access_token']}"}
            project = await seed_member_project(repository, headers)
            pid = str(project.project_id)
            await _bind_seven_providers(
                repository,
                store,
                monkeypatch,
                adapters,
                project_id=project.project_id,
                actor_id=project.actor_id,
            )

            async def _require_fetch() -> None:
                response = await client.post(
                    "/fetch",
                    headers=headers,
                    json=fetch_payload("require", ["exa"], project_id=pid),
                )
                response.raise_for_status()

            async def _auto_fetch() -> None:
                response = await client.post(
                    "/fetch", headers=headers, json=fetch_payload("auto", None, project_id=pid)
                )
                response.raise_for_status()

            for mode, providers, call in (
                ("require", "exa", _require_fetch),
                ("auto", "all", _auto_fetch),
            ):
                await _run_mix(
                    latency_rows,
                    commit=commit,
                    transport="rest-inprocess",
                    operation="fetch",
                    routing_mode=mode,
                    providers=providers,
                    repository=repository,
                    selects=measured_selects,
                    call=call,
                )
        _assert_measured_samples_succeeded(
            latency_rows, transport="rest-inprocess", operation="fetch"
        )
        report_dir = REPO_ROOT / "test_reports" / "a2-takeover" / "latency"
        plotted = _write_latency_report(latency_rows, report_dir)
        _assert_report(latency_rows, report_dir, plotted=plotted)
    finally:
        if detach is not None:
            detach()
        await drain_background_tasks()
        clear_config_cache()
        clear_quota_poll_cache()
        await repository.close()


async def test_mcp_search_latency(
    tmp_path: Path, latency_rows: list[dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    clear_config_cache()
    clear_quota_poll_cache()
    repository = await SQLiteRepository.open(tmp_path / "mcp-search-latency.db")
    selects: list[int] = [0]
    detach: Callable[[], None] | None = None
    try:
        await seed_repository(repository, SEVEN_PROVIDERS)
        await lift_repository_rate_windows(repository, SEVEN_PROVIDERS)
        detach = attach_select_counter(repository, selects, _READS_UNAVAILABLE_REASONS)
        measured_selects = selects if detach is not None else None
        adapters = [OfflineAdapter(name) for name in SEVEN_PROVIDERS]
        service, key = await mcp_project_key(repository, "latency-mcp")
        pid = str(key.project_id)
        await _bind_seven_providers(
            repository,
            _latency_store(repository),
            monkeypatch,
            adapters,
            project_id=key.project_id,
            actor_id=key.owner.id,
        )
        server = create_server(
            adapters,
            repository=repository,
            auth_service=service,
            stdio_token=SecretStr(key.raw),
        )
        commit = git_commit()

        async def _require_search() -> None:
            await server.call_tool(
                "search",
                {"request": search_payload("require", ["exa"], project_id=pid)},
            )

        async def _auto_search() -> None:
            await server.call_tool(
                "search", {"request": search_payload("auto", None, project_id=pid)}
            )

        async def _fanout_search() -> None:
            await server.call_tool(
                "search",
                {
                    "request": search_payload(
                        "fanout", ["exa", "tavily"], fanout=True, project_id=pid
                    )
                },
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
        _assert_measured_samples_succeeded(
            latency_rows, transport="mcp-inprocess", operation="search"
        )
        report_dir = REPO_ROOT / "test_reports" / "a2-takeover" / "latency"
        plotted = _write_latency_report(latency_rows, report_dir)
        _assert_report(latency_rows, report_dir, plotted=plotted)
    finally:
        if detach is not None:
            detach()
        await drain_background_tasks()
        clear_config_cache()
        clear_quota_poll_cache()
        await repository.close()


async def test_mcp_fetch_latency(
    tmp_path: Path, latency_rows: list[dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    clear_config_cache()
    clear_quota_poll_cache()
    repository = await SQLiteRepository.open(tmp_path / "mcp-fetch-latency.db")
    selects: list[int] = [0]
    detach: Callable[[], None] | None = None
    try:
        await seed_repository(repository, SEVEN_PROVIDERS)
        await lift_repository_rate_windows(repository, SEVEN_PROVIDERS)
        detach = attach_select_counter(repository, selects, _READS_UNAVAILABLE_REASONS)
        measured_selects = selects if detach is not None else None
        adapters = [OfflineAdapter(name) for name in SEVEN_PROVIDERS]
        service, key = await mcp_project_key(repository, "latency-mcp-fetch")
        pid = str(key.project_id)
        await _bind_seven_providers(
            repository,
            _latency_store(repository),
            monkeypatch,
            adapters,
            project_id=key.project_id,
            actor_id=key.owner.id,
        )
        server = create_server(
            adapters,
            repository=repository,
            auth_service=service,
            stdio_token=SecretStr(key.raw),
        )
        commit = git_commit()

        async def _require_fetch() -> None:
            await server.call_tool(
                "fetch",
                {"request": fetch_payload("require", ["exa"], project_id=pid)},
            )

        async def _auto_fetch() -> None:
            await server.call_tool(
                "fetch", {"request": fetch_payload("auto", None, project_id=pid)}
            )

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
        _assert_measured_samples_succeeded(
            latency_rows, transport="mcp-inprocess", operation="fetch"
        )
        report_dir = REPO_ROOT / "test_reports" / "a2-takeover" / "latency"
        plotted = _write_latency_report(latency_rows, report_dir)
        _assert_report(latency_rows, report_dir, plotted=plotted)
    finally:
        if detach is not None:
            detach()
        await drain_background_tasks()
        clear_config_cache()
        clear_quota_poll_cache()
        await repository.close()
