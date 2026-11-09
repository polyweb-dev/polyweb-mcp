# mypy: disable-error-code="untyped-decorator"
"""Step definitions for the routing-latency acceptance scenarios (@latency).

One harness per adapter mode (``offline`` fake adapters, ``live`` real
adapters) is started lazily by the first scenario that needs it, reused by
every later scenario of the feature, and torn down by a feature-layer cleanup
that also writes ``test_reports/routing_latency_<mode>.{csv,md}`` (plus the
pyinstrument profiles when ``POLYWEB_LATENCY_PROFILE=1``) and prints the
compact per-provider summary. A failed harness start is remembered: every later
scenario of the run fails immediately with that error instead of retrying.

The gated value is server-side: ``added_ms = server_ms - provider_ms`` where
``server_ms`` runs from the request reaching the Polyweb app until its
response leaves it. Client wall time and client overhead are reported only.

Live adapters receive their key only through the explicit ``api_key``
constructor seam from the harness env (``_explicit_api_key`` in
``environment.py``); production code stays vault-only. A missing key skips the
scenario with a reason that names the env var, never its value.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Awaitable, Callable
from contextlib import suppress
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from behave import given, then, when  # type: ignore[import-untyped]

from polyweb.adapters.base import ProviderAdapter
from polyweb.adapters.brave import BraveAdapter
from polyweb.adapters.exa import ExaAdapter
from polyweb.adapters.firecrawl import FirecrawlAdapter
from polyweb.adapters.keenable import KeenableAdapter
from polyweb.adapters.parallel import ParallelAdapter
from polyweb.adapters.tavily import TavilyAdapter
from polyweb.adapters.tinyfish import TinyfishAdapter
from polyweb.adapters.youcom import YoucomAdapter
from polyweb.infrastructure.http import create_async_client
from polyweb.infrastructure.secrets import PROVIDER_ENV_VARS, ProviderName
from tests.bdd.features.environment import _LIVE_GATE, _explicit_api_key, _harness_env_key
from tests.fixtures.latency import CANONICAL_PROVIDERS, fake_adapter_for, git_commit
from tests.fixtures.latency_reports import (
    ADDED_P95_BUDGET_MS,
    ComboOutcome,
    summary_line,
    write_reports,
)
from tests.fixtures.latency_servers import RoutingLatencyHarness

OFFLINE = "offline"
LIVE = "live"

OFFLINE_WARMUP = 5
OFFLINE_MEASURED = 30

#: Live sample-count overrides (real credits: keep them small).
LIVE_WARMUP_ENV = "POLYWEB_LATENCY_LIVE_WARMUP"
LIVE_SAMPLES_ENV = "POLYWEB_LATENCY_LIVE_SAMPLES"
LIVE_WARMUP_DEFAULT = 1
LIVE_SAMPLES_DEFAULT = 5

#: Opt-in server-side pyinstrument profiling of measured requests.
PROFILE_ENV = "POLYWEB_LATENCY_PROFILE"

#: A stable public page for live fetches, and a one-result live search.
LIVE_FETCH_URL = "https://example.com/"
LIVE_SEARCH_EXTRA: dict[str, Any] = {"limit": 1}

_REPORT_NOTES: dict[str, tuple[str, ...]] = {
    OFFLINE: (
        "Instant fake adapters mirror each real adapter's capability flags and limit rail.",
        "Before the servers start, every catalog rate window in each server repository is "
        "lifted through the limit service's update_record seam: REST and MCP admission still "
        "run on every request, but vendor rate windows cannot deny instant fakes.",
        "Behave, the client loop, and both servers share one process, so after startup the "
        "harness freezes that heap (gc.freeze): a full collection would otherwise scan objects "
        "no single server owns and stall one measured request. Request garbage is still "
        "collected.",
    ),
    LIVE: (
        "Real adapters with explicit harness-env keys; providers without a key are skipped.",
        "Requests are spaced per provider to the documented per-second/per-minute rate "
        "windows; the spacing is outside every timing.",
    ),
}

_LIVE_CONSTRUCTORS: dict[str, Callable[..., ProviderAdapter]] = {
    "brave": BraveAdapter,
    "exa": ExaAdapter,
    "firecrawl": FirecrawlAdapter,
    "keenable": KeenableAdapter,
    "parallel": ParallelAdapter,
    "tavily": TavilyAdapter,
    "tinyfish": TinyfishAdapter,
    "you": YoucomAdapter,
}


@dataclass
class _LatencyRun:
    """Feature-scoped state of one adapter mode: the only store of outcomes."""

    mode: str
    outcomes: list[ComboOutcome] = field(default_factory=list)
    harness: RoutingLatencyHarness | None = None
    start_error: BaseException | None = None
    warmup: int = 0
    measured: int = 0

    def record(self, outcome: ComboOutcome) -> None:
        key = (outcome.transport, outcome.operation, outcome.provider)
        self.outcomes = [
            item for item in self.outcomes if (item.transport, item.operation, item.provider) != key
        ]
        self.outcomes.append(outcome)


_RUNS: dict[str, _LatencyRun] = {}


# ----------------------------------------------------------------- live gates


def live_skip_reason(provider: str) -> str | None:
    """Return why a live provider cannot run, naming the env var only."""

    name = ProviderName(provider)
    if name is ProviderName.KEENABLE:
        if os.environ.get(_LIVE_GATE) != "1":
            return f"live Keenable latency requires {_LIVE_GATE}=1 (keyless provider)"
        return None
    if not _harness_env_key(name):
        return (
            f"{PROVIDER_ENV_VARS[name]} is not set or empty (harness live-gate reads the "
            "process env only); live latency for this provider is skipped"
        )
    return None


def live_providers() -> list[str]:
    """Return the canonical providers whose live gate is open."""

    return [name for name in CANONICAL_PROVIDERS if live_skip_reason(name) is None]


def _env_count(env_var: str, default: int, minimum: int) -> int:
    raw = os.environ.get(env_var)
    if raw is None or not raw.strip():
        return default
    try:
        value = int(raw)
    except ValueError as error:
        raise ValueError(f"{env_var} must be an integer") from error
    if value < minimum:
        raise ValueError(f"{env_var} must be >= {minimum}")
    return value


def live_sample_counts() -> tuple[int, int]:
    """Return ``(warmup, measured)`` for live runs, honouring the env overrides."""

    return (
        _env_count(LIVE_WARMUP_ENV, LIVE_WARMUP_DEFAULT, 0),
        _env_count(LIVE_SAMPLES_ENV, LIVE_SAMPLES_DEFAULT, 1),
    )


def profile_enabled() -> bool:
    """Return whether ``POLYWEB_LATENCY_PROFILE=1`` asks for profiles."""

    return os.environ.get(PROFILE_ENV) == "1"


def build_live_adapters(
    providers: list[str],
) -> tuple[list[ProviderAdapter], Callable[[], Awaitable[None]]]:
    """Build real adapters with explicit harness keys on one owned HTTP client."""

    client = create_async_client()
    adapters = [
        _LIVE_CONSTRUCTORS[name](client, api_key=_explicit_api_key(ProviderName(name)))
        for name in providers
    ]

    async def close() -> None:
        for adapter in adapters:
            with suppress(Exception):
                await adapter.aclose()
        await client.aclose()

    return adapters, close


def build_fake_adapters() -> tuple[list[ProviderAdapter], Callable[[], Awaitable[None]]]:
    """Build one instant fake adapter per canonical provider."""

    adapters: list[ProviderAdapter] = [fake_adapter_for(name) for name in CANONICAL_PROVIDERS]

    async def close() -> None:
        return None

    return adapters, close


# ------------------------------------------------------------------ lifecycle


def _run(context: Any, mode: str) -> _LatencyRun:
    run = _RUNS.get(mode)
    if run is None:
        run = _LatencyRun(mode=mode)
        _RUNS[mode] = run
        context.add_cleanup(_finish_run, mode, layer="feature")
    return run


def _finish_run(mode: str) -> None:
    run = _RUNS.pop(mode, None)
    if run is None:
        return
    profile_paths: list[Path] = []
    profile_error: Exception | None = None
    try:
        if run.harness is not None and run.harness.profile:
            try:
                profile_paths = run.harness.write_profiles(mode)
            except Exception as error:
                profile_error = error
                print(
                    f"routing latency: writing the {mode} profiles failed: "
                    f"{type(error).__name__}: {error}",
                    file=sys.stderr,
                    flush=True,
                )
    finally:
        try:
            if run.harness is not None:
                run.harness.stop()
        finally:
            if run.outcomes:
                commit = run.harness.commit if run.harness is not None else git_commit()
                csv_path, md_path = write_reports(
                    mode,
                    run.outcomes,
                    commit=commit,
                    warmup=run.warmup,
                    measured=run.measured,
                    notes=_REPORT_NOTES[mode],
                )
                names = [csv_path.name, md_path.name, *(path.name for path in profile_paths)]
                _print_summary(run, names)
    if profile_error is not None:
        raise profile_error


def _print_summary(run: _LatencyRun, files: list[str]) -> None:
    lines = [
        "",
        f"Routing latency summary ({run.mode}; gate: p95 server-side added = server_ms - "
        f"provider_ms < {ADDED_P95_BUDGET_MS:.0f} ms; client overhead and reads are reported "
        "only):",
    ]
    lines += [
        f"  {summary_line(outcome)}"
        for outcome in sorted(run.outcomes, key=lambda o: (o.transport, o.operation, o.provider))
    ]
    lines.append("  reports: " + ", ".join(f"test_reports/{name}" for name in files))
    stream = sys.__stdout__ or sys.stdout
    print("\n".join(lines), file=stream, flush=True)


def _ensure_harness(run: _LatencyRun, build: Callable[[], RoutingLatencyHarness]) -> None:
    """Start the run's harness once; a failed start fails every later scenario."""

    if run.start_error is not None:
        raise AssertionError(
            f"the {run.mode} latency harness failed to start earlier in this run: "
            f"{type(run.start_error).__name__}: {run.start_error}"
        ) from run.start_error
    if run.harness is not None:
        return
    harness = build()
    run.warmup = harness.warmup
    run.measured = harness.measured
    try:
        harness.start()
    except BaseException as error:
        run.start_error = error
        raise
    run.harness = harness


