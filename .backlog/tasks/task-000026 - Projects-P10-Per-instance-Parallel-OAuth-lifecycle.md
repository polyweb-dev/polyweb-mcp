---
id: TASK-000026
title: Projects P10 - Per-instance Parallel OAuth lifecycle
status: To Do
assignee: []
created_date: '2026-10-24T15:54:00Z'
updated_date: '2026-10-24T15:57:00Z'
labels:
  - projects-first
  - phase-p10
  - parallel-b
milestone: m-1
dependencies:
  - TASK-000024
  - TASK-000025
references:
  - src/freesearch/services/parallel_oauth.py
  - src/freesearch/routers/oauth.py
  - src/freesearch/infrastructure/encrypted_store.py
  - src/freesearch/services/limits_sync.py
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
ordinal: 1100
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Parallel OAuth currently uses singleton grant slots. Separate accounts must not overwrite, refresh or disconnect each other.

Phase: P10. Execution lane: parallel-b. Milestone: Projects 2 - Project-first release.

Dependency gate: P08 (TASK-000024), P09 (TASK-000025)
Do not implement or mark In Progress until every dependency is Done, merged into the integration branch, and its acceptance evidence is available. Priority and phase numbers never override this gate. Parallel work is permitted only where the dependency graph and shared-file ownership allow it.

Accepted scope from plan section 10 / P10:

Namespace device flows and grants by credential instance. Scope start, poll, disconnect, refresh, and balance synchronization.
Use generation checks and per-credential refresh serialization so an old refresh cannot restore a disconnected grant.
Keep OAuth client and device secrets in the encrypted store.

Cross-phase constraints:
User-approved constraints: one human account type; one common scoped RBAC service; system/project roles are assignments, not account types. Preserve internal UUIDs and local/WorkOS storage constraints without implementing WorkOS/cloud features. Use one internal installation account. Project tokens can expire or have no expiration. Support private and explicitly shared credential instances. Strict pool/project caps are the default; fair loans require their later phase. Use a fresh alpha database; do not migrate/import old history, humans, settings or secrets. Never use the live database or real provider credentials for tests. Desktop UI only; local environment controls ports.

Verification expectations:
Use mocked device flows and token refresh with multiple credentials. Exercise disconnect/refresh races, stale generations, permission removal and orphan flow cleanup.
Use the managed verification specification for required quality commands and test placement. Record objective evidence before completion.

Before code work, read AGENTS.md and applicable skills, use CodeGraph for indexed code, inspect current implementation and record the task implementation plan through Backlog. The referenced design is context; this future ticket intentionally has no speculative implementation-plan field.

Documentation: local .agents/communication/projects-feature-plan.md, sections 4-10 for design and scope, section 11 for ordering. The managed specification documents are durable copies for checkouts where the gitignored local plan is absent. Use the execution-index document for exact phase-to-ticket IDs and ready-work commands.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 OAuth start/poll/disconnect and stored secrets are scoped to the selected credential instance and authorized owner.
- [ ] #2 Two Parallel OAuth accounts can coexist and synchronize their own balances.
- [ ] #3 Disconnect, expiry or refresh of one credential leaves another usable.
- [ ] #4 A stale refresh cannot restore a disconnected or rotated credential generation.
- [ ] #5 Permission removal before device-flow completion prevents unauthorized activation and leaves no active orphan flow.
- [ ] #6 Provider OAuth remains distinct from future WorkOS human authentication.
<!-- AC:END -->

## Definition of Done
<!-- DOD:BEGIN -->
- [ ] #1 All phase acceptance criteria have objective test or review evidence recorded in Backlog before Done.
<!-- DOD:END -->
