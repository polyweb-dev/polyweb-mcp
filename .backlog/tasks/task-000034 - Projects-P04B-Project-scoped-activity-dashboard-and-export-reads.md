---
id: TASK-000034
title: Projects P04B - Project-scoped activity, dashboard and export reads
status: To Do
assignee: []
created_date: '2026-10-25T14:51:00Z'
labels:
  - projects-first
  - phase-p04
  - parallel-a
milestone: m-0
dependencies:
  - TASK-000021
references:
  - src/freesearch/persistence/storage.py
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
ordinal: 550
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
P04 makes new usage and trace rows project-owned, but reads still use account identity. Teammates need collaborative project activity, and no read path may disclose another project's records.

Phase: P04B. Execution lane: parallel-a. Milestone: Projects 1 - Foundation.

Dependency gate: P04 (TASK-000021)
Do not implement or mark In Progress until every dependency is Done, merged into the integration branch, and its acceptance evidence is available. Priority and phase numbers never override this gate. Parallel work is permitted only where the dependency graph and shared-file ownership allow it.

Accepted scope from plan section 10 / P04 (Tasklet B):

Scope dashboard, activity detail, pagination, counts and export reads to the selected project.
Include project scope in pagination cursors, cache keys, exports and dashboards (plan section 5, ownership of operational data).
Trace reads change from account-only visibility to project visibility; document that permitted teammates can inspect new traces in the same project (plan section 9).

Restructure note (2026-10-25): Split from P04 so P05 can start after the P04 writer card. Phase P04 is complete only when TASK-000021 and this card are Done. P05 runs in parallel: give services/monitoring.py and storage.py one owner per integration step.

Cross-phase constraints:
User-approved constraints: one human account type; one common scoped RBAC service; system/project roles are assignments, not account types. Preserve internal UUIDs and local/WorkOS storage constraints without implementing WorkOS/cloud features. Use one internal installation account. Project tokens can expire or have no expiration. Support private and explicitly shared credential instances. Strict pool/project caps are the default; fair loans require their later phase. Use a fresh alpha database; do not migrate/import old history, humans, settings or secrets. Never use the live database or real provider credentials for tests. Desktop UI only; local environment controls ports.

Verification expectations:
Test scoped usage, trace lists/details, counts, cursors and exports with two projects and concurrent fake calls. Run relevant observability integration and adversarial suites.
Use the managed verification specification for required quality commands and test placement. Record objective evidence before completion.

Before code work, read AGENTS.md and applicable skills, use CodeGraph for indexed code, inspect current implementation and record the task implementation plan through Backlog. The referenced design is context; this future ticket intentionally has no speculative implementation-plan field.

Documentation: local .agents/communication/projects-feature-plan.md, sections 4-10 for design and scope, section 11 for ordering. The managed specification documents are durable copies for checkouts where the gitignored local plan is absent. Use the execution-index document for exact phase-to-ticket IDs and ready-work commands.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 Activity lists, detail reads, dashboard aggregates, exports and pagination are project-scoped.
- [ ] #2 Guessed record IDs or a cursor from another project cannot disclose its data.
- [ ] #3 A user in two projects sees only the selected project's activity, usage and counts.
<!-- AC:END -->
