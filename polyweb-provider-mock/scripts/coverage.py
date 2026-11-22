#!/usr/bin/env python3
"""Run a provider-mock workflow command and preserve coverage reports."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = PROJECT_ROOT.parent
REPORT_ROOT = WORKSPACE_ROOT / "coverage" / "backend" / "provider-mock"
CONFIG = PROJECT_ROOT / "coverage.toml"


def coverage(env: dict[str, str], *args: str) -> int:
    return subprocess.run(
        [sys.executable, "-m", "coverage", *args],
        cwd=WORKSPACE_ROOT,
        env=env,
        check=False,
    ).returncode


def write_reports(env: dict[str, str]) -> int:
    with (REPORT_ROOT / "summary.txt").open("w", encoding="utf-8") as summary:
        status = subprocess.run(
            [sys.executable, "-m", "coverage", "report"],
            cwd=WORKSPACE_ROOT,
            env=env,
            stdout=summary,
            check=False,
        ).returncode
    if status != 0:
        return status
    for args in (
        ("xml", "-q", "-o", str(REPORT_ROOT / "coverage.xml")),
        ("json", "-q", "-o", str(REPORT_ROOT / "coverage.json")),
        ("lcov", "-q", "-o", str(REPORT_ROOT / "coverage.lcov")),
        ("html", "-q", "-d", str(REPORT_ROOT / "html")),
    ):
        status = coverage(env, *args)
        if status != 0:
            return status
    total = next(
        (
            line
            for line in reversed((REPORT_ROOT / "summary.txt").read_text().splitlines())
            if line.startswith("TOTAL")
        ),
        "",
    )
    print(f"Provider-mock coverage: {' '.join(total.split()) or 'no total'}")
    return 0


def run(command: Sequence[str]) -> int:
    if not command:
        raise ValueError("run needs a command")
    shutil.rmtree(REPORT_ROOT, ignore_errors=True)
    REPORT_ROOT.mkdir(parents=True)
    env = dict(os.environ)
    env["COVERAGE_RCFILE"] = str(CONFIG)
    env["COVERAGE_FILE"] = str(REPORT_ROOT / "coverage.sqlite")
    env["COVERAGE_PROCESS_START"] = str(CONFIG)
    status = subprocess.run(list(command), cwd=WORKSPACE_ROOT, env=env, check=False).returncode

    report_env = dict(env)
    report_env.pop("COVERAGE_PROCESS_START", None)
    if not any(REPORT_ROOT.glob("coverage.sqlite.*")):
        (REPORT_ROOT / "summary.txt").write_text(
            "No coverage data was recorded.\n", encoding="utf-8"
        )
        print("No provider-mock coverage data was recorded", file=sys.stderr)
        return status or 1
    report_status = coverage(report_env, "combine", "-q")
    if report_status == 0:
        report_status = write_reports(report_env)
    if report_status != 0:
        print(f"Coverage reporting failed with exit status {report_status}", file=sys.stderr)
    return status or report_status


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] != "run":
        print("usage: coverage.py run -- <command...>", file=sys.stderr)
        return 2
    command = args[1:]
    if command[:1] == ["--"]:
        command = command[1:]
    try:
        return run(command)
    except ValueError as exc:
        print(f"provider-mock coverage: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
