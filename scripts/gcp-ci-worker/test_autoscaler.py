"""Queue selection checks with no cloud allocation or daemon execution."""

import unittest
from unittest.mock import patch

import autoscaler


def task(size, pipeline=1, repo=1, provider="gcp"):
    return {
        "repo_id": repo,
        "pipeline_id": pipeline,
        "labels": {"size": size, "provider": provider},
    }


class QueueTests(unittest.TestCase):
    def test_standalone_standard_and_mutation(self):
        for size, profile in [("standard", "standard"), ("heavy", "mutation")]:
            with self.subTest(size=size):
                demand, pipelines = autoscaler.queue_demand({"pending": [task(size)]}, {})
                self.assertTrue(demand[profile]["pending"])
                self.assertFalse(demand["combined"]["pending"])
                self.assertEqual(pipelines, [])

    def test_same_pipeline_uses_one_combined_worker(self):
        state = {"workers": {}}
        with (
            patch.object(autoscaler, "spawn_worker", return_value=True) as spawn,
            patch.object(autoscaler, "save_state"),
        ):
            autoscaler.manage_queue(
                {"pending": [task("heavy"), task("standard")]}, state, 120, 1000
            )
        self.assertEqual(spawn.call_count, 1)
        self.assertEqual(spawn.call_args.args[0], "combined")
        self.assertEqual(state["workers"]["combined"]["pipelines"], ["1:1"])

    def test_unrelated_pipelines_are_not_mistaken_for_combined_run(self):
        demand, pipelines = autoscaler.queue_demand(
            {"pending": [task("heavy", pipeline=1), task("standard", pipeline=2)]}, {}
        )
        self.assertTrue(demand["mutation"]["pending"])
        self.assertTrue(demand["standard"]["pending"])
        self.assertEqual(pipelines, [])

    def test_repository_identity_is_part_of_pipeline_identity(self):
        _, pipelines = autoscaler.queue_demand(
            {"pending": [task("heavy", repo=1), task("standard", repo=2)]}, {}
        )
        self.assertEqual(pipelines, [])

    def test_dependency_waiting_tasks_participate_in_combined_detection(self):
        demand, pipelines = autoscaler.queue_demand(
            {"pending": [task("standard")], "waiting_on_deps": [task("heavy")]}, {}
        )
        self.assertTrue(demand["combined"]["pending"])
        self.assertFalse(demand["standard"]["pending"])
        self.assertEqual(pipelines, ["1:1"])

    def test_combined_assignment_survives_mutation_completion_and_restart(self):
        workers = {"combined": {"pipelines": ["1:1"]}}
        demand, pipelines = autoscaler.queue_demand({"pending": [task("standard")]}, workers)
        self.assertTrue(demand["combined"]["pending"])
        self.assertFalse(demand["standard"]["pending"])
        self.assertEqual(pipelines, ["1:1"])

    def test_other_providers_and_missing_pipeline_ids_do_not_create_combined_assignment(self):
        demand, pipelines = autoscaler.queue_demand(
            {
                "pending": [
                    task("heavy", provider="other"),
                    task("heavy", pipeline=None),
                    task("standard", pipeline=None),
                ]
            },
            {},
        )
        self.assertFalse(demand["combined"]["pending"])
        self.assertEqual(pipelines, [])

    def test_running_combined_tasks_keep_worker_busy(self):
        state = {
            "workers": {"combined": {"name": "combined-vm", "pipelines": ["1:1"], "last_busy": 1}}
        }
        with (
            patch.object(autoscaler, "destroy_worker") as destroy,
            patch.object(autoscaler, "save_state"),
        ):
            autoscaler.manage_queue({"running": [task("standard")]}, state, 120, 1000)
        destroy.assert_not_called()
        self.assertEqual(state["workers"]["combined"]["last_busy"], 1000)

    def test_idle_combined_worker_is_destroyed_after_timeout(self):
        state = {
            "workers": {"combined": {"name": "combined-vm", "pipelines": ["1:1"], "last_busy": 1}}
        }
        with (
            patch.object(autoscaler, "destroy_worker", return_value=True) as destroy,
            patch.object(autoscaler, "save_state"),
        ):
            autoscaler.manage_queue({}, state, 120, 1000)
        destroy.assert_called_once_with("combined-vm")
        self.assertEqual(state["workers"], {})

    def test_failed_destruction_keeps_worker_tracked(self):
        state = {"workers": {"standard": {"name": "standard-vm", "last_busy": 1}}}
        with (
            patch.object(autoscaler, "destroy_worker", return_value=False),
            patch.object(autoscaler, "save_state"),
        ):
            autoscaler.manage_queue({}, state, 120, 1000)
        self.assertIn("standard", state["workers"])

    def test_idle_standard_worker_is_released_before_combined_allocation(self):
        state = {"workers": {"standard": {"name": "idle16", "last_busy": 999}}}
        calls = []
        with (
            patch.object(
                autoscaler,
                "destroy_worker",
                side_effect=lambda name: calls.append("destroy") or True,
            ),
            patch.object(
                autoscaler, "spawn_worker", side_effect=lambda *args: calls.append("spawn") or True
            ),
            patch.object(autoscaler, "save_state"),
        ):
            autoscaler.manage_queue(
                {"pending": [task("heavy"), task("standard")]}, state, 120, 1000
            )
        self.assertEqual(calls, ["destroy", "spawn"])
        self.assertNotIn("standard", state["workers"])

    def test_busy_standard_worker_is_not_destroyed_for_combined_run(self):
        state = {"workers": {"standard": {"name": "busy16", "last_busy": 999}}}
        with (
            patch.object(autoscaler, "destroy_worker") as destroy,
            patch.object(autoscaler, "spawn_worker", return_value=True),
            patch.object(autoscaler, "save_state"),
        ):
            autoscaler.manage_queue(
                {
                    "pending": [task("heavy"), task("standard")],
                    "running": [task("standard", pipeline=2)],
                },
                state,
                120,
                3000,
            )
        destroy.assert_not_called()

    def test_idle_combined_worker_is_released_before_new_standalone_run(self):
        state = {
            "workers": {"combined": {"name": "idle64", "last_busy": 999, "pipelines": ["1:1"]}}
        }
        calls = []
        with (
            patch.object(
                autoscaler,
                "destroy_worker",
                side_effect=lambda name: calls.append("destroy") or True,
            ),
            patch.object(
                autoscaler, "spawn_worker", side_effect=lambda *args: calls.append("spawn") or True
            ),
            patch.object(autoscaler, "save_state"),
        ):
            autoscaler.manage_queue({"pending": [task("standard", pipeline=2)]}, state, 120, 1000)
        self.assertEqual(calls, ["destroy", "spawn"])
        self.assertNotIn("combined", state["workers"])
        self.assertIn("standard", state["workers"])

    def test_paused_queue_does_not_provision(self):
        with patch.object(autoscaler, "spawn_worker") as spawn:
            autoscaler.manage_queue({"paused": True, "pending": [task("standard")]}, {}, 120, 1000)
        spawn.assert_not_called()


if __name__ == "__main__":
    unittest.main()
