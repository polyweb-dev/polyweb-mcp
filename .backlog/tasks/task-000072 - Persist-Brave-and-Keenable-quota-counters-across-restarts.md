---
id: TASK-000072
title: Persist Brave and Keenable quota counters across restarts
status: To Do
assignee: []
created_date: '2026-11-14T11:37:00Z'
labels: []
dependencies: []
priority: high
type: bug
ordinal: 61000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Since aae1b63 (TASK-000042) BraveAdapter.hydrate_quota and KeenableAdapter.hydrate_quota (src/polyweb/adapters/brave.py, keenable.py) are never called, so their locally counted monthly usage resets to zero on every restart and the providers can be over-used past their caps.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 Brave and Keenable usage counters are restored from the repository on startup
- [ ] #2 Restart test proves counted usage survives a runtime rebuild
<!-- AC:END -->
