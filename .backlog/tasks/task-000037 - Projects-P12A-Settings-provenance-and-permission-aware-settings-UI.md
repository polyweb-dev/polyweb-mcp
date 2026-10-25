---
id: TASK-000037
title: Projects P12A - Settings provenance and permission-aware settings UI
status: To Do
assignee: []
created_date: '2026-10-25T14:51:00Z'
labels:
  - projects-first
  - phase-p12
  - parallel-ui
milestone: m-1
dependencies:
  - TASK-000020
  - TASK-000023
references:
  - freesearch-ui/src/components/settings
  - freesearch-ui/src/app/permissions.ts
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
ordinal: 1250
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
P03 already exposes scoped system and project settings with per-field provenance. The desktop needs one shared settings UI composition that later copy (P13) and trace-policy (P14) controls extend, instead of three cards editing the same settings screens.

Phase: P12A. Execution lane: parallel-ui. Milestone: Projects 2 - Project-first release.

Dependency gate: P03 (TASK-000020), P06 (TASK-000023)
Do not implement or mark In Progress until every dependency is Done, merged into the integration branch, and its acceptance evidence is available. Priority and phase numbers never override this gate. Parallel work is permitted only where the dependency graph and shared-file ownership allow it.

Accepted scope from plan section 10 / P12 (part of Tasklet B):

Add setting provenance and permission-based read-only behavior for system and project settings.
Show effective value, system/project source scope, revision and an Inherit/reset action (plan sections 4.7 and 8). Project members see read-only settings unless the effective permission permits an edit.
Allocation views and system allocation edits stay in P12 (TASK-000005).

Restructure note (2026-10-25): Split from P12. This card owns the shared settings UI composition; P13 and P14 extend it. Phase P12 is complete only when this card and TASK-000005 are Done.

Cross-phase constraints:
User-approved constraints: one human account type; one common scoped RBAC service; system/project roles are assignments, not account types. Preserve internal UUIDs and local/WorkOS storage constraints without implementing WorkOS/cloud features. Use one internal installation account. Project tokens can expire or have no expiration. Support private and explicitly shared credential instances. Strict pool/project caps are the default; fair loans require their later phase. Use a fresh alpha database; do not migrate/import old history, humans, settings or secrets. Never use the live database or real provider credentials for tests. Desktop UI only; local environment controls ports.

Verification expectations:
Run colocated component tests and a desktop BDD journey for member read-only, admin override, reset-to-inherit and stale-revision conflict. Run required frontend audits/build.
Use the managed verification specification for required quality commands and test placement. Record objective evidence before completion.

Before code work, read AGENTS.md and applicable skills, use CodeGraph for indexed code, inspect current implementation and record the task implementation plan through Backlog. The referenced design is context; this future ticket intentionally has no speculative implementation-plan field.

Documentation: local .agents/communication/projects-feature-plan.md, sections 4-10 for design and scope, section 11 for ordering. The managed specification documents are durable copies for checkouts where the gitignored local plan is absent. Use the execution-index document for exact phase-to-ticket IDs and ready-work commands.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 Settings show effective value, source scope and reset-to-inherit behavior.
- [ ] #2 Read-only and edit affordances follow backend effective permissions rather than legacy human account types.
- [ ] #3 Stale-revision conflicts are shown to the user instead of silently overwriting settings.
- [ ] #4 System settings and project settings screens stay separate; no project control can raise a system ceiling.
<!-- AC:END -->
