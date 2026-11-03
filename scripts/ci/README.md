# CI artifacts in Gitea

The manual backend workflows publish report ZIP files to the Gitea Generic Package Registry.
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

Open <https://gitea.thiocyanate.dev/freesearch/-/packages> through the private network.
Use a Gitea account with package read permission in the `freesearch` organization.
Each workflow uses a package such as `freesearch-api-mutation` or `freesearch-api-latency`.
Each version contains the pipeline number, rerun count, and a unique upload timestamp.
Download `reports.zip`. Extract the ZIP to open its reports.

The upload step also prints the package URL, download URL, size, and SHA256 checksum.

## Credentials and network

The repository secret is `gitea_artifact_upload_token`.
It contains the token for the `ci-upload` account, with `write:package` scope.
Woodpecker exposes it only on manual events. Test steps do not receive this secret.
The secret has no image filter because the upload step executes commands rather than a plugin.

The package write permission also permits deletion. Do not give this token to untrusted jobs.
Future production image uploads need separate credentials.

The uploader connects directly to tailnet address `100.64.0.2:443`.
It uses `gitea.thiocyanate.dev` for TLS SNI, certificate verification, and the HTTP Host header.
This preserves valid TLS when a Docker step does not use MagicDNS.
The uploader does not use a public fallback, an HTTP proxy, or an insecure TLS option.
It does not follow redirects with credentials.
The upload image uses a digest pin.

## Manual verification

1. Start a new manual pipeline on `feature/project` after the configuration commit.
2. Select a test workflow. `api-unit` gives a smaller first check than mutation tests.
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

References: [Gitea Generic Package Registry](https://docs.gitea.com/usage/packages/generic/),
[Woodpecker workflow conditions](https://woodpecker-ci.org/docs/usage/workflow-syntax),
[Woodpecker secret filters](https://woodpecker-ci.org/docs/usage/secrets).
