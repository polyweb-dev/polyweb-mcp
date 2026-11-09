# Golden image verification, 2026-11-03

- Project: `polyweb-513423`
- Zone: `us-central1-a`
- Image: `woodpecker-worker-v1`
- Family: `woodpecker-ci-worker`
- Status: `READY`

The build used `e2-standard-4` and Ubuntu `ubuntu-2404-noble-amd64-v20261024`.
The build stopped the builder before capture and deleted its VM and boot disk after capture.

The image contains these Docker references:

```text
woodpeckerci/woodpecker-agent:v3
sha256:a7d7299a13add0b3936fa0ac9ed23507fe283a7fc7d9596c4289d7e8206541eb

ghcr.io/astral-sh/uv:python3.12-bookworm-slim
sha256:e5b65587bce7de595f299855d7385fe7fca39b8a74baa261ba1b7147afa78e58
```

The queue autoscaler created `gcp-spot-standard-1793668462` for a manual `api-unit` run.
The Spot VM used `c3d-highcpu-8`.
Its boot disk identified `woodpecker-worker-v1` as its source image.
Live inspection confirmed enabled Docker and Tailscale services and both image digests above.

The Woodpecker agent was healthy. Headscale reported the ephemeral worker online at `100.64.0.6`.
The `ci-worker-lifetime.timer` deadline was 02:15:17 UTC, 60 minutes after startup.

[Pipeline 9](https://woodpecker.thiocyanate.dev/repos/1/pipeline/9) passed on agent 4.
Its commit was `fafed8c08c3395a60367faea953d6440a0a071b7` on `feature/project`.
The unit test result was `2073 passed, 1 warning in 26.05s`.
The workflow, with clone and dependency setup, took 40 seconds.

The VM creation timestamp was 01:14:27.272 UTC.
The VM last-start timestamp was 01:14:57.850 UTC.
The startup log recorded `CI_WORKER_BOOTSTRAP_START uptime=16.47` at 01:15:17 UTC.
It recorded `CI_WORKER_AGENT_STARTED uptime=19.75` at 01:15:20 UTC.
Woodpecker started the workflow at 01:15:21 UTC and finished it at 01:16:01 UTC.

The bootstrap commands took 3.28 seconds.
The agent started at 19.75 seconds of kernel uptime, approximately 53 seconds after VM creation.
This run did not meet the estimated 12–15 second boot time.
The systemd critical chain placed Docker startup at 14.09 seconds of userspace time.
GCP allocation and OS startup remain part of total readiness time.

The autoscaler detected 120 seconds of idle time at 01:18:00 UTC.
It completed VM deletion and Headscale node cleanup at 01:18:54 UTC.
Final GCP instance and disk lists were empty.
Headscale retained only the server bridge. The autoscaler service remained active with no tracked workers.

Five isolated automation checks passed on the VPS without cloud API calls or application test execution.
Bash syntax, YAML validation, whitespace checks, and documentation structural checks passed.
The local VPS agent remained stopped throughout verification.

The optional image-builder deployment workflow requires the `gcp_image_builder_key` repository secret.
This run used the authenticated VPS CLI. It did not add a service account key to Woodpecker.
