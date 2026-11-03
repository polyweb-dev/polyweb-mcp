# GCP worker image

The image family is `polyweb-513423/woodpecker-ci-worker`.
The base image is Ubuntu 24.04 AMD64.
Docker CE and Tailscale start at boot.
The Docker cache contains these images:

- `woodpeckerci/woodpecker-agent:v3`
- `ghcr.io/astral-sh/uv:python3.12-bookworm-slim`

The builder never receives agent credentials or Headscale credentials.
The preparation script removes machine identity and Tailscale state before capture.
The build script stops the VM, creates the image, and deletes the VM and disk.
The image tags resolve at bake time. Rebuild the image to receive updates.

## Create an image from the VPS

Use an authenticated `gcloud` CLI with Compute instance, disk, and image permissions.
The builder uses no service account.

```bash
GCP_PROJECT_ID=polyweb-513423 GCP_ZONE=us-central1-a \
  bash scripts/gcp-ci-worker/build-image.sh woodpecker-worker-v2
```

Use a new image name for each build.
The script waits up to 20 minutes for package installation and Docker downloads.
Its exit trap deletes the builder after success or failure.
After an interrupted host or CI process, check for VMs with `role=ci-image-builder`.
Delete any abandoned builder and its boot disk.

## Create an image through Woodpecker

The `.woodpecker/image-builder.yaml` workflow accepts only a `deployment` event on `feature/project` with target `worker-image`.
Ordinary manual test pipelines do not select this workflow.

1. Create a repository secret named `gcp_image_builder_key` with a service account JSON key.
2. Restrict the secret to deployment events and the `google/cloud-sdk:stable` image.
3. Give that account Compute instance, disk, and image permissions in `polyweb-513423`.
4. Create a deployment for `feature/project` with target `worker-image` through the Woodpecker UI or API.

This workflow requires a GCP worker.
For the first image, use the VPS command above.
The local VPS credentials suffice for that command. The CI secret is optional until you use the deployment workflow.

## Install the worker CLI

The repository copy of `worker.py` preserves the live CLI.
The autoscaler continues to call `/home/administrator/Programs/gcp-ci-worker/worker.py`.

```bash
python3 scripts/gcp-ci-worker/test_worker.py
install -m 755 scripts/gcp-ci-worker/worker.py /home/administrator/Programs/gcp-ci-worker/worker.py
```

Set `GCP_IMAGE_FAMILY="woodpecker-ci-worker"` and `GCP_IMAGE_PROJECT="polyweb-513423"` in the private `.env`.
Use `worker.env.example` as a reference. Keep the other values and credentials.
The autoscaler reads configuration each cycle. The CLI reads it for each new worker.

The startup script joins Headscale and starts the cached agent.
It performs no package installation or Docker image pull.
A systemd timer shuts the worker down after the configured lifetime.
The autoscaler deletes idle workers after its idle timeout.

## Mutation workers

The mutation profile uses `n2-standard-64` Spot VMs with the `size=heavy` label.
Set `GCP_MUTATION_MACHINE_TYPE="n2-standard-64"` and `GCP_MUTATION_REGIONS="asia-south2,us-south1"` in the private `.env`.

The CLI checks available Compute zones in region order: Delhi (`asia-south2`), then Dallas (`us-south1`).
It selects the first available zone in each region.
If the API lists no zone for a preferred region, the CLI skips that region.
An explicit `--zone` selects one zone without region discovery.

On 2026-11-03, the Compute API confirmed Delhi zones `asia-south2-a`, `asia-south2-b`, and `asia-south2-c`.
The previous Phoenix preference had no available Compute zones for this project.
The Dallas N2 CPU quota was 200, with a total regional CPU quota of 100.
Both reported zero usage before the allocation attempt.
The N2 machine type has 64 vCPUs and 256 GiB of memory.
The standard profile uses `c3d-highcpu-8` and its separate Iowa zone configuration.

The single N2 allocation attempt on 2026-11-03 selected `us-south1-a` after the Phoenix availability check.
GCP rejected it with `CPUS_ALL_REGIONS`: the global CPU quota was 32.
The request required 64 vCPUs. The mutation suite did not start.

A sufficient global CPU quota is required before another attempt.
No second allocation attempt or pipeline restart occurred.

## Standard worker capacity fallback

Set `GCP_FALLBACK_ZONES="us-central1-b,us-central1-c,us-central1-f"` in the private `.env`.
The worker CLI tries `GCP_ZONE` first, then each fallback zone in order.
These zones use the Iowa regional price schedule.
The Compute API confirmed `c3d-highcpu-60` support in all four zones on 2026-11-03.
Machine type support does not guarantee free Spot capacity.

Only a `ZONE_RESOURCE_POOL_EXHAUSTED` error or its canonical resource shortage message triggers another zone attempt.
Permission, configuration, global quota, and connection errors stop the request.
Regional CPU quota errors skip other zones in that region.
They permit a subsequent attempt in a different configured region.
The Iowa-only standard configuration stops on regional quota errors.

An explicit `create --zone` selects one zone and disables fallback.
The CLI reuses the startup script and Headscale key after confirmed capacity failures.

The `destroy` command finds the worker zone through the Compute API.
It does not assume the primary zone.
If GCP already removed the Spot VM, the CLI still checks Headscale state.
If multiple worker VMs have the same name, use `destroy --zone` to select one.

The live check on 2026-11-03 exhausted capacity in `us-central1-a` and `us-central1-b`.
The next attempt in `us-central1-c` returned `CPUS_PER_VM_FAMILY` with a regional C3D limit of 24.
The former C3D mutation profile required 60 CPUs. A zone change cannot bypass a regional quota.

Request a sufficient family quota before another 60-core C3D mutation run.
Allow quota for the standard worker too if both profiles must run concurrently.
The CLI stopped at the quota error. No test VM or disk remained.

## Verify a new image

1. Trigger the `api-unit` workflow on `feature/project` through Woodpecker.
2. Confirm that the autoscaler creates a GCP worker from the new image.
3. Check the Headscale node and the Woodpecker agent connection.
4. Compare the serial log markers `CI_WORKER_BOOTSTRAP_START` and `CI_WORKER_AGENT_STARTED` with VM creation time.
5. Confirm that the workflow succeeds.
6. Wait for the idle timeout and confirm that the VM, boot disk, and Headscale node disappear.

The markers use kernel uptime. They do not include GCP allocation time.
Measure API connection time separately. Do not assume a 12–15 second boot time.

To restore an earlier golden image, deprecate the new family member. You can also select another image family in the private configuration.
The fast startup script requires a golden image. A stock Ubuntu image requires the previous installation script.

References: [GCP custom images](https://docs.cloud.google.com/compute/docs/images/create-custom),
[Woodpecker workflow syntax](https://woodpecker-ci.org/docs/usage/workflow-syntax),
[Woodpecker API](https://woodpecker-ci.org/api).
Regional prices: [GCP Spot VM prices](https://cloud.google.com/spot-vms/pricing).