# ---------------------------------------------------------------------- steps


@given("the routing latency servers are running with instant fake adapters for every provider")
def step_offline_servers(context: Any) -> None:
    run = _run(context, OFFLINE)
    _ensure_harness(
        run,
        lambda: RoutingLatencyHarness(
            adapter_mode="fake",
            providers=CANONICAL_PROVIDERS,
            adapter_builder=build_fake_adapters,
            warmup=OFFLINE_WARMUP,
            measured=OFFLINE_MEASURED,
            lift_rate_windows=True,
            profile=profile_enabled(),
        ),
    )
    context.latency_run = run


@given(
    'the live "{provider}" adapter is enabled by the harness env '
    "for {operation:w} over {transport:w}"
)
def step_live_gate(context: Any, provider: str, operation: str, transport: str) -> None:
    run = _run(context, LIVE)
    context.latency_run = run
    reason = live_skip_reason(provider)
    if reason is not None:
        run.record(ComboOutcome(transport, operation, provider, "live", "skipped", reason))
        context.scenario.skip(reason=reason)


@given("the routing latency servers are running with live adapters")
def step_live_servers(context: Any) -> None:
    run = _run(context, LIVE)

    def build() -> RoutingLatencyHarness:
        providers = live_providers()
        warmup, measured = live_sample_counts()
        return RoutingLatencyHarness(
            adapter_mode="live",
            providers=providers,
            adapter_builder=lambda: build_live_adapters(providers),
            warmup=warmup,
            measured=measured,
            fetch_url=LIVE_FETCH_URL,
            search_extra=LIVE_SEARCH_EXTRA,
            pace_to_rate_windows=True,
            profile=profile_enabled(),
        )

    _ensure_harness(run, build)
    context.latency_run = run


