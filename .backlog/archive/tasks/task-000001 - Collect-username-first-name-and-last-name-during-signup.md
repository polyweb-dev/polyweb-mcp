---
id: TASK-000001
title: Collect username, first name, and last name during signup
status: To Do
assignee: []
created_date: 2026-10-15 22:19
updated_date: '2026-11-09T15:38:00Z'
labels: []
dependencies:
  - TASK-000040
  - TASK-000041
type: feature
ordinal: 10000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Signup should collect the user identity fields needed for account profiles.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 Signup collects username, first name, and last name.
- [ ] #2 The submitted values are validated and saved to the user profile.
<!-- AC:END -->

## Comments

<!-- COMMENTS:BEGIN -->
created: 2026-10-26T09:48:00Z

---

2026-10-25: The username, first name and last name columns land in the settled schema (TASK-000040). This card keeps the signup API and UI work, after TASK-000041 removes the account-role choice from signup.

---

created: 2026-11-09T15:38:00Z

---

Merged into TASK-000063 at the user request. Signup collection and validation of username, first name and last name, plus profile persistence, are now acceptance criteria there together with first-project creation and consistent user-name display. Archiving this superseded task; its completed prerequisites are retained on TASK-000063.

---
<!-- COMMENTS:END -->
