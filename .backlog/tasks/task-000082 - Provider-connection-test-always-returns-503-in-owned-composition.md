---
id: TASK-000082
title: Provider connection test always returns 503 in owned composition
status: To Do
assignee: []
created_date: '2026-11-15T15:06:00Z'
labels: []
dependencies: []
priority: medium
type: bug
ordinal: 70000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
_ensure_provider_adapter (src/polyweb/routers/control.py ~544-553) looks up the adapter in app.state._routes. Since TASK-000042 adapters are built lazily per credential in ExecutionService._lease_adapter, so that list is empty in owned composition and the provider connection test endpoint always answers 503. Found during TASK-000070 planning.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 The provider connection test builds or leases an adapter for the selected credential and reports the real vendor result
- [ ] #2 An integration test covers the connection test in owned composition
<!-- AC:END -->
