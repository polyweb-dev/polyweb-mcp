---
id: TASK-000022
title: Projects P05 - Shared execution service and scoped REST/MCP paths
status: To Do
assignee: []
created_date: '2026-10-24T15:54:00Z'
updated_date: '2026-10-25T14:51:00Z'
labels:
  - projects-first
  - phase-p05
  - parallel-a
milestone: m-0
dependencies:
  - TASK-000020
  - TASK-000021
references:
  - src/freesearch/routers/api.py
  - src/freesearch/mcp/server.py
  - src/freesearch/services/routing.py
  - src/freesearch/services/monitoring.py
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
ordinal: 600
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
REST and MCP currently compose their own global runtimes. Both transports must apply identical project policy before provider execution and accounting.

Phase: P05. Execution lane: parallel-a. Milestone: Projects 1 - Foundation.

Dependency gate: P03 (TASK-000020), P04 (TASK-000021)
Do not implement or mark In Progress until every dependency is Done, merged into the integration branch, and its acceptance evidence is available. Priority and phase numbers never override this gate. Parallel work is permitted only where the dependency graph and shared-file ownership allow it.

Accepted scope from plan section 10 / P05:

Extract common execution policy into `services/` without a general rewrite of adapters.
Pass project context through route selection, dispatch, fanout, usage, and trace creation in both transports.
Add explicit project execution routes and preserve current fallback behavior.

Restructure note (2026-10-25): Depends on the P04 writer card only; TASK-000034 scoped reads can run in parallel. Give services/monitoring.py and storage.py one owner per integration step.

Cross-phase constraints:
User-approved constraints: one human account type; one common scoped RBAC service; system/project roles are assignments, not account types. Preserve internal UUIDs and local/WorkOS storage constraints without implementing WorkOS/cloud features. Use one internal installation account. Project tokens can expire or have no expiration. Support private and explicitly shared credential instances. Strict pool/project caps are the default; fair loans require their later phase. Use a fresh alpha database; do not migrate/import old history, humans, settings or secrets. Never use the live database or real provider credentials for tests. Desktop UI only; local environment controls ports.

Verification expectations:
Use fake providers to compare REST and MCP behavior, including rejection before side effects, pinned routes, fanout and existing fallback/terminal quota contracts.
Use the managed verification specification for required quality commands and test placement. Record objective evidence before completion.

Before code work, read AGENTS.md and applicable skills, use CodeGraph for indexed code, inspect current implementation and record the task implementation plan through Backlog. The referenced design is context; this future ticket intentionally has no speculative implementation-plan field.

Documentation: local .agents/communication/projects-feature-plan.md, sections 4-10 for design and scope, section 11 for ordering. The managed specification documents are durable copies for checkouts where the gitignored local plan is absent. Use the execution-index document for exact phase-to-ticket IDs and ready-work commands.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 Transport-neutral execution policy accepts validated project context and is shared by scoped REST and MCP paths.
- [ ] #2 Routing, dispatch, fanout, usage and trace writes preserve the same originating project.
- [ ] #3 REST and MCP produce equivalent policy decisions and attribution for equivalent requests.
- [ ] #4 Invalid scope or insufficient permission prevents any provider or accounting side effect.
- [ ] #5 Existing fallback and terminal-denial behavior remains covered by meaningful characterization tests.
- [ ] #6 Real multi-project execution stays behind the preview/release gate.
<!-- AC:END -->

## Definition of Done
<!-- DOD:BEGIN -->
- [ ] #1 All phase acceptance criteria have objective test or review evidence recorded in Backlog before Done.
<!-- DOD:END -->
