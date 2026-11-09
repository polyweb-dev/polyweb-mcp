#!/usr/bin/env python3
"""
Woodpecker CI Queue Autoscaler for GCP Spot Workers.

Monitors Woodpecker CI queue via REST API and automatically spins up
Independent Spot instances on GCP for ready workflows,
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
        temporary = STATE_FILE.with_suffix(".tmp")
        with open(temporary, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)
        temporary.replace(STATE_FILE)
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


PROFILE_CPUS = {"standard": 16, "mutation": 64, "combined": 64}


def task_profile(task: dict[str, Any]) -> str | None:
    """Only ready GCP workflows with a supported size request capacity."""
    if label_value(task.get("labels"), "provider") != "gcp":
        return None
    return {"standard": "standard", "heavy": "mutation"}.get(
        label_value(task.get("labels"), "size")
    )


def normalize_workers(state: dict[str, Any]) -> dict[str, Any]:
    """Migrate profile-keyed state without losing ownership of live VMs."""
    workers = {}
    for key, worker in state.setdefault("workers", {}).items():
        worker.setdefault("profile", key)
        workers[worker["name"]] = worker
    state["workers"] = workers
    return workers


def compatible(worker: dict[str, Any], profile: str) -> bool:
    return worker["profile"] in {profile, "combined"}


def retire_worker(name: str, workers: dict[str, Any], state: dict[str, Any]) -> bool:
    if not destroy_worker(name):
        return False
    del workers[name]
    save_state(state)
    return True


def busy_workers(qinfo: dict[str, Any], workers: dict[str, Any]) -> set[str]:
    """Protect named running agents, conservatively handling legacy queue responses."""
    busy = set()
    for task in qinfo.get("running", []) or []:
        name = task.get("agent_name")
        if name in workers:
            busy.add(name)
        elif not name and (profile := task_profile(task)):
            busy.update(name for name, worker in workers.items() if compatible(worker, profile))
    return busy


def make_room(
    workers: dict[str, Any],
    reserved: set[str],
    profile: str,
    state: dict[str, Any],
    max_workers: int,
    max_cpus: int,
) -> bool:
    """Reclaim unused workers when a different size needs the capacity budget."""

    def fits() -> bool:
        cpus = sum(PROFILE_CPUS[w["profile"]] for w in workers.values())
        return len(workers) < max_workers and cpus + PROFILE_CPUS[profile] <= max_cpus

    for name in list(workers):
        if fits():
            return True
        if name not in reserved and not retire_worker(name, workers, state):
            return False
    return fits()


def manage_queue(
    qinfo: dict[str, Any],
    state: dict[str, Any],
    idle_timeout: int,
    now: float,
    max_workers: int = 4,
    max_cpus: int = 64,
    startup_timeout: int = 300,
) -> None:
    """Allocate one capacity-1 agent per ready workflow, including booting agents."""
    if qinfo.get("paused"):
        return
    workers = normalize_workers(state)
    busy = busy_workers(qinfo, workers)
    for name in busy:
        workers[name].update(last_busy=now, seen_running=True)
    for name, worker in list(workers.items()):
        if name in busy:
            continue
        expired = (
            not worker.get("seen_running")
            and now - worker.get("created_at", now) >= startup_timeout
        )
        idle = now - worker.get("last_busy", now) >= idle_timeout
        if expired or idle:
            retire_worker(name, workers, state)

    reserved = set(busy)
    failed_profiles: set[str] = set()
    for task in qinfo.get("pending", []) or []:
        profile = task_profile(task)
        if profile is None:
            continue
        available = next(
            (
                name
                for name, worker in workers.items()
                if name not in reserved and compatible(worker, profile)
            ),
            None,
        )
        if available is not None:
            reserved.add(available)
            workers[available]["last_busy"] = now
            continue
        if profile in failed_profiles or not make_room(
            workers, reserved, profile, state, max_workers, max_cpus
        ):
            continue
        # Names remain unique for several allocations in the same poll and after restart.
        name = f"gcp-spot-{profile}-{time.time_ns()}"
        if not spawn_worker(profile, name):
            failed_profiles.add(profile)
            continue
        workers[name] = {"name": name, "profile": profile, "created_at": now, "last_busy": now}
        reserved.add(name)
        save_state(state)
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
            manage_queue(
                qinfo,
                state,
                idle_timeout,
                time.time(),
                max_workers=max(1, int(config.get("MAX_WORKERS", "4"))),
                max_cpus=max(1, int(config.get("MAX_TOTAL_CPUS", "64"))),
                startup_timeout=max(1, int(config.get("WORKER_STARTUP_TIMEOUT_SECONDS", "300"))),
            )

        # Sleep for poll interval
        for _ in range(poll_interval):
            if not RUNNING:
                break
            time.sleep(1)

    logger.info("Autoscaler stopped cleanly.")


if __name__ == "__main__":
    run_loop()
