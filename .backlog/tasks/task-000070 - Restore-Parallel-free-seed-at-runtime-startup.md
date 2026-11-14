---
id: TASK-000070
title: Restore Parallel free-seed at runtime startup
status: To Do
assignee: []
created_date: '2026-11-14T11:37:00Z'
labels: []
dependencies: []
priority: high
type: bug
ordinal: 59000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Since aae1b63 (TASK-000042) the runtime no longer calls ParallelAdapter.set_free_seed or hydrate_quota (src/polyweb/adapters/parallel.py), so the configured Parallel free-seed is saved but never applied. The docstring at src/polyweb/routers/api.py ~603 still says quota state hydrates at compose time and is stale.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 Configured Parallel free-seed is applied to the adapter when the runtime generation is composed
- [ ] #2 Parallel quota state is hydrated from the repository on startup
- [ ] #3 routers/api.py compose docstring matches the actual startup behaviour
<!-- AC:END -->