@when('I send warm {operation:w} requests pinned to "{provider}" over {transport:w}')
def step_measure(context: Any, operation: str, provider: str, transport: str) -> None:
    run: _LatencyRun = context.latency_run
    harness = run.harness
    assert harness is not None, "the latency harness is not running"
    if not harness.supports(provider, operation):
        reason = f"{provider} does not support {operation} (capability {operation}=False): N/A"
        mode = harness.adapter_mode
        run.record(ComboOutcome(transport, operation, provider, mode, "n/a", reason))
        context.scenario.skip(reason=reason)
        return
    outcome = harness.measure(transport, operation, provider)
    run.record(outcome)
    context.latency_outcome = outcome


@then('every measured {operation:w} request is served by "{provider}"')
def step_all_ok(context: Any, operation: str, provider: str) -> None:
    outcome: ComboOutcome = context.latency_outcome
    assert (outcome.operation, outcome.provider) == (operation, provider)
    failures = {status: n for status, n in outcome.status_counts().items() if status != "ok"}
    if failures or not outcome.measured:
        outcome.verdict = "fail"
        outcome.reason = f"failed requests: {failures}"
    assert outcome.measured, "no measured requests were recorded"
    assert not failures, (
        f"{outcome.transport} {operation} pinned to {provider}: "
        f"{len(outcome.ok_measured)}/{len(outcome.measured)} succeeded with exactly one "
        f"provider call and one matching server request; statuses {failures}"
    )


