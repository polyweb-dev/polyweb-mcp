---
id: TASK-000053
title: Add Milan mutation fallback and request global CPU quota 64
status: Done
assignee:
  - '@codex'
created_date: '2026-11-03T01:58:00Z'
updated_date: '2026-11-03T02:02:00Z'
labels: []
dependencies: []
ordinal: 38000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
User requests mutation order Delhi, Milan, Dallas and global CPU quota 64 to permit the N2 64-vCPU worker.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 Live mutation configuration and repository defaults select Delhi, Milan, Dallas with standard profile unchanged.
- [x] #2 A global CPU quota increase to exactly 64 is submitted and the effective quota or approval state is verified and documented.
- [x] #3 Focused checks pass and changes are pushed to feature/project.
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. Verify Milan machine support and update mutation region order with focused regression checks. 2. Use Cloud Quotas to request global CPUs=64 and inspect its outcome. 3. Deploy configuration, document effective or pending quota state, and push.
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Deployed and pushed mutation order asia-south2,europe-west8,us-south1 in 96d08de. Verified n2-standard-64 support in europe-west8-a. Standard configuration unchanged. All 20 isolated automation checks pass, including exact region ordering independent of API order. Cloud Quotas API was enabled as a prerequisite. Initial request hit a daily increase-request quota on the default CLI consumer project (32555940559); no preference existed after that rejection. Retried with explicit --billing-project=polyweb-513423. Preference woodpecker-global-cpus-64 was created at 02:00:45 UTC, requestedValue 64, and approved at 02:00:47 UTC with grantedValue 64 and stateDetail Quota request approved to 64. Compute project-info independently confirmed CPUS_ALL_REGIONS limit 64, usage 0. No worker was provisioned or pipeline restarted. Autoscaler remains active. Rebuild documentation includes quota inspection commands and approval evidence.
<!-- SECTION:NOTES:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
Added Milan as the second mutation region, with Delhi first and Dallas third, and deployed the configuration. Requested exactly 64 global CPUs and verified Google approval plus effective Compute quota 64. Twenty focused checks pass. No test allocation was started.
<!-- SECTION:FINAL_SUMMARY:END -->
