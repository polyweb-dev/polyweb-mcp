"""Isolated checks for archive safety, private HTTPS, and failure handling."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

import upload_gitea as uploader
import yaml

SCRIPT_DIR = Path(__file__).resolve().parent
REPO = SCRIPT_DIR.parent.parent


class ArtifactTests(unittest.TestCase):
    def symlink_or_skip(
        self,
        link: Path,
        target: Path,
        *,
        target_is_directory: bool = False,
    ) -> None:
        try:
            link.symlink_to(target, target_is_directory=target_is_directory)
        except OSError as exc:
            self.skipTest(f"symlink creation unavailable: {exc}")

    def test_reports_and_log_only_with_selected_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "coverage/gremlins").mkdir(parents=True)
            (root / "test_reports").mkdir()
            (root / "test_reports/.private").mkdir()
            for name in [
                "coverage/gremlins/index.html",
                "coverage/gremlins/gremlins.json",
                "test_reports/latency.md",
                "mutation-tests.log",
                ".env",
                "test_reports/.env",
                "test_reports/credentials.db",
                "test_reports/.private/token.json",
            ]:
                (root / name).write_text("example")
            self.symlink_or_skip(root / "test_reports/link.txt", root / ".env")
            with patch.dict(os.environ, {"CI_PIPELINE_STATUS": "failure", "SECRET": "hidden"}):
                uploader.make_bundle(root, "api-mutation", root / "bundle.zip")
            with zipfile.ZipFile(root / "bundle.zip") as archive:
                self.assertEqual(
                    set(archive.namelist()),
                    {
                        "ci-metadata.json",
                        "coverage/gremlins/index.html",
                        "coverage/gremlins/gremlins.json",
                        "test_reports/latency.md",
                        "mutation-tests.log",
                    },
                )
                metadata = json.loads(archive.read("ci-metadata.json"))
                self.assertEqual(metadata["CI_PIPELINE_STATUS"], "failure")
                self.assertNotIn("SECRET", metadata)

    def test_symlink_report_parent_does_not_escape_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "outside/gremlins").mkdir(parents=True)
            (root / "outside/gremlins/secret.json").write_text("secret")
            self.symlink_or_skip(
                root / "coverage", root / "outside", target_is_directory=True
            )
            self.assertEqual(uploader.report_files(root, "api-mutation"), [])

    def test_ui_reports_include_playwright_output_and_exclude_test_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in [
                "polyweb-ui/playwright-report/index.html",
                "polyweb-ui/test-results/results.json",
                "polyweb-ui/test-results/video.webm",
                "polyweb-ui/coverage/index.html",
            ]:
                (root / name).parent.mkdir(parents=True, exist_ok=True)
                (root / name).write_text("example")
            files = uploader.report_files(root, "ui-bdd")
            self.assertEqual(
                {path.relative_to(root).as_posix() for path in files},
                {
                    "polyweb-ui/coverage/index.html",
                    "polyweb-ui/playwright-report/index.html",
                    "polyweb-ui/test-results/results.json",
                },
            )

    def test_size_and_file_count_limits(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "unit-tests.log").write_text("12345")
            for limit in [
                patch.object(uploader, "MAX_BYTES", 4),
                patch.object(uploader, "MAX_FILES", 0),
            ]:
                with limit, self.assertRaisesRegex(ValueError, "limit"):
                    uploader.report_files(root, "api-unit")

    def test_setup_failure_still_produces_metadata_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            uploader.make_bundle(root, "api-unit", root / "bundle.zip")
            with zipfile.ZipFile(root / "bundle.zip") as archive:
                self.assertEqual(archive.namelist(), ["ci-metadata.json"])

    def test_private_tls_upload_and_rejected_redirect(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / "bundle.zip"
            archive.write_bytes(b"test ZIP")
            for status in [201, 302, 401, 413, 500]:
                with (
                    patch.object(uploader.socket, "create_connection") as tcp,
                    patch.object(uploader.ssl, "create_default_context") as context,
                    patch.object(uploader.http.client, "HTTPSConnection") as https,
                    patch("builtins.print"),
                ):
                    connection = https.return_value
                    connection.getresponse.return_value.status = status
                    if status == 201:
                        uploader.publish(archive, "package", "version", "credential")
                    else:
                        with self.assertRaisesRegex(RuntimeError, f"HTTP {status}"):
                            uploader.publish(archive, "package", "version", "credential")
                    tcp.assert_called_once_with(("100.64.0.2", 443), timeout=120)
                    context.return_value.wrap_socket.assert_called_once_with(
                        tcp.return_value.__enter__.return_value,
                        server_hostname="gitea.thiocyanate.dev",
                    )
                    call = connection.request.call_args
                    self.assertEqual(
                        call.args[:2],
                        (
                            "PUT",
                            "/api/packages/polyweb/generic/package/version/reports.zip",
                        ),
                    )
                    self.assertEqual(call.kwargs["headers"]["Content-Length"], "8")
                    self.assertEqual(call.kwargs["headers"]["Authorization"], "token credential")
                    connection.close.assert_called_once()

    def test_package_owner_can_be_selected_at_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / "bundle.zip"
            archive.write_bytes(b"test ZIP")
            with (
                patch.dict(os.environ, {"GITEA_PACKAGE_OWNER": "existing-owner"}),
                patch.object(uploader.socket, "create_connection"),
                patch.object(uploader.ssl, "create_default_context"),
                patch.object(uploader.http.client, "HTTPSConnection") as https,
                patch("builtins.print"),
            ):
                https.return_value.getresponse.return_value.status = 201
                uploader.publish(archive, "polyweb-api-unit", "version", "credential")
                request = https.return_value.request.call_args
                self.assertEqual(
                    request.args[1],
                    "/api/packages/existing-owner/generic/polyweb-api-unit/version/reports.zip",
                )

    def test_missing_token_stops_before_archive_or_connection(self) -> None:
        with (
            patch.dict(os.environ, {}, clear=True),
            patch("sys.argv", ["upload_gitea.py", "api-unit"]),
            patch.object(uploader, "publish") as publish,
        ):
            with self.assertRaisesRegex(ValueError, "missing"):
                uploader.main()
            publish.assert_not_called()

    def test_all_manual_workflows_upload_after_failure_without_test_secrets(self) -> None:
        for workflow, log in uploader.WORKFLOWS.items():
            with self.subTest(workflow=workflow):
                config = yaml.safe_load((REPO / ".woodpecker" / f"{workflow}.yaml").read_text())
                self.assertEqual(config["when"], [{"event": "manual"}])
                steps = config["steps"]
                test, upload = list(steps.values())
                self.assertNotIn("GITEA_UPLOAD_TOKEN", test.get("environment", {}))
                self.assertIn(f"run-and-log.sh {log}", "\n".join(test["commands"]))
                self.assertNotIn("failure", test)
                self.assertEqual(
                    upload["when"],
                    [
                        {"event": "manual", "status": ["success", "failure"]},
                    ],
                )
                self.assertEqual(
                    upload["environment"]["GITEA_UPLOAD_TOKEN"],
                    {
                        "from_secret": "gitea_artifact_upload_token",
                    },
                )
                self.assertIn("@sha256:", upload["image"])
                self.assertEqual(
                    upload["commands"], [f"python scripts/ci/upload_gitea.py {workflow}"]
                )

    def test_log_wrapper_preserves_failure_and_progress(self) -> None:
        if shutil.which("stdbuf") is None:
            self.skipTest("GNU stdbuf is not available")
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / "command.log"
            result = subprocess.run(
                [
                    "bash",
                    str(SCRIPT_DIR / "run-and-log.sh"),
                    str(log),
                    "bash",
                    "-c",
                    "printf 'first\\rsecond\\n'; exit 7",
                ],
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 7)
            self.assertEqual(result.stdout, b"first\nsecond\n")
            self.assertEqual(log.read_bytes(), b"first\rsecond\n")


if __name__ == "__main__":
    unittest.main()
