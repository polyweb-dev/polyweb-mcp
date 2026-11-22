# CI artifacts in Gitea

The manual backend and UI workflows publish report ZIP files to the Gitea Generic Package Registry.
The source repository remains on GitHub. Woodpecker still uses GitHub.
No artifact service or Git repository in Gitea is necessary.

## Contents

Each ZIP contains `ci-metadata.json` and the available report files.
The metadata includes the workflow, pipeline number, commit, branch, and workflow status.
The archive contains files from `coverage/gremlins` and `test_reports`, plus that workflow's log.
Mutation reports include `coverage/gremlins/index.html` and `coverage/gremlins/gremlins.json`.
The uploader excludes caches, database files, environment files, hidden paths, and symbolic links.

The uploader limits each ZIP to 256 MiB and 2000 source files.
It also limits the total source size to 256 MiB.

An upload failure fails its step. It does not hide an earlier test failure.
The upload step runs after success or failure. It can publish metadata after an early setup failure.
A forced worker shutdown or Spot preemption can prevent the upload step from completion.

## Access

Open <https://gitea.thiocyanate.dev/polyweb/-/packages> through the private network.
Use a Gitea account with package read permission in the `polyweb` organization.
Each workflow uses a package such as `polyweb-api-mutation`, `polyweb-ui-quality`, or `polyweb-ui-bdd`.
Each version contains the pipeline number, rerun count, and a unique upload timestamp.
Download `reports.zip`. Extract the ZIP to open its reports.

The upload step also prints the package URL, download URL, size, and SHA256 checksum.

## Time limit

No CI job may run longer than 60 minutes. Three independent checks enforce it:

1. `run-and-log.sh` gives each test step at most 55 minutes, which leaves time
   for the clone and the upload. On a GCP worker it also stops 2 minutes before
   the VM's own deadline, which matters on a reused VM. A stopped step exits
   with status 124 and prints a `CI_TIME_LIMIT_EXCEEDED` banner, also written
   to the uploaded log. `CI_STEP_TIMEOUT_SECONDS` can lower the limit for one
   step; it cannot raise it.
2. GCP deletes every worker VM 60 minutes after it starts through
   `--max-run-duration`, even if the guest hangs. Before deleting an idle VM,
   the autoscaler marks its agent `no_schedule` and checks the queue again, so
   Woodpecker cannot hand it a workflow while the VM is going away.
3. The autoscaler cancels any pipeline whose workflow has been marked running
   for 60 minutes. Woodpecker applies timeouts on the agent, so a workflow
   whose VM disappeared would otherwise stay running on the server forever.
   The autoscaler journal logs `CI_TIME_LIMIT_EXCEEDED` with the pipeline and
   workflow.

A stall is often intermittent. Rerun the pipeline once; if the same step stops
again, the last lines before the banner show what hung.

## Test metrics

Every step that uses `run-and-log.sh` records job-level resource use (layer 3)
from its container's cgroup: CPU time and average use of the VM's CPUs, CPU
throttling, peak memory, OOM kills, disk I/O, and pressure stall time. The
summary goes to the step output and `test_reports/ci-metrics/<step>.json`.

Test suites also write JUnit XML (layer 1) to `test_reports/junit/`:
pytest, Behave, Vitest and Playwright. With `POLYWEB_TEST_METRICS=1`:

- pytest adds per-test `metric.*` properties to its JUnit XML: wall time, CPU
  time, CPU-to-wall ratio, memory, and disk I/O (`tests/resource_metrics.py`).
- Vitest writes one JSON line per test to `test_reports/metrics/`: wall time,
  worker thread CPU time, and V8 heap (`polyweb-ui/src/test/resource-metrics.ts`).

Playwright and Behave rely on layer 3, because their work happens in browser,
server, or API processes outside the test runner. All of these files are in
the uploaded report ZIP. `CI_JOB_METRICS=0` turns off the step metrics.

## Credentials and network

The repository secret is `gitea_artifact_upload_token`.
It contains the token for the `ci-upload` account, with `write:package` scope.
Woodpecker exposes it only on manual events. Test steps do not receive this secret.
The secret has no image filter because the upload step executes commands rather than a plugin.
Set `GITEA_PACKAGE_OWNER` as a Woodpecker repository variable when the package
owner differs from `polyweb`. This keeps external package ownership separate
from the application brand and lets an existing package namespace move later.

The package write permission also permits deletion. Do not give this token to untrusted jobs.
Future production image uploads need separate credentials.

The uploader connects directly to tailnet address `100.64.0.2:443`.
It uses `gitea.thiocyanate.dev` for TLS SNI, certificate verification, and the HTTP Host header.
This preserves valid TLS when a Docker step does not use MagicDNS.
The uploader does not use a public fallback, an HTTP proxy, or an insecure TLS option.
It does not follow redirects with credentials.
The upload image uses a digest pin.

## Manual verification

1. Start a new manual pipeline after the configuration commit.
2. Select a test workflow. `ui-quality` gives a compact UI gate. `ui-bdd` runs the stubbed and visual browser suite.
3. Confirm that its `upload-artifacts` step succeeds.
4. Open the package URL from that step.
5. Download the ZIP and inspect `ci-metadata.json` and the test log.

Start a new pipeline rather than restart an old pipeline tied to an earlier commit.
The configuration does not start a pipeline automatically.
Retention rules and a physical storage cap remain separate work.
The current Gitea package quota applies per owner. It does not bound total VPS disk use.

## Local checks

These commands do not start CI jobs or contact Gitea:

```bash
uv run --no-sync --with pyyaml python -m unittest discover -s scripts/ci -p 'test_*.py' -v
uv run --no-sync ruff check scripts/ci
uv run --no-sync mypy --follow-imports=silent scripts/ci/upload_gitea.py
```

The UI jobs use Node 24 for static checks and unit tests, and the official
Playwright image for browser tests. The BDD job runs critical desktop
`@smoke` scenarios. It does not run `@live` or `@mobile` scenarios.

References: [Gitea Generic Package Registry](https://docs.gitea.com/usage/packages/generic/),
[Woodpecker workflow conditions](https://woodpecker-ci.org/docs/usage/workflow-syntax),
[Woodpecker secret filters](https://woodpecker-ci.org/docs/usage/secrets).
