"""Per-test resource metrics (layer 2), recorded as JUnit XML properties.

Enabled with ``POLYWEB_TEST_METRICS=1`` (see ``tests/conftest.py``). Each test's
setup, call and teardown are measured together and attached to its JUnit
``<testcase>`` as ``metric.*`` properties, so ``--junitxml`` output carries
them. pytest-xdist forwards them from its workers.

All numbers come from the test's own process (an xdist worker):

* ``metric.wall_s``: elapsed time.
* ``metric.cpu_s``: user plus system CPU of this process and of any child
  process the test waited for. ``metric.cpu_ratio`` is ``cpu_s / wall_s``:
  near 1 means CPU bound, near 0 means waiting on I/O, sleeps or a server.
* ``metric.rss_mib`` and ``metric.rss_delta_mib``: resident memory after the
  test and its change. ``metric.peak_rss_raise_mib`` is how far the test raised
  the process's high-water mark (0 unless it set a new peak).
* ``metric.disk_read_mib`` and ``metric.disk_write_mib``: storage I/O (Linux).
* ``metric.voluntary_switches``: context switches while waiting, another sign
  of I/O-bound work.

Every probe is a ``getrusage`` call or a small ``/proc`` read, so the cost per
test is a few microseconds. ``POLYWEB_TEST_METRICS_TOP`` (default 5) sets how
many of the slowest, most CPU-heavy and most memory-hungry tests the terminal
summary lists; 0 disables the summary.
"""

from __future__ import annotations

import os
import resource
import sys
import time
from collections.abc import Generator
from dataclasses import dataclass
from pathlib import Path

import pytest

ENV_FLAG = "POLYWEB_TEST_METRICS"
_STATUS = Path("/proc/self/status")
_IO = Path("/proc/self/io")
# ru_maxrss is KiB on Linux and bytes on macOS.
_MAXRSS_TO_MIB = 1 / (1024 * 1024) if sys.platform == "darwin" else 1 / 1024
_START = pytest.StashKey["_Sample"]()


def enabled() -> bool:
    return os.environ.get(ENV_FLAG, "") not in {"", "0", "false", "no"}


@dataclass(frozen=True)
class _Sample:
    wall: float
    cpu: float
    maxrss_mib: float
    rss_mib: float | None
    read_bytes: int | None
    write_bytes: int | None
    voluntary: int


def _rss_mib() -> float | None:
    try:
        for line in _STATUS.read_text().splitlines():
            if line.startswith("VmRSS:"):
                return int(line.split()[1]) / 1024
    except OSError:
        pass
    return None


def _io_bytes() -> tuple[int | None, int | None]:
    try:
        fields = dict(line.split(": ", 1) for line in _IO.read_text().splitlines())
        return int(fields["read_bytes"]), int(fields["write_bytes"])
    except (OSError, KeyError, ValueError):
        return None, None


def _sample() -> _Sample:
    own = resource.getrusage(resource.RUSAGE_SELF)
    children = resource.getrusage(resource.RUSAGE_CHILDREN)
    read_bytes, write_bytes = _io_bytes()
    return _Sample(
        wall=time.perf_counter(),
        cpu=own.ru_utime + own.ru_stime + children.ru_utime + children.ru_stime,
        maxrss_mib=own.ru_maxrss * _MAXRSS_TO_MIB,
        rss_mib=_rss_mib(),
        read_bytes=read_bytes,
        write_bytes=write_bytes,
        voluntary=own.ru_nvcsw,
    )


def _measure(start: _Sample, end: _Sample) -> dict[str, float | int]:
    wall = max(end.wall - start.wall, 1e-9)
    cpu = max(end.cpu - start.cpu, 0.0)
    metrics: dict[str, float | int] = {
        "wall_s": round(wall, 4),
        "cpu_s": round(cpu, 4),
        "cpu_ratio": round(cpu / wall, 3),
        "peak_rss_raise_mib": round(end.maxrss_mib - start.maxrss_mib, 1),
        "voluntary_switches": end.voluntary - start.voluntary,
    }
    if end.rss_mib is not None and start.rss_mib is not None:
        metrics["rss_mib"] = round(end.rss_mib, 1)
        metrics["rss_delta_mib"] = round(end.rss_mib - start.rss_mib, 1)
    if None not in (start.read_bytes, end.read_bytes, start.write_bytes, end.write_bytes):
        metrics["disk_read_mib"] = round((end.read_bytes - start.read_bytes) / 1048576, 2)  # type: ignore[operator]
        metrics["disk_write_mib"] = round((end.write_bytes - start.write_bytes) / 1048576, 2)  # type: ignore[operator]
    return metrics


class ResourceMetrics:
    """Plugin object, registered by ``tests/conftest.py`` when enabled."""

    def __init__(self, top: int) -> None:
        self.top = top
        self.rows: list[tuple[str, dict[str, float]]] = []

    @pytest.hookimpl(tryfirst=True)
    def pytest_runtest_setup(self, item: pytest.Item) -> None:
        item.stash[_START] = _sample()

    # The teardown report is built from item.user_properties, so the
    # properties must be added before it exists: wrap makereport.
    @pytest.hookimpl(wrapper=True)
    def pytest_runtest_makereport(
        self, item: pytest.Item, call: pytest.CallInfo[None]
    ) -> Generator[None, pytest.TestReport, pytest.TestReport]:
        if call.when == "teardown" and (start := item.stash.get(_START, None)) is not None:
            for name, value in _measure(start, _sample()).items():
                item.user_properties.append((f"metric.{name}", value))
        return (yield)

    # Runs on the xdist controller too, which sees every worker's reports.
    def pytest_runtest_logreport(self, report: pytest.TestReport) -> None:
        if report.when != "teardown" or not self.top:
            return
        values = {
            name.removeprefix("metric."): float(value)
            for name, value in report.user_properties
            if isinstance(name, str)
            and name.startswith("metric.")
            and isinstance(value, int | float | str)
        }
        if values:
            self.rows.append((report.nodeid, values))

    def pytest_terminal_summary(self, terminalreporter: pytest.TerminalReporter) -> None:
        if not self.rows or not self.top:
            return
        write = terminalreporter.write_line
        terminalreporter.section("test resource metrics")
        total_wall = sum(values["wall_s"] for _, values in self.rows)
        total_cpu = sum(values["cpu_s"] for _, values in self.rows)
        write(
            f"{len(self.rows)} tests, {total_wall:.1f}s test time, {total_cpu:.1f}s CPU "
            f"(ratio {total_cpu / max(total_wall, 1e-9):.2f})"
        )
        for title, key, unit in (
            ("slowest", "wall_s", "s"),
            ("most CPU", "cpu_s", "s CPU"),
            ("largest memory raise", "peak_rss_raise_mib", " MiB"),
        ):
            ranked = sorted(self.rows, key=lambda row: row[1].get(key, 0.0), reverse=True)
            write(f"{title}:")
            for nodeid, values in ranked[: self.top]:
                write(
                    f"  {values.get(key, 0.0):9.2f}{unit}  cpu_ratio "
                    f"{values.get('cpu_ratio', 0.0):.2f}  {nodeid}"
                )


def register(config: pytest.Config) -> None:
    if enabled() and not config.pluginmanager.has_plugin("polyweb-resource-metrics"):
        top = int(os.environ.get("POLYWEB_TEST_METRICS_TOP", "5"))
        config.pluginmanager.register(ResourceMetrics(top), "polyweb-resource-metrics")
