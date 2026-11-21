"""Autoscaler capacity and lifecycle checks without cloud allocation."""

import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import autoscaler


def task(size="standard", name=None, provider="gcp"):
    return {"labels": {"size": size, "provider": provider}, "agent_name": name}


def worker(name="vm", profile="standard", **extra):
    return {"name": name, "profile": profile, "created_at": 900, "last_busy": 990, **extra}


class QueueTests(unittest.TestCase):
    def setUp(self):
        self.spawn = self.enterContext(patch.object(autoscaler, "spawn_worker", return_value=True))
        self.destroy = self.enterContext(
            patch.object(autoscaler, "destroy_worker", return_value=True)
        )
        self.enterContext(patch.object(autoscaler, "save_state"))

    def manage(self, queue, state=None, now=1000, **limits):
        if state is None:
            state = {"workers": {}}
        autoscaler.manage_queue(queue, state, 120, now, **limits)
        return state

    def test_two_standard_workflows_get_separate_vms(self):
        state = self.manage({"pending": [task(), task()]})
        self.assertEqual(self.spawn.call_count, 2)
        self.assertEqual(len(state["workers"]), 2)
        self.assertEqual({w["profile"] for w in state["workers"].values()}, {"standard"})

    def test_mixed_pipeline_is_no_longer_serialized_on_combined_worker(self):
        state = self.manage({"pending": [task("heavy"), task()]}, max_cpus=80)
        self.assertEqual(
            {w["profile"] for w in state["workers"].values()}, {"mutation", "standard"}
        )

    def test_booting_workers_are_counted_across_polls_and_restart(self):
        queue = {"pending": [task(), task()]}
        state = self.manage(queue)
        restored = copy.deepcopy(state)
        self.manage(queue, restored, now=1005)
        self.assertEqual(self.spawn.call_count, 2)

    def test_running_worker_does_not_cover_pending_capacity(self):
        state = {"workers": {"vm": worker()}}
        self.manage({"running": [task(name="vm")], "pending": [task()]}, state)
        self.spawn.assert_called_once()
        self.destroy.assert_not_called()
        self.assertTrue(state["workers"]["vm"]["seen_running"])

    def test_named_running_worker_is_protected_even_for_unrecognized_labels(self):
        state = {"workers": {"vm": worker(last_busy=1)}}
        self.manage({"running": [task(provider="other", name="vm")]}, state)
        self.destroy.assert_not_called()

    def test_legacy_profile_keyed_state_preserves_active_worker(self):
        state = {"workers": {"standard": worker(last_busy=1)}}
        self.manage({"running": [task(name="vm")]}, state)
        self.assertEqual(set(state["workers"]), {"vm"})
        self.spawn.assert_not_called()
        self.destroy.assert_not_called()

    def test_legacy_combined_worker_without_profile_can_drain(self):
        state = {"workers": {"combined": {"name": "old", "last_busy": 1}}}
        self.manage({"running": [task(name="old")]}, state)
        self.destroy.assert_not_called()
        self.assertEqual(state["workers"]["old"]["profile"], "combined")

    def test_legacy_running_response_without_agent_name_is_conservative(self):
        state = {"workers": {"standard": worker(last_busy=1)}}
        self.manage({"running": [task()]}, state)
        self.destroy.assert_not_called()

    def test_worker_count_cap(self):
        state = self.manage({"pending": [task()] * 5}, max_workers=2)
        self.assertEqual(len(state["workers"]), 2)

    def test_cpu_budget_limits_standard_workers(self):
        state = self.manage({"pending": [task()] * 5}, max_cpus=32)
        self.assertEqual(len(state["workers"]), 2)

    def test_heavy_workflow_waits_for_busy_standard_worker_to_finish(self):
        state = {"workers": {"vm": worker()}}
        self.manage({"running": [task(name="vm")], "pending": [task("heavy")]}, state)
        self.spawn.assert_not_called()
        self.destroy.assert_not_called()

    def test_idle_incompatible_worker_is_reclaimed_to_fit_heavy_workflow(self):
        state = {"workers": {"vm": worker()}}
        self.manage({"pending": [task("heavy")]}, state)
        self.destroy.assert_called_once_with("vm")
        self.spawn.assert_called_once()
        self.assertEqual(self.spawn.call_args.args[0], "mutation")

    def test_idle_matching_worker_is_reused(self):
        self.manage({"pending": [task()]}, {"workers": {"vm": worker()}})
        self.spawn.assert_not_called()
        self.destroy.assert_not_called()

    def test_dependent_and_other_provider_workflows_do_not_allocate(self):
        self.manage(
            {"waiting_on_deps": [task()], "pending": [task(provider="other"), task("unknown")]}
        )
        self.spawn.assert_not_called()

    def test_paused_queue_does_not_change_workers(self):
        state = {"workers": {"vm": worker(last_busy=1)}}
        before = copy.deepcopy(state)
        self.manage({"paused": True, "pending": [task()]}, state)
        self.assertEqual(state, before)
        self.spawn.assert_not_called()
        self.destroy.assert_not_called()

    def test_completed_worker_is_deleted_after_idle_timeout(self):
        state = {"workers": {"vm": worker(last_busy=1, seen_running=True)}}
        self.manage({}, state)
        self.destroy.assert_called_once_with("vm")
        self.assertEqual(state["workers"], {})

    def test_failed_destruction_keeps_worker_tracked(self):
        self.destroy.return_value = False
        state = {"workers": {"vm": worker(last_busy=1)}}
        self.manage({}, state)
        self.assertIn("vm", state["workers"])

    def test_failed_reclamation_does_not_exceed_budget(self):
        self.destroy.return_value = False
        self.manage({"pending": [task("heavy")]}, {"workers": {"vm": worker()}})
        self.spawn.assert_not_called()

    def test_failed_provision_does_not_track_phantom_workers_or_retry_same_poll(self):
        self.spawn.return_value = False
        state = self.manage({"pending": [task()] * 3})
        self.spawn.assert_called_once()
        self.assertEqual(state["workers"], {})

    def test_worker_that_never_connects_is_replaced_after_startup_deadline(self):
        state = {"workers": {"vm": worker(created_at=500)}}
        self.manage({"pending": [task()]}, state)
        self.destroy.assert_called_once_with("vm")
        self.spawn.assert_called_once()
        self.assertNotIn("vm", state["workers"])

    def test_live_worker_is_not_deleted_at_startup_deadline(self):
        state = {"workers": {"vm": worker(created_at=1, last_busy=1)}}
        self.manage({"running": [task(name="vm")]}, state)
        self.destroy.assert_not_called()


