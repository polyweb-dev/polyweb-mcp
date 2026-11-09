---
id: TASK-000002
title: Replace Playground Raw JSON inspection with Activity details popup
status: To Do
assignee: []
created_date: 2026-10-15 22:19
updated_date: '2026-10-30T19:47:00Z'
labels: []
dependencies:
  - TASK-000047
documentation:
  - doc-000008
type: enhancement
ordinal: 11000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
In Playground, users should open the associated Activity details in a popup instead of inspecting raw JSON.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 The Inspect Raw JSON action is replaced by a View Details button.
- [ ] #2 The button opens the matching Activity details in a popup.
- [ ] #3 The popup uses the same project-scoped trace inspector as Activity. Missing or metadata-only traces explain unavailable details without a global lookup.
<!-- AC:END -->
