---
id: TASK-000023
title: Projects P06 - Desktop project shell and membership UX
status: In Progress
assignee:
  - '@devin'
created_date: '2026-10-24T15:54:00Z'
updated_date: '2026-10-25T18:01:00Z'
labels:
  - projects-first
  - phase-p06
  - parallel-ui
milestone: m-0
dependencies:
  - TASK-000019
  - TASK-000020
references:
  - freesearch-ui/src/app/routes.ts
  - freesearch-ui/src/app/ProtectedWorkspace.tsx
  - freesearch-ui/src/app/permissions.ts
  - freesearch-ui/src/store/AppStoreProvider.tsx
  - freesearch-ui/src/services/api/freesearchApi.ts
documentation:
  - doc-000001
  - doc-000002
  - doc-000003
  - doc-000004
  - doc-000005
  - .agents/communication/projects-feature-plan.md
  - .backlog/docs/doc-000005 - Projects-execution-index-start-here.md
priority: high
type: feature
ordinal: 700
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
The UI currently uses flat routes and account-only persisted state. Project switching must not expose stale results or the wrong project's settings and permissions.

Phase: P06. Execution lane: parallel-ui. Milestone: Projects 1 - Foundation.

Dependency gate: P02 (TASK-000019), P03 (TASK-000020)
Do not implement or mark In Progress until every dependency is Done, merged into the integration branch, and its acceptance evidence is available. Priority and phase numbers never override this gate. Parallel work is permitted only where the dependency graph and shared-file ownership allow it.

Accepted scope from plan section 10 / P06:

Tasklet A adds the project list, selector, URL routes, API scope, store keys, and request cancellation.
Tasklet B adds project creation for permitted system users, member administration, and extra role assignment.
Keep system navigation separate and expose no unsupported project execution mode.

Restructure note (2026-10-25): P02 project/membership endpoints and P03 settings endpoints exist, so this card no longer waits for P04/P05. Project-scoped activity, usage and playground views moved to TASK-000036. Until TASK-000036 lands, do not present account-scoped activity, usage or playground results under /p/:projectId routes, and keep project navigation behind the PROJECTS_PREVIEW rollout state (plan P00: no UI-only tenant isolation). Phase P06 is complete only when this card and TASK-000036 are Done.

Cross-phase constraints:
User-approved constraints: one human account type; one common scoped RBAC service; system/project roles are assignments, not account types. Preserve internal UUIDs and local/WorkOS storage constraints without implementing WorkOS/cloud features. Use one internal installation account. Project tokens can expire or have no expiration. Support private and explicitly shared credential instances. Strict pool/project caps are the default; fair loans require their later phase. Use a fresh alpha database; do not migrate/import old history, humans, settings or secrets. Never use the live database or real provider credentials for tests. Desktop UI only; local environment controls ports.

Verification expectations:
Run colocated Vitest tests and desktop Playwright-BDD journeys for two tabs, rapid switches, role changes, direct links and zero-membership states. Run all required frontend audit/build checks.
Use the managed verification specification for required quality commands and test placement. Record objective evidence before completion.

Before code work, read AGENTS.md and applicable skills, use CodeGraph for indexed code, inspect current implementation and record the task implementation plan through Backlog. The referenced design is context; this future ticket intentionally has no speculative implementation-plan field.

Documentation: local .agents/communication/projects-feature-plan.md, sections 4-10 for design and scope, section 11 for ordering. The managed specification documents are durable copies for checkouts where the gitignored local plan is absent. Use the execution-index document for exact phase-to-ticket IDs and ready-work commands.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 The desktop shell provides project list/selection and project URLs while account/system routes remain separate.
- [x] #2 Pending requests and old polls stop or their late results are ignored on project change.
- [x] #3 Persisted drafts and domain state are isolated by account, project and schema version.
- [x] #4 System-authorized project creation and project membership/role administration use effective backend permissions.
- [x] #5 Two tabs can use different projects without leaking drafts or access rights; a role change in one project leaves the other project unchanged.
- [x] #6 Human session state remains independent from project state; no cloud login workflow is added.
- [x] #7 No account-scoped activity, usage or playground results appear under project routes before TASK-000036.
<!-- AC:END -->

## Definition of Done
<!-- DOD:BEGIN -->
- [x] #1 All phase acceptance criteria have objective test or review evidence recorded in Backlog before Done.
<!-- DOD:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. Backend contract additions (thin, reuse ScopedAuthorizationService; no migration):
   - GET /api/v1/system/access -> {rollout_state, permissions[]} (live system-scope permissions).
   - GET /api/v1/projects/{id}/access -> {project_id, permissions[], roles[], policy_revision}; inaccessible/unknown -> 404.
   - ProjectMemberRead gains email; ProjectMemberAdd accepts exactly one of user_id/email; ProjectCreate accepts exactly one of initial_admin_user_id/initial_admin_email. Unknown/inactive email -> same 400 as an unknown user_id. No user directory/search.
   - Unit + integration tests with temporary databases.
