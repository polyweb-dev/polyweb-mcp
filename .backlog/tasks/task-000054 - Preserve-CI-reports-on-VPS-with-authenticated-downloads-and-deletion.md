---
id: TASK-000054
title: Preserve CI reports on VPS with authenticated downloads and deletion
status: In Progress
assignee:
  - '@codex'
created_date: '2026-11-03T02:47:00Z'
updated_date: '2026-11-03T16:02:00Z'
labels: []
dependencies: []
ordinal: 38000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Disposable GCP worker cleanup removes mutation JSON and latency report files. User wants durable VPS storage and download/delete access associated with Woodpecker.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 Mutation HTML/JSON and latency report bundles upload to VPS after success or failure, without hiding test failures.
- [ ] #2 Report bundles remain available after worker deletion through a Woodpecker-authenticated download/delete interface.
- [ ] #3 Uploads are authenticated, paths and archive sizes are bounded, downloads are attachments, and deletion requires write permission plus CSRF protection.
- [ ] #4 Automation, service configuration and instructions are preserved in freesearch, with isolated service/upload checks and a real CI smoke verification.
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. Configure standard Gitea Generic Package API uploads for every manual test workflow, with unique pipeline/workflow/retry bundle names and allowlisted report/log files. 2. Capture test output without changing exit status and run a separate secret-bearing upload step after success or failure. 3. Store the existing package-only CI token as a repository secret restricted to manual events, without the plugin-only image filter. 4. Preserve canonical TLS and use the existing private tailnet address explicitly so Docker job DNS cannot select public or ZeroTier routes. 5. Add narrow archive/upload and workflow-contract checks, validate the live secret and registry with a disposable package, document access and limits, then publish configuration to feature/project without triggering a job. 6. Leave real pipeline verification to the user manual run and keep broader acceptance criteria pending.
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
2026-11-03: User rejected the bespoke artifact application and explicitly authorized removal and a separate Gitea setup chat. Removed receiver/uploader/tests/service assets and synthetic smoke workflow; removed upload steps while retaining mutation HTML/JSON, progress streaming and test log capture. Latency log capture is now inline and verified with mocked success/database-failure/BDD-failure exits. Removed live systemd service, custom Caddy route, Tailnet 9010 forwarding and ACL allowance, and ci_artifact_upload_token repository secret (204). Caddy validation/reload, Headscale policy validation, Woodpecker health 204 and HTTPS 200 passed; autoscaler remains active and Tailnet gRPC9000 remains. Recovered Run13 ZIP/metadata copied to Programs/gcp-ci-worker/reports/freesearch/pipeline-13. Private rollback archive: /home/administrator/.local/state/freesearch/retired-artifact-service-20261103T131417Z. All Woodpecker YAML parses and git diff --check passes. New top-level setup-only chat uses opencode commandcode/z-ai/glm-5.3-flash variant max, thread mcp:launch:f4137bc8380a9072a9200e2a427ec84370b24ab90eb8fde60fdb3938cfef9d73; authorized official Gitea Docker deployment under Programs/gitea and Caddy changes, user updating Technitium gitea.thiocyanate.dev. Automatic artifact upload remains absent pending Gitea CI integration; original ACs remain unverified and task stays In Progress.

2026-11-03: User approved private Gitea access after creating Technitium A -> 10.242.90.30. Added Headscale extra A gitea.thiocyanate.dev -> 100.64.0.2 and ci-worker -> server:443 ACL; preserved port9000. Added Gitea-only Caddy TLS listener127.0.0.1:8443, raw tailnet443 forwarding to it, explicit other-host404, and public-destination403 on shared Gitea route. Validated candidates before reload/restart. Private rollback copies under ~/.local/state/freesearch/gitea-private-access-20261103T153820Z. Isolated temporary ci-worker peer verified MagicDNS answer, valid TLS health200, OCI anonymous401, both existing package tokens read200, TCP9000 allowed, TCP22/3040/8443 blocked, ACL also denies8000/5380, and other-host404. DNS and HTTPS were checked separately because userspace SOCKS hostname resolution uses system DNS. Removed temporary peer/container/key file and expired short-lived enrollment key. Headscale/Gitea/Woodpecker healthy; user autoscaler active. Local Gitea runbook and obsolete DNS guidance updated. No GCP VM/build or package mutation. Actual CI-container DNS/upload integration and storage/security follow-ups remain unverified/pending; task remains In Progress.

2026-11-03: User authorized Gitea artifact upload configuration and reserved the first real CI job for a manual trigger. Added upload-artifacts steps to all six manual backend test workflows, using a digest-pinned UV/Python image and success/failure conditions. Test commands now retain raw logs and preserve exit status through run-and-log.sh. Standard Gitea Generic Package API uploader creates per-workflow ZIPs with pipeline/rerun/time versions, selected metadata, coverage/gremlins HTML+JSON, test_reports, and the workflow log. Rejects oversized input/ZIP, excessive files, hidden paths, DB/env files and symlinks. Connects to tailnet100.64.0.2:443 with canonical SNI/Host and default TLS verification, no redirects or public DNS fallback. Configured repository secret gitea_artifact_upload_token from existing ci-upload token, manual events only, images empty to avoid the prior plugin-filter failure. Eight isolated checks passed, including failure/log preservation and archive/transport boundaries; Ruff and strict uploader MyPy passed; all seven YAML files passed Woodpecker3.20.1 strict lint and embedded bash syntax checks. Disposable ci-worker-tag peer uploaded a415-byte ZIP through the actual private path; CD read token downloaded matching SHA256; CI token deleted it204. Removed test peer/container and expired test enrollment key. No Woodpecker pipeline or GCP VM started. Documented configuration in scripts/ci/README.md. Real CI verification remains pending the user manual run; original broader ACs remain unchecked, and task remains In Progress.
<!-- SECTION:NOTES:END -->
