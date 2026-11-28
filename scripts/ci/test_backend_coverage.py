"""Checks for backend coverage collection, combining, and report uploads."""

from __future__ import annotations

import shutil
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import backend_coverage
import upload_gitea as uploader
import yaml

REPO = Path(__file__).resolve().parents[2]
# A parent process and a child process each import a different polyweb module.
CHILD = (
    "import subprocess, sys; import polyweb.infrastructure.dates; "
    "subprocess.run([sys.executable, '-c', "
    "'import polyweb.infrastructure.borrowed_transport'], check=True); "
    "sys.exit({status})"
)


def measured_files(data: Path) -> set[str]:
    with sqlite3.connect(data) as connection:
        return {Path(path).as_posix() for (path,) in connection.execute("SELECT path FROM file")}


class BackendCoverageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root)
        # The CI settings, narrowed to one package so reports stay quick.
        config = backend_coverage.RCFILE.read_text()
        narrowed = config.replace(
            'source_pkgs = ["polyweb"]', 'source_pkgs = ["polyweb.infrastructure"]'
        )
        self.assertNotEqual(narrowed, config)
        rcfile = self.root / "coverage.toml"
        rcfile.write_text(narrowed)
        rcfile_patch = patch.object(backend_coverage, "RCFILE", rcfile)
        rcfile_patch.start()
        self.addCleanup(rcfile_patch.stop)

    def run_suite(self, suite: str, status: int) -> int:
        command = [sys.executable, "-c", CHILD.format(status=status)]
        return backend_coverage.run(self.root, suite, command)

    def test_failed_command_keeps_status_and_measures_child_processes(self) -> None:
        self.assertEqual(self.run_suite("unit", 3), 3)
        out = self.root / "coverage/backend/unit"
        self.assertEqual(
            {path.name for path in out.iterdir()},
            {
                "coverage.sqlite",
                "coverage.xml",
                "coverage.json",
                "coverage.lcov",
                "summary.txt",
                "html",
            },
        )
        files = measured_files(out / "coverage.sqlite")
        for module in ["dates.py", "borrowed_transport.py"]:
            self.assertIn(f"src/polyweb/infrastructure/{module}", files)
        self.assertIn("TOTAL", (out / "summary.txt").read_text())
        # Crapper reads only the combined file, never per-suite reports.
        self.assertFalse((self.root / "coverage/backend/lcov.info").exists())

    def test_combined_suites_write_the_single_crapper_input(self) -> None:
        self.assertEqual(self.run_suite("unit", 0), 0)
        self.assertEqual(self.run_suite("integration", 0), 0)
        bundle = self.root / "bundle"
        shutil.copytree(self.root / "coverage", bundle / "coverage")
        status = backend_coverage.combine(
            self.root, "combined", [self.root / "coverage/backend/unit/coverage.sqlite", bundle]
        )
        self.assertEqual(status, 0)
        lcov = (self.root / "coverage/backend/lcov.info").read_text()
        self.assertIn("polyweb/infrastructure/dates.py", lcov)
        self.assertEqual(lcov, (self.root / "coverage/backend/combined/coverage.lcov").read_text())

    def test_command_without_python_records_no_data_and_fails(self) -> None:
        status = backend_coverage.run(self.root, "unit", ["true"])
        self.assertEqual(status, 1)
        summary = self.root / "coverage/backend/unit/summary.txt"
        self.assertEqual(summary.read_text(), "No coverage data was recorded.\n")

    def test_suite_names_cannot_leave_the_report_tree(self) -> None:
        for name in ["../unit", "unit/x", "", "Unit"]:
            with self.subTest(name=name), self.assertRaises(ValueError):
                backend_coverage.output_dir(self.root, name)

    def test_combine_without_data_files_is_an_error(self) -> None:
        (self.root / "empty").mkdir()
        with self.assertRaisesRegex(ValueError, "No coverage.sqlite"):
            backend_coverage.combine(self.root, "combined", [self.root / "empty"])


class CoverageUploadTests(unittest.TestCase):
    def test_uploads_reports_and_only_validated_coverage_data(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            suite = root / "coverage/backend/unit"
            (suite / "html").mkdir(parents=True)
            (root / "coverage/backend/other/nested").mkdir(parents=True)
            for name in ["coverage.lcov", "coverage.xml", "summary.txt", "html/index.html"]:
                (suite / name).write_text("example")
            (suite / "coverage.sqlite.host.1.x").write_text("leftover worker data")
            schema = "CREATE TABLE coverage_schema (version integer); CREATE TABLE meta (k text);"
            schema += "CREATE TABLE file (id integer, path text);"
            for path, script in [
                (suite / "coverage.sqlite", schema),
                (root / "coverage/backend/other/coverage.sqlite", "CREATE TABLE credential (k);"),
                (root / "coverage/backend/other/nested/coverage.sqlite", schema),
                (root / "coverage/backend/coverage.sqlite", schema),
            ]:
                with sqlite3.connect(path) as connection:
                    connection.executescript(script)
                connection.close()
            (root / "coverage/backend/lcov.info").write_text("combined locally")
            files = uploader.report_files(root, "api-unit")
            self.assertEqual(
                {path.relative_to(root).as_posix() for path in files},
                {
                    "coverage/backend/unit/coverage.lcov",
                    "coverage/backend/unit/coverage.sqlite",
                    "coverage/backend/unit/coverage.xml",
                    "coverage/backend/unit/summary.txt",
                    "coverage/backend/unit/html/index.html",
                },
            )

    def test_non_sqlite_file_with_coverage_data_name_is_excluded(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "coverage/backend/unit").mkdir(parents=True)
            (root / "coverage/backend/unit/coverage.sqlite").write_text("SECRET=value")
            self.assertEqual(uploader.report_files(root, "api-unit"), [])


class WorkflowTests(unittest.TestCase):
    def test_backend_suites_run_pytest_under_the_coverage_helper(self) -> None:
        for workflow, suite in [("api-unit", "unit"), ("api-integration", "integration")]:
            with self.subTest(workflow=workflow):
                config = yaml.safe_load((REPO / ".woodpecker" / f"{workflow}.yaml").read_text())
                script = "\n".join(next(iter(config["steps"].values()))["commands"])
                pytest_lines = [line for line in script.splitlines() if "pytest tests/" in line]
                self.assertEqual(len(pytest_lines), 1)
                helper, _, measured = pytest_lines[0].partition(" -- ")
                self.assertEqual(
                    helper.strip(), f"uv run python scripts/ci/backend_coverage.py run {suite}"
                )
                # A timeout must stop the tests, not the helper that writes reports.
                self.assertNotIn("timeout", helper)
                self.assertIn("uv run pytest", measured)


if __name__ == "__main__":
    unittest.main()
