---
id: TASK-000064
title: Scale Woodpecker workflows on independent Spot workers
status: Done
assignee:
  - '@codex'
created_date: '2026-11-09T15:47:00Z'
updated_date: '2026-11-09T15:59:00Z'
labels: []
dependencies: []
ordinal: 53000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Standard workflows share one Spot VM and queue even when GCP has spare quota. Provision enough independent one-workflow agents for queued API and UI work.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 Independent ready workflows can run concurrently on separate Spot VMs within configured worker and CPU bounds
- [x] #2 Unit tests cover booting capacity, running worker protection, restart compatibility, limits, and cleanup
- [x] #3 Live API and UI workflows demonstrate overlapping execution and successful artifact uploads
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. Replace profile singleton allocation with bounded workflow demand and retain existing worker ownership across restarts. 2. Run focused unit and static checks. 3. Deploy during an empty queue, trigger API integration and UI quality together, and record overlapping execution and cleanup.
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Deployed independent worker allocation to the user service after an empty-queue check. Defaults: MAX_WORKERS=4, MAX_TOTAL_CPUS=64, startup timeout=300 seconds. All 39 focused unit tests, Ruff, and focused MyPy passed. Triggered api-integration #60 and ui-quality #61 together on main.

Confirmed simultaneous execution on distinct agents: API #60 integration-tests started at 15:52:37 UTC on agent 31; UI #61 ui-quality started at 15:52:08 UTC on agent 30. Queue snapshots show both running, zero pending, and exactly two tracked 16-vCPU workers.

Both workflows passed: API #60 had 1,655 tests; UI #61 had 2,473 tests plus checks/build. Test steps overlapped for 89 seconds (complete pipelines: 98 seconds). Both reports.zip uploads succeeded under polyweb with the existing CI credential. Automatic cleanup removed both VMs and Headscale nodes by 15:58:22 UTC. Final queue and worker state were empty. Full evidence: scripts/gcp-ci-worker/verification-2026-11-09.md.
<!-- SECTION:NOTES:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
Replaced one-worker-per-profile serialization with independent workflow capacity. Added worker and CPU limits, startup recovery, state migration, and atomic state writes. Deployed and verified concurrent API/UI execution, successful artifacts, and automatic cleanup. All 39 focused unit tests and relevant static checks passed. GCP quota and Spot availability remain capacity limits.
<!-- SECTION:FINAL_SUMMARY:END -->
