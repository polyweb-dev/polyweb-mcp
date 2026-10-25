---
id: TASK-000004
title: Projects P15A - Agent-account, anonymous-execution and account-type removal
status: To Do
assignee: []
created_date: 2026-10-15 22:19
updated_date: '2026-10-25T14:51:00Z'
labels:
  - projects-first
  - phase-p15
  - parallel-cleanup
milestone: m-1
dependencies:
  - TASK-000006
  - TASK-000023
references:
  - src/freesearch/models/users.py
  - src/freesearch/persistence/users.py
  - src/freesearch/services/users.py
  - src/freesearch/routers/auth.py
  - src/freesearch/mcp/auth.py
  - freesearch-ui/src/domains/auth/model/types.ts
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
ordinal: 1600
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Project tokens (P07) replace agent accounts. Once tokens authenticate REST and MCP machine execution, agent accounts, anonymous execution and account-type role fields have no remaining purpose and only add legacy paths that later phases would have to carry.

Phase: P15A. Execution lane: parallel-cleanup. Milestone: Projects 2 - Project-first release.

Dependency gate: P07 (TASK-000006), P06 (TASK-000023)
Do not implement or mark In Progress until every dependency is Done, merged into the integration branch, and its acceptance evidence is available. Priority and phase numbers never override this gate. Parallel work is permitted only where the dependency graph and shared-file ownership allow it.

Accepted scope from plan section 10 / P15:

Remove agent registration, agent login, anonymous execution, account-type role choices, and all legacy account-type role fields from the active schema and contracts. Remove obsolete global account-role checks.
Require a fresh database; do not convert old users, sessions, history, or agent credentials.
Execution stays in PROJECTS_PREVIEW; the strict cutover is a separate card.

Restructure note (2026-10-25): Split from P15 (user decision 2026-10-25). The strict cutover rehearsal and release remain in TASK-000038. Phase P15 is complete only when this card and TASK-000038 are Done. mcp/auth.py, routers/auth.py and freesearch-ui/src/app/permissions.ts may also be edited by P12A, P12 or P16: one owner per integration step.

Cross-phase constraints:
User-approved constraints: one human account type; one common scoped RBAC service; system/project roles are assignments, not account types. Preserve internal UUIDs and local/WorkOS storage constraints without implementing WorkOS/cloud features. Use one internal installation account. Project tokens can expire or have no expiration. Support private and explicitly shared credential instances. Strict pool/project caps are the default; fair loans require their later phase. Use a fresh alpha database; do not migrate/import old history, humans, settings or secrets. Never use the live database or real provider credentials for tests. Desktop UI only; local environment controls ports.

Verification expectations:
Run auth, user, migration/schema and REST/MCP HTTP/stdio/persistent-session tests proving agent and anonymous requests fail and human login/refresh still work. Run affected frontend auth checks.
Use the managed verification specification for required quality commands and test placement. Record objective evidence before completion.

Before code work, read AGENTS.md and applicable skills, use CodeGraph for indexed code, inspect current implementation and record the task implementation plan through Backlog. The referenced design is context; this future ticket intentionally has no speculative implementation-plan field.

Documentation: local .agents/communication/projects-feature-plan.md, sections 4-10 for design and scope, section 11 for ordering. The managed specification documents are durable copies for checkouts where the gitignored local plan is absent. Use the execution-index document for exact phase-to-ticket IDs and ready-work commands.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 Agent account creation and login, anonymous execution and legacy admin/developer/agent account-type fields are absent from active contracts and schema.
- [ ] #2 All human users use ordinary identity records and common scoped RBAC; no global account-role/superuser shortcut remains authoritative.
- [ ] #3 No REST, MCP HTTP/stdio or persistent-session execution path accepts an agent account or anonymous request.
- [ ] #4 No old accounts, sessions, provider secrets, settings or execution history are converted or imported.
- [ ] #5 The original TASK-000004 outcome is preserved: agent accounts cannot be created or signed in and human flows work.
<!-- AC:END -->

## Definition of Done
<!-- DOD:BEGIN -->
- [ ] #1 All phase acceptance criteria have objective test or review evidence recorded in Backlog before Done.
<!-- DOD:END -->
