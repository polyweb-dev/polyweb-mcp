# CI report archive

Open [CI reports](https://woodpecker.thiocyanate.dev/artifacts/) after login to Woodpecker.
The page permits Woodpecker administrators to download and delete report bundles.
The page uses the Woodpecker session cookie. It also accepts a Woodpecker API token for API access.
Each row links to its pipeline and shows the workflow, commit, result, and ZIP contents.

Select **Download ZIP** to receive a bundle.
Extract the ZIP before you open its HTML report.
Select **Confirm deletion**, then **Delete bundle**, to remove one bundle permanently.
The archive does not automatically delete old bundles.

The files live on the VPS at:

```text
/home/administrator/Programs/woodpecker-artifacts/data/
  <pipeline-number>--<workflow>.zip
  <pipeline-number>--<workflow>.json
```

The JSON beside the ZIP contains server metadata. It is not the mutation JSON report.
The ZIP contains the original report files and `artifact-manifest.json`.
The service rejects duplicate pipeline/workflow bundles to preserve the original record.
The archive accepts bundles up to 100 MiB, with a total ZIP storage limit of 5 GiB.
Delete old bundles through the page when storage reaches this limit.

## Pipeline reports

The mutation workflow requests console, HTML, and JSON output.
Its bundle contains `coverage/gremlins/`, `mutation-tests.log`, and any `test_reports/` files from its baseline.
The latency workflow bundle contains `test_reports/` and `routing-latency-tests.log`.
This preserves Markdown, CSV, PNG, and other report files recursively.
Test scope and parallel worker counts remain the same.

Both workflows run `upload-reports` after success or failure.
The upload step prints an authenticated download URL and the archive page URL.
It uses Python from the base image, so dependency installation failure does not prevent upload.
If no report exists after an early failure, the bundle contains a manifest.
The test command retains its failure exit code even when upload succeeds.

A forced cancellation, Spot preemption, or VM shutdown can prevent upload step execution.
Files that the test tool did not produce cannot appear in the archive.
Run 13 contains only the console log and pipeline metadata recovered before this archive existed.
Its original mutation JSON was no longer available after workspace cleanup.

## Service configuration

The service source is `server.py`. It uses only the Python standard library.
The systemd unit is `woodpecker-artifacts.service`.
The installed source and private configuration live in `/home/administrator/Programs/woodpecker-artifacts/`.
The `.env` file has mode 0600 and contains:

```text
ARTIFACT_PORT=9080
ARTIFACT_ROOT=/home/administrator/Programs/woodpecker-artifacts/data
ARTIFACT_PUBLIC_URL=https://woodpecker.thiocyanate.dev
ARTIFACT_ALTERNATE_ORIGINS=https://ci.thiocyanate.dev
WOODPECKER_URL=http://127.0.0.1:8000
ARTIFACT_UPLOAD_TOKEN=<private upload-only credential>
WOODPECKER_API_TOKEN=<private server-side token for pipeline verification>
```

The upload credential is a separate random value in the private service configuration.
The repository secret `ci_artifact_upload_token` supplies it only to manual runs and the `ghcr.io/astral-sh/uv` image.
The image filter omits the tag because this Woodpecker version rejects dots in secret image tags.
The upload credential cannot download or delete reports.
The server-side API token never enters a CI step.

Install or update the source and systemd unit with these commands:

```bash
install -m 644 scripts/ci-artifacts/server.py /home/administrator/Programs/woodpecker-artifacts/server.py
install -m 644 scripts/ci-artifacts/woodpecker-artifacts.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now woodpecker-artifacts
systemctl --user restart woodpecker-artifacts
```

Preserve the private `.env` and `data/` directory during updates.
For recovery on another VPS, restore these files from a private backup and restore the repository secret.

The service listens only on `127.0.0.1:9080`.
Caddy proxies `/artifacts` and `/artifacts/*` under the Woodpecker hostnames to that listener.
Use `Caddyfile.snippet` inside the hostname block, then validate and reload Caddy.
Other paths continue to the Woodpecker server on port 8000.

CI uploads use `http://100.64.0.2:9010` over the encrypted private Tailnet.
The Tailscale bridge forwards port 9010 to `127.0.0.1:9080`.
Its persistent serve configuration matches `tailscale-serve.json`.
The Headscale ACL permits `tag:ci-worker` to reach `tag:server:9000` and `tag:server:9010`.
The upload path does not depend on the DNS configuration of the browser hostname.

All downloads are attachments. The service does not execute reports or serve uploaded HTML under the Woodpecker origin.
It validates upload credentials, pipeline/workflow identity, ZIP paths, and archive sizes.
Deletion requires an administrator session, an allowed Origin, a CSRF token, and explicit confirmation.

## Verification

```bash
python3 scripts/ci-artifacts/test_artifacts.py
systemctl --user status woodpecker-artifacts
journalctl --user -u woodpecker-artifacts --no-pager -n 30
```

Select the `artifact-smoke` workflow for a small GCP upload check.
Set its manual variable `ARTIFACT_SMOKE_FAIL=1` to verify upload after a deliberate failure.
The workflow is expected to fail in this mode while its upload step succeeds.
Download its ZIP and delete the synthetic bundle through the reports page.

References: [Woodpecker plugins](https://woodpecker-ci.org/docs/usage/plugins/overview),
[steps after failure](https://woodpecker-ci.org/docs/usage/workflow-syntax),
[mutation report formats](https://pytest-gremlins.readthedocs.io/en/stable/guide/reports/).
