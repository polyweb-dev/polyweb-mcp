#!/usr/bin/env python3
"""
Woodpecker CI Queue Autoscaler for GCP Spot Workers.

Monitors Woodpecker CI queue via REST API and automatically spins up
Spot instances (standard / mutation / combined) on GCP when workflows are queued,
and tears them down when builds finish.

Zero external dependencies - Python stdlib only.
"""

from __future__ import annotations

import json
import logging
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
ENV_FILE = SCRIPT_DIR / ".env"
STATE_FILE = SCRIPT_DIR / ".autoscaler_state.json"
WORKER_SCRIPT = SCRIPT_DIR / "worker.py"

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("gcp-ci-autoscaler")

RUNNING = True


def signal_handler(signum: int, frame: Any) -> None:
    global RUNNING
    logger.info("Received termination signal, shutting down autoscaler loop...")
    RUNNING = False


signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)


def load_env() -> dict[str, str]:
    """Parse .env file."""
    config: dict[str, str] = {}
    if not ENV_FILE.is_file():
        return config
    with open(ENV_FILE, encoding="utf-8") as f:
        for line in f:
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if "=" in stripped:
                k, v = stripped.split("=", 1)
                config[k.strip()] = v.strip().strip("'\"")
    return config


def load_state() -> dict[str, Any]:
    """Load tracked workers state from disk."""
    if not STATE_FILE.is_file():
        return {"workers": {}}
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            state = json.load(f)
            if not isinstance(state, dict):
                raise ValueError("Autoscaler state must be an object")
            return state
    except Exception as e:
        logger.warning("Could not read %s, starting fresh state: %s", STATE_FILE, e)
        return {"workers": {}}


def save_state(state: dict[str, Any]) -> None:
    """Save tracked workers state to disk."""
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)
    except Exception as e:
        logger.error("Failed to write state file %s: %s", STATE_FILE, e)


def fetch_queue_info(server_url: str, token: str) -> dict[str, Any] | None:
    """Query Woodpecker /api/queue/info."""
    url = f"{server_url.rstrip('/')}/api/queue/info"
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "User-Agent": "gcp-ci-autoscaler/1.0",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            if resp.status == 200:
                data = resp.read()
                result = json.loads(data.decode("utf-8"))
                if not isinstance(result, dict):
                    raise ValueError("Queue response must be an object")
                return result
    except urllib.error.HTTPError as e:
        if e.code == 401:
            logger.error("Authentication failed: WOODPECKER_API_TOKEN is invalid or unauthorized.")
        else:
            logger.error("HTTP error querying %s: %s %s", url, e.code, e.reason)
    except Exception as e:
        logger.error("Error connecting to Woodpecker server at %s: %s", url, e)
    return None


def spawn_worker(profile: str, instance_name: str) -> bool:
    """Launch worker.py create --profile <profile> --name <name>."""
    logger.info("Spawning GCP Spot worker '%s' with profile '%s'...", instance_name, profile)
    cmd = [
        sys.executable,
        str(WORKER_SCRIPT),
        "create",
        "--profile",
        profile,
        "--name",
        instance_name,
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, check=True)
        logger.info("Worker '%s' provisioned successfully.\n%s", instance_name, proc.stdout)
        return True
    except subprocess.CalledProcessError as e:
        logger.error(
            "Failed to provision worker '%s':\nStdout: %s\nStderr: %s",
            instance_name,
            e.stdout,
            e.stderr,
        )
        return False


def destroy_worker(instance_name: str) -> bool:
    """Launch worker.py destroy <name>."""
    logger.info("Destroying GCP Spot worker '%s'...", instance_name)
    cmd = [
        sys.executable,
        str(WORKER_SCRIPT),
        "destroy",
        instance_name,
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, check=True)
        logger.info("Worker '%s' destroyed successfully.\n%s", instance_name, proc.stdout)
        return True
    except subprocess.CalledProcessError as e:
        logger.error(
            "Failed to destroy worker '%s':\nStdout: %s\nStderr: %s",
            instance_name,
            e.stdout,
            e.stderr,
        )
        return False


def label_value(task_labels: Any, key: str) -> str:
    """Read labels from current API maps and legacy list/string forms."""
    if isinstance(task_labels, dict):
        return str(task_labels.get(key, ""))
    entries = task_labels.split(",") if isinstance(task_labels, str) else task_labels
    if isinstance(entries, list):
        for item in entries:
            label, separator, value = str(item).partition("=")
            if separator and label.strip() == key:
                return value.strip()
    return ""


def pipeline_key(task: dict[str, Any]) -> str:
    """Scope a combined allocation to one repository and pipeline."""
    if task.get("repo_id") and task.get("pipeline_id"):
        return f"{task['repo_id']}:{task['pipeline_id']}"
    return ""


