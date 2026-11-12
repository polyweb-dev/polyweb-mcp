"""A3 authority routing-latency gate (TASK-000045 DoD #4).

Polyweb must add under 150 ms at p95 per provider, end to end, over REST
and MCP, measured in-process exactly like the A2 routing-latency harness:
REST drives the FastAPI app through ``httpx.ASGITransport``, MCP mixes call
``server.call_tool`` in-process, offline instant adapters carry fake-provider
time (``ProviderClock``), and a real temporary SQLite repository stores the
seeded quota, bindings, and the shared pool the execution authority must
fence.

The added latency is ``wall_time_ms - provider_time_ms``. Every measured
sample must itself succeed; the report lands in ``test_reports/a3-authority/
latency/`` (CSV and Markdown; read counts are a diagnostic, not a limit).
"""

from __future__ import annotations

import csv
import platform
import sqlite3
import sys
import time
from collections.abc import Awaitable, Callable, Sequence
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

_WARMUP_PER_MIX = 10
_MEASURED_PER_MIX = 30

_MIXES: tuple[tuple[str, str, str, str], ...] = (
    ("rest-inprocess", "search", "require", "exa"),
    ("rest-inprocess", "search", "auto", "all"),
    ("rest-inprocess", "fetch", "require", "exa"),
    ("mcp-inprocess", "search", "require", "exa"),
    ("mcp-inprocess", "search", "auto", "all"),
    ("mcp-inprocess", "fetch", "require", "exa"),
)

_ADDED_P95_LIMIT_MS = 150.0

_REPORT_DIR = REPO_ROOT / "test_reports" / "a3-authority" / "latency"

_COLUMNS = (
    "commit",
    "transport",
    "operation",
    "routing_mode",
    "providers",
    "phase",
    "request_index",
    "wall_time_ms",
    "provider_time_ms",
    "added_time_ms",
    "provider_calls",
    "status",
    "error",
)

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
    """Assign owned pools with generous synthetic capacity to all seven fakes."""

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


