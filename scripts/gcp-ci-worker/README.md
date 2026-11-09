# GCP Spot workers for Woodpecker CI

These scripts create GCP Spot VMs for Woodpecker workflows and delete idle workers.
Each agent accepts one workflow at a time.
The autoscaler creates separate worker capacity for independent ready workflows.

## Files

- `worker.py`: create, list, inspect, and delete workers.
- `autoscaler.py`: allocate workers from the Woodpecker queue.
- `worker.env.example`: configuration template with placeholders.
- `prepare-image.sh`: prepare the worker image.
- `build-image.sh`: create the image and remove the temporary builder.
- `test_worker.py` and `test_autoscaler.py`: unit tests with mocked cloud operations.

## Prerequisites

Use Python 3 and an authenticated `gcloud` CLI on the control host.
The GCP account requires Compute instance, disk, and image permissions.
Worker creation also requires access to the Headscale administration container.
The worker network must reach Headscale and the Woodpecker agent endpoint.

Review the deployment constants in `worker.py` before installation on another host.
These constants include the container configuration path, agent endpoint, and secret fallback path.
Also review the defaults in the image scripts and the image-builder workflow.
Keep deployment-specific values and operational records in a private runbook outside the repository.

## Configuration

Install the worker CLI and autoscaler in the same private directory.
Both scripts read `.env` from that directory.
The autoscaler reads configuration on each poll. The worker CLI reads configuration for each command.

On the first installation, create `.env` from `worker.env.example`.
Replace every placeholder before use.
Restrict the file to the service account with filesystem permissions such as `chmod 600`.
Preserve the private file on subsequent updates.

Configure these values:

| Variable | Purpose |
| --- | --- |
| `GCP_PROJECT_ID` | Project for worker VMs |
| `GCP_IMAGE_PROJECT` | Project that contains the worker image |
| `GCP_IMAGE_FAMILY` | Worker image family |
| `GCP_STANDARD_CANDIDATES` | Ordered standard machine and region pairs |
| `GCP_HEAVY_CANDIDATES` | Ordered heavy machine and region pairs |
| `GCP_BOOT_DISK_SIZE` | Worker boot disk size |
| `WOODPECKER_SERVER_URL` | Server URL for the queue API |
| `WOODPECKER_API_TOKEN` | API credential with queue access |
| `WOODPECKER_AGENT_SECRET` | Credential for agent registration |
| `GCP_SERVICE_ACCOUNT_KEY` | Optional local path to a service account key |

Use comma-separated `machine@region` pairs for each candidate list.
The CLI tries all available zones in each region before the next candidate.
Capacity shortages and regional CPU quota failures permit fallback.
A regional CPU quota failure skips the other zones in that region.
Permission failures and global CPU quota failures stop allocation.

An explicit `--zone` disables fallback.
An explicit `--machine-type` overrides the machine for each preferred region.

## Worker capacity

The standard profile uses 16 vCPUs. The mutation profile uses 64 vCPUs.
Keep candidate machine sizes consistent with these CPU budget values.
The CLI retains the combined profile for manual use and compatibility with old workers.
The autoscaler no longer groups mixed pipelines onto one combined worker.

| Variable | Default | Purpose |
| --- | --- | --- |
| `MAX_WORKERS` | `4` | Maximum tracked worker count |
| `MAX_TOTAL_CPUS` | `64` | Maximum total worker vCPUs |
| `POLL_INTERVAL_SECONDS` | `5` | Queue poll interval |
| `IDLE_TIMEOUT_SECONDS` | `120` | Idle period before worker deletion |
| `WORKER_STARTUP_TIMEOUT_SECONDS` | `300` | Deadline for a new worker to accept work |

The CPU budget includes idle VMs and VMs whose agents have not connected.
The default budget permits four standard workers or one mutation worker.
A mutation workflow waits while active standard workers consume the required budget.
The autoscaler can delete unused workers to release capacity for another profile.
It protects workers with active workflows.
GCP quotas and Spot availability can still delay allocation.

Each agent retains `WOODPECKER_MAX_WORKFLOWS=1`.
The autoscaler can reuse a compatible idle VM for another workflow.
Dependent workflows receive capacity only after Woodpecker places them in the ready queue.
A worker that never accepts work receives a replacement after the startup timeout.
The default VM lifetimes are 60 minutes for standard and 30 minutes for mutation.

## Worker image

The image uses Ubuntu 24.04 AMD64 with Docker CE and Tailscale.
It caches the Woodpecker agent and the Python test image.
The preparation script removes machine identity and Tailscale state before image capture.
The builder receives no agent credentials or Headscale credentials.
Image tags resolve at build time. Rebuild the image to receive updates.

Set your project and zone explicitly:

```bash
GCP_PROJECT_ID="<project-id>" GCP_ZONE="<zone>" \
  bash scripts/gcp-ci-worker/build-image.sh "<new-image-name>"
```

Use a unique image name for each build.
The script waits up to 20 minutes for package installation and image downloads.
Its exit trap deletes the builder VM and its boot disk.
After an interrupted build, check for abandoned VMs with the `role=ci-image-builder` label.

For a CI image build, configure `.woodpecker/image-builder.yaml` for your deployment.
Use a branch that its `when` filters accept and the deployment target `worker-image`.
Supply the `gcp_image_builder_key` repository secret with Compute permissions.
Restrict the secret to deployment events and the configured builder image.
The workflow requires an available GCP worker.
For the first image, use the control-host command above.

Worker startup uses the prepared image without package installation or image downloads.
A systemd timer stops each VM after its configured lifetime.
The autoscaler deletes idle VMs and their Headscale nodes.

## Installation and updates

Run the unit tests from the repository root:

```bash
uv run --no-sync python -m unittest discover -s scripts/gcp-ci-worker -p 'test_*.py' -q
```

Before an update, confirm that the queue and tracked worker state are empty.
Stop the autoscaler service before replacement of its executable.
Set the destination to your private installation directory:

```bash
CI_WORKER_DIR="/path/to/ci-worker"
install -m 755 scripts/gcp-ci-worker/worker.py "$CI_WORKER_DIR/worker.py"
install -m 755 scripts/gcp-ci-worker/autoscaler.py "$CI_WORKER_DIR/autoscaler.py"
```

Configure a service to execute `autoscaler.py` with Python 3 from that directory.
Start the service after installation and confirm that it remains active.
Preserve `.env` and `.autoscaler_state.json` on every update.
The state file records worker ownership.
The autoscaler converts old profile keys to VM names and writes state through atomic file replacement.

## Verification

1. Trigger one API workflow and one UI workflow on a remote branch.
2. Confirm that both workflows execute at the same time on separate agents.
3. Confirm that the worker count and total vCPUs remain within the configured limits.
4. Confirm that both workflows and their artifact uploads succeed.
5. Wait for the idle timeout.
6. Confirm that the VMs, boot disks, and Headscale nodes disappear.

For image startup checks, inspect `CI_WORKER_BOOTSTRAP_START` and `CI_WORKER_AGENT_STARTED` in the VM serial log.
These markers use kernel uptime and exclude GCP allocation time.
Measure allocation and agent connection time separately.
Keep deployment-specific measurements and pipeline records in the private runbook.

To restore an earlier image, select another image family or deprecate the current family member.
Worker startup requires a prepared image.

## References

- [GCP custom images](https://docs.cloud.google.com/compute/docs/images/create-custom)
- [GCP Spot VM prices](https://cloud.google.com/spot-vms/pricing)
- [Woodpecker workflow syntax](https://woodpecker-ci.org/docs/usage/workflow-syntax)
- [Woodpecker API](https://woodpecker-ci.org/api)
