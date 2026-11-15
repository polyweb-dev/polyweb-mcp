---
id: TASK-000086
title: >-
  Manual record for a key with split search and fetch pools reaches only the
  search pool
status: To Do
assignee: []
created_date: '2026-11-15T23:46:00Z'
labels: []
dependencies: []
priority: medium
type: bug
ordinal: 72000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Found in the PR #78 review (A5) for TASK-000070. services/manual_quota.py _balance_pools prefers the key's SEARCH pool link, so a key linked to different search and fetch pools resolves only to the search pool. A pool-scoped manual record for the fetch pool returns 422, and the fetch pool's vendor 402 is never cleared by Set balance.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 A key linked to different search and fetch pools can receive a manual record for either pool, and the record clears that pool's stored denial
- [ ] #2 An integration test covers a key with split search and fetch pools
<!-- AC:END -->