async def _record_request(
    rows: list[dict[str, Any]],
    *,
    commit: str,
    transport: str,
    operation: str,
    routing_mode: str,
    providers: str,
    phase: str,
    request_index: int,
    call: Callable[[], Awaitable[Any]],
) -> None:
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
    await drain_background_tasks()
    rows.append(
        {
            "commit": commit,
            "transport": transport,
            "operation": operation,
            "routing_mode": routing_mode,
            "providers": providers,
            "phase": phase,
            "request_index": request_index,
            "wall_time_ms": f"{elapsed_ms:.6f}",
            "provider_time_ms": f"{provider_ms:.6f}",
            "added_time_ms": f"{elapsed_ms - provider_ms:.6f}",
            "provider_calls": provider_calls,
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
    call: Callable[[], Awaitable[Any]],
    db_reads: list[dict[str, Any]] | None = None,
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
        phase="cold",
        request_index=0,
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
            phase="warmup",
            request_index=index,
            call=call,
        )
    selects: list[int] = [0]
    detach = attach_select_counter(repository, selects)
    try:
        for index in range(_MEASURED_PER_MIX):
            await _record_request(
                rows,
                commit=commit,
                transport=transport,
                operation=operation,
                routing_mode=routing_mode,
                providers=providers,
                phase="measured",
                request_index=index,
                call=call,
            )
    finally:
        if detach is not None:
            detach()
    if db_reads is not None:
        measured_reads = selects[0] if detach is not None else None
        db_reads.append(
            {
                "transport": transport,
                "operation": operation,
                "routing_mode": routing_mode,
                "providers": providers,
                "samples": _MEASURED_PER_MIX,
                "foreground_selects": measured_reads,
                "selects_per_request": (
                    round(measured_reads / _MEASURED_PER_MIX, 2)
                    if measured_reads is not None
                    else None
                ),
                "counter_available": detach is not None,
            }
        )


def _write_db_reads_report(db_reads: Sequence[dict[str, Any]]) -> None:
    """Write engine SELECTs per measured mix, including background reads (no gate)."""

    csv_path = _REPORT_DIR / "db_reads.csv"
    md_path = _REPORT_DIR / "db_reads.md"
    with open(csv_path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "transport",
                "operation",
                "routing_mode",
                "providers",
                "samples",
                "foreground_selects",
                "selects_per_request",
                "counter_available",
            ],
        )
        writer.writeheader()
        for row in db_reads:
            writer.writerow(row)
    lines = [
        "# A3 authority engine SELECT diagnostic",
        "",
        "Engine SELECT statements on the shared repository engine, counted with",
        "the existing `attach_select_counter` seam during the measured loop only",
        f"({_MEASURED_PER_MIX} requests per mix). Cold requests, cache warming, and warmup",
        "requests are excluded. Counts include authorization,",
        "binding, credential, pool, allocation, order, settings, health, usage,",
        "and quota reads plus any background SELECT inside the mix window. They",
        "are a diagnostic, not a pass/fail limit: no threshold applies.",
        "The legacy CSV column `foreground_selects` includes those background reads.",
        "An unavailable counter leaves the SELECT count and per-request average blank.",
        "",
        "| transport | operation | routing | providers | samples | selects | each | counter |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for row in db_reads:
        reads_cell = "" if row["foreground_selects"] is None else str(row["foreground_selects"])
        each_cell = "" if row["selects_per_request"] is None else str(row["selects_per_request"])
        lines.append(
            f"| {row['transport']} | {row['operation']} | {row['routing_mode']} | "
            f"{row['providers']} | {row['samples']} | {reads_cell} | "
            f"{each_cell} | "
            f"{'available' if row['counter_available'] else 'unavailable'} |"
        )
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _assert_mixes_routed(
    rows: Sequence[dict[str, Any]],
) -> None:
    """Every measured sample of every mix must be a real, successful request."""

    failures = [
        (row["transport"], row["operation"], row["status"], row["error"])
        for row in rows
        if row["phase"] == "measured" and row["status"] != "ok"
    ]
    assert failures == [], f"latency samples measured failures, not routing: {failures[:4]}"


_STATS: tuple[str, ...] = ("mean", "p50", "p90", "p95", "p99")


def _added_stats(
    rows: Sequence[dict[str, Any]],
) -> dict[tuple[str, str, str, str], dict[str, float]]:
    """Return mean and percentiles of the added time per measured mix."""

    table: dict[tuple[str, str, str, str], dict[str, float]] = {}
    for transport, operation, routing_mode, providers in _MIXES:
        added = sorted(
            float(row["added_time_ms"])
            for row in rows
            if row["phase"] == "measured"
            and row["transport"] == transport
            and row["operation"] == operation
            and row["routing_mode"] == routing_mode
            and row["providers"] == providers
            and row["status"] == "ok"
        )
        table[(transport, operation, routing_mode, providers)] = {
            "mean": sum(added) / len(added) if added else 0.0,
            "p50": percentile(added, 50.0),
            "p90": percentile(added, 90.0),
            "p95": percentile(added, 95.0),
            "p99": percentile(added, 99.0),
        }
    return table


def _assert_added_p95_under_limit(
    table: dict[tuple[str, str, str, str], dict[str, float]],
) -> None:
    """The DoD gate is the added p95 per mix."""

    for (transport, operation, routing_mode, providers), stats in table.items():
        assert stats["p95"] < _ADDED_P95_LIMIT_MS, (
            f"{transport} {operation} {routing_mode} {providers}: added p95 "
            f"{stats['p95']:.3f} ms exceeds the {_ADDED_P95_LIMIT_MS:.0f} ms DoD gate"
        )


def _write_report(
    rows: Sequence[dict[str, Any]],
    table: dict[tuple[str, str, str, str], dict[str, float]],
) -> None:
    """Write the CSV and Markdown artifacts of this run."""
    _REPORT_DIR.mkdir(parents=True, exist_ok=True)
    csv_path = _REPORT_DIR / "routing_latency.csv"
    md_path = _REPORT_DIR / "routing_latency.md"
    with open(csv_path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(_COLUMNS))
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {key: ("" if row.get(key) is None else row.get(key)) for key in _COLUMNS}
            )
    commit = str(rows[0].get("commit")) if rows else git_commit()
    lines = [
        "# A3 authority routing-latency report",
        "",
        f"- commit: {commit}",
        f"- python: {sys.version.splitlines()[0]}",
        f"- platform: {platform.platform()}",
        f"- sqlite: {sqlite3.sqlite_version}",
        "",
        "Added time per measured mix (wall time minus fake-provider time);",
        "the gate applies to p95:",
        "",
        "| transport | operation | routing | providers | "
        + " | ".join(f"added {stat} ms" for stat in _STATS)
        + " | p95 gate |",
        "|---|---|---|---|" + "---|" * len(_STATS) + "---|",
    ]
    for transport, operation, mode, providers in _MIXES:
        stats = table[(transport, operation, mode, providers)]
        lines.append(
            f"| {transport} | {operation} | {mode} | {providers} | "
            + " | ".join(f"{stats[stat]:.3f}" for stat in _STATS)
            + f" | {_ADDED_P95_LIMIT_MS:.1f} |"
        )
    lines += [
        "",
        "In-process harness (httpx.ASGITransport / server.call_tool); wall",
        "times exclude network wire cost. Read counts are a diagnostic, not a",
        "pass/fail limit. Fake adapters and a temporary database only.",
    ]
    md_path.write_text("\n".join(lines), encoding="utf-8")


