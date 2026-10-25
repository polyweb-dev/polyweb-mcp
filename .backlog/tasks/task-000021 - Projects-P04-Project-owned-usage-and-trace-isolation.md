---
id: TASK-000021
title: Projects P04 - Project-owned usage and trace writers
status: In Progress
assignee: []
created_date: '2026-10-24T15:54:00Z'
updated_date: '2026-10-25T15:41:00Z'
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
Keep actor attribution and distinguish system audit events. No historical data backfill is necessary.

Restructure note (2026-10-25): Tasklet B (scoped dashboard, activity detail, pagination and export reads) moved to TASK-000034. P05 depends only on this card. Phase P04 is complete only when this card and TASK-000034 are Done. P08 and P11A run in parallel: allocate Alembic revisions serially and serialize edits to storage.py and database_migrations.py.

Cross-phase constraints:
User-approved constraints: one human account type; one common scoped RBAC service; system/project roles are assignments, not account types. Preserve internal UUIDs and local/WorkOS storage constraints without implementing WorkOS/cloud features. Use one internal installation account. Project tokens can expire or have no expiration. Support private and explicitly shared credential instances. Strict pool/project caps are the default; fair loans require their later phase. Use a fresh alpha database; do not migrate/import old history, humans, settings or secrets. Never use the live database or real provider credentials for tests. Desktop UI only; local environment controls ports.

Verification expectations:
Test project ownership on usage and trace writes with two projects and concurrent and fanout fake calls, including root/child span attribution and system audit events. Run relevant observability integration and adversarial suites.
Use the managed verification specification for required quality commands and test placement. Record objective evidence before completion.

Before code work, read AGENTS.md and applicable skills, use CodeGraph for indexed code, inspect current implementation and record the task implementation plan through Backlog. The referenced design is context; this future ticket intentionally has no speculative implementation-plan field.

Documentation: local .agents/communication/projects-feature-plan.md, sections 4-10 for design and scope, section 11 for ordering. The managed specification documents are durable copies for checkouts where the gitignored local plan is absent. Use the execution-index document for exact phase-to-ticket IDs and ready-work commands.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 New project usage and execution traces have non-null project ownership plus the required actor and request attribution.
- [ ] #2 Root and child spans retain trusted project attribution during concurrent and fanout operations.
- [ ] #3 System audit events remain explicitly system-scoped; no legacy-data backfill is introduced.
<!-- AC:END -->

## Definition of Done
<!-- DOD:BEGIN -->
- [ ] #1 All phase acceptance criteria have objective test or review evidence recorded in Backlog before Done.
<!-- DOD:END -->

## Comments

<!-- COMMENTS:BEGIN -->
author: @devin
created: 2026-10-25T15:06:00Z

---

Migration merge rule (2026-10-25): this card adds an Alembic revision while another lane also changes schema. Land the migration and its database_migrations.py schema-validation change as a small first pull request. P04 lands first when P04 and P08 are both ready; otherwise the first merged migration keeps the next number. The other branch rebases, renames its revision to the following number, sets down_revision to the new head, and updates the head literal in tests/integration/persistence/test_database_migrations.py, tests/integration/persistence/test_projects.py and tests/fixtures/alpha_fixtures.py. Keep one migration head. See doc-000005, Worktrees and merging.

---
<!-- COMMENTS:END -->
