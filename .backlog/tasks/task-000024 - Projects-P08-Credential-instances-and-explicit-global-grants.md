---
id: TASK-000024
title: Projects P08 - Credential instances and explicit global grants
status: To Do
assignee: []
created_date: '2026-10-24T15:54:00Z'
updated_date: '2026-10-24T15:57:00Z'
labels:
  - projects-first
  - phase-p08
  - parallel-b
milestone: m-1
dependencies:
  - TASK-000020
references:
  - src/freesearch/infrastructure/encrypted_store.py
  - src/freesearch/infrastructure/cryptography.py
  - src/freesearch/routers/control.py
  - src/freesearch/persistence/storage.py
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
ordinal: 900
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
The singleton provider secret slots prevent multiple keys for one provider. Shared reuse must avoid duplicate secrets while keeping private credentials isolated.

Phase: P08. Execution lane: parallel-b. Milestone: Projects 2 - Project-first release.

Dependency gate: P03 (TASK-000020)
Do not implement or mark In Progress until every dependency is Done, merged into the integration branch, and its acceptance evidence is available. Priority and phase numbers never override this gate. Parallel work is permitted only where the dependency graph and shared-file ownership allow it.

Accepted scope from plan section 10 / P08:

Add credential metadata, per-instance encrypted slots, generation numbers, ownership, and global project grants.
Store newly entered provider secrets through the encrypted store. Preserve delete-wins tombstone behavior for the new per-instance slots.
No old provider-secret import is necessary.

Cross-phase constraints:
User-approved constraints: one human account type; one common scoped RBAC service; system/project roles are assignments, not account types. Preserve internal UUIDs and local/WorkOS storage constraints without implementing WorkOS/cloud features. Use one internal installation account. Project tokens can expire or have no expiration. Support private and explicitly shared credential instances. Strict pool/project caps are the default; fair loans require their later phase. Use a fresh alpha database; do not migrate/import old history, humans, settings or secrets. Never use the live database or real provider credentials for tests. Desktop UI only; local environment controls ports.

Verification expectations:
Use encrypted-store and persistence tests with fake secrets. Exercise private ownership, explicit grants, generation rotation and delete-wins behavior. Do not read live keys.
Use the managed verification specification for required quality commands and test placement. Record objective evidence before completion.

Before code work, read AGENTS.md and applicable skills, use CodeGraph for indexed code, inspect current implementation and record the task implementation plan through Backlog. The referenced design is context; this future ticket intentionally has no speculative implementation-plan field.

Documentation: local .agents/communication/projects-feature-plan.md, sections 4-10 for design and scope, section 11 for ordering. The managed specification documents are durable copies for checkouts where the gitignored local plan is absent. Use the execution-index document for exact phase-to-ticket IDs and ready-work commands.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 Multiple separately labelled credential instances can exist for the same provider.
- [ ] #2 One installation-shared credential can serve explicitly granted projects without duplicate secret storage.
- [ ] #3 A project's private credential cannot be enumerated, read or bound by another project.
- [ ] #4 Imported credentials expose only permitted metadata; project administrators cannot rotate, delete or reshare a system-owned secret.
- [ ] #5 Per-instance encrypted storage preserves generation and delete-wins tombstone behavior without secret output.
- [ ] #6 No legacy credential import or cloud credential-management feature is introduced.
<!-- AC:END -->

## Definition of Done
<!-- DOD:BEGIN -->
- [ ] #1 All phase acceptance criteria have objective test or review evidence recorded in Backlog before Done.
<!-- DOD:END -->
