---
id: TASK-000053
title: Add Milan mutation fallback and request global CPU quota 64
status: In Progress
assignee:
  - '@codex'
created_date: '2026-11-03T01:58:00Z'
labels: []
dependencies: []
ordinal: 37000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
User requests mutation order Delhi, Milan, Dallas and global CPU quota 64 to permit the N2 64-vCPU worker.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 Live mutation configuration and repository defaults select Delhi, Milan, Dallas with standard profile unchanged.
- [ ] #2 A global CPU quota increase to exactly 64 is submitted and the effective quota or approval state is verified and documented.
- [ ] #3 Focused checks pass and changes are pushed to feature/project.
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. Verify Milan machine support and update mutation region order with focused regression checks. 2. Use Cloud Quotas to request global CPUs=64 and inspect its outcome. 3. Deploy configuration, document effective or pending quota state, and push.
<!-- SECTION:PLAN:END -->