async def test_a3_rest_and_mcp_authority_latency(
    tmp_path: Path, auth_secret: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    del auth_secret
    clear_config_cache()
    clear_quota_poll_cache()
    repository = await SQLiteRepository.open(tmp_path / "a3-authority-latency.db")
    rows: list[dict[str, Any]] = []
    adapters = [OfflineAdapter(name) for name in SEVEN_PROVIDERS]
    try:
        await seed_repository(repository, SEVEN_PROVIDERS)
        await lift_repository_rate_windows(repository, SEVEN_PROVIDERS)
        store = _latency_store(repository)
        app = create_app(adapters, repository=repository, secret_store=store)
        commit = git_commit()
        transport = httpx.ASGITransport(app=app)
        # The shared execution service is composed by the app lifespan; the
        # A3 authority fence and pool admission ride that composition.
        async with (
            app.router.lifespan_context(app),
            httpx.AsyncClient(transport=transport, base_url="http://test") as client,
        ):
            email = temp_email("a3-latency")
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

            async def rest_search_require() -> None:
                response = await client.post(
                    "/search",
                    json=search_payload("require", ["exa"], project_id=pid),
                    headers=headers,
                )
                response.raise_for_status()

            async def rest_search_auto() -> None:
                response = await client.post(
                    "/search",
                    json=search_payload("auto", None, project_id=pid),
                    headers=headers,
                )
                response.raise_for_status()

            async def rest_fetch_require() -> None:
                response = await client.post(
                    "/fetch",
                    headers=headers,
                    json=fetch_payload("require", ["exa"], project_id=pid),
                )
                response.raise_for_status()

            rest_calls = {
                ("search", "require"): rest_search_require,
                ("search", "auto"): rest_search_auto,
                ("fetch", "require"): rest_fetch_require,
            }
            db_reads: list[dict[str, Any]] = []

            # REST mixes run against the live app.
            for transport_name, operation, mode, providers in _MIXES:
                if transport_name != "rest-inprocess":
                    continue
                await _run_mix(
                    rows,
                    commit=commit,
                    transport=transport_name,
                    operation=operation,
                    routing_mode=mode,
                    providers=providers,
                    repository=repository,
                    call=rest_calls[(operation, mode)],
                    db_reads=db_reads,
                )

        # MCP mixes run against a separate stdio composition of the same DB.
        service, key = await mcp_project_key(repository, "a3-latency-mcp")
        pid_mcp = str(key.project_id)
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

        async def mcp_search_require() -> None:
            await server.call_tool(
                "search",
                {"request": search_payload("require", ["exa"], project_id=pid_mcp)},
            )

        async def mcp_search_auto() -> None:
            await server.call_tool(
                "search", {"request": search_payload("auto", None, project_id=pid_mcp)}
            )

        async def mcp_fetch_require() -> None:
            await server.call_tool(
                "fetch",
                {"request": fetch_payload("require", ["exa"], project_id=pid_mcp)},
            )

        for transport_name, operation, mode, providers in _MIXES:
            if transport_name != "mcp-inprocess":
                continue
            if operation == "search" and mode == "require":
                call_mcp: Callable[[], Awaitable[Any]] = mcp_search_require
            elif operation == "search":
                call_mcp = mcp_search_auto
            else:
                call_mcp = mcp_fetch_require
            await _run_mix(
                rows,
                commit=commit,
                transport=transport_name,
                operation=operation,
                routing_mode=mode,
                providers=providers,
                repository=repository,
                call=call_mcp,
                db_reads=db_reads,
            )

        _assert_mixes_routed(rows)
        table = _added_stats(rows)
        _write_report(rows, table)
        _write_db_reads_report(db_reads)
        assert (_REPORT_DIR / "routing_latency.csv").exists()
        assert (_REPORT_DIR / "routing_latency.md").exists()
        assert (_REPORT_DIR / "db_reads.csv").exists()
        assert (_REPORT_DIR / "db_reads.md").exists()
        _assert_added_p95_under_limit(table)
    finally:
        await drain_background_tasks()
        clear_config_cache()
        clear_quota_poll_cache()
        await repository.close()
