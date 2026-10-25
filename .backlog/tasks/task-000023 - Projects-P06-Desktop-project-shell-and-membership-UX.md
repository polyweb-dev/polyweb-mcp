---
id: TASK-000023
title: Projects P06 - Desktop project shell and membership UX
status: To Do
assignee: []
created_date: '2026-10-24T15:54:00Z'
updated_date: '2026-10-25T14:51:00Z'
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
- [ ] #1 The desktop shell provides project list/selection and project URLs while account/system routes remain separate.
- [ ] #2 Pending requests and old polls stop or their late results are ignored on project change.
- [ ] #3 Persisted drafts and domain state are isolated by account, project and schema version.
- [ ] #4 System-authorized project creation and project membership/role administration use effective backend permissions.
- [ ] #5 Two tabs can use different projects without leaking drafts or access rights; a role change in one project leaves the other project unchanged.
- [ ] #6 Human session state remains independent from project state; no cloud login workflow is added.
- [ ] #7 No account-scoped activity, usage or playground results appear under project routes before TASK-000036.
<!-- AC:END -->

## Definition of Done
<!-- DOD:BEGIN -->
- [ ] #1 All phase acceptance criteria have objective test or review evidence recorded in Backlog before Done.
<!-- DOD:END -->
