---
id: TASK-000056
title: Projects - Project rename, edit and lifecycle management
status: To Do
assignee: []
created_date: '2026-11-05T09:13:00Z'
labels:
  - frontend
  - backend
dependencies: []
references:
  - docs/UI-ENHANCEMENTS.md
ordinal: 35000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
The Projects UI lets users create and view a project but not rename or edit it, and the Overview has no lifecycle action. The backend has no general project-update route; archive exists separately. Review finding G1 in docs/UI-ENHANCEMENTS.md (2026-11-02). Deferred by Dhruv on 2026-11-04 so the review fixes stay in scope.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 The project-management contract (rename, edit fields, archive, restore) is agreed and recorded
- [ ] #2 The backend exposes the agreed update route with permission checks and integration tests
- [ ] #3 A project admin can rename the project and archive it from the UI, and other members see the change
<!-- AC:END -->
