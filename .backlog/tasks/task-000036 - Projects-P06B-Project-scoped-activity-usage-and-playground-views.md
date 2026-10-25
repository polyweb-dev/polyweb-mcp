---
id: TASK-000036
title: Projects P06B - Project-scoped activity, usage and playground views
status: To Do
assignee: []
created_date: '2026-10-25T14:51:00Z'
labels:
  - projects-first
  - phase-p06
  - parallel-ui
milestone: m-0
dependencies:
  - TASK-000034
  - TASK-000022
  - TASK-000023
references:
  - freesearch-ui/src/features/activity
  - freesearch-ui/src/app/routes.ts
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
ordinal: 750
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
The desktop shell can select a project before scoped backend reads and execution exist. Activity, usage and playground screens must switch to project-scoped APIs only once P04B and P05 provide them, so a project switch never shows another project's results.

Phase: P06B. Execution lane: parallel-ui. Milestone: Projects 1 - Foundation.

Dependency gate: P04B (TASK-000034), P05 (TASK-000022), P06 (TASK-000023)
Do not implement or mark In Progress until every dependency is Done, merged into the integration branch, and its acceptance evidence is available. Priority and phase numbers never override this gate. Parallel work is permitted only where the dependency graph and shared-file ownership allow it.

Accepted scope from plan section 10 / P06 (remaining Tasklet A scope):

Wire activity, usage, dashboard and playground screens under /p/:projectId to the project-scoped trace, usage and execution APIs.
On a project switch, abort pending requests, stop old polls, clear old results and reset unsaved project forms; ignore stale responses when cancellation loses a race (plan section 8).
Human playground calls use the human session and project membership, never a project token.

Restructure note (2026-10-25): Split from P06 so the shell and membership UX can start after P02/P03. Phase P06 is complete only when TASK-000023 and this card are Done. P14 also edits freesearch-ui/src/features/activity and follows this card.

Cross-phase constraints:
User-approved constraints: one human account type; one common scoped RBAC service; system/project roles are assignments, not account types. Preserve internal UUIDs and local/WorkOS storage constraints without implementing WorkOS/cloud features. Use one internal installation account. Project tokens can expire or have no expiration. Support private and explicitly shared credential instances. Strict pool/project caps are the default; fair loans require their later phase. Use a fresh alpha database; do not migrate/import old history, humans, settings or secrets. Never use the live database or real provider credentials for tests. Desktop UI only; local environment controls ports.

Verification expectations:
Run colocated Vitest tests and desktop Playwright-BDD journeys for two tabs, rapid project switches during pending requests and polls, and direct links. Run all required frontend audit/build checks.
Use the managed verification specification for required quality commands and test placement. Record objective evidence before completion.

Before code work, read AGENTS.md and applicable skills, use CodeGraph for indexed code, inspect current implementation and record the task implementation plan through Backlog. The referenced design is context; this future ticket intentionally has no speculative implementation-plan field.

Documentation: local .agents/communication/projects-feature-plan.md, sections 4-10 for design and scope, section 11 for ordering. The managed specification documents are durable copies for checkouts where the gitignored local plan is absent. Use the execution-index document for exact phase-to-ticket IDs and ready-work commands.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 Activity, usage, dashboard and playground screens under /p/:projectId call only project-scoped APIs for the URL project.
- [ ] #2 Two tabs can use different projects without shared results, stale polls or cross-project activity.
- [ ] #3 Late responses from a previous project are ignored and old results are cleared on project change.
- [ ] #4 Direct links to another project's activity or trace detail show the consistent inaccessible-resource state.
<!-- AC:END -->
