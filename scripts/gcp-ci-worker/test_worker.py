"""Isolated checks for generated startup commands. No cloud or Docker access."""

import argparse
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import worker


class BootstrapTests(unittest.TestCase):
    def test_bootstrap_passes_credentials_as_literal_arguments(self):
        secret = "space ' quote; $(touch /tmp/ci-bootstrap-injection)"
        script = worker.generate_startup_script(
            "ci-test", "test-auth", secret, "provider=gcp,size=standard", 15
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            log = root / "calls.jsonl"
            for command in ("systemd-run", "systemctl", "tailscale", "docker"):
                executable = root / command
                executable.write_text(
                    "#!/usr/bin/python3\nimport json, os, sys\n"
                    "with open(os.environ['CALL_LOG'], 'a') as f:\n"
                    "    f.write(json.dumps(sys.argv) + '\\n')\n"
                )
                executable.chmod(0o755)
            subprocess.run(
                ["bash", "-s"],
                input=script,
                text=True,
                check=True,
                capture_output=True,
                env={**os.environ, "PATH": f"{root}:/usr/bin:/bin", "CALL_LOG": str(log)},
            )
            calls = [json.loads(line) for line in log.read_text().splitlines()]
        docker_run = next(
            call for call in calls if Path(call[0]).name == "docker" and call[1] == "run"
        )
        self.assertIn("WOODPECKER_AGENT_SECRET=" + secret, docker_run)
        self.assertIn("--pull=never", docker_run)
        self.assertIn("WOODPECKER_MAX_WORKFLOWS=1", docker_run)
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
                worker.generate_startup_script(
                    "ci-test", "auth", "secret", "provider=gcp", lifetime
                )


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
                env={
                    **os.environ,
                    "PATH": f"{root}:/usr/bin:/bin",
                    "CALL_LOG": str(log),
                    "BAKE_MARKER": marker,
                },
                capture_output=True,
                text=True,
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


class AllocationTests(unittest.TestCase):
    def zone_result(self):
        return subprocess.CompletedProcess(
            [],
            0,
            stdout=json.dumps(
                [
                    {"name": region + suffix, "region": "regions/" + region}
                    for region in [
                        "asia-south2",
                        "us-west4",
                        "northamerica-northeast2",
                        "europe-west8",
                    ]
                    for suffix in ["-b", "-a"]
                ]
            ),
        )

    def test_standard_pairs_follow_screenshot_order_and_all_zones(self):
        with patch.object(worker, "run_gcloud", return_value=self.zone_result()):
            self.assertEqual(
                worker.worker_candidates({"GCP_PROJECT_ID": "test"}, "standard", None),
                [
                    ("n2-highcpu-16", "northamerica-northeast2-a"),
                    ("n2-highcpu-16", "northamerica-northeast2-b"),
                    ("e2-highcpu-16", "us-west4-a"),
                    ("e2-highcpu-16", "us-west4-b"),
                    ("n2-highcpu-16", "asia-south2-a"),
                    ("n2-highcpu-16", "asia-south2-b"),
                ],
            )

    def test_mutation_and_combined_use_same_64cpu_preferences(self):
        with patch.object(worker, "run_gcloud", return_value=self.zone_result()):
            for profile in ["mutation", "combined"]:
                with self.subTest(profile=profile):
                    candidates = worker.worker_candidates({"GCP_PROJECT_ID": "test"}, profile, None)
                    self.assertEqual(
                        [zone for _, zone in candidates],
                        [
                            "northamerica-northeast2-a",
                            "northamerica-northeast2-b",
                            "asia-south2-a",
                            "asia-south2-b",
                            "europe-west8-a",
                            "europe-west8-b",
                        ],
                    )
                    self.assertEqual({machine for machine, _ in candidates}, {"n2-highcpu-64"})

    def test_explicit_zone_disables_discovery_and_machine_override_is_honored(self):
        with patch.object(worker, "run_gcloud") as run:
            self.assertEqual(
                worker.worker_candidates({}, "combined", "custom-a", "custom-64"),
                [("custom-64", "custom-a")],
            )
            run.assert_not_called()

    def test_custom_candidates_and_missing_region(self):
        config = {
            "GCP_PROJECT_ID": "test",
            "GCP_STANDARD_CANDIDATES": "n2-highcpu-16@missing,e2-highcpu-16@us-west4",
        }
        with patch.object(worker, "run_gcloud", return_value=self.zone_result()):
            self.assertEqual(
                worker.worker_candidates(config, "standard", None),
                [("e2-highcpu-16", "us-west4-a"), ("e2-highcpu-16", "us-west4-b")],
            )
        with self.assertRaises(ValueError):
            worker.worker_candidates({"GCP_STANDARD_CANDIDATES": "invalid"}, "standard", None)

    def test_capacity_fallback_changes_machine_and_region_together(self):
        error = subprocess.CalledProcessError(1, "gcloud", stderr="ZONE_RESOURCE_POOL_EXHAUSTED")
        success = subprocess.CompletedProcess([], 0, stdout="created")
        with patch.object(worker, "run_gcloud", side_effect=[error, success]) as run:
            result = worker.create_in_candidates(
                ["--zone=northamerica-northeast2-a", "--machine-type=n2-highcpu-16"],
                {},
                [("n2-highcpu-16", "northamerica-northeast2-a"), ("e2-highcpu-16", "us-west4-a")],
            )
            self.assertIs(result, success)
            self.assertEqual(
                run.call_args.args[0], ["--zone=us-west4-a", "--machine-type=e2-highcpu-16"]
            )

    def test_regional_cpu_quota_skips_region_but_not_other_regions(self):
        error = subprocess.CalledProcessError(
            1, "gcloud", stderr="Quota N2_CPUS exceeded in region northamerica-northeast2"
        )
        with patch.object(
            worker,
            "run_gcloud",
            side_effect=[error, subprocess.CompletedProcess([], 0, stdout="ok")],
        ) as run:
            worker.create_in_candidates(
                ["--zone=first", "--machine-type=first"],
                {},
                [
                    ("n2-highcpu-16", "northamerica-northeast2-a"),
                    ("n2-highcpu-16", "northamerica-northeast2-b"),
                    ("e2-highcpu-16", "us-west4-a"),
                ],
            )
            self.assertEqual(run.call_count, 2)
            self.assertIn("--machine-type=e2-highcpu-16", run.call_args.args[0])

    def test_fatal_errors_do_not_allocate_in_other_regions(self):
        for detail in [
            "PERMISSION_DENIED",
            "connection timed out",
            "INVALID_FIELD_VALUE",
            "Quota CPUS_ALL_REGIONS exceeded in all regions",
        ]:
            with (
                self.subTest(detail=detail),
                patch.object(
                    worker,
                    "run_gcloud",
                    side_effect=subprocess.CalledProcessError(1, "gcloud", stderr=detail),
                ) as run,
            ):
                with self.assertRaises(subprocess.CalledProcessError):
                    worker.create_in_candidates(
                        ["--zone=a", "--machine-type=n2"],
                        {},
                        [("n2", "first-a"), ("e2", "second-a")],
                    )
                self.assertEqual(run.call_count, 1)

    def test_all_capacity_failures_and_empty_candidates_fail(self):
        error = subprocess.CalledProcessError(1, "gcloud", stderr="ZONE_RESOURCE_POOL_EXHAUSTED")
        with patch.object(worker, "run_gcloud", side_effect=error) as run:
            with self.assertRaises(subprocess.CalledProcessError):
                worker.create_in_candidates(
                    ["--zone=a", "--machine-type=n2"], {}, [("n2", "first-a"), ("e2", "second-a")]
                )
            self.assertEqual(run.call_count, 2)
        with self.assertRaises(ValueError):
            worker.create_in_candidates([], {}, [])

    def test_create_preserves_spot_and_profile_labels(self):
        for profile, machine, labels in [
            ("standard", "n2-highcpu-16", "size=standard,provider=gcp,spot=true"),
            ("mutation", "n2-highcpu-64", "size=heavy,provider=gcp,spot=true"),
            ("combined", "n2-highcpu-64", "size=*,provider=gcp,spot=true"),
        ]:
            args = argparse.Namespace(
                profile=profile,
                project=None,
                zone=None,
                machine_type=None,
                labels=None,
                lifetime=None,
                name="test-worker",
            )
            with (
                patch.object(
                    worker,
                    "get_config",
                    return_value={"GCP_PROJECT_ID": "test", "WOODPECKER_AGENT_SECRET": "secret"},
                ),
                patch.object(worker, "worker_candidates", return_value=[(machine, "first-a")]),
                patch.object(worker, "generate_headscale_key", return_value="auth"),
                patch.object(
                    worker, "generate_startup_script", return_value="#!/bin/bash\n"
                ) as startup,
                patch.object(
                    worker,
                    "create_in_candidates",
                    return_value=subprocess.CompletedProcess([], 0, stdout=""),
                ) as create,
            ):
                self.assertEqual(worker.cmd_create(args), 0)
                self.assertIn("--machine-type=" + machine, create.call_args.args[0])
                self.assertIn("--provisioning-model=SPOT", create.call_args.args[0])
                self.assertEqual(startup.call_args.kwargs["agent_labels"], labels)


class DestroyTests(unittest.TestCase):
    def test_destroy_discovers_fallback_zone(self):
        result = subprocess.CompletedProcess(
            [], 0, stdout=json.dumps([{"name": "test", "zone": "zones/us-central1-b"}])
        )
        with (
            patch.object(worker, "get_config", return_value={"GCP_PROJECT_ID": "test"}),
            patch.object(
                worker,
                "run_gcloud",
                side_effect=[result, subprocess.CompletedProcess([], 0, stdout="")],
            ) as run,
            patch.object(
                worker.subprocess,
                "run",
                return_value=subprocess.CompletedProcess([], 0, stdout="[]"),
            ),
        ):
            self.assertEqual(
                worker.cmd_destroy(argparse.Namespace(project=None, zone=None, name="test")), 0
            )
            self.assertIn("--zone=us-central1-b", run.call_args_list[1].args[0])

    def test_destroy_already_absent_worker_only_cleans_headscale(self):
        with (
            patch.object(worker, "get_config", return_value={"GCP_PROJECT_ID": "test"}),
            patch.object(
                worker, "run_gcloud", return_value=subprocess.CompletedProcess([], 0, stdout="[]")
            ) as run,
            patch.object(
                worker.subprocess,
                "run",
                return_value=subprocess.CompletedProcess([], 0, stdout="[]"),
            ),
        ):
            self.assertEqual(
                worker.cmd_destroy(argparse.Namespace(project=None, zone=None, name="test")), 0
            )
            self.assertEqual(run.call_count, 1)

    def test_destroy_does_not_guess_when_worker_name_is_ambiguous(self):
        result = subprocess.CompletedProcess(
            [],
            0,
            stdout=json.dumps(
                [
                    {"name": "test", "zone": "zones/us-central1-a"},
                    {"name": "test", "zone": "zones/us-central1-b"},
                ]
            ),
        )
        with (
            patch.object(worker, "get_config", return_value={"GCP_PROJECT_ID": "test"}),
            patch.object(worker, "run_gcloud", return_value=result) as run,
        ):
            with self.assertRaises(RuntimeError):
                worker.cmd_destroy(argparse.Namespace(project=None, zone=None, name="test"))
            self.assertEqual(run.call_count, 1)


if __name__ == "__main__":
    unittest.main()
