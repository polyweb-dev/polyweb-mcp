"""Isolated checks for generated startup commands. No cloud or Docker access."""
import argparse
import json
import os
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

import worker


class BootstrapTests(unittest.TestCase):
    def test_bootstrap_passes_credentials_as_literal_arguments(self):
        secret = "space ' quote; $(touch /tmp/ci-bootstrap-injection)"
        script = worker.generate_startup_script("ci-test", "test-auth", secret, "provider=gcp,size=standard", 15)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            log = root / "calls.jsonl"
            for command in ("systemd-run", "systemctl", "tailscale", "docker"):
                executable = root / command
                executable.write_text(
                    "#!/usr/bin/python3\nimport json, os, sys\n"
                    "with open(os.environ['CALL_LOG'], 'a') as f: f.write(json.dumps(sys.argv) + '\\n')\n"
                )
                executable.chmod(0o755)
            subprocess.run(["bash", "-s"], input=script, text=True, check=True,
                           capture_output=True, env={**os.environ, "PATH": f"{root}:/usr/bin:/bin", "CALL_LOG": str(log)})
            calls = [json.loads(line) for line in log.read_text().splitlines()]
        docker_run = next(call for call in calls if Path(call[0]).name == "docker" and call[1] == "run")
        self.assertIn("WOODPECKER_AGENT_SECRET=" + secret, docker_run)
        self.assertIn("--pull=never", docker_run)
        self.assertIn("--on-active=15m", calls[0])
        tailscale = next(call for call in calls if Path(call[0]).name == "tailscale")
        self.assertIn("--authkey=test-auth", tailscale)
        self.assertIn("--timeout=60s", tailscale)
        self.assertFalse(Path("/tmp/ci-bootstrap-injection").exists())

    def test_bootstrap_has_no_package_or_image_downloads(self):
        script = worker.generate_startup_script("ci-test", "auth", "secret", "provider=gcp", 10)
        subprocess.run(["bash", "-n"], input=script, text=True, check=True)
        for command in ("apt-get", "curl ", "docker pull"):
            self.assertNotIn(command, script)

    def test_bootstrap_requires_a_shutdown_deadline(self):
        for lifetime in (0, -1):
            with self.assertRaises(ValueError):
                worker.generate_startup_script("ci-test", "auth", "secret", "provider=gcp", lifetime)


class ImageBuildTests(unittest.TestCase):
    def run_builder(self, marker):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            log = root / "calls.jsonl"
            executable = root / "gcloud"
            executable.write_text(
                "#!/usr/bin/python3\nimport json, os, sys\n"
                "args = sys.argv[1:]\n"
                "with open(os.environ['CALL_LOG'], 'a') as f: f.write(json.dumps(args) + '\\n')\n"
                "if 'instances' in args and 'describe' in args: sys.exit(1)\n"
                "if 'get-serial-port-output' in args: print(os.environ['BAKE_MARKER'])\n"
            )
            executable.chmod(0o755)
            result = subprocess.run(
                ["bash", str(Path(__file__).with_name("build-image.sh")), "test-image"],
                env={**os.environ, "PATH": f"{root}:/usr/bin:/bin", "CALL_LOG": str(log), "BAKE_MARKER": marker},
                capture_output=True, text=True,
            )
            calls = [json.loads(line) for line in log.read_text().splitlines()]
        return result, calls

    def test_capture_stops_builder_and_deletes_it(self):
        result, calls = self.run_builder("CI_IMAGE_BAKE_SUCCESS")
        self.assertEqual(result.returncode, 0, result.stderr)
        stop = next(i for i, c in enumerate(calls) if "stop" in c)
        capture = next(i for i, c in enumerate(calls) if "images" in c and "create" in c)
        self.assertLess(stop, capture)
        self.assertIn("delete", calls[-1])
        self.assertIn("--delete-disks=all", calls[-1])

    def test_failed_preparation_deletes_builder_without_capture(self):
        result, calls = self.run_builder("CI_IMAGE_BAKE_FAILED")
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(any("images" in c and "create" in c for c in calls))
        self.assertIn("delete", calls[-1])


