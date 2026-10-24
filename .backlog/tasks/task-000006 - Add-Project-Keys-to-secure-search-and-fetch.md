---
id: TASK-000006
title: Projects P07 - Project tokens and authenticated machine execution
status: To Do
assignee: []
created_date: 2026-10-15 22:19
updated_date: '2026-10-24T15:57:00Z'
labels:
  - projects-first
  - phase-p07
  - parallel-a
milestone: m-0
dependencies:
  - TASK-000022
  - TASK-000023
references:
  - src/freesearch/infrastructure/auth_asgi.py
  - src/freesearch/mcp/auth.py
  - src/freesearch/services/users.py
  - freesearch-ui/src/domains/auth
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
ordinal: 800
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Machine execution should use scoped project credentials rather than agent user accounts or browser human sessions.

Phase: P07. Execution lane: parallel-a. Milestone: Projects 1 - Foundation.

Dependency gate: P05 (TASK-000022), P06 (TASK-000023)
Do not implement or mark In Progress until every dependency is Done, merged into the integration branch, and its acceptance evidence is available. Priority and phase numbers never override this gate. Parallel work is permitted only where the dependency graph and shared-file ownership allow it.

Accepted scope from plan section 10 / P07:

Tasklet A adds token schema, digest verification, issue, list, revoke, rotate, and expiry operations.
Tasklet B adds token administration UI and REST/MCP authentication, including stdio and persistent tool sessions.
Require project-token authentication for machine execution in preview mode. Keep human session authentication separate.
Support dated tokens and tokens without expiration throughout storage, API contracts, rotation, and UI controls.

Cross-phase constraints:
User-approved constraints: one human account type; one common scoped RBAC service; system/project roles are assignments, not account types. Preserve internal UUIDs and local/WorkOS storage constraints without implementing WorkOS/cloud features. Use one internal installation account. Project tokens can expire or have no expiration. Support private and explicitly shared credential instances. Strict pool/project caps are the default; fair loans require their later phase. Use a fresh alpha database; do not migrate/import old history, humans, settings or secrets. Never use the live database or real provider credentials for tests. Desktop UI only; local environment controls ports.

Verification expectations:
Exercise REST, MCP HTTP/stdio and persistent tool sessions with fake adapters. Cover token leakage, expiry, revocation, project mismatch, scopes, queued dispatch and human session coexistence.
Use the managed verification specification for required quality commands and test placement. Record objective evidence before completion.

Before code work, read AGENTS.md and applicable skills, use CodeGraph for indexed code, inspect current implementation and record the task implementation plan through Backlog. The referenced design is context; this future ticket intentionally has no speculative implementation-plan field.

Documentation: local .agents/communication/projects-feature-plan.md, sections 4-10 for design and scope, section 11 for ordering. The managed specification documents are durable copies for checkouts where the gitignored local plan is absent. Use the execution-index document for exact phase-to-ticket IDs and ready-work commands.

Origin: Reuses TASK-000006, originally "Add Project Keys to secure search and fetch". Its original outcome remains part of this phase.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 Project token issue/list/revoke/rotate operations store verifier digests and reveal raw secret material only in the issue response.
- [ ] #2 Execution tokens bind to exactly one project and permitted search/fetch scopes through the common authorizer.
- [ ] #3 Tokens cannot access human account or control-plane management operations.
- [ ] #4 Invalid, expired, revoked, wrong-project or wrong-scope requests fail before provider access, including persistent MCP sessions.
- [ ] #5 Explicit expires_at null creates a No expiration token; omission uses the documented default, and rotation preserves the selected lifetime unless explicitly changed.
- [ ] #6 No-expiration tokens remain valid beyond the default lifetime but fail after revocation or project suspension.
- [ ] #7 Human browser execution continues through human sessions without storing a project token in browser history or persistent application state.
<!-- AC:END -->

## Definition of Done
<!-- DOD:BEGIN -->
- [ ] #1 All phase acceptance criteria have objective test or review evidence recorded in Backlog before Done.
<!-- DOD:END -->
