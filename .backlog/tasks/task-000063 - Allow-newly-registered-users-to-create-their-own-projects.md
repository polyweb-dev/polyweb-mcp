---
id: TASK-000063
title: Complete self-service signup, profile names and project creation
status: Done
assignee: []
created_date: '2026-11-09T15:36:00Z'
updated_date: '2026-11-10T02:30:00Z'
labels:
  - frontend
  - backend
  - onboarding
  - projects-first
  - signup
  - profiles
dependencies:
  - TASK-000040
  - TASK-000041
references:
  - >-
    C:\Users\shara\.t3\userdata\attachments\mcp-ef53194d-3bc5-4bd8-af1e-7dfc981ed007-9badece4-ce74-421d-889b-40b62322f894.png
  - >-
    C:\Users\shara\.t3\userdata\attachments\mcp-ef53194d-3bc5-4bd8-af1e-7dfc981ed007-00a78696-ca91-45e7-93e3-4195844cc4b2.png
  - >-
    C:\Users\shara\.t3\userdata\attachments\mcp-ef53194d-3bc5-4bd8-af1e-7dfc981ed007-025190e3-42a2-4abe-9cbf-8691edebbed3.png
priority: high
type: bug
ordinal: 1000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Reported after a fresh local database was created on branch chore/rename (head 84a6128). A user completed public signup and reached the Projects page, but had no way to create a project. The empty state says: You are not a member of any project / Ask a system administrator to add you. No create-project action is visible. This blocks a new user from using the product independently.

Every active, authenticated user must be able to create their own projects without first joining an existing project or receiving a system-administrator grant. Creation must give the creator project-scoped administration while preserving isolation from other users and system administration.

This task also absorbs TASK-000001: signup must collect username, first name, and last name, validate the submitted values, and save them to the user profile. The source task noted that profile columns were covered by TASK-000040 and signup API/UI work followed TASK-000041. The separate signup task is retired after consolidation here.

Additional reported problem: the sidebar account trigger/menu and Account page currently identify the signed-in user only by email. Use the saved personal name as the primary user identity in the sidebar and Account page, and consistently in other applicable user-identity views such as project members, ownership labels and activity attribution. Show full name when available, then username, with email as a fallback for existing or incomplete profiles. Keep email available as secondary contact/sign-in information where useful, and derive avatar initials from the same identity. This requirement concerns user display identity; it must not rename projects or broaden permissions.

