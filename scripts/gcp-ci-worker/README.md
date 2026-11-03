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
