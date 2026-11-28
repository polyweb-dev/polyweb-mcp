#!/usr/bin/env python3
"""Measure backend test commands with coverage.py and keep durable reports.

run <suite> -- <command...>
    Run the command with coverage started in every Python process it creates,
    including pytest-xdist workers and CLI or server subprocesses. Reports land
    in coverage/backend/<suite>/, even when the command fails. The exit status
    is the command's status, or the report status when the command passed.

combine <name> <path>...
    Merge coverage.sqlite data files, or directories that contain them, such as
    extracted CI report ZIPs, into coverage/backend/<name>/. Also writes
    coverage/backend/lcov.info, the one LCOV file that
    `crapper --use-existing-coverage` reads from this tree.

Run it with the project environment (`uv run python ...`) so coverage.py is
importable. See scripts/ci/README.md.
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RCFILE = ROOT / "scripts" / "ci" / "coverage.toml"
DATA_NAME = "coverage.sqlite"
# Per-suite LCOV uses a name crapper does not glob, so only the combined
# coverage/backend/lcov.info feeds it. Crapper keeps one LCOV record per file
# and does not sum overlapping reports.
CRAPPER_LCOV = "lcov.info"
SUITE = re.compile(r"[a-z][a-z0-9-]{0,39}")


def output_dir(root: Path, name: str) -> Path:
    if not SUITE.fullmatch(name):
        raise ValueError(f"Coverage suite name must match {SUITE.pattern}: {name!r}")
    return root / "coverage" / "backend" / name


def coverage_env(out: Path) -> dict[str, str]:
    env = dict(os.environ)
    env["COVERAGE_RCFILE"] = str(RCFILE)
    env["COVERAGE_FILE"] = str(out / DATA_NAME)
    return env


def coverage(env: dict[str, str], *args: str) -> int:
    # Data stores repository-relative paths, so coverage runs from the repository.
    command = [sys.executable, "-m", "coverage", *args]
    return subprocess.run(command, env=env, cwd=ROOT, check=False).returncode


def write_reports(env: dict[str, str], root: Path, out: Path) -> int:
    """Write text, XML, JSON, LCOV, and HTML reports from out/coverage.sqlite."""
    with (out / "summary.txt").open("w", encoding="utf-8") as summary:
        status = subprocess.run(
            [sys.executable, "-m", "coverage", "report"],
            env=env,
            cwd=ROOT,
            stdout=summary,
            check=False,
        ).returncode
    if status != 0:
        return status
    for args in (
        ("xml", "-q", "-o", str(out / "coverage.xml")),
        ("json", "-q", "-o", str(out / "coverage.json")),
        ("lcov", "-q", "-o", str(out / "coverage.lcov")),
        ("html", "-q", "-d", str(out / "html")),
    ):
        status = coverage(env, *args)
        if status != 0:
            return status
    lines = (out / "summary.txt").read_text(encoding="utf-8").splitlines()
    total = next((line for line in reversed(lines) if line.startswith("TOTAL")), "")
    print(f"Coverage reports: {out.relative_to(root)} ({' '.join(total.split()) or 'no total'})")
    return 0


def run(root: Path, suite: str, command: Sequence[str]) -> int:
    if not command:
        raise ValueError("run needs a command after --")
    out = output_dir(root, suite)
    shutil.rmtree(out, ignore_errors=True)
    out.mkdir(parents=True)
    env = coverage_env(out)
    # coverage's .pth hook starts measurement in each new Python process.
    env["COVERAGE_PROCESS_START"] = str(RCFILE)
    status = subprocess.run(list(command), env=env, cwd=ROOT, check=False).returncode
    env.pop("COVERAGE_PROCESS_START")
    if not any(out.glob(f"{DATA_NAME}.*")):
        (out / "summary.txt").write_text("No coverage data was recorded.\n", encoding="utf-8")
        print(f"No coverage data was recorded in {out.relative_to(root)}", file=sys.stderr)
        return status or 1
    report = coverage(env, "combine", "-q")
    if report == 0:
        report = write_reports(env, root, out)
    if report != 0:
        print(f"Coverage reporting failed with exit status {report}", file=sys.stderr)
    return status or report


def data_files(paths: Sequence[Path], out: Path) -> list[Path]:
    found: list[Path] = []
    for path in paths:
        if path.is_file():
            found.append(path)
        elif path.is_dir():
            found.extend(sorted(path.rglob(DATA_NAME)))
        else:
            raise ValueError(f"Coverage input does not exist: {path}")
    target = (out / DATA_NAME).resolve()
    unique = sorted({path.resolve() for path in found} - {target})
    if not unique:
        raise ValueError(f"No {DATA_NAME} files found in the given paths")
    return unique


def combine(root: Path, name: str, paths: Sequence[Path]) -> int:
    out = output_dir(root, name)
    inputs = data_files(paths, out)
    shutil.rmtree(out, ignore_errors=True)
    out.mkdir(parents=True)
    env = coverage_env(out)
    status = coverage(env, "combine", "-q", "--keep", *map(str, inputs))
    if status == 0:
        status = write_reports(env, root, out)
    if status == 0:
        shutil.copyfile(out / "coverage.lcov", out.parent / CRAPPER_LCOV)
        print(f"Combined {len(inputs)} data files; crapper input: coverage/backend/{CRAPPER_LCOV}")
    return status


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    commands = parser.add_subparsers(dest="action", required=True)
    run_parser = commands.add_parser("run", help="measure a test command")
    run_parser.add_argument("suite")
    run_parser.add_argument("command", nargs=argparse.REMAINDER)
    combine_parser = commands.add_parser("combine", help="merge data files")
    combine_parser.add_argument("name")
    combine_parser.add_argument("paths", nargs="+", type=Path)
    args = parser.parse_args(argv)
    if args.action == "run":
        command = args.command[1:] if args.command[:1] == ["--"] else args.command
        return run(ROOT, args.suite, command)
    return combine(ROOT, args.name, args.paths)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except ValueError as exc:
        print(f"backend_coverage: {exc}", file=sys.stderr)
        sys.exit(2)
