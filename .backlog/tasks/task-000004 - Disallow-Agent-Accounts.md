---
id: TASK-000004
title: Projects P15 - Project-first cutover and agent-account removal
status: To Do
assignee: []
created_date: 2026-10-15 22:19
updated_date: '2026-10-24T15:57:00Z'
labels:
  - projects-first
  - phase-p15
  - serial-release
milestone: m-1
dependencies:
  - TASK-000006
  - TASK-000027
  - TASK-000005
  - TASK-000028
  - TASK-000029
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
The alpha release should replace account classifications and anonymous/agent access only after the complete project-first workflow and strict isolation gates exist.

Phase: P15. Execution lane: serial-release. Milestone: Projects 2 - Project-first release.

Dependency gate: P07 (TASK-000006), P11 (TASK-000027), P12 (TASK-000005), P13 (TASK-000028), P14 (TASK-000029)
Do not implement or mark In Progress until every dependency is Done, merged into the integration branch, and its acceptance evidence is available. Priority and phase numbers never override this gate. Parallel work is permitted only where the dependency graph and shared-file ownership allow it.

Accepted scope from plan section 10 / P15:

Rehearse a fresh database bootstrap, project-token issue, provider setup, and client configuration with synthetic data.
Enable strict project authentication and release multiple-project execution.
Remove agent registration, agent login, and all legacy account-type role fields from the active schema and contracts.

Remove account-type role choices, anonymous execution, and obsolete global account-role checks.
Require a fresh database for the alpha cutover. Do not convert old users, sessions, history, or agent credentials.
Create non-null project ownership and scoped role-assignment constraints directly in the fresh schema.

Cross-phase constraints:
User-approved constraints: one human account type; one common scoped RBAC service; system/project roles are assignments, not account types. Preserve internal UUIDs and local/WorkOS storage constraints without implementing WorkOS/cloud features. Use one internal installation account. Project tokens can expire or have no expiration. Support private and explicitly shared credential instances. Strict pool/project caps are the default; fair loans require their later phase. Use a fresh alpha database; do not migrate/import old history, humans, settings or secrets. Never use the live database or real provider credentials for tests. Desktop UI only; local environment controls ports.

Verification expectations:
Rehearse a fresh temporary database and synthetic account/provider setup. Run full relevant auth, migration/schema, REST/MCP isolation and desktop release journeys with implementation evidence.
Use the managed verification specification for required quality commands and test placement. Record objective evidence before completion.

Before code work, read AGENTS.md and applicable skills, use CodeGraph for indexed code, inspect current implementation and record the task implementation plan through Backlog. The referenced design is context; this future ticket intentionally has no speculative implementation-plan field.

Documentation: local .agents/communication/projects-feature-plan.md, sections 4-10 for design and scope, section 11 for ordering. The managed specification documents are durable copies for checkouts where the gitignored local plan is absent. Use the execution-index document for exact phase-to-ticket IDs and ready-work commands.

Origin: Reuses TASK-000004, originally "Disallow Agent Accounts". Its original outcome remains part of this phase.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 Fresh alpha bootstrap, human login/refresh, project selection, provider setup and project-token client configuration work together.
- [ ] #2 Agent account creation and login, anonymous execution and legacy admin/developer/agent account-type fields are absent from active contracts and schema.
- [ ] #3 All human users use ordinary identity records and common scoped RBAC; no global account-role/superuser shortcut remains authoritative.
- [ ] #4 No REST, MCP HTTP/stdio or persistent-session execution path accepts an agent account or anonymous request.
- [ ] #5 No old accounts, sessions, provider secrets, settings or execution history are converted or imported.
- [ ] #6 Project ownership, grants and at-least-one-active-project-admin invariants hold before enabling PROJECTS_STRICT.
- [ ] #7 The original TASK-000004 outcome is preserved: agent accounts cannot be created or signed in and human flows work.
<!-- AC:END -->

## Definition of Done
<!-- DOD:BEGIN -->
- [ ] #1 All phase acceptance criteria have objective test or review evidence recorded in Backlog before Done.
<!-- DOD:END -->
