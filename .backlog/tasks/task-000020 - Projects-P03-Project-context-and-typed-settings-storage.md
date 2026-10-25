---
id: TASK-000020
title: Projects P03 - Project context and typed settings storage
status: In Progress
assignee: []
created_date: '2026-10-24T15:54:00Z'
updated_date: '2026-10-25T10:24:00Z'
labels:
  - projects-first
  - phase-p03
  - serial-foundation
milestone: m-0
dependencies:
  - TASK-000019
references:
  - src/freesearch/configuration/provider_config.py
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
ordinal: 1000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Global singleton settings currently affect all requests. Project-specific behavior needs validated context and typed overrides with a visible and enforceable inheritance policy.

Phase: P03. Execution lane: serial-foundation. Milestone: Projects 1 - Foundation.

Dependency gate: P02 (TASK-000019)
Do not implement or mark In Progress until every dependency is Done, merged into the integration branch, and its acceptance evidence is available. Priority and phase numbers never override this gate. Parallel work is permitted only where the dependency graph and shared-file ownership allow it.

Accepted scope from plan section 10 / P03:

Add `ProjectContext`, project-aware repository facades, system settings, project overrides, and revisioned resolution.
Expose scoped settings reads and bounded writes. Keep execution in preview mode during this phase.
Extract configuration resolution out of transport handlers where necessary.

Cross-phase constraints:
User-approved constraints: one human account type; one common scoped RBAC service; system/project roles are assignments, not account types. Preserve internal UUIDs and local/WorkOS storage constraints without implementing WorkOS/cloud features. Use one internal installation account. Project tokens can expire or have no expiration. Support private and explicitly shared credential instances. Strict pool/project caps are the default; fair loans require their later phase. Use a fresh alpha database; do not migrate/import old history, humans, settings or secrets. Never use the live database or real provider credentials for tests. Desktop UI only; local environment controls ports.

Verification expectations:
Test inheritance and revision conflicts with temporary repositories. Run affected configuration, control-router and persistence suites plus backend checks.
Use the managed verification specification for required quality commands and test placement. Record objective evidence before completion.

Before code work, read AGENTS.md and applicable skills, use CodeGraph for indexed code, inspect current implementation and record the task implementation plan through Backlog. The referenced design is context; this future ticket intentionally has no speculative implementation-plan field.

Documentation: local .agents/communication/projects-feature-plan.md, sections 4-10 for design and scope, section 11 for ordering. The managed specification documents are durable copies for checkouts where the gitignored local plan is absent. Use the execution-index document for exact phase-to-ticket IDs and ready-work commands.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 Immutable validated account/project context reaches project repository and settings operations.
- [ ] #2 System defaults and explicit project overrides resolve with per-field provenance and system safety constraints.
- [ ] #3 Missing overrides, explicit false, null, empty collections, reset and replacement rules retain their documented distinct meanings.
- [ ] #4 Stale revisions reject writes instead of silently overwriting another change.
- [ ] #5 Settings reads/writes cannot cross project scope; cross-process cache invalidation respects system and project revisions.
- [ ] #6 Project execution remains in preview mode until the release gate.
<!-- AC:END -->

## Definition of Done
<!-- DOD:BEGIN -->
- [ ] #1 All phase acceptance criteria have objective test or review evidence recorded in Backlog before Done.
<!-- DOD:END -->
