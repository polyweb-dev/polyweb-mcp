#!/usr/bin/env python3
"""
GCP Spot VM CI Worker Automation for Woodpecker CI & Headscale.

Zero external dependencies - uses standard library only.
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_ENV_FILE = SCRIPT_DIR / ".env"
HEADSCALE_COMPOSE = Path("/home/administrator/headscale/docker-compose.yml")
WOODPECKER_ENV = Path("/home/administrator/Programs/woodpecker/.env")
HEADSCALE_URL = "https://headscale.thiocyanate.dev"
TAILSCALE_SERVER_TARGET = "100.64.0.2:9000"

PROFILES: dict[str, dict[str, Any]] = {
    "standard": {
        "machine_type": "c3d-highcpu-8",
        "labels": "size=standard,provider=gcp,spot=true",
        "lifetime": 60,
    },
    "mutation": {
        "machine_type": "n2-standard-64",
        "regions": "asia-south2,europe-west8,us-south1",
        "labels": "size=heavy,provider=gcp,spot=true",
        "lifetime": 30,
    },
}


def load_env_file(path: Path) -> dict[str, str]:
    """Parse a simple KEY=VALUE or KEY="VALUE" .env file."""
    env: dict[str, str] = {}
    if not path.is_file():
        return env

    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if "=" in stripped:
                k, v = stripped.split("=", 1)
                k = k.strip()
                v = v.strip().strip("'\"")
                env[k] = v
    return env


def get_config() -> dict[str, str]:
    """Load config from .env with fallback to Woodpecker server secrets."""
    config = load_env_file(DEFAULT_ENV_FILE)

    # Fallback for Woodpecker Agent secret
    if not config.get("WOODPECKER_AGENT_SECRET"):
        wp_env = load_env_file(WOODPECKER_ENV)
        if wp_secret := wp_env.get("WOODPECKER_AGENT_SECRET"):
            config["WOODPECKER_AGENT_SECRET"] = wp_secret

    return config


def run_gcloud(args: list[str], config: dict[str, str], input_data: str | None = None) -> subprocess.CompletedProcess[str]:
    """Execute a gcloud command, either natively or via Docker if gcloud is not in PATH."""
    gcloud_bin = shutil.which("gcloud")

    if gcloud_bin:
        cmd = [gcloud_bin] + args
    else:
        # Fall back to Docker containerized gcloud
        gcloud_config_dir = Path.home() / ".config" / "gcloud"
        gcloud_config_dir.mkdir(parents=True, exist_ok=True)
        cmd = [
            "docker", "run", "--rm", "-i",
            "-v", f"{gcloud_config_dir}:/root/.config/gcloud",
        ]
        # If service account key is referenced, mount its parent directory
        sa_key = config.get("GCP_SERVICE_ACCOUNT_KEY")
        if sa_key and Path(sa_key).is_file():
            sa_path = Path(sa_key).resolve()
            cmd.extend(["-v", f"{sa_path}:{sa_path}:ro"])

        cmd.extend(["google/cloud-sdk:alpine", "gcloud"])
        cmd.extend(args)

    return subprocess.run(cmd, input=input_data, text=True, capture_output=True, check=True)


def generate_headscale_key() -> str:
    """Generate a single-use, ephemeral Headscale pre-auth key tagged tag:ci-worker."""
    cmd = [
        "docker", "compose", "-f", str(HEADSCALE_COMPOSE),
        "exec", "-T", "headscale",
        "headscale", "preauthkeys", "create",
        "--user", "1",
        "--tags", "tag:ci-worker",
        "--ephemeral",
        "--expiration", "1h",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    key = result.stdout.strip()
    if not key:
        raise RuntimeError(f"Headscale returned empty preauthkey. Stderr: {result.stderr}")
    return key


def create_in_zones(args: list[str], config: dict[str, str], zones: list[str]) -> subprocess.CompletedProcess[str]:
    """Retry capacity failures or move to another region after a regional CPU quota failure."""
    quota_regions: set[str] = set()
    for index, zone in enumerate(zones):
        region = zone.rsplit("-", 1)[0]
        if region in quota_regions:
            continue
        zoned_args = [f"--zone={zone}" if arg.startswith("--zone=") else arg for arg in args]
        print(f"[*] Trying zone {zone}...")
        try:
            return run_gcloud(zoned_args, config)
        except subprocess.CalledProcessError as error:
            detail = error.stderr or ""
            print(detail, file=sys.stderr)
            # Some gcloud versions render the canonical message without the code.
            capacity_error = (
                "ZONE_RESOURCE_POOL_EXHAUSTED" in detail
                or "does not have enough resources available to fulfill the request" in " ".join(detail.split())
            )
            regional_cpu_quota = (
                "quota" in detail.lower() and "exceeded" in detail.lower()
                and "region" in detail.lower() and "cpu" in detail.lower()
                and "CPUS_ALL_REGIONS" not in detail
            )
            if regional_cpu_quota:
                quota_regions.add(region)
            next_zones = [candidate for candidate in zones[index + 1:]
                          if candidate.rsplit("-", 1)[0] not in quota_regions]
            if not (capacity_error or regional_cpu_quota) or not next_zones:
                raise
            print(f"[*] {'Regional CPU quota exceeded' if regional_cpu_quota else 'No capacity'} in {zone}; trying {next_zones[0]}.")
    raise ValueError("At least one worker zone is required")


def worker_zones(config: dict[str, str], profile: str | None, explicit_zone: str | None) -> list[str]:
    """Keep standard zone settings separate from mutation's preferred regions."""
    if explicit_zone:
        return [explicit_zone]
    if profile == "mutation":
        regions = list(dict.fromkeys(region.strip() for region in config.get(
            "GCP_MUTATION_REGIONS", PROFILES["mutation"]["regions"]).split(",") if region.strip()))
        result = run_gcloud([
            "compute", "zones", "list", f"--project={config['GCP_PROJECT_ID']}",
            "--filter=status=UP", "--format=json(name,region)",
        ], config)
        available = json.loads(result.stdout)
        zones = []
        for region in regions:
            matches = sorted(item["name"] for item in available
                             if item["region"].rsplit("/", 1)[-1] == region)
            if matches:
                zones.append(matches[0])
            else:
                print(f"[*] No available Compute zone in preferred region {region}; skipping it.")
        if not zones:
            raise RuntimeError("No Compute zones available in the configured mutation regions")
        return zones
    return list(dict.fromkeys([config.get("GCP_ZONE", "us-central1-a")] + [
        zone.strip() for zone in config.get("GCP_FALLBACK_ZONES", "").split(",") if zone.strip()
    ]))


