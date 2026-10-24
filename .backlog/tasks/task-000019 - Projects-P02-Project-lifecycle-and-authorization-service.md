---
id: TASK-000019
title: Projects P02 - Project lifecycle and authorization service
status: To Do
assignee: []
created_date: '2026-10-24T15:54:00Z'
updated_date: '2026-10-24T15:57:00Z'
labels:
  - projects-first
  - phase-p02
  - serial-foundation
milestone: m-0
dependencies:
  - TASK-000018
references:
  - src/freesearch/services/users.py
  - src/freesearch/routers/auth.py
  - src/freesearch/cli/users.py
  - src/freesearch/persistence/users.py
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
ordinal: 300
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Different project roles must apply to the same human identity without granting installation-wide privilege or leaving a project without an administrator.

Phase: P02. Execution lane: serial-foundation. Milestone: Projects 1 - Foundation.

Dependency gate: P01 (TASK-000018)
Do not implement or mark In Progress until every dependency is Done, merged into the integration branch, and its acceptance evidence is available. Priority and phase numbers never override this gate. Parallel work is permitted only where the dependency graph and shared-file ownership allow it.

Accepted scope from plan section 10 / P02:

Add project list/create/archive and membership read/change endpoints behind the rollout state.
Implement the common RBAC service, built-in scoped roles, extra role assignments, delegation limits, and live authorization checks.
Guard all administrator-affecting operations in write transactions.

Cross-phase constraints:
User-approved constraints: one human account type; one common scoped RBAC service; system/project roles are assignments, not account types. Preserve internal UUIDs and local/WorkOS storage constraints without implementing WorkOS/cloud features. Use one internal installation account. Project tokens can expire or have no expiration. Support private and explicitly shared credential instances. Strict pool/project caps are the default; fair loans require their later phase. Use a fresh alpha database; do not migrate/import old history, humans, settings or secrets. Never use the live database or real provider credentials for tests. Desktop UI only; local environment controls ports.

Verification expectations:
Use unit permission matrices and real SQLite concurrency tests with separate connections. Cover self-removal, demotion, bulk changes and account-wide deactivation.
Use the managed verification specification for required quality commands and test placement. Record objective evidence before completion.

Before code work, read AGENTS.md and applicable skills, use CodeGraph for indexed code, inspect current implementation and record the task implementation plan through Backlog. The referenced design is context; this future ticket intentionally has no speculative implementation-plan field.

Documentation: local .agents/communication/projects-feature-plan.md, sections 4-10 for design and scope, section 11 for ordering. The managed specification documents are durable copies for checkouts where the gitignored local plan is absent. Use the execution-index document for exact phase-to-ticket IDs and ready-work commands.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 One common authorization service governs system and project operations using the stable permission catalog and scoped role assignments.
- [ ] #2 Project list/create/archive and membership/role operations enforce the documented scope and delegation boundaries.
- [ ] #3 The same human can be project_member in one project and project_admin in another without an account conversion.
- [ ] #4 Concurrent membership removal, demotion and account deactivation cannot remove a project's last active administrator through supported app or CLI paths.
- [ ] #5 No project role or legacy superuser flag bypasses system or project permission checks.
- [ ] #6 System administration remains a scoped assignment and does not imply project content membership.
<!-- AC:END -->

## Definition of Done
<!-- DOD:BEGIN -->
- [ ] #1 All phase acceptance criteria have objective test or review evidence recorded in Backlog before Done.
<!-- DOD:END -->
