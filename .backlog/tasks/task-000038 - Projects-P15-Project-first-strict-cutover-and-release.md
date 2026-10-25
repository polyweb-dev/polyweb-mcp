---
id: TASK-000038
title: Projects P15 - Project-first strict cutover and release
status: To Do
assignee: []
created_date: '2026-10-25T14:51:00Z'
labels:
  - projects-first
  - phase-p15
  - serial-release
milestone: m-1
dependencies:
  - TASK-000027
  - TASK-000005
  - TASK-000028
  - TASK-000029
  - TASK-000004
references:
  - src/freesearch/persistence/database_migrations.py
  - src/freesearch/routers/api.py
  - src/freesearch/mcp/server.py
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
ordinal: 1650
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
The project-first release replaces the old installation. Strict project authentication and multi-project execution should be enabled only after provider isolation, strict caps, settings copy and trace policy all pass on a fresh database.

Phase: P15. Execution lane: serial-release. Milestone: Projects 2 - Project-first release.

Dependency gate: P11 (TASK-000027), P12 (TASK-000005), P13 (TASK-000028), P14 (TASK-000029), P15A (TASK-000004)
Do not implement or mark In Progress until every dependency is Done, merged into the integration branch, and its acceptance evidence is available. Priority and phase numbers never override this gate. Parallel work is permitted only where the dependency graph and shared-file ownership allow it.

Accepted scope from plan section 10 / P15 (cutover and release):

Rehearse a fresh database bootstrap, project-token issue, provider setup, and client configuration with synthetic data.
Enable strict project authentication (PROJECTS_STRICT) and release multiple-project execution.
Require a fresh database for the alpha cutover. Create non-null project ownership and scoped role-assignment constraints directly in the fresh schema.

Restructure note (2026-10-25): Agent, anonymous and account-type removal moved to P15A (TASK-000004). Phase P15 is complete only when TASK-000004 and this card are Done. P16 no longer waits for this card; P19 does, so the fair-capacity milestone qualifies against the released strict configuration.

Cross-phase constraints:
User-approved constraints: one human account type; one common scoped RBAC service; system/project roles are assignments, not account types. Preserve internal UUIDs and local/WorkOS storage constraints without implementing WorkOS/cloud features. Use one internal installation account. Project tokens can expire or have no expiration. Support private and explicitly shared credential instances. Strict pool/project caps are the default; fair loans require their later phase. Use a fresh alpha database; do not migrate/import old history, humans, settings or secrets. Never use the live database or real provider credentials for tests. Desktop UI only; local environment controls ports.

Verification expectations:
Rehearse a fresh temporary database and synthetic account/provider setup. Run full relevant auth, migration/schema, REST/MCP isolation and desktop release journeys with implementation evidence.
Use the managed verification specification for required quality commands and test placement. Record objective evidence before completion.

Before code work, read AGENTS.md and applicable skills, use CodeGraph for indexed code, inspect current implementation and record the task implementation plan through Backlog. The referenced design is context; this future ticket intentionally has no speculative implementation-plan field.

Documentation: local .agents/communication/projects-feature-plan.md, sections 4-10 for design and scope, section 11 for ordering. The managed specification documents are durable copies for checkouts where the gitignored local plan is absent. Use the execution-index document for exact phase-to-ticket IDs and ready-work commands.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 Fresh alpha bootstrap, human login/refresh, project selection, provider setup and project-token client configuration work together.
- [ ] #2 Project ownership, grants and at-least-one-active-project-admin invariants hold before enabling PROJECTS_STRICT.
- [ ] #3 No old accounts, sessions, provider secrets, settings or execution history are converted or imported.
- [ ] #4 No unscoped execution rows, orphan grants or administrator-free projects remain after the rehearsal.
<!-- AC:END -->