@then("the p95 server-side Polyweb-added latency is under {budget_ms:d} ms")
def step_p95_budget(context: Any, budget_ms: int) -> None:
    outcome: ComboOutcome = context.latency_outcome
    assert float(budget_ms) == ADDED_P95_BUDGET_MS, (
        f"feature budget {budget_ms} ms drifted from ADDED_P95_BUDGET_MS={ADDED_P95_BUDGET_MS}"
    )
    p95 = outcome.added_p95
    shown = "n/a" if p95 is None else f"{p95:.2f} ms"
    harness = context.latency_run.harness
    if harness is not None and harness.profile:
        # Profiling inflates server time, so a profiled run reports only.
        if outcome.verdict != "fail":
            outcome.verdict = "profiled"
        print(summary_line(outcome))
        print(
            f"{PROFILE_ENV}=1: the p95 gate is not asserted on a profiled run "
            f"(pyinstrument overhead inflates server time; p95 {shown}); run without "
            "profiling for the gated numbers."
        )
        return
    passed = p95 is not None and p95 < budget_ms
    if outcome.verdict != "fail":
        outcome.verdict = "pass" if passed else "fail"
    print(summary_line(outcome))
    assert passed, (
        f"{outcome.transport} {outcome.operation} pinned to {outcome.provider} "
        f"({outcome.adapter_mode}): p95 server-side Polyweb-added latency "
        f"(server_ms - provider_ms) {shown} is not under {budget_ms} ms "
        f"({summary_line(outcome)})"
    )


@then("database reads per request are reported")
def step_reads_reported(context: Any) -> None:
    outcome: ComboOutcome = context.latency_outcome
    reads = outcome.read_values()
    # Diagnostic only: read counts are reported, never pass/fail.
    if reads:
        print(
            f"db reads per request ({outcome.transport} {outcome.operation} "
            f"{outcome.provider}): min={min(reads):.0f} max={max(reads):.0f}"
        )
    else:
        print("db reads per request: unavailable (no SELECT listener on the engine)")


@then("provider time and server-side Polyweb-added time are reported separately")
def step_times_reported(context: Any) -> None:
    outcome: ComboOutcome = context.latency_outcome
    for sample in outcome.ok_measured:
        assert sample.provider_ms is not None and sample.added_ms is not None
        assert sample.server_ms is not None
    print(summary_line(outcome))
