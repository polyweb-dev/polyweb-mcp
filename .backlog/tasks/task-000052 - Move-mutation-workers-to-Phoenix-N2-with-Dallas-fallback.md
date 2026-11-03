---
id: TASK-000052
title: Move mutation workers to Phoenix N2 with Dallas fallback
status: In Progress
assignee:
  - '@codex'
created_date: '2026-11-03T01:47:00Z'
labels: []
dependencies: []
ordinal: 36000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
User requests mutation-only n2-standard-64 Spot workers, Phoenix first then Dallas, and one test attempt. Keep the standard worker profile and Iowa routing intact.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 Only mutation defaults select n2-standard-64 and Phoenix then Dallas; standard profile is unchanged.
- [ ] #2 Region-scoped CPU quota failures can try another configured region without retrying the same quota region or bypassing global errors.
- [ ] #3 A single mutation allocation and pipeline attempt is made where capacity and quotas permit; evidence, cleanup and automation are saved and pushed.
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. Verify N2 availability and regional quotas. 2. Add mutation-specific defaults and overrides, cross-region CPU quota fallback, and focused tests. 3. Deploy and provision once without queuing repeated autoscaler retries. If successful, run mutation once, observe and clean up. 4. Record result and push.
<!-- SECTION:PLAN:END -->
