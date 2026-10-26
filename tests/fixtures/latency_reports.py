"""Routing-latency samples, per-combination outcomes, and the CSV/Markdown reports.

Definitions used everywhere in the reports:

- ``server_ms``: time from the HTTP request scope reaching the FreeSearch ASGI
  app until its final response body (``more_body`` false) is sent.
- ``provider_ms``: summed duration of the adapter ``search``/``fetch`` calls
  made while serving the request.
- ``added_ms`` (the gated value): ``server_ms - provider_ms``.
- ``wall_ms``: client-observed time around the HTTP POST / MCP ``call_tool``.
- ``client_overhead_ms``: ``wall_ms - server_ms`` (client stack, loopback TCP,
  and uvicorn parsing outside the app). Reported, never gated.
- ``db_reads``: SELECT statements on the server repository during the sample.
  Diagnostic only, never pass/fail.
"""

from __future__ import annotations

import csv
import platform
import sqlite3
import sys
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from tests.fixtures.latency import default_report_dir, percentile

#: Acceptance budget: server-side FreeSearch-added time per request at p95.
ADDED_P95_BUDGET_MS = 80.0

CSV_COLUMNS: tuple[str, ...] = (
    "commit",
    "transport",
    "operation",
    "provider",
    "adapter_mode",
    "phase",
    "request_index",
    "server_ms",
    "provider_ms",
    "added_ms",
    "wall_ms",
    "client_overhead_ms",
    "db_reads",
    "provider_calls",
    "status",
)


@dataclass
class LatencySample:
    """One request; ``added_ms`` is server-side, ``db_reads`` is a diagnostic."""

    transport: str
    operation: str
    provider: str
    adapter_mode: str
    phase: str
    request_index: int
    wall_ms: float | None
    server_ms: float | None
    provider_ms: float | None
    added_ms: float | None
    client_overhead_ms: float | None
    db_reads: int | None
    provider_calls: int
    status: str


@dataclass
class ComboOutcome:
    """The verdict of one transport x operation x provider combination."""

    transport: str
    operation: str
    provider: str
    adapter_mode: str
    verdict: str
    reason: str = ""
    samples: list[LatencySample] = field(default_factory=list)

    @property
    def measured(self) -> list[LatencySample]:
        return [sample for sample in self.samples if sample.phase == "measured"]

    @property
    def ok_measured(self) -> list[LatencySample]:
        return [sample for sample in self.measured if sample.status == "ok"]

    def _values(self, attribute: str) -> list[float]:
        values = (getattr(sample, attribute) for sample in self.ok_measured)
        return sorted(float(value) for value in values if value is not None)

    def added_values(self) -> list[float]:
        return self._values("added_ms")

    def provider_values(self) -> list[float]:
        return self._values("provider_ms")

    def server_values(self) -> list[float]:
        return self._values("server_ms")

    def wall_values(self) -> list[float]:
        return self._values("wall_ms")

    def overhead_values(self) -> list[float]:
        return self._values("client_overhead_ms")

    def read_values(self) -> list[float]:
        return self._values("db_reads")

    @property
    def added_p95(self) -> float | None:
        """Return the p95 server-side added time, or ``None`` with no OK sample."""

        values = self.added_values()
        return percentile(values, 95.0) if values else None

    def status_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for sample in self.measured:
            counts[sample.status] = counts.get(sample.status, 0) + 1
        return counts


def pct_text(values: Sequence[float], pct: float, *, digits: int = 2) -> str:
    """Format one percentile, or ``n/a`` when there is no OK sample."""

    return f"{percentile(values, pct):.{digits}f}" if values else "n/a"


def summary_line(outcome: ComboOutcome) -> str:
    """Return the compact one-line per-combination summary (no secrets)."""

    label = f"{outcome.transport:<4} {outcome.operation:<6} {outcome.provider:<9}"
    if not outcome.samples:
        return f"{label} {outcome.verdict}: {outcome.reason}"
    added = outcome.added_values()
    return (
        f"{label} n={len(outcome.ok_measured)}/{len(outcome.measured)} "
        f"server-added p50={pct_text(added, 50.0)}ms p95={pct_text(added, 95.0)}ms "
        f"provider p95={pct_text(outcome.provider_values(), 95.0)}ms "
        f"client-overhead p50={pct_text(outcome.overhead_values(), 50.0)}ms "
        f"reads p50={pct_text(outcome.read_values(), 50.0, digits=0)} [{outcome.verdict}]"
    )


def _fmt(value: float | None) -> str:
    return "" if value is None else f"{value:.3f}"


def _sample_row(commit: str, sample: LatencySample) -> dict[str, object]:
    return {
        "commit": commit,
        "transport": sample.transport,
        "operation": sample.operation,
        "provider": sample.provider,
        "adapter_mode": sample.adapter_mode,
        "phase": sample.phase,
        "request_index": sample.request_index,
        "server_ms": _fmt(sample.server_ms),
        "provider_ms": _fmt(sample.provider_ms),
        "added_ms": _fmt(sample.added_ms),
        "wall_ms": _fmt(sample.wall_ms),
        "client_overhead_ms": _fmt(sample.client_overhead_ms),
        "db_reads": "" if sample.db_reads is None else sample.db_reads,
        "provider_calls": sample.provider_calls,
        "status": sample.status,
    }