def queue_demand(
    qinfo: dict[str, Any],
    workers: dict[str, Any],
) -> tuple[dict[str, dict[str, bool]], list[str]]:
    """Keep mixed pipelines on one wildcard 64-vCPU worker until all tasks finish."""
    tasks = [
        task
        for state in ("pending", "waiting_on_deps", "running")
        for task in qinfo.get(state, []) or []
        if label_value(task.get("labels"), "provider") == "gcp"
    ]
    alive = {pipeline_key(task) for task in tasks} - {""}
    combined = set(workers.get("combined", {}).get("pipelines", [])) & alive
    sizes: dict[str, set[str]] = {}
    for task in tasks:
        key = pipeline_key(task)
        if key:
            sizes.setdefault(key, set()).add(label_value(task.get("labels"), "size"))
    combined.update(key for key, values in sizes.items() if {"heavy", "standard"} <= values)
    demand = {
        profile: {"pending": False, "running": False}
        for profile in ("combined", "mutation", "standard")
    }
    for state in ("pending", "running"):
        for task in qinfo.get(state, []) or []:
            if label_value(task.get("labels"), "provider") != "gcp":
                continue
            size = label_value(task.get("labels"), "size")
            if size not in {"standard", "heavy"}:
                continue
            profile = (
                "combined"
                if pipeline_key(task) in combined
                else ("mutation" if size == "heavy" else "standard")
            )
            demand[profile][state] = True
    return demand, sorted(combined)


def manage_queue(
    qinfo: dict[str, Any], state: dict[str, Any], idle_timeout: int, now: float
) -> None:
    if qinfo.get("paused"):
        return
    workers = state.setdefault("workers", {})
    demand, combined_pipelines = queue_demand(qinfo, workers)
    for profile, size in (("standard", "standard"), ("mutation", "heavy")):
        if profile in workers and any(
            task.get("agent_name") == workers[profile]["name"]
            or (not task.get("agent_name") and label_value(task.get("labels"), "size") == size)
            for task in qinfo.get("running", []) or []
        ):
            demand[profile]["running"] = True
    # Release idle incompatible workers before a new profile consumes CPU quota.
    # Never terminate an active workflow or a worker needed by another pipeline.
    if any(flags["pending"] and profile not in workers for profile, flags in demand.items()):
        for profile in list(workers):
            if profile in demand and not any(demand[profile].values()):
                if not destroy_worker(workers[profile]["name"]):
                    return
                del workers[profile]
                save_state(state)
    for profile, flags in demand.items():
        manage_profile_worker(
            profile, flags["pending"], flags["running"], workers, idle_timeout, now, state
        )
    if "combined" in workers:
        workers["combined"]["pipelines"] = combined_pipelines
        save_state(state)


def manage_profile_worker(
    profile: str,
    has_pending: bool,
    has_running: bool,
    workers: dict[str, Any],
    idle_timeout: int,
    now: float,
    state: dict[str, Any],
) -> None:
    worker = workers.get(profile)
    if has_pending:
        if not worker:
            name = f"gcp-spot-{profile}-{int(now)}"
            if spawn_worker(profile, name):
                workers[profile] = {
                    "name": name,
                    "profile": profile,
                    "created_at": now,
                    "last_busy": now,
                }
                save_state(state)
        else:
            worker["last_busy"] = now
            save_state(state)
    elif worker:
        if has_running:
            worker["last_busy"] = now
            save_state(state)
        else:
            idle_time = now - worker.get("last_busy", now)
            if idle_time >= idle_timeout:
                logger.info(
                    "%s worker '%s' idle for %.0fs (threshold: %ds). Triggering teardown.",
                    profile.capitalize(),
                    worker["name"],
                    idle_time,
                    idle_timeout,
                )
                if destroy_worker(worker["name"]):
                    del workers[profile]
                    save_state(state)


def run_loop() -> None:
    logger.info("Starting GCP Spot CI Autoscaler service...")
    state = load_state()

    while RUNNING:
        config = load_env()
        server_url = config.get("WOODPECKER_SERVER_URL", "http://127.0.0.1:8000")
        token = config.get("WOODPECKER_API_TOKEN", "").strip()
        poll_interval = int(config.get("POLL_INTERVAL_SECONDS", "5"))
        idle_timeout = int(config.get("IDLE_TIMEOUT_SECONDS", "120"))

        if not token:
            logger.warning(
                "WOODPECKER_API_TOKEN is not set in %s. Waiting for token to be configured...",
                ENV_FILE,
            )
            time.sleep(poll_interval * 2)
            continue

        qinfo = fetch_queue_info(server_url, token)
        if qinfo is not None:
            manage_queue(qinfo, state, idle_timeout, time.time())

        # Sleep for poll interval
        for _ in range(poll_interval):
            if not RUNNING:
                break
            time.sleep(1)

    logger.info("Autoscaler stopped cleanly.")


if __name__ == "__main__":
    run_loop()