2. Frontend domain domains/projects: wire decoders, API client (AbortSignal on every read), types, permission helper, project storage key (account, project, schema version), validated last-project preference.
3. shared scoped-request hook: abort on scope change/unmount, ignore stale responses by generation, stop old polls.
4. Providers: account-level ProjectsProvider (system access + project list) under ProtectedWorkspace; project subtree keyed by account+project so a switch clears results and resets unsaved forms; project access polled and refreshed on focus/403.
5. features/projects: sidebar project selector (separate landmark, Preview badge, preserves current section when permitted), /projects list + zero-membership state + system-authorized create, /p/:projectId overview, /p/:projectId/members (add by email, suspend/reactivate, remove, extra role assign/remove, LAST_PROJECT_ADMIN handling), project-scoped persisted add-member draft.
6. Routes: /projects and /p/:projectId[/members]; other /p/:projectId/* sections redirect to the overview until TASK-000036 (no account-scoped activity/usage/playground under project routes). Flat account routes unchanged. returnTo accepts project deep links.
7. Tests: colocated Vitest for domain/hook/components; Playwright-BDD stubbed journeys for two tabs, rapid switches, role change isolation, direct links, zero membership. Default backend stub answers project endpoints with 404 so existing scenarios/snapshots stay unchanged.
8. Verify: ruff, mypy, changed-area pytest then full unit/integration; pnpm test/depcruise/knip/lint/typecheck/build/typecheck:e2e/test:e2e --project=chromium on the wt_3 port (5177).
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Backend contract added for the UI (no migration): GET /api/v1/system/access {rollout_state, permissions}; GET /api/v1/projects/{id}/access {project_id, permissions, roles, policy_revision} (404 for unknown or inaccessible, system admin without membership included); ProjectMemberRead.email; ProjectMemberAdd accepts user_id or email; ProjectCreate accepts initial_admin_user_id or initial_admin_email. Authorization runs before email resolution; unknown/inactive email returns the same empty 400 as an unknown user_id. User decisions (2026-10-25): identify members by email; keep existing flat account routes unchanged until TASK-000036.

Frontend: shared/lib/useScopedResource (abort on scope change/unmount, generation guard, poll + focus stop, reload no-op after scope close); domains/projects (strict decoders, API with AbortSignal, projectStorageKey freesearch:<ns>:v<N>:<account>:<project>, validated last-project preference, ProjectsProvider rollout gate, ProjectScopeProvider 30s/focus access poll); features/projects (sidebar selector in its own Projects landmark with Preview badge and section preservation, /projects list + zero-membership + create gated by project.create, /p/:id overview, /p/:id/members gated by members.manage/roles.assign with persisted project-scoped add-member draft); app ProjectWorkspace keyed by account:project; other /p/:id/* sections redirect to the overview.

Evidence: backend ruff clean, mypy 0 errors; test_projects_api.py 2->6 tests and tests/unit/models/test_projects.py 29->31, all pass. Frontend pnpm test 1871->1938 cases (116->129 files), all pass; lint 0 errors (warnings only in pre-existing files); typecheck, typecheck:e2e, build pass; knip/depcruise show only pre-existing findings. Playwright-BDD projects-shell.feature 5/5 on port 5177: zero membership + unavailable direct link, deep link after restore, rapid switch (late Alpha request observed aborted), two tabs (per-project drafts, Alpha demotion removes controls in tab 1 while tab 2 refetches and keeps Beta controls and draft), sysadmin create -> overview and /p/<id>/usage redirect with no Usage heading.

Pre-existing baseline issues (not caused by P06, not fixed): without a running backend, most other stubbed e2e scenarios fail at session restore because installBackendStub has no /auth routes (restore view renders before the workspace mounts; error-context files under freesearch-ui/test-results). Backend: 1 unit + 27 integration failures and 6 errors in untouched files from obsolete developer-role and anonymous-search expectations.
<!-- SECTION:NOTES:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
P06 shell and membership UX. The backend now exposes live effective permissions (system and per project) and email-based member identification. The desktop UI adds a project selector, /projects, /p/:projectId and /p/:projectId/members, with scope-keyed request cancellation, project-keyed persisted drafts and permission-driven member and role administration. Flat account routes are unchanged, and no account-scoped activity, usage or playground results appear under project routes. Verified by backend unit/integration tests, 1938 Vitest cases, frontend audits and 5/5 Playwright-BDD project journeys. Status stays In Progress until the branch merges into the integration branch (dependents P07, P12A, P15A and P06B gate on merged code). Follow-ups for the owner: the stale e2e auth stubbing and the stale backend role/anonymous-search test expectations predate this card.
<!-- SECTION:FINAL_SUMMARY:END -->
