"""Unit tests for the routing-latency Behave steps and their shared harness helpers.

Covers the live per-provider gates (env var named, never its value), the live
sample-count overrides, request pacing, fake-adapter capability mirroring,
provider-time instrumentation that keeps the adapter type, the percentile
method, and the report writer. No network call and no real credential is used.
"""

from __future__ import annotations

import asyncio
import csv
import sys
from pathlib import Path
from typing import cast

import httpx
import pytest
from pydantic import SecretStr
from starlette.types import Message, Receive, Scope, Send

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from freesearch.adapters.registry import _ADAPTERS  # noqa: E402
from freesearch.infrastructure.secrets import PROVIDER_ENV_VARS, ProviderName  # noqa: E402
from freesearch.models.contracts import SearchRequest, SearchResponse  # noqa: E402
from freesearch.models.provider_limits import AuthMode  # noqa: E402
from tests.bdd.features.steps import routing_latency_steps as steps  # noqa: E402
from tests.fixtures.execution import EXECUTION_PROJECT_ID  # noqa: E402
from tests.fixtures.latency import (  # noqa: E402
    CANONICAL_PROVIDERS,
    OfflineAdapter,
    fake_adapter_for,
    percentile,
)
from tests.fixtures.latency_reports import (  # noqa: E402
    CSV_COLUMNS,
    ComboOutcome,
    LatencySample,
    summary_line,
    write_reports,
)
from tests.fixtures.latency_servers import (  # noqa: E402
    ProviderClock,
    RoutingLatencyHarness,
    ServerTimer,
    ServerTiming,
    minimum_request_intervals,
)

_SENTINEL_KEY = "unit-sentinel-key-material-0001"


def _clear_live_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for env_var in PROVIDER_ENV_VARS.values():
        monkeypatch.delenv(env_var, raising=False)
    for env_var in ("FREESEARCH_RUN_LIVE", steps.LIVE_WARMUP_ENV, steps.LIVE_SAMPLES_ENV):
        monkeypatch.delenv(env_var, raising=False)


# --- live gates -----------------------------------------------------------------


@pytest.mark.parametrize("provider", [p for p in CANONICAL_PROVIDERS if p != "keenable"])
def test_live_gate_names_the_missing_env_var(
    monkeypatch: pytest.MonkeyPatch, provider: str
) -> None:
    _clear_live_env(monkeypatch)
    reason = steps.live_skip_reason(provider)
    assert reason is not None
    assert PROVIDER_ENV_VARS[ProviderName(provider)] in reason
    assert "is not set or empty" in reason

    monkeypatch.setenv(PROVIDER_ENV_VARS[ProviderName(provider)], "")
    assert "is not set or empty" in (steps.live_skip_reason(provider) or "")