def generate_startup_script(
    instance_name: str,
    preauth_key: str,
    agent_secret: str,
    agent_labels: str,
    max_lifetime_min: int,
) -> str:
    """Join the tailnet and start the agent using a pre-baked worker image."""
    if max_lifetime_min <= 0:
        raise ValueError("Worker lifetime must be positive")
    return f"""#!/usr/bin/env bash
set -euo pipefail
printf 'CI_WORKER_BOOTSTRAP_START uptime=%s\\n' "$(cut -d' ' -f1 /proc/uptime)"

# A systemd timer survives the startup script and bounds worker runtime.
systemd-run --unit=ci-worker-lifetime --on-active={max_lifetime_min}m /usr/sbin/poweroff
systemctl start docker tailscaled

tailscale up \\
  --login-server={shlex.quote(HEADSCALE_URL)} \\
  --authkey={shlex.quote(preauth_key)} \\
  --hostname={shlex.quote(instance_name)} \\
  --accept-routes=false \\
  --timeout=60s

# Startup metadata can run again after a reboot. Replace the old container.
docker rm -f woodpecker-agent >/dev/null 2>&1 || true
docker run -d \\
  --name woodpecker-agent \\
  --hostname={shlex.quote(instance_name)} \\
  --restart unless-stopped \\
  --pull=never \\
  -v /var/run/docker.sock:/var/run/docker.sock \\
  -e {shlex.quote("WOODPECKER_SERVER=" + TAILSCALE_SERVER_TARGET)} \\
  -e {shlex.quote("WOODPECKER_AGENT_SECRET=" + agent_secret)} \\
  -e {shlex.quote("WOODPECKER_AGENT_LABELS=" + agent_labels)} \\
  woodpeckerci/woodpecker-agent:v3
printf 'CI_WORKER_AGENT_STARTED uptime=%s\\n' "$(cut -d' ' -f1 /proc/uptime)"
"""