def _empty_row(commit: str, outcome: ComboOutcome) -> dict[str, object]:
    row: dict[str, object] = dict.fromkeys(CSV_COLUMNS, "")
    row.update(
        {
            "commit": commit,
            "transport": outcome.transport,
            "operation": outcome.operation,
            "provider": outcome.provider,
            "adapter_mode": outcome.adapter_mode,
            "phase": "n/a",
            "status": f"{outcome.verdict}:{outcome.reason}",
        }
    )
    return row


def write_reports(
    harness_label: str,
    outcomes: Iterable[ComboOutcome],
    *,
    commit: str,
    warmup: int,
    measured: int,
    output_dir: Path | None = None,
    notes: Sequence[str] = (),
) -> tuple[Path, Path]:
    """Write ``routing_latency_<label>.csv`` and ``.md``; return both paths."""

    resolved = output_dir or default_report_dir()
    resolved.mkdir(parents=True, exist_ok=True)
    ordered = sorted(outcomes, key=lambda o: (o.transport, o.operation, o.provider))
    csv_path = resolved / f"routing_latency_{harness_label}.csv"
    md_path = resolved / f"routing_latency_{harness_label}.md"
    with open(csv_path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(CSV_COLUMNS))
        writer.writeheader()
        for outcome in ordered:
            if not outcome.samples:
                writer.writerow(_empty_row(commit, outcome))
            for sample in outcome.samples:
                writer.writerow(_sample_row(commit, sample))
    md_path.write_text(
        _markdown(
            harness_label, ordered, commit=commit, warmup=warmup, measured=measured, notes=notes
        ),
        encoding="utf-8",
    )
    return csv_path, md_path


def _result_row(outcome: ComboOutcome) -> str:
    head = f"| {outcome.transport} | {outcome.operation} | {outcome.provider} | "
    head += f"{outcome.adapter_mode} | "
    if not outcome.samples:
        return head + "- | " * 10 + f"{outcome.verdict}: {outcome.reason} |"
    added = outcome.added_values()
    provider = outcome.provider_values()
    cells = [
        f"{len(outcome.ok_measured)}/{len(outcome.measured)}",
        pct_text(added, 50.0),
        pct_text(added, 95.0),
        f"{max(added):.2f}" if added else "n/a",
        pct_text(provider, 50.0),
        pct_text(provider, 95.0),
        pct_text(outcome.server_values(), 95.0),
        pct_text(outcome.wall_values(), 95.0),
        pct_text(outcome.overhead_values(), 50.0),
        pct_text(outcome.read_values(), 50.0, digits=0),
        outcome.verdict,
    ]
    return head + " | ".join(cells) + " |"


def _markdown(
    label: str,
    outcomes: Sequence[ComboOutcome],
    *,
    commit: str,
    warmup: int,
    measured: int,
    notes: Sequence[str] = (),
) -> str:
    lines = [
        f"# Routing latency report ({label})",
        "",
        "## Method",
        "Real servers over loopback TCP: the REST app and the MCP Streamable HTTP",
        "app are each served by uvicorn on 127.0.0.1 with an OS-assigned port, in",
        "their own thread, event loop, and temporary SQLite repository. Clients",
        "call over TCP (httpx for REST; the MCP SDK streamable-http client with one",
        "ClientSession for MCP). Each request pins exactly one provider with",
        '`routing: {"mode": "require", "providers": [<provider>]}`.',
        "",
        "- server_ms: from the HTTP request reaching the FreeSearch ASGI app until its",
        "  final response body is sent (timing middleware around the served app; for",
        "  MCP the one POST /mcp carrying the tool call).",
        "- provider_ms: summed duration of the adapter search/fetch calls during",
        "  the request (bound instance methods wrapped; adapter type unchanged).",
        "- added_ms (gated): server_ms - provider_ms, the server-side FreeSearch time.",
        "- wall_ms / client_overhead_ms: client-observed time and wall_ms - server_ms",
        "  (client stack, loopback TCP, uvicorn parsing). Reported, not gated.",
        "- db_reads: SELECT statements on the server repository engine during the",
        "  request. Diagnostic only; never pass/fail.",
        "",
        "Warm procedure per combination: the target repository's config and quota",
        "poll caches are cleared, then effective_config_for_name per provider plus",
        f"routing_policy, then {warmup} warmup and {measured} measured requests.",
        "Out-of-band quota refresh tasks are drained after every request.",
        f"Pass/fail: p95 added_ms < {ADDED_P95_BUDGET_MS:.0f} ms and every measured",
        "request succeeds on the pinned provider with exactly one matching server",
        "request. Percentiles use linear interpolation between closest ranks; a row",
        "without OK samples reports n/a.",
        *[f"- {note}" for note in notes],
        "",
        "## Environment",
        f"- commit: {commit}",
        f"- python: {sys.version.split()[0]}",
        f"- platform: {platform.platform()}",
        f"- sqlite: {sqlite3.sqlite_version}",
        "",
        "## Results",
        "| transport | operation | provider | mode | ok/measured | added p50 ms | "
        "added p95 ms | added max ms | provider p50 ms | provider p95 ms | "
        "server p95 ms | wall p95 ms | client overhead p50 ms | reads p50 | verdict |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|",
        *[_result_row(outcome) for outcome in outcomes],
        "",
    ]
    return "\n".join(lines)
