---
id: TASK-000054
title: Preserve CI reports on VPS with authenticated downloads and deletion
status: In Progress
assignee:
  - '@codex'
created_date: '2026-11-03T02:47:00Z'
updated_date: '2026-11-03T13:16:00Z'
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
1. Remove the rejected custom artifact receiver, uploader, smoke workflow and deployed service while preserving recovered Run 13 data and a private rollback archive. 2. Remove only its Caddy route, Tailnet forwarding rule, ACL allowance and repository upload secret; preserve existing applications and CI connectivity. 3. Keep useful report generation and log capture in CI without a custom service dependency. 4. User requested a separate top-level OpenCode CommandCode GLM-5.3-Flash max-reasoning chat for a Gitea Community deployment under Programs; leave final artifact integration and acceptance verification pending.
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
2026-11-03: User rejected the bespoke artifact application and explicitly authorized removal and a separate Gitea setup chat. Removed receiver/uploader/tests/service assets and synthetic smoke workflow; removed upload steps while retaining mutation HTML/JSON, progress streaming and test log capture. Latency log capture is now inline and verified with mocked success/database-failure/BDD-failure exits. Removed live systemd service, custom Caddy route, Tailnet 9010 forwarding and ACL allowance, and ci_artifact_upload_token repository secret (204). Caddy validation/reload, Headscale policy validation, Woodpecker health 204 and HTTPS 200 passed; autoscaler remains active and Tailnet gRPC9000 remains. Recovered Run13 ZIP/metadata copied to Programs/gcp-ci-worker/reports/freesearch/pipeline-13. Private rollback archive: /home/administrator/.local/state/freesearch/retired-artifact-service-20261103T131417Z. All Woodpecker YAML parses and git diff --check passes. New top-level setup-only chat uses opencode commandcode/z-ai/glm-5.3-flash variant max, thread mcp:launch:f4137bc8380a9072a9200e2a427ec84370b24ab90eb8fde60fdb3938cfef9d73; authorized official Gitea Docker deployment under Programs/gitea and Caddy changes, user updating Technitium gitea.thiocyanate.dev. Automatic artifact upload remains absent pending Gitea CI integration; original ACs remain unverified and task stays In Progress.
<!-- SECTION:NOTES:END -->