def cmd_create(args: argparse.Namespace) -> int:
    """Provision a new GCP Spot instance."""
    config = get_config()

    # Apply profile defaults if specified
    profile_cfg = PROFILES.get(getattr(args, "profile", None) or "")
    default_machine = profile_cfg["machine_type"] if profile_cfg else config.get("GCP_MACHINE_TYPE", "c3d-highcpu-8")
    if getattr(args, "profile", None) == "mutation":
        default_machine = config.get("GCP_MUTATION_MACHINE_TYPE", default_machine)
    default_labels = profile_cfg["labels"] if profile_cfg else config.get("WOODPECKER_AGENT_LABELS", "size=standard,provider=gcp,spot=true")
    default_lifetime = profile_cfg["lifetime"] if profile_cfg else int(config.get("MAX_VM_LIFETIME_MINUTES", "120"))

    project_id = args.project or config.get("GCP_PROJECT_ID")
    machine_type = args.machine_type or default_machine
    disk_size = config.get("GCP_BOOT_DISK_SIZE", "50GB")
    image_family = config.get("GCP_IMAGE_FAMILY", "woodpecker-ci-worker")
    image_project = config.get("GCP_IMAGE_PROJECT", "polyweb-513423")
    agent_labels = args.labels or default_labels
    lifetime_min = int(args.lifetime or default_lifetime)

    agent_secret = config.get("WOODPECKER_AGENT_SECRET")

    if not project_id or project_id == "your-gcp-project-id":
        print(f"Error: GCP_PROJECT_ID is not configured in {DEFAULT_ENV_FILE} or --project flag.", file=sys.stderr)
        return 1

    if not agent_secret:
        print("Error: WOODPECKER_AGENT_SECRET could not be found.", file=sys.stderr)
        return 1

    # Optional service account authentication
    sa_key = config.get("GCP_SERVICE_ACCOUNT_KEY")
    if sa_key and Path(sa_key).is_file():
        print("[*] Activating GCP service account...")
        run_gcloud([
            "auth", "activate-service-account",
            f"--key-file={sa_key}",
            f"--project={project_id}",
        ], config)

    zones = worker_zones({**config, "GCP_PROJECT_ID": project_id}, getattr(args, "profile", None), args.zone)
    zone = zones[0]
    instance_name = args.name or f"gcp-worker-{int(time.time())}"

    print(f"[*] Generating ephemeral Headscale pre-auth key for '{instance_name}'...")
    preauth_key = generate_headscale_key()

    print(f"[*] Generating bootstrap cloud-init script (safety watchdog: {lifetime_min}m)...")
    startup_content = generate_startup_script(
        instance_name=instance_name,
        preauth_key=preauth_key,
        agent_secret=agent_secret,
        agent_labels=agent_labels,
        max_lifetime_min=lifetime_min,
    )

    with tempfile.NamedTemporaryFile("w", prefix="startup-", suffix=".sh", delete=False) as tmp:
        tmp.write(startup_content)
        tmp_path = Path(tmp.name)

    try:
        print(f"[*] Provisioning GCP Spot VM '{instance_name}' ({machine_type}) in {zone}...")
        gcloud_args = [
            "compute", "instances", "create", instance_name,
            f"--project={project_id}",
            f"--zone={zone}",
            f"--machine-type={machine_type}",
            "--provisioning-model=SPOT",
            "--instance-termination-action=DELETE",
            f"--image-family={image_family}",
            f"--image-project={image_project}",
            f"--boot-disk-size={disk_size}",
            "--boot-disk-type=pd-balanced",
            f"--metadata-from-file=startup-script={tmp_path}",
            "--labels=role=ci-worker,managed-by=woodpecker",
        ]
        res = create_in_zones(gcloud_args, config, zones)
        print(res.stdout)
        print("=" * 70)
        print(f"[SUCCESS] Spot worker '{instance_name}' created successfully.")
        print(f"Labels: {agent_labels}")
        print("Tailscale & Woodpecker Agent are bootstrapping in the background.")
        print("=" * 70)
    finally:
        tmp_path.unlink(missing_ok=True)

    return 0


def cmd_list(args: argparse.Namespace) -> int:
    """List all active GCP spot CI workers."""
    config = get_config()
    project_id = args.project or config.get("GCP_PROJECT_ID")
    if not project_id or project_id == "your-gcp-project-id":
        print("Error: GCP_PROJECT_ID not configured.", file=sys.stderr)
        return 1

    gcloud_args = [
        "compute", "instances", "list",
        f"--project={project_id}",
        "--filter=labels.role=ci-worker",
        "--format=table(name,zone,machineType,status,creationTimestamp)",
    ]
    res = run_gcloud(gcloud_args, config)
    print(res.stdout)
    return 0


