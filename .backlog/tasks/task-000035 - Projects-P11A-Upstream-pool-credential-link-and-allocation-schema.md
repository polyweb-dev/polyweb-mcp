---
id: TASK-000035
title: Projects P11A - Upstream pool, credential link and allocation schema
status: To Do
assignee: []
created_date: '2026-10-25T14:51:00Z'
updated_date: '2026-10-25T15:06:00Z'
labels:
  - projects-first
  - phase-p11
  - parallel-b
milestone: m-1
dependencies:
  - TASK-000024
references:
  - src/freesearch/persistence/limit_rows.py
  - src/freesearch/persistence/limit_repository.py
  - src/freesearch/models/provider_limits.py
  - src/freesearch/persistence/database_migrations.py
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
ordinal: 950
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Several keys can share one real upstream quota, and keyless providers can share IP-scoped limits. Pool identity must exist before binding-aware routing so health, quota observations and breakers are keyed to the correct shared scope once, not reworked when strict enforcement arrives.

Phase: P11A. Execution lane: parallel-b. Milestone: Projects 2 - Project-first release.

Dependency gate: P08 (TASK-000024)
Do not implement or mark In Progress until every dependency is Done, merged into the integration branch, and its acceptance evidence is available. Priority and phase numbers never override this gate. Parallel work is permitted only where the dependency graph and shared-file ownership allow it.

Accepted scope from plan section 10 / P11 (Tasklet A):

Add explicit upstream pools, credential-pool links and project allocations with loans disabled (plan section 5: upstream_quota_pools, credential_pool_links, project_pool_allocations).
Link existing limit tables to credential and pool identities instead of duplicating a shared upstream balance per project. Preserve native balance pools, CRD conversion profiles and per-operation cost semantics.
No enforcement change: atomic admission remains in P11 (TASK-000027).

Restructure note (2026-10-25): Plan section 10 requires splitting pool schema and identity from atomic enforcement. This tasklet moved ahead of P09 so P09 keys shared observations to real pool identities. Phase P11 is complete only when this card and TASK-000027 are Done. Allocate the Alembic revision serially with P04, P07 and P08 and merge one schema head.

Cross-phase constraints:
User-approved constraints: one human account type; one common scoped RBAC service; system/project roles are assignments, not account types. Preserve internal UUIDs and local/WorkOS storage constraints without implementing WorkOS/cloud features. Use one internal installation account. Project tokens can expire or have no expiration. Support private and explicitly shared credential instances. Strict pool/project caps are the default; fair loans require their later phase. Use a fresh alpha database; do not migrate/import old history, humans, settings or secrets. Never use the live database or real provider credentials for tests. Desktop UI only; local environment controls ports.

Verification expectations:
Use temporary fresh databases and persistence tests with fake credentials: multiple keys in one pool, multiple pools per operation, keyless shared IP pools, strict-default allocations and schema validation. No enforcement or live provider calls.
Use the managed verification specification for required quality commands and test placement. Record objective evidence before completion.

Before code work, read AGENTS.md and applicable skills, use CodeGraph for indexed code, inspect current implementation and record the task implementation plan through Backlog. The referenced design is context; this future ticket intentionally has no speculative implementation-plan field.

Documentation: local .agents/communication/projects-feature-plan.md, sections 4-10 for design and scope, section 11 for ordering. The managed specification documents are durable copies for checkouts where the gitignored local plan is absent. Use the execution-index document for exact phase-to-ticket IDs and ready-work commands.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 Explicit upstream pool identity follows the documented vendor account/project/key/IP scope, not an automatic one-pool-per-key assumption.
- [ ] #2 Project allocations default to strict caps with capacity loans disabled.
- [ ] #3 Credentials link to pools per operation scope; adding a credential never creates extra capacity or resets a pool's consumed allowance.
- [ ] #4 Shared pool rows carry an explicit shared-pool ownership category and are not attached to an arbitrary project.
- [ ] #5 Schema validation, fresh-database creation and foreign-key checks cover the new tables.
<!-- AC:END -->

## Comments

<!-- COMMENTS:BEGIN -->
author: @devin
created: 2026-10-25T15:06:00Z

---

Migration merge rule (2026-10-25): this card adds an Alembic revision while another lane also changes schema. Land the migration and its database_migrations.py schema-validation change as a small first pull request. P04 lands first when P04 and P08 are both ready; otherwise the first merged migration keeps the next number. The other branch rebases, renames its revision to the following number, sets down_revision to the new head, and updates the head literal in tests/integration/persistence/test_database_migrations.py, tests/integration/persistence/test_projects.py and tests/fixtures/alpha_fixtures.py. Keep one migration head. See doc-000005, Worktrees and merging.

---
<!-- COMMENTS:END -->