class TimeLimitTests(unittest.TestCase):
    def setUp(self):
        self.destroy = self.enterContext(
            patch.object(autoscaler, "destroy_worker", return_value=True)
        )
        self.enterContext(patch.object(autoscaler, "spawn_worker", return_value=True))
        self.enterContext(patch.object(autoscaler, "save_state"))

    def test_worker_past_the_fixed_limit_is_deleted_even_while_busy(self):
        now = 10_000
        old = worker(created_at=now - autoscaler.WORKER_MAX_AGE_SECONDS, last_busy=now)
        state = {"workers": {"vm": old}}
        autoscaler.manage_queue({"running": [task(name="vm")]}, state, 120, now)
        self.destroy.assert_called_once_with("vm")
        self.assertEqual(state["workers"], {})

    def test_busy_worker_inside_the_limit_is_kept(self):
        now = 10_000
        state = {"workers": {"vm": worker(created_at=now - 50 * 60, last_busy=now)}}
        autoscaler.manage_queue({"running": [task(name="vm")]}, state, 120, now)
        self.destroy.assert_not_called()

    def pipeline(self, number, started, workflows, status="running", created=None):
        return {
            "number": number,
            "status": status,
            "started": started,
            "created": created or started,
            "workflows": workflows,
        }

    def reap(self, pipelines, now):
        """Run the reaper against a fake API; return cancel calls."""
        details = {p["number"]: p for p in pipelines}
        calls = []

        def fake(server, token, path, method="GET"):
            calls.append((method, path))
            if path == "/api/user/repos":
                return [{"id": 1, "full_name": "org/repo", "active": True}]
            if "?page=1&" in path:
                return [{k: v for k, v in p.items() if k != "workflows"} for p in pipelines]
            if "?page=" in path:
                return []
            if method == "POST":
                return None
            return details[int(path.rsplit("/", 1)[1])]

        with patch.object(autoscaler, "api_request", side_effect=fake):
            cancelled = autoscaler.reap_overdue_pipelines("http://ci", "token", now)
        return cancelled, [path for method, path in calls if method == "POST"]

    def test_workflow_running_past_an_hour_cancels_its_pipeline(self):
        now = 100_000
        stuck = {"name": "api-bdd", "state": "running", "started": now - 3600}
        done = {"name": "api-unit", "state": "success", "started": now - 3600}
        cancelled, posts = self.reap([self.pipeline(205, now - 3700, [stuck, done])], now)
        self.assertEqual(cancelled, [(1, 205)])
        self.assertEqual(posts, ["/api/repos/1/pipelines/205/cancel"])

    def test_long_pipeline_whose_workflows_are_each_short_is_left_alone(self):
        # Workflows that waited for capacity: the pipeline is old, each job is not.
        now = 100_000
        late = {"name": "api-mutation", "state": "running", "started": now - 20 * 60}
        cancelled, posts = self.reap([self.pipeline(7, now - 90 * 60, [late])], now)
        self.assertEqual((cancelled, posts), ([], []))

    def test_recent_and_finished_pipelines_are_not_fetched_or_cancelled(self):
        now = 100_000
        recent = self.pipeline(8, now - 600, [{"state": "running", "started": now - 600}])
        finished = self.pipeline(9, now - 9000, [], status="killed")
        cancelled, posts = self.reap([recent, finished], now)
        self.assertEqual((cancelled, posts), ([], []))


class StateTests(unittest.TestCase):
    def test_saved_state_can_be_loaded_without_partial_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            state = {"workers": {"vm": worker()}}
            with patch.object(autoscaler, "STATE_FILE", path):
                autoscaler.save_state(state)
                self.assertEqual(autoscaler.load_state(), state)
                self.assertFalse(path.with_suffix(".tmp").exists())


if __name__ == "__main__":
    unittest.main()