def cmd_destroy(args: argparse.Namespace) -> int:
    """Destroy a GCP spot instance and clean up Headscale state."""
    config = get_config()
    project_id = args.project or config.get("GCP_PROJECT_ID")

    if not project_id:
        print("Error: GCP_PROJECT_ID not configured.", file=sys.stderr)
        return 1

    instance_name = args.name
    # Resolve the actual zone rather than assuming the primary zone after fallback.
    result = run_gcloud([
        "compute", "instances", "list", f"--project={project_id}",
        f"--filter=name={instance_name} AND labels.role=ci-worker", "--format=json(name,zone)",
    ], config)
    matches = [item for item in json.loads(result.stdout) if item["name"] == instance_name]
    if args.zone:
        matches_in_zone = [item for item in matches if item["zone"].rsplit("/", 1)[-1] == args.zone]
        if matches and not matches_in_zone:
            raise RuntimeError(f"Worker {instance_name} exists in a different zone; omit --zone to discover it")
        matches = matches_in_zone
    if len(matches) > 1:
        raise RuntimeError(f"Multiple workers named {instance_name}; specify --zone")
    if matches:
        zone = matches[0]["zone"].rsplit("/", 1)[-1]
        print(f"[*] Deleting GCP instance '{instance_name}' in zone {zone}...")
        res = run_gcloud([
            "compute", "instances", "delete", instance_name,
            f"--project={project_id}", f"--zone={zone}", "--quiet",
        ], config)
        print(res.stdout)
    else:
        print(f"[*] GCP worker '{instance_name}' is already absent; checking Headscale state.")

    # Check Headscale for leftover node record
    print(f"[*] Checking Headscale nodes for '{instance_name}'...")
    try:
        nodes_res = subprocess.run([
            "docker", "compose", "-f", str(HEADSCALE_COMPOSE),
            "exec", "-T", "headscale",
            "headscale", "nodes", "list", "-o", "json",
        ], capture_output=True, text=True, check=True)
        nodes: list[dict[str, Any]] = json.loads(nodes_res.stdout)
        for n in nodes:
            if n.get("name") == instance_name or n.get("givenName") == instance_name:
                node_id = n.get("id")
                print(f"[*] Purging node ID {node_id} from Headscale...")
                subprocess.run([
                    "docker", "compose", "-f", str(HEADSCALE_COMPOSE),
                    "exec", "-T", "headscale",
                    "headscale", "nodes", "delete", "-i", str(node_id), "--force",
                ], check=False)
    except Exception as e:
        print(f"Notice: Headscale node cleanup check skipped: {e}")

    print(f"[SUCCESS] Worker '{instance_name}' destroyed.")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    """Show status of Headscale nodes on the tailnet."""
    subprocess.run([
        "docker", "compose", "-f", str(HEADSCALE_COMPOSE),
        "exec", "-T", "headscale",
        "headscale", "nodes", "list",
    ], check=True)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="GCP Spot CI Worker Management for Woodpecker & Headscale",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # create
    p_create = subparsers.add_parser("create", help="Provision a new GCP Spot CI worker")
    p_create.add_argument("--profile", choices=["standard", "mutation"], help="Preset profile (standard: c3d-highcpu-8 / size=standard; mutation: n2-standard-64 / size=heavy)")
    p_create.add_argument("--name", help="Custom instance name (default: auto-timestamped)")
    p_create.add_argument("--project", help="GCP Project ID (overrides .env)")
    p_create.add_argument("--zone", help="GCP Zone (overrides .env)")
    p_create.add_argument("--machine-type", help="Machine type (e.g. e2-standard-4)")
    p_create.add_argument("--labels", help="Woodpecker agent labels (e.g. 'size=large,provider=gcp')")
    p_create.add_argument("--lifetime", type=int, help="Max lifetime in minutes before auto-shutdown")
    p_create.set_defaults(func=cmd_create)

    # list
    p_list = subparsers.add_parser("list", help="List active GCP spot workers")
    p_list.add_argument("--project", help="GCP Project ID (overrides .env)")
    p_list.set_defaults(func=cmd_list)

    # destroy
    p_destroy = subparsers.add_parser("destroy", help="Destroy a GCP spot worker")
    p_destroy.add_argument("name", help="Instance name to delete")
    p_destroy.add_argument("--project", help="GCP Project ID (overrides .env)")
    p_destroy.add_argument("--zone", help="GCP Zone (overrides .env)")
    p_destroy.set_defaults(func=cmd_destroy)

    # status
    p_status = subparsers.add_parser("status", help="Show Headscale tailnet nodes")
    p_status.set_defaults(func=cmd_status)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
