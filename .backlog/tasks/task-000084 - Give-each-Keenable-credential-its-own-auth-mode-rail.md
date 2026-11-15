---
id: TASK-000084
title: Give each Keenable credential its own auth-mode rail
status: To Do
assignee: []
created_date: '2026-11-15T17:34:00Z'
labels: []
dependencies: []
priority: low
type: bug
ordinal: 71000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Found in the TASK-000070 final review (F6). ExecutionService preparation calls ProviderLimitsService.apply_keenable_auth_mode for each built Keenable adapter, but the rail is process-wide, so with keyed and keyless Keenable credentials active together the rail flips to whichever credential was built last.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 Keyed and keyless Keenable credentials keep separate auth-mode rails when both are active
- [ ] #2 A test with one keyed and one keyless Keenable credential shows each request admitted against its own rail
<!-- AC:END -->
