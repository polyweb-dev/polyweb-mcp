---
id: TASK-000030
title: Projects P16 - Single execution authority across transports
status: To Do
assignee: []
created_date: '2026-10-24T15:54:00Z'
updated_date: '2026-10-25T14:51:00Z'
labels:
  - projects-first
  - phase-p16
  - serial-fairness
milestone: m-2
dependencies:
  - TASK-000022
  - TASK-000006
  - TASK-000027
  - TASK-000004
references:
  - src/freesearch/routers/api.py
  - src/freesearch/mcp/server.py
  - src/freesearch/mcp/auth.py
  - src/freesearch/services/provider_limits.py
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
ordinal: 1700
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Atomic counters can cap multiple processes, but independent REST and MCP schedulers cannot provide one shared fair service order for borrowed capacity.

Phase: P16. Execution lane: serial-fairness. Milestone: Projects 3 - Fair capacity.

Dependency gate: P05 (TASK-000022), P07 (TASK-000006), P11 (TASK-000027), P15A (TASK-000004)
Do not implement or mark In Progress until every dependency is Done, merged into the integration branch, and its acceptance evidence is available. Priority and phase numbers never override this gate. Parallel work is permitted only where the dependency graph and shared-file ownership allow it.

Accepted scope from plan section 10 / P16:

Host one authoritative execution runtime and make MCP forward to it in shared deployments.
Preserve token checks, cancellation, end-to-end deadlines, and trace propagation at the authority.
Support an explicit standalone MCP authority mode only for exclusive deployments.

Restructure note (2026-10-25): Decoupled from the TASK-000038 strict cutover (user decision 2026-10-25): needs P05, P07 tokens, P11 atomic caps and P15A agent removal. Coordinate mcp/auth.py, routers/api.py and mcp/server.py with TASK-000038: one owner per integration step.

Cross-phase constraints:
User-approved constraints: one human account type; one common scoped RBAC service; system/project roles are assignments, not account types. Preserve internal UUIDs and local/WorkOS storage constraints without implementing WorkOS/cloud features. Use one internal installation account. Project tokens can expire or have no expiration. Support private and explicitly shared credential instances. Strict pool/project caps are the default; fair loans require their later phase. Use a fresh alpha database; do not migrate/import old history, humans, settings or secrets. Never use the live database or real provider credentials for tests. Desktop UI only; local environment controls ports.

Verification expectations:
Test mixed REST/MCP execution, forwarding authentication, cancellation, deadline and trace propagation, authority loss and duplicate-authority rejection with fake providers.
Use the managed verification specification for required quality commands and test placement. Record objective evidence before completion.

Before code work, read AGENTS.md and applicable skills, use CodeGraph for indexed code, inspect current implementation and record the task implementation plan through Backlog. The referenced design is context; this future ticket intentionally has no speculative implementation-plan field.

Documentation: local .agents/communication/projects-feature-plan.md, sections 4-10 for design and scope, section 11 for ordering. The managed specification documents are durable copies for checkouts where the gitignored local plan is absent. Use the execution-index document for exact phase-to-ticket IDs and ready-work commands.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 Shared deployments use one authoritative adapter/execution runtime for REST and MCP dispatch.
- [ ] #2 MCP forwarding preserves validated credentials, project context, cancellation, end-to-end deadlines and trusted trace attribution.
- [ ] #3 Standalone MCP authority mode is explicit and exclusive for a shared pool.
- [ ] #4 Authority outage rejects or fails predictably without direct-provider bypass.
- [ ] #5 Duplicate independent authority configuration cannot enable execution for a borrowed pool.
- [ ] #6 No Redis, multi-region or cloud onboarding implementation is required.
<!-- AC:END -->

## Definition of Done
<!-- DOD:BEGIN -->
- [ ] #1 All phase acceptance criteria have objective test or review evidence recorded in Backlog before Done.
<!-- DOD:END -->
