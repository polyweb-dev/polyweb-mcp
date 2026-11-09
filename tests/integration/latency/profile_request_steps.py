"""Per-step and per-query latency profile of one provider-executing request.

Measurement only. It drives the real FastAPI app in-process, records every SQL
statement's duration from SQLAlchemy's cursor events, and reads back the app's
own persisted span durations (``trace_spans``) for the same request. Nothing
under ``src/polyweb`` is modified, monkeypatched, or re-implemented.

Two windows are reported, and they differ on purpose:

* ``wall`` — the client-visible call. It includes the bounded post-response
  trace flush that the ASGI app awaits before its callable returns.
* ``root`` — the app's own ``POST /search`` span, opened after the auth guard
  and closed when the final body byte is handed to the server. With uvicorn
  this is the ``server_ms`` the latency reports gate on.

Span durations are integer milliseconds, so a stage below 1 ms reads as 0 or 1;
the SQL figures are microseconds and carry the fine detail.

Usage::

    uv run python -m tests.integration.latency.profile_request_steps
    uv run python -m tests.integration.latency.profile_request_steps --mode fanout \\
        --providers exa,tavily
    uv run python -m tests.integration.latency.profile_request_steps --no-lifespan
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import os
import re
import tempfile
import threading
import time
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import event as sa_event
from sqlalchemy import text as sa_text

from polyweb.configuration.config import get_settings
from polyweb.models.observability import TraceSpanName
from polyweb.persistence.storage import SQLiteRepository
from polyweb.routers.api import create_app
from polyweb.routers.control import clear_config_cache
from polyweb.services.monitoring import clear_quota_poll_cache
from polyweb.services.provider_limits import ProviderLimitsService
from tests.fixtures.auth import TEMP_PASSWORD, temp_email
from tests.fixtures.execution import seed_member_project
from tests.fixtures.latency import (
    OfflineAdapter,
    drain_background_tasks,
    percentile,
    search_payload,
    seed_repository,
    warm_route_caches,
)
from tests.fixtures.latency_servers import lift_rate_windows

PROVIDERS: tuple[str, ...] = (
    "exa",
    "firecrawl",
    "tavily",
    "parallel",
    "you",
    "brave",
    "keenable",
)
ROOT_SPAN = "POST /search"
STAGE_ORDER: tuple[str, ...] = (
    ROOT_SPAN,
    TraceSpanName.ROUTE,
    TraceSpanName.PROVIDER,
    TraceSpanName.PROVIDER_HTTP,
    TraceSpanName.PROVIDER_PARSE,
    TraceSpanName.RESULTS,
    TraceSpanName.RESPONSE,
)
_WRITE_VERBS = frozenset({"INSERT", "UPDATE", "DELETE"})
_JWT_ENV = "POLYWEB_AUTH_JWT_SECRET"


# --------------------------------------------------------------------------- samples


@dataclass(frozen=True)
class QuerySample:
    """One executed SQL statement and how long the driver spent on it."""

    key: str
    verb: str
    duration_us: float


@dataclass
class RequestSample:
    """One request: its client wall time, statement time, and span durations."""

    wall_ms: float
    queries: list[QuerySample]
    spans: dict[str, list[int]] = field(default_factory=dict)

    @property
    def query_total_us(self) -> float:
        return sum(sample.duration_us for sample in self.queries)

    @property
    def write_count(self) -> int:
        return sum(1 for sample in self.queries if sample.verb in _WRITE_VERBS)

    @property
    def read_count(self) -> int:
        return len(self.queries) - self.write_count


def _median(values: Sequence[float]) -> float:
    return percentile(sorted(values), 50.0) if values else 0.0


def _p95(values: Sequence[float]) -> float:
    return percentile(sorted(values), 95.0) if values else 0.0


# ------------------------------------------------------------------ query recorder


def _query_key(statement: str) -> tuple[str, str]:
    """Return ``(verb, "VERB table")`` for one statement; table is best effort."""

    collapsed = " ".join(statement.split())
    verb = collapsed.split(" ", 1)[0].upper() if collapsed else "?"
    table = re.search(
        r"\b(?:FROM|INTO|UPDATE|JOIN)\s+([A-Za-z_][A-Za-z0-9_]*)", collapsed, re.IGNORECASE
    )
    name = table.group(1).lower() if table is not None else ""
    return verb, f"{verb} {name}".strip()


class QueryRecorder:
    """Record every cursor execution's duration through SQLAlchemy events.

    The listeners are attached from this script only; the application and its
    repositories are untouched. ``mark``/``since`` isolate one request even
    though the listeners stay attached for the whole run.
    """

    def __init__(self) -> None:
        self._samples: list[QuerySample] = []
        self._lock = threading.Lock()
        self._detach: list[Any] = []

    def attach(self, repository: SQLiteRepository) -> None:
        engine = getattr(getattr(repository, "_engine", None), "sync_engine", None)
        if engine is None:
            raise RuntimeError("the repository exposes no sync engine to listen on")

        def _before(
            conn: Any, cursor: Any, statement: str, params: Any, ctx: Any, many: Any
        ) -> None:
            conn.info["_profile_started_ns"] = time.perf_counter_ns()

        def _after(
            conn: Any, cursor: Any, statement: str, params: Any, ctx: Any, many: Any
        ) -> None:
            started = conn.info.pop("_profile_started_ns", None)
            if started is None:
                return
            verb, key = _query_key(statement)
            elapsed_us = (time.perf_counter_ns() - started) / 1000.0
            with self._lock:
                self._samples.append(QuerySample(key=key, verb=verb, duration_us=elapsed_us))

        sa_event.listen(engine, "before_cursor_execute", _before)
        sa_event.listen(engine, "after_cursor_execute", _after)
        self._detach = [
            lambda: sa_event.remove(engine, "before_cursor_execute", _before),
            lambda: sa_event.remove(engine, "after_cursor_execute", _after),
        ]

    def detach(self) -> None:
        for remove in self._detach:
            with contextlib.suppress(Exception):
                remove()
        self._detach = []

    def mark(self) -> int:
        with self._lock:
            return len(self._samples)

    def since(self, marker: int) -> list[QuerySample]:
        with self._lock:
            return list(self._samples[marker:])


# -------------------------------------------------------------------- span reader


async def _read_spans(repository: SQLiteRepository, trace_id: str) -> dict[str, list[int]]:
    """Return ``{span name: [duration_ms, ...]}`` for one trace, read from the DB."""

    statement = sa_text(
        "SELECT name, duration_ms FROM trace_spans WHERE trace_id = :trace_id ORDER BY started_at"
    )
    spans: dict[str, list[int]] = {}
    async with repository.session() as session:
        rows = (await session.execute(statement, {"trace_id": trace_id})).all()
    for name, duration_ms in rows:
        spans.setdefault(str(name), []).append(int(duration_ms))
    return spans


# ------------------------------------------------------------------------ driving


async def _exercise(
    repository: SQLiteRepository,
    recorder: QueryRecorder,
    *,
    mode: str,
    providers: Sequence[str],
    fanout: bool,
    samples: int,
    warmup: int,
    lifespan: bool,
) -> list[RequestSample]:
    """Run the cold, warmup, and measured requests and return measured samples."""

    adapters = [OfflineAdapter(name) for name in PROVIDERS]
    app = create_app(adapters, repository=repository)
    measured: list[RequestSample] = []

    async def _drive(client: httpx.AsyncClient, headers: dict[str, str], pid: str) -> None:
        payload = search_payload(mode, list(providers), fanout=fanout, project_id=pid)

        async def _once(phase: str) -> None:
            marker = recorder.mark()
            started = time.perf_counter()
            response = await client.post("/search", json=payload, headers=headers)
            wall_ms = (time.perf_counter() - started) * 1000.0
            response.raise_for_status()
            queries = recorder.since(marker)
            trace_id = response.headers.get("x-trace-id")
            await drain_background_tasks()
            spans = await _read_spans(repository, trace_id) if trace_id else {}
            if phase == "measured":
                measured.append(RequestSample(wall_ms=wall_ms, queries=queries, spans=spans))

        await _once("cold")
        await warm_route_caches(repository, PROVIDERS)
        for _ in range(warmup):
            await _once("warmup")
        for _ in range(samples):
            await _once("measured")

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        if lifespan:
            async with app.router.lifespan_context(app):
                limits = app.state.limits
                if isinstance(limits, ProviderLimitsService):
                    await lift_rate_windows(limits, PROVIDERS)
                await _login_and_run(client, repository, _drive)
        else:
            await _login_and_run(client, repository, _drive)
    return measured


async def _login_and_run(
    client: httpx.AsyncClient,
    repository: SQLiteRepository,
    drive: Any,
) -> None:
    """Register, log in, seed the execution project, then run the mix."""

    email = temp_email("profile-steps")
    registered = await client.post(
        "/auth/register", json={"email": email, "password": TEMP_PASSWORD}
    )
    registered.raise_for_status()
    logged_in = await client.post(
        "/auth/jwt/login", data={"username": email, "password": TEMP_PASSWORD}
    )
    logged_in.raise_for_status()
    headers = {"Authorization": f"Bearer {logged_in.json()['access_token']}"}
    pid = str((await seed_member_project(repository, headers)).project_id)
    await drive(client, headers, pid)


# ------------------------------------------------------------------------ report


def _report(
    samples: Sequence[RequestSample],
    *,
    mode: str,
    providers: Sequence[str],
    fanout: bool,
    lifespan: bool,
) -> None:
    wal = sorted(sample.wall_ms for sample in samples)
    roots = sorted(
        float(sample.spans[ROOT_SPAN][0]) for sample in samples if sample.spans.get(ROOT_SPAN)
    )
    label = "fanout" if fanout else mode
    print()
    print(f"== Mix: rest-inprocess search {label} providers={','.join(providers)} ==")
    print(
        f"   measured={len(samples)} lifespan={'on' if lifespan else 'off'} "
        f"trace_spans={'on' if roots else 'off'}"
    )
    print()
    print("== Per request ==")
    print(f"   wall              median={_median(wal):8.3f} ms   p95={_p95(wal):8.3f} ms")
    if roots:
        print(
            f"   root span         median={_median(roots):8.3f} ms   p95={_p95(roots):8.3f} ms"
            f"   ({_median(roots) / _median(wal) * 100.0:5.1f}% of wall)"
        )
    queried = sorted(sample.query_total_us for sample in samples)
    print(
        f"   SQL total         median={_median(queried) / 1000.0:8.3f} ms"
        f"   p95={_p95(queried) / 1000.0:8.3f} ms"
    )
    print(
        f"   statements/req    reads={_median([float(s.read_count) for s in samples]):5.1f}"
        f"   writes={_median([float(s.write_count) for s in samples]):5.1f}"
    )

    if roots:
        print()
        print("== Stage durations (median/p95 ms, share of root) ==")
        print(f"   {'stage':<28}{'n/req':>7}{'median':>10}{'p95':>10}{'share':>9}")
        root_median = _median(roots)
        for name in STAGE_ORDER:
            values: list[int] = []
            counts: list[float] = []
            for sample in samples:
                durations = sample.spans.get(name, [])
                counts.append(float(len(durations)))
                values.extend(float(value) for value in durations)
            if not values:
                continue
            share = _median(values) / root_median * 100.0 if root_median else 0.0
            print(
                f"   {name:<28}{_median(counts):7.1f}{_median(values):10.3f}"
                f"{_p95(values):10.3f}{share:8.1f}%"
            )

    print()
    print("== SQL statements (median per execution) ==")
    print(
        f"   {'statement':<34}{'exec/req':>10}{'median_us':>12}{'p95_us':>10}{'total_us/req':>14}"
    )
    keys: dict[str, tuple[list[float], float]] = {}
    for sample in samples:
        counts: dict[str, int] = {}
        for query in sample.queries:
            keys.setdefault(query.key, ([], 0.0))
            keys[query.key][0].append(query.duration_us)
            counts[query.key] = counts.get(query.key, 0) + 1
        for key, count in counts.items():
            durations, total = keys[key]
            keys[key] = (durations, total + count)
    ordered = sorted(keys.items(), key=lambda item: _median(item[1][0]), reverse=True)
    for key, (durations, exec_count) in ordered:
        per_request = exec_count / len(samples)
        total_us = sum(durations) / len(samples)
        print(
            f"   {key:<34}{per_request:10.2f}{_median(durations):12.1f}"
            f"{_p95(durations):10.1f}{total_us:14.1f}"
        )

    print()
    print("== Unexplained time ==")
    wall_median = _median(wal)
    sql_median = _median(queried) / 1000.0
    if roots:
        root_median = _median(roots)
        children: dict[str, float] = {}
        for name in STAGE_ORDER[1:]:
            values = [
                float(percentile(sorted(sample.spans[name]), 50.0))
                for sample in samples
                if sample.spans.get(name)
            ]
            if values:
                children[name] = _median(values)
        child_total = sum(children.values())
        print(
            f"   wall - root       {wall_median - root_median:8.3f} ms"
            "   auth guard, body buffering, trace flush"
        )
        print(
            f"   root - stages     {root_median - child_total:8.3f} ms"
            "   scope resolution, request parse, serialization"
        )
        print(f"   stages total      {child_total:8.3f} ms")
    print(f"   SQL inside wall   {sql_median:8.3f} ms   ({sql_median / wall_median * 100.0:5.1f}%)")
    print()
    print("== Notes ==")
    print("   - Provider stages run concurrently in fanout; one median is counted.")
    print("   - A statement's time is driver execute time. The aiosqlite thread")
    print("     handoff and any worker queueing sit outside it, so the SQL total is")
    print("     a floor, not the whole database cost.")
    print("   - Span durations are integer milliseconds; a stage under 1 ms reads 0.")
    print("   - Figures compare runs on this machine, not machines with each other.")


# -------------------------------------------------------------------------- entry


def _configure_env() -> bool:
    """Set a JWT secret when the process has none; return whether this did."""

    if os.environ.get(_JWT_ENV):
        return False
    os.environ[_JWT_ENV] = "profile-request-steps-" + "s" * 32
    get_settings.cache_clear()
    return True


async def _main(args: argparse.Namespace) -> None:
    set_env = _configure_env()
    providers = tuple(name.strip() for name in args.providers.split(",") if name.strip())
    fanout = args.mode == "fanout"
    clear_config_cache()
    clear_quota_poll_cache()
    recorder = QueryRecorder()
    with tempfile.TemporaryDirectory(prefix="polyweb-profile-") as directory:
        repository = await SQLiteRepository.open(Path(directory) / "profile.db")
        try:
            await seed_repository(repository, PROVIDERS)
            recorder.attach(repository)
            samples = await _exercise(
                repository,
                recorder,
                mode=args.mode,
                providers=providers,
                fanout=fanout,
                samples=args.samples,
                warmup=args.warmup,
                lifespan=not args.no_lifespan,
            )
            _report(
                samples,
                mode=args.mode,
                providers=providers,
                fanout=fanout,
                lifespan=not args.no_lifespan,
            )
        finally:
            recorder.detach()
            await drain_background_tasks()
            clear_config_cache()
            clear_quota_poll_cache()
            await repository.close()
            if set_env:
                os.environ.pop(_JWT_ENV, None)
                get_settings.cache_clear()


def _parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--mode", default="require", choices=("require", "auto", "fanout"))
    parser.add_argument("--providers", default="exa", help="comma-separated provider names")
    parser.add_argument("--samples", type=int, default=30)
    parser.add_argument("--warmup", type=int, default=10)
    parser.add_argument(
        "--no-lifespan",
        action="store_true",
        help="skip the app lifespan: no tracing and no limit admission (pytest-mix parity)",
    )
    return parser.parse_args(list(argv) if argv is not None else None)


if __name__ == "__main__":
    asyncio.run(_main(_parse_args()))
