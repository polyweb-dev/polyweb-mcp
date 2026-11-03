"""Exercise the archive HTTP boundary, uploader and failure-path log capture."""
import http.client
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.parse
import zipfile
from pathlib import Path

from server import ArtifactServer, MAX_BYTES


class ArtifactTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.server = ArtifactServer(("127.0.0.1", 0), self.root / "data", "upload-test-token",
                                     "service-test-token", "http://unused", "https://ci.example")
        self.server.api = self.fake_api
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.admin = {"Authorization": "Bearer admin"}

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.temporary.cleanup()

    def fake_api(self, path, headers):
        if path.startswith("/api/repos/1/pipelines/"):
            return {"commit": "abc123", "workflows": [{"name": "api-mutation"}, {"name": "api-latency"}]}
        if headers.get("Authorization") == "Bearer admin" or headers.get("Cookie") == "user_sess=session-test":
            return {"id": 1, "admin": True, "login": "admin"}
        if headers.get("Authorization") == "Bearer reader":
            return {"id": 2, "admin": False, "login": "reader"}
        raise urllib.error.HTTPError("http://unused", 401, "Unauthorized", {}, None)

    def request(self, method, path, data=None, headers=None):
        connection = http.client.HTTPConnection(*self.server.server_address, timeout=5)
        connection.request(method, path, data, headers or {})
        response = connection.getresponse()
        result = response.status, dict(response.getheaders()), response.read()
        connection.close()
        return result

    def archive(self, name="coverage/gremlins/index.html"):
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as bundle:
            bundle.writestr(name, "<h1>Report</h1>")
        return stream.getvalue()

    def upload(self, archive=None, key="9--api-mutation"):
        return self.request("POST", "/artifacts/upload/" + key, archive or self.archive(),
                            {"Authorization": "Bearer upload-test-token", "X-Artifact-Status": "failure"})

    def test_anonymous_and_non_admin_downloads_are_denied(self):
        self.assertEqual(self.request("GET", "/artifacts/")[0], 401)
        self.assertEqual(self.request("GET", "/artifacts/", headers={"Authorization": "Bearer reader"})[0], 403)

    def test_existing_woodpecker_cookie_is_forwarded_for_authentication(self):
        status, _, body = self.request("GET", "/artifacts/", headers={"Cookie": "user_sess=session-test"})
        self.assertEqual(status, 200)
        self.assertIn(b"CI reports", body)

    def test_upload_download_and_metadata_survive_server_recreation(self):
        self.assertEqual(self.upload()[0], 201)
        record = json.loads((self.server.root / "9--api-mutation.json").read_text())
        self.assertEqual(record["commit"], "abc123")
        self.assertEqual(record["status"], "failure")
        self.assertEqual(self.upload()[0], 409)
        self.server.shutdown(); self.server.server_close(); self.thread.join()
        self.server = ArtifactServer(("127.0.0.1", 0), self.root / "data", "upload-test-token",
                                     "service-test-token", "http://unused", "https://ci.example")
        self.server.api = self.fake_api
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        status, headers, data = self.request("GET", "/artifacts/download/9--api-mutation", headers=self.admin)
        self.assertEqual(status, 200)
        self.assertIn("attachment", headers["Content-Disposition"])
        with zipfile.ZipFile(io.BytesIO(data)) as bundle:
            self.assertEqual(bundle.read("coverage/gremlins/index.html"), b"<h1>Report</h1>")

    def test_bad_upload_token_and_unverified_workflow_are_denied(self):
        self.assertEqual(self.request("POST", "/artifacts/upload/9--api-mutation", self.archive())[0], 401)
        self.assertEqual(self.upload(key="9--not-a-workflow")[0], 400)

    def test_unsafe_archive_paths_and_oversized_body_are_rejected(self):
        for name in ("../secret", "/absolute", "a\\b"):
            with self.subTest(name=name):
                self.assertEqual(self.upload(self.archive(name))[0], 400)
        self.assertEqual(self.request("POST", "/artifacts/upload/9--api-mutation", headers={
            "Authorization": "Bearer upload-test-token", "Content-Length": str(MAX_BYTES + 1)})[0], 413)
        self.assertFalse(list(self.server.root.glob("*.zip")))

    def test_deletion_requires_authentication_origin_csrf_and_confirmation(self):
        self.upload()
        path = "/artifacts/delete/9--api-mutation"
        self.assertEqual(self.request("GET", path, headers=self.admin)[0], 404)
        self.assertEqual(self.request("POST", path, b"confirm=yes", self.admin)[0], 403)
        _, _, page = self.request("GET", "/artifacts/", headers=self.admin)
        token = re.search(rb'name="csrf" value="([a-f0-9]+)"', page).group(1).decode()
        data = urllib.parse.urlencode({"csrf": token, "confirm": "yes"}).encode()
        self.assertEqual(self.request("POST", path, data, {**self.admin, "Origin": "https://evil.example"})[0], 403)
        self.assertEqual(self.request("POST", path, data, {**self.admin, "Origin": "https://ci.example"})[0], 303)
        self.assertEqual(self.request("GET", "/artifacts/download/9--api-mutation", headers=self.admin)[0], 404)

    def test_uploader_packages_reports_and_skips_symlinks(self):
        workspace = self.root / "workspace"
        reports = workspace / "test_reports"
        reports.mkdir(parents=True)
        (reports / "latency.csv").write_text("ms\n1\n")
        outside = self.root / "private.env"
        outside.write_text("must not upload")
        (reports / "link").symlink_to(outside)
        env = {**os.environ, "CI_PIPELINE_NUMBER": "9", "CI_WORKFLOW_NAME": "api-latency",
               "CI_PIPELINE_STATUS": "failure", "CI_ARTIFACT_UPLOAD_TOKEN": "upload-test-token",
               "CI_ARTIFACT_URL": "http://127.0.0.1:" + str(self.server.server_port)}
        result = subprocess.run([sys.executable, str(Path(__file__).with_name("upload.py")), "test_reports"],
                                cwd=workspace, env=env, capture_output=True, text=True, check=True)
        self.assertIn("Download", result.stdout)
        with zipfile.ZipFile(self.server.root / "9--api-latency.zip") as bundle:
            self.assertEqual(set(bundle.namelist()), {"test_reports/latency.csv", "artifact-manifest.json"})

    def test_early_failure_can_upload_manifest_without_reports(self):
        workspace = self.root / "workspace"
        workspace.mkdir()
        env = {**os.environ, "CI_PIPELINE_NUMBER": "9", "CI_WORKFLOW_NAME": "api-mutation",
               "CI_PIPELINE_STATUS": "failure", "CI_ARTIFACT_UPLOAD_TOKEN": "upload-test-token",
               "CI_ARTIFACT_URL": "http://127.0.0.1:" + str(self.server.server_port)}
        subprocess.run([sys.executable, str(Path(__file__).with_name("upload.py")), "missing-reports"],
                        cwd=workspace, env=env, capture_output=True, check=True)
        with zipfile.ZipFile(self.server.root / "9--api-mutation.zip") as bundle:
            self.assertEqual(json.loads(bundle.read("artifact-manifest.json"))["report_files"], 0)

    def test_latency_capture_preserves_failure_and_stops_later_tests(self):
        workspace = self.root / "workspace"
        workspace.mkdir()
        uv = workspace / "uv"
        uv.write_text('#!/bin/sh\necho "$@"\ncase "$*" in *behave*) exit 7;; esac\n')
        uv.chmod(0o755)
        result = subprocess.run(["bash", str(Path(__file__).with_name("run-latency.sh"))], cwd=workspace,
                                env={**os.environ, "PATH": str(workspace) + ":" + os.environ["PATH"]},
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 7)
        self.assertIn("behave", (workspace / "routing-latency-tests.log").read_text())
        self.assertNotIn("pytest", result.stdout)


if __name__ == "__main__":
    unittest.main()