class ZoneFallbackTests(unittest.TestCase):
    def test_capacity_error_tries_next_zone(self):
        error = subprocess.CalledProcessError(1, "gcloud", stderr="ZONE_RESOURCE_POOL_EXHAUSTED_WITH_DETAILS")
        success = subprocess.CompletedProcess([], 0, stdout="created")
        with patch.object(worker, "run_gcloud", side_effect=[error, success]) as run:
            result = worker.create_in_zones(["compute", "instances", "create", "test", "--zone=us-central1-a"], {},
                                            ["us-central1-a", "us-central1-b"])
        self.assertIs(result, success)
        self.assertIn("--zone=us-central1-b", run.call_args_list[1].args[0])

    def test_non_capacity_errors_never_try_another_zone(self):
        for detail in ("QUOTA_EXCEEDED", "PERMISSION_DENIED", "connection timed out", "INVALID_FIELD_VALUE"):
            with self.subTest(detail=detail), patch.object(worker, "run_gcloud", side_effect=
                    subprocess.CalledProcessError(1, "gcloud", stderr=detail)) as run:
                with self.assertRaises(subprocess.CalledProcessError):
                    worker.create_in_zones(["--zone=a"], {}, ["a", "b"])
                self.assertEqual(run.call_count, 1)

    def test_all_capacity_failures_are_reported(self):
        error = subprocess.CalledProcessError(1, "gcloud", stderr="ZONE_RESOURCE_POOL_EXHAUSTED")
        with patch.object(worker, "run_gcloud", side_effect=error) as run:
            with self.assertRaises(subprocess.CalledProcessError):
                worker.create_in_zones(["--zone=a"], {}, ["a", "b"])
            self.assertEqual(run.call_count, 2)

    def test_rendered_gcloud_stockout_message_also_tries_next_zone(self):
        detail = "The zone 'us-central1-a' does not have enough\n  resources available to fulfill the request."
        with patch.object(worker, "run_gcloud", side_effect=[
                subprocess.CalledProcessError(1, "gcloud", stderr=detail),
                subprocess.CompletedProcess([], 0, stdout="created")]) as run:
            worker.create_in_zones(["--zone=a"], {}, ["a", "b"])
            self.assertEqual(run.call_count, 2)

    def test_create_uses_configured_zones_unless_explicitly_pinned(self):
        config = {"GCP_PROJECT_ID": "test", "WOODPECKER_AGENT_SECRET": "secret",
                  "GCP_ZONE": "us-central1-a", "GCP_FALLBACK_ZONES": "us-central1-b, us-central1-c,us-central1-b"}
        for zone, expected in ((None, ["us-central1-a", "us-central1-b", "us-central1-c"]),
                               ("us-central1-f", ["us-central1-f"])):
            args = argparse.Namespace(profile="mutation", project=None, zone=zone, machine_type=None,
                                      labels=None, lifetime=None, name="test-worker")
            with patch.object(worker, "get_config", return_value=config), \
                    patch.object(worker, "generate_headscale_key", return_value="auth"), \
                    patch.object(worker, "create_in_zones", return_value=subprocess.CompletedProcess([], 0, stdout="")) as create:
                self.assertEqual(worker.cmd_create(args), 0)
                self.assertEqual(create.call_args.args[2], expected)

    def test_destroy_discovers_fallback_zone(self):
        result = subprocess.CompletedProcess([], 0, stdout=json.dumps([{"name": "test", "zone": "zones/us-central1-b"}]))
        with patch.object(worker, "get_config", return_value={"GCP_PROJECT_ID": "test"}), \
                patch.object(worker, "run_gcloud", side_effect=[result, subprocess.CompletedProcess([], 0, stdout="")]) as run, \
                patch.object(worker.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, stdout="[]")):
            self.assertEqual(worker.cmd_destroy(argparse.Namespace(project=None, zone=None, name="test")), 0)
            self.assertIn("--zone=us-central1-b", run.call_args_list[1].args[0])

    def test_destroy_already_absent_worker_only_cleans_headscale(self):
        with patch.object(worker, "get_config", return_value={"GCP_PROJECT_ID": "test"}), \
                patch.object(worker, "run_gcloud", return_value=subprocess.CompletedProcess([], 0, stdout="[]")) as run, \
                patch.object(worker.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, stdout="[]")):
            self.assertEqual(worker.cmd_destroy(argparse.Namespace(project=None, zone=None, name="test")), 0)
            self.assertEqual(run.call_count, 1)

    def test_destroy_does_not_guess_when_worker_name_is_ambiguous(self):
        result = subprocess.CompletedProcess([], 0, stdout=json.dumps([
            {"name": "test", "zone": "zones/us-central1-a"}, {"name": "test", "zone": "zones/us-central1-b"}]))
        with patch.object(worker, "get_config", return_value={"GCP_PROJECT_ID": "test"}), \
                patch.object(worker, "run_gcloud", return_value=result) as run:
            with self.assertRaises(RuntimeError):
                worker.cmd_destroy(argparse.Namespace(project=None, zone=None, name="test"))
            self.assertEqual(run.call_count, 1)


if __name__ == "__main__":
    unittest.main()