Reproduction: start with a fresh installation, sign up as a regular user, sign in, and open Projects with zero memberships; then inspect the sidebar account control and Account page. Screenshot references cover all three observations. Root cause has not been investigated; check UI availability and API authorization when implementation starts. Separate from TASK-000056, which covers editing and lifecycle management of existing projects.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 An active user who signs up normally can create a project without a system-administrator grant or any existing project membership.
- [x] #2 The desktop Projects empty state exposes an actionable create-project flow instead of requiring administrator assistance to get started.
- [x] #3 Project creation succeeds through the API for the same regular-user identity; access is not enabled only in the UI.
- [x] #4 A successfully created project appears in the project list and selector, and the creator has project-scoped administration after reload and sign-in.
- [x] #5 Users can create additional projects; creating a project grants no system-administrator privileges and no access to projects owned by other users.
- [x] #6 Regression coverage verifies fresh signup through first-project creation, creator permissions, and isolation from other users.
- [x] #7 Profile names and username remain available through authenticated profile reads after reload and subsequent sign-in.
- [x] #8 The sidebar account trigger and account menu identify the user primarily by full name, falling back to username and then email when name data is absent; avatar initials follow the same identity.
- [x] #9 The Account page shows the saved name and username along with email and sign-in details; email is not the only visible user identity when a name exists.
- [x] #10 Other applicable views that identify a user, including project member lists, ownership labels and activity attribution, consistently show available names while retaining email where needed for contact or disambiguation and preserving existing visibility permissions.
- [x] #11 Existing users with incomplete name fields retain working sign-in and usable identity labels through the documented fallback; names do not grant additional permissions.
- [x] #12 Regression coverage verifies signup field validation and persistence, name display and fallbacks across the sidebar, Account page and other affected identity views, alongside the first-project creation flow.
- [x] #13 Username, first name and last name are mandatory signup parameters, just like email. Both the desktop signup form and signup API require, validate and persist all three fields on the user profile.
- [x] #14 Signup rejects omitted, null, empty or whitespace-only username, first name or last name with clear field-level validation errors, and does not create an account when any required field is invalid. Regression coverage exercises these cases through the UI and API.
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. Backend stage (this agent): self-service project creation for any active authenticated regular user without membership or system admin; creator durably granted project admin; preserve isolation, system RBAC, inactive/unauthenticated restrictions; mandatory signup username/first_name/last_name with atomic per-field validation; persist/expose profile on authenticated reads; expose available profile names in member/owner/activity responses within existing visibility; no TASK-000056 lifecycle expansion. 2. Frontend stage (separate agent): empty-state create flow, sidebar/Account/member/owner/activity display with full-name greater than username greater than email fallback and avatar initials. 3. Independent tester stage: regression coverage for fresh signup to first-project creation, creator permissions, isolation, signup validation/persistence, display fallbacks. 4. Adversarial Codex review plus executor CI (unit/integration/BDD/latency as applicable on Woodpecker). 5. Final Devin UI-only review. 6. Finalization and PR.
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Finalization (metadata only, no app/test/config changes). Scope: signup/self-service projects/profiles identity display/legacy/isolation; no broad lifecycle changes. Validation: local backend unit 2216 passed 1 skip; frontend 2564 tests + deps/lint/types/build green. Fresh-signup first-project, creator admin durable atomic, repeated projects, role isolation, inactive/key deny, exact own lists, reciprocal 404, no-system-roles, routing 403 verified (integration). Auth: username<=64, first/last<=100, trimmed, per-field 422, dup username case variants, relogin persist. Identity: full-name>username>email + avatar initials across sidebar/account/members/owners/pools/API-key creator/activity; API-key actors never human; legacy nullable fallback; vault.manage unchanged. UI smoke (signup fields, zero-membership first-project, reload) passed. Reviews: Codex GPT-6.1 Sol HIGH APPROVE incl. final T20 after bloat removals; Devin Sonnet5.5 UI APPROVE 9.0/10 (1440x900+1280x800) after key-table overflow fix. CI: api-integration #68 PASS 1690 @1d2765c; api-bdd #69 PASS 289scn/1336steps @7c97852 (all T20 6 + core-users 7 ran); api-latency #64 PASS @2ac797c (offline p95 94.58/A3 107.023<150ms, 4 mpl skips); ui-quality #65 PASS 2564+gates @2ac797c; ui-bdd #66 PASS 7 smoke @2ac797c. Deltas 2ac->1d backend test contracts only; 1d->7c T20 harness only; app/UI unchanged so reused passes legit. Budget 8/30 used, 22 left; parent runs 5 final head-confirmation runs after this metadata commit.
<!-- SECTION:NOTES:END -->

## Comments

<!-- COMMENTS:BEGIN -->
created: 2026-11-09T15:39:00Z

---

User clarification: username, first name and last name are mandatory on every new signup, like email. Display-name fallbacks apply to legacy or incomplete existing profiles and do not make any of these signup fields optional.

---
<!-- COMMENTS:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
TASK-000063 implementation ready (metadata finalization only; no app/test/config change in this commit). Self-service signup/project creation: active ordinary users create projects via UI empty-state and API with durable atomic creator project-admin, repeated projects, role isolation, inactive/key deny, no system grants. Signup requires username (<=64), first/last (<=100), trimmed, per-field 422, dup-username case variants, relogin persistence. Identity display full-name>username>email with avatar initials across sidebar/account/members/owners/pools/API-key creator/activity; legacy nullable fallback; vault.manage unchanged. Evidence: backend unit 2216 pass/1 skip; frontend 2564 + gates green; integration fresh-signup/isolation matrix; UI smoke; Codex HIGH APPROVE (final T20) + Devin UI 9.0/10; Woodpecker api-integration #68 @1d2765c, api-bdd #69 @7c97852, api-latency #64 @2ac797c (p95<150ms), ui-quality #65 @2ac797c, ui-bdd #66 @2ac797c (app/UI unchanged across delta SHAs). No PR created by this agent. Pending: parent-planned 5 final head-confirmation runs after this metadata commit.
<!-- SECTION:FINAL_SUMMARY:END -->
