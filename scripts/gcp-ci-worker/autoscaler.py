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

# Fixed policy: no CI job (Woodpecker workflow) runs longer than an hour. The
# job wrapper and the VM deadline normally end it first; this server-side
# check catches a workflow whose agent vanished, which Woodpecker otherwise
# shows as running indefinitely (pipeline 205 ran for 24 hours that way).
JOB_LIMIT_SECONDS = 60 * 60
# A VM is deleted by GCP at 60 minutes; anything still tracked later is stale.
WORKER_MAX_AGE_SECONDS = JOB_LIMIT_SECONDS + 5 * 60
REAP_INTERVAL_SECONDS = 60
REAP_LOOKBACK_SECONDS = 3 * 24 * 60 * 60
REAP_MAX_PAGES = 5


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


def api_request(server_url: str, token: str, path: str, method: str = "GET") -> Any:
    """Call the Woodpecker REST API and return the decoded JSON body (or None)."""
    url = f"{server_url.rstrip('/')}{path}"
    req = urllib.request.Request(
        url,
        method=method,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "User-Agent": "gcp-ci-autoscaler/1.0",
        },
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        body = resp.read()
    return json.loads(body.decode("utf-8")) if body.strip() else None


def fetch_queue_info(server_url: str, token: str) -> dict[str, Any] | None:
    """Query Woodpecker /api/queue/info."""
    try:
        result = api_request(server_url, token, "/api/queue/info")
        if not isinstance(result, dict):
            raise ValueError("Queue response must be an object")
        return result
    except urllib.error.HTTPError as e:
        if e.code == 401:
            logger.error("Authentication failed: WOODPECKER_API_TOKEN is invalid or unauthorized.")
        else:
            logger.error("HTTP error querying queue info: %s %s", e.code, e.reason)
    except Exception as e:
        logger.error("Error connecting to Woodpecker server at %s: %s", server_url, e)
    return None


def overdue_workflows(pipeline: dict[str, Any], now: float, limit: int) -> list[dict[str, Any]]:
    """Workflows still marked running after the fixed job limit."""
    return [
        workflow
        for workflow in pipeline.get("workflows") or []
        if workflow.get("state") == "running"
        and workflow.get("started")
        and now - workflow["started"] >= limit
    ]


def reap_overdue_pipelines(
    server_url: str, token: str, now: float, limit: int = JOB_LIMIT_SECONDS
) -> list[tuple[int, int]]:
    """Cancel every pipeline that has a workflow running past the fixed job limit.

    Woodpecker enforces timeouts on the agent, so a workflow whose agent or VM
    disappeared stays "running" on the server forever. Returns (repo id,
    pipeline number) pairs that were cancelled.
    """
    cancelled: list[tuple[int, int]] = []
    for repo in api_request(server_url, token, "/api/user/repos") or []:
        if not repo.get("active", True):
            continue
        repo_id = repo["id"]
        for page in range(1, REAP_MAX_PAGES + 1):
            pipelines = api_request(
                server_url,
                token,
                f"/api/repos/{repo_id}/pipelines?page={page}&perPage=50&per_page=50",
            )
            if not pipelines:
                break
            for summary in pipelines:
                if summary.get("status") != "running" or not summary.get("started"):
                    continue
                if now - summary["started"] < limit:
                    continue
                number = summary["number"]
                pipeline = api_request(
                    server_url, token, f"/api/repos/{repo_id}/pipelines/{number}"
                )
                overdue = overdue_workflows(pipeline or {}, now, limit)
                if not overdue:
                    continue
                for workflow in overdue:
                    logger.error(
                        "CI_TIME_LIMIT_EXCEEDED: %s pipeline %s workflow '%s' has been running "
                        "%d minutes, past the fixed %d-minute CI job limit (agent %s). "
                        "Cancelling the pipeline; rerun it if the stall was intermittent.",
                        repo.get("full_name", repo_id),
                        number,
                        workflow.get("name"),
                        (now - workflow["started"]) // 60,
                        limit // 60,
                        workflow.get("agent_id"),
                    )
                try:
                    api_request(
                        server_url,
                        token,
                        f"/api/repos/{repo_id}/pipelines/{number}/cancel",
                        method="POST",
                    )
                    cancelled.append((repo_id, number))
                except Exception as e:
                    logger.error("Could not cancel pipeline %s: %s", number, e)
            if min(p.get("created") or now for p in pipelines) < now - REAP_LOOKBACK_SECONDS:
                break
    return cancelled


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
    for name, worker in list(workers.items()):
        age = now - worker.get("created_at", now)
        if age >= WORKER_MAX_AGE_SECONDS:
            # GCP deletes the VM at 60 minutes; never keep or protect it longer.
            logger.error(
                "CI_TIME_LIMIT_EXCEEDED: worker '%s' is %d minutes old, past the fixed "
                "%d-minute limit; deleting it.",
                name,
                age // 60,
                JOB_LIMIT_SECONDS // 60,
            )
            retire_worker(name, workers, state)
            busy.discard(name)
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
    last_reap = 0.0

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

        if time.time() - last_reap >= REAP_INTERVAL_SECONDS:
            last_reap = time.time()
            try:
                reap_overdue_pipelines(server_url, token, last_reap)
            except Exception as e:
                logger.error("Overdue pipeline check failed: %s", e)

        # Sleep for poll interval
        for _ in range(poll_interval):
            if not RUNNING:
                break
            time.sleep(1)

    logger.info("Autoscaler stopped cleanly.")


if __name__ == "__main__":
    run_loop()
