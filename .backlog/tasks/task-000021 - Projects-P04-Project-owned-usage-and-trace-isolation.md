---
id: TASK-000021
title: Projects P04 - Project-owned usage and trace isolation
status: To Do
assignee: []
created_date: '2026-10-24T15:54:00Z'
updated_date: '2026-10-24T15:57:00Z'
labels:
  - projects-first
  - phase-p04
  - parallel-a
milestone: m-0
dependencies:
  - TASK-000020
references:
  - src/freesearch/persistence/storage.py
  - src/freesearch/persistence/otel_exporter.py
  - src/freesearch/services/monitoring.py
  - src/freesearch/infrastructure/observability_asgi.py
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
ordinal: 500
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Current activity is account-scoped and usage lacks project ownership. Teammates need collaborative project activity without exposing another project's records.

Phase: P04. Execution lane: parallel-a. Milestone: Projects 1 - Foundation.

Dependency gate: P03 (TASK-000020)
Do not implement or mark In Progress until every dependency is Done, merged into the integration branch, and its acceptance evidence is available. Priority and phase numbers never override this gate. Parallel work is permitted only where the dependency graph and shared-file ownership allow it.

Accepted scope from plan section 10 / P04:

Tasklet A adds non-null project ownership to usage and execution traces, with corresponding writer changes.
Tasklet B scopes dashboard, activity detail, pagination, and export reads.
Keep actor attribution and distinguish system audit events. No historical data backfill is necessary.

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
- [ ] #1 New project usage and execution traces have non-null project ownership plus the required actor and request attribution.
- [ ] #2 Root and child spans retain trusted project attribution during concurrent and fanout operations.
- [ ] #3 Activity lists, detail reads, dashboard aggregates, exports and pagination are project-scoped.
- [ ] #4 Guessed record IDs or a cursor from another project cannot disclose its data.
- [ ] #5 System audit events remain explicitly system-scoped; no legacy-data backfill is introduced.
<!-- AC:END -->

## Definition of Done
<!-- DOD:BEGIN -->
- [ ] #1 All phase acceptance criteria have objective test or review evidence recorded in Backlog before Done.
<!-- DOD:END -->