def test_live_gate_opens_with_a_key_and_never_echoes_key_material(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_live_env(monkeypatch)
    monkeypatch.setenv(PROVIDER_ENV_VARS[ProviderName.EXA], _SENTINEL_KEY)

    assert steps.live_skip_reason("exa") is None
    for provider in CANONICAL_PROVIDERS:
        assert _SENTINEL_KEY not in (steps.live_skip_reason(provider) or "")
    assert "exa" in steps.live_providers()
    assert "tavily" not in steps.live_providers()


def test_keyless_keenable_is_gated_on_run_live(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_live_env(monkeypatch)
    reason = steps.live_skip_reason("keenable")
    assert reason is not None and "FREESEARCH_RUN_LIVE=1" in reason

    monkeypatch.setenv("FREESEARCH_RUN_LIVE", "1")
    assert steps.live_skip_reason("keenable") is None


def test_live_sample_counts_default_and_override(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_live_env(monkeypatch)
    assert steps.live_sample_counts() == (1, 5)

    monkeypatch.setenv(steps.LIVE_WARMUP_ENV, "0")
    monkeypatch.setenv(steps.LIVE_SAMPLES_ENV, "3")
    assert steps.live_sample_counts() == (0, 3)

    monkeypatch.setenv(steps.LIVE_SAMPLES_ENV, "0")
    with pytest.raises(ValueError, match=steps.LIVE_SAMPLES_ENV):
        steps.live_sample_counts()
    monkeypatch.setenv(steps.LIVE_SAMPLES_ENV, "many")
    with pytest.raises(ValueError, match=steps.LIVE_SAMPLES_ENV):
        steps.live_sample_counts()


def test_live_adapters_receive_the_harness_key_through_the_explicit_seam(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_live_env(monkeypatch)
    monkeypatch.setenv(PROVIDER_ENV_VARS[ProviderName.TINYFISH], _SENTINEL_KEY)

    async def build_and_close() -> list[str]:
        adapters, close = steps.build_live_adapters(["tinyfish", "keenable"])
        try:
            return [adapter.name for adapter in adapters]
        finally:
            await close()

    # Tinyfish fails closed without a key, so construction proves the key arrived;
    # Keenable without a key builds its keyless rail.
    assert asyncio.run(build_and_close()) == ["tinyfish", "keenable"]


def test_request_pacing_respects_short_vendor_windows() -> None:
    intervals = minimum_request_intervals(["firecrawl", "tinyfish", "keenable", "exa"])
    assert intervals["firecrawl"] == pytest.approx(1.1 * 60 / 10)
    assert intervals["tinyfish"] == pytest.approx(1.1 * 60 / 30)
    assert intervals["keenable"] == pytest.approx(1.1 * 1 / 10)
    assert intervals["exa"] == pytest.approx(1.1 * 1 / 10)
    assert minimum_request_intervals([]) == {}


# --- fake adapters --------------------------------------------------------------


def test_canonical_providers_match_the_adapter_registry() -> None:
    assert sorted(provider.value for provider in _ADAPTERS) == list(CANONICAL_PROVIDERS)
    assert len(CANONICAL_PROVIDERS) == 8


def test_fake_adapters_mirror_real_capability_flags_and_rails() -> None:
    async def compare() -> None:
        client = httpx.AsyncClient()
        try:
            for provider in CANONICAL_PROVIDERS:
                key = None if provider == "keenable" else SecretStr(_SENTINEL_KEY)
                real = steps._LIVE_CONSTRUCTORS[provider](client, api_key=key)
                fake = fake_adapter_for(provider)
                try:
                    assert fake.name == real.name == provider
                    assert fake.capabilities == real.capabilities, provider
                    assert fake.limit_auth_mode == real.limit_auth_mode, provider
                finally:
                    await real.aclose()
        finally:
            await client.aclose()

    asyncio.run(compare())
    assert fake_adapter_for("brave").capabilities.fetch is False
    assert fake_adapter_for("keenable").limit_auth_mode is AuthMode.KEYLESS


def test_provider_clock_times_calls_without_changing_the_adapter_type() -> None:
    class _SlowAdapter(OfflineAdapter):
        async def search(self, request: SearchRequest) -> SearchResponse:
            await asyncio.sleep(0.02)
            return await super().search(request)

    adapter = _SlowAdapter("exa")
    clock = ProviderClock()
    assert clock.instrument(adapter) is adapter
    assert type(adapter) is _SlowAdapter and isinstance(adapter, OfflineAdapter)

    request = SearchRequest(query="probe", project_id=EXECUTION_PROJECT_ID)
    response = asyncio.run(adapter.search(request))
    assert response.provider == "exa"
    provider_ms, calls = clock.snapshot()
    assert calls == 1
    assert provider_ms >= 15.0

    clock.reset()
    assert clock.snapshot() == (0.0, 0)


def test_percentile_interpolates_between_closest_ranks() -> None:
    assert percentile([], 95.0) == 0.0
    assert percentile([7.0], 95.0) == 7.0
    values = [float(v) for v in range(1, 21)]
    assert percentile(values, 50.0) == pytest.approx(10.5)
    assert percentile(values, 95.0) == pytest.approx(19.05)


# --- reports --------------------------------------------------------------------


def _outcome(added: list[float]) -> ComboOutcome:
    outcome = ComboOutcome("rest", "search", "exa", "fake", "pass")
    for index, value in enumerate(added):
        outcome.samples.append(
            LatencySample(
                transport="rest",
                operation="search",
                provider="exa",
                adapter_mode="fake",
                phase="measured",
                request_index=index,
                wall_ms=value + 3.0,
                server_ms=value + 1.0,
                provider_ms=1.0,
                added_ms=value,
                client_overhead_ms=2.0,
                db_reads=12,
                provider_calls=1,
                status="ok",
            )
        )
    return outcome


def test_reports_list_measured_rows_and_not_applicable_rows(tmp_path: Path) -> None:
    measured = _outcome([10.0, 20.0, 30.0])
    not_applicable = ComboOutcome(
        "rest", "fetch", "brave", "fake", "n/a", "brave does not support fetch"
    )
    csv_path, md_path = write_reports(
        "unit",
        [measured, not_applicable],
        commit="abc1234",
        warmup=0,
        measured=3,
        output_dir=tmp_path,
        notes=("rate windows lifted for instant fakes",),
    )

    with open(csv_path, newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        assert reader.fieldnames == list(CSV_COLUMNS)
        rows = list(reader)
    assert len(rows) == 4
    assert {row["phase"] for row in rows} == {"measured", "n/a"}
    assert rows[0]["status"].startswith("n/a:")
    markdown = md_path.read_text(encoding="utf-8")
    assert "| rest | search | exa | fake | 3/3 |" in markdown
    assert "n/a: brave does not support fetch" in markdown
    assert "- rate windows lifted for instant fakes" in markdown
    assert "server-added p50=20.00ms p95=29.00ms" in summary_line(measured)
    assert "client-overhead p50=2.00ms" in summary_line(measured)
    assert "reads p50=12" in summary_line(measured)


def test_rows_without_ok_samples_report_not_applicable_percentiles(tmp_path: Path) -> None:
    failed = _outcome([10.0])
    failed.samples[0].status = "http_503"
    failed.verdict = "fail"

    line = summary_line(failed)
    assert "n=0/1" in line
    assert "p50=n/a" in line and "p95=n/a" in line and "0.00" not in line
    assert failed.added_p95 is None
    _csv_path, md_path = write_reports(
        "unit-fail", [failed], commit="abc1234", warmup=0, measured=1, output_dir=tmp_path
    )
    assert "| rest | search | exa | fake | 0/1 | n/a | n/a | n/a |" in md_path.read_text(
        encoding="utf-8"
    )


def test_server_timer_records_the_final_body_and_passes_lifespan_through() -> None:
    sent: list[str] = []

    async def app(scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            sent.append(scope["type"])
            return
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"a", "more_body": True})
        await asyncio.sleep(0.01)
        await send({"type": "http.response.body", "body": b"b"})

    async def send(message: Message) -> None:
        sent.append(str(message["type"]))

    async def receive() -> Message:
        return {"type": "http.request"}

    timer = ServerTimer(app)
    asyncio.run(timer({"type": "lifespan"}, receive, send))
    mark = timer.mark()
    asyncio.run(timer({"type": "http", "method": "POST", "path": "/search"}, receive, send))

    timings = timer.collect(mark, lambda t: t.method == "POST" and t.path == "/search")
    assert len(timings) == 1
    assert isinstance(timings[0], ServerTiming)
    assert timings[0].elapsed_ms >= 9.0
    assert sent[0] == "lifespan"
    assert timer.collect(timer.mark(), lambda t: True, timeout=0.01) == []


def test_profile_write_failure_still_stops_the_harness(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A failing profile writer is reported, the harness still stops, and the
    profile error surfaces after cleanup."""

    stopped: list[bool] = []

    class _Harness:
        profile = True
        commit = "abc1234"

        def write_profiles(self, label: str) -> list[Path]:
            raise OSError("disk full")

        def stop(self) -> None:
            stopped.append(True)

    run = steps._LatencyRun(mode="unit-profile-failure")
    run.harness = cast(RoutingLatencyHarness, _Harness())
    steps._RUNS[run.mode] = run

    with pytest.raises(OSError, match="disk full"):
        steps._finish_run(run.mode)

    assert stopped == [True]
    assert run.mode not in steps._RUNS
    assert "writing the unit-profile-failure profiles failed: OSError" in capsys.readouterr().err
