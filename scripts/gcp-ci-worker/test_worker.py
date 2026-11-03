"""Isolated checks for generated startup commands. No cloud or Docker access."""
import json
import os
import subprocess
import tempfile
import unittest
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


if __name__ == "__main__":
    unittest.main()
