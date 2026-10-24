---
id: TASK-000005
title: Projects P12 - Project provider, settings, and limits UX
status: To Do
assignee: []
created_date: 2026-10-15 22:19
updated_date: '2026-10-24T15:57:00Z'
labels:
  - projects-first
  - phase-p12
  - serial-join
milestone: m-1
dependencies:
  - TASK-000023
  - TASK-000024
  - TASK-000025
  - TASK-000026
  - TASK-000027
references:
  - freesearch-ui/src/components/settings
  - freesearch-ui/src/domains/providers
  - freesearch-ui/src/features/quota
  - freesearch-ui/src/features/oauth
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
type: enhancement
ordinal: 1300
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Users need a coherent project-first table/settings experience after the scoped provider and strict-limit APIs exist, with clear separation between global authority and project choices.

Phase: P12. Execution lane: serial-join. Milestone: Projects 2 - Project-first release.

Dependency gate: P06 (TASK-000023), P08 (TASK-000024), P09 (TASK-000025), P10 (TASK-000026), P11 (TASK-000027)
Do not implement or mark In Progress until every dependency is Done, merged into the integration branch, and its acceptance evidence is available. Priority and phase numbers never override this gate. Parallel work is permitted only where the dependency graph and shared-file ownership allow it.

Accepted scope from plan section 10 / P12:

Tasklet A adds global credential/grant administration and project binding, private key, and OAuth controls.
Tasklet B adds setting provenance, allocation views, system allocation edits, and permission-based read-only behavior.
Show credential labels and pool ownership without raw secrets or unrelated project usage.

Cross-phase constraints:
User-approved constraints: one human account type; one common scoped RBAC service; system/project roles are assignments, not account types. Preserve internal UUIDs and local/WorkOS storage constraints without implementing WorkOS/cloud features. Use one internal installation account. Project tokens can expire or have no expiration. Support private and explicitly shared credential instances. Strict pool/project caps are the default; fair loans require their later phase. Use a fresh alpha database; do not migrate/import old history, humans, settings or secrets. Never use the live database or real provider credentials for tests. Desktop UI only; local environment controls ports.

Verification expectations:
Run colocated component tests and desktop BDD for shared/private credentials, multiple bindings, effective values, scoped roles and the complete create-project-to-execute workflow. Run required frontend audits/build.
Use the managed verification specification for required quality commands and test placement. Record objective evidence before completion.

Before code work, read AGENTS.md and applicable skills, use CodeGraph for indexed code, inspect current implementation and record the task implementation plan through Backlog. The referenced design is context; this future ticket intentionally has no speculative implementation-plan field.

Documentation: local .agents/communication/projects-feature-plan.md, sections 4-10 for design and scope, section 11 for ordering. The managed specification documents are durable copies for checkouts where the gitignored local plan is absent. Use the execution-index document for exact phase-to-ticket IDs and ready-work commands.

Origin: Reuses TASK-000005, originally "Update Projects mode, tables, and global/project settings". Its original outcome remains part of this phase.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 Project tables support shared credential grants, private credentials, multiple provider bindings and per-project enablement/priority.
- [ ] #2 System administration is separate from project configuration; unrelated credential metadata and project usage remain private.
- [ ] #3 Settings show effective value, source scope and reset-to-inherit behavior.
- [ ] #4 Allocation edits are limited to the proper system permissions and cannot raise a system ceiling through a project control.
- [ ] #5 UI controls follow backend effective permissions rather than legacy human account types.
- [ ] #6 A user can create an authorized project, assign members, configure providers, issue a token and inspect isolated activity through the desktop workflow.
- [ ] #7 Existing Projects table/global-project settings intent from TASK-000005 remains satisfied.
<!-- AC:END -->

## Definition of Done
<!-- DOD:BEGIN -->
- [ ] #1 All phase acceptance criteria have objective test or review evidence recorded in Backlog before Done.
<!-- DOD:END -->
