---
id: TASK-000028
title: Projects P13 - Safe settings copy
status: To Do
assignee: []
created_date: '2026-10-24T15:54:00Z'
updated_date: '2026-10-24T15:57:00Z'
labels:
  - projects-first
  - phase-p13
  - parallel-copy
milestone: m-1
dependencies:
  - TASK-000020
  - TASK-000025
  - TASK-000005
references:
  - src/freesearch/routers/control.py
  - src/freesearch/configuration/provider_config.py
  - freesearch-ui/src/components/settings
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
ordinal: 1400
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Copying project setup should save repetitive configuration without copying secrets, membership, capacity authority or another project's accumulated state.

Phase: P13. Execution lane: parallel-copy. Milestone: Projects 2 - Project-first release.

Dependency gate: P03 (TASK-000020), P09 (TASK-000025), P12 (TASK-000005)
Do not implement or mark In Progress until every dependency is Done, merged into the integration branch, and its acceptance evidence is available. Priority and phase numbers never override this gate. Parallel work is permitted only where the dependency graph and shared-file ownership allow it.

Accepted scope from plan section 10 / P13:

Add preview/apply contracts, revision checks, copy modes, binding validation, and the project copy dialog.
Make the operation transactional and auditable. Treat shared allocation changes as separate system-admin proposals.

Cross-phase constraints:
User-approved constraints: one human account type; one common scoped RBAC service; system/project roles are assignments, not account types. Preserve internal UUIDs and local/WorkOS storage constraints without implementing WorkOS/cloud features. Use one internal installation account. Project tokens can expire or have no expiration. Support private and explicitly shared credential instances. Strict pool/project caps are the default; fair loans require their later phase. Use a fresh alpha database; do not migrate/import old history, humans, settings or secrets. Never use the live database or real provider credentials for tests. Desktop UI only; local environment controls ports.

Verification expectations:
Test preview/apply revision conflicts, both inheritance modes, source/target authorization, missing grants and transactional failure. Cover the desktop copy dialog.
Use the managed verification specification for required quality commands and test placement. Record objective evidence before completion.

Before code work, read AGENTS.md and applicable skills, use CodeGraph for indexed code, inspect current implementation and record the task implementation plan through Backlog. The referenced design is context; this future ticket intentionally has no speculative implementation-plan field.

Documentation: local .agents/communication/projects-feature-plan.md, sections 4-10 for design and scope, section 11 for ordering. The managed specification documents are durable copies for checkouts where the gitignored local plan is absent. Use the execution-index document for exact phase-to-ticket IDs and ready-work commands.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 Copy requires source read and target copy/write permissions and offers a preview before apply.
- [ ] #2 Overrides-only is the default; effective snapshot explicitly pins inherited values.
- [ ] #3 Source/target revisions detect stale previews and selected changes apply atomically with audit attribution.
- [ ] #4 Only credential references already authorized for the target can be copied; source private secrets cannot cross projects.
- [ ] #5 Tokens, members, roles, secrets, history, balances, limiter state and extra privileges are never copied.
- [ ] #6 Shared capacity changes remain system-admin proposals rather than permissions granted by settings copy.
<!-- AC:END -->

## Definition of Done
<!-- DOD:BEGIN -->
- [ ] #1 All phase acceptance criteria have objective test or review evidence recorded in Backlog before Done.
<!-- DOD:END -->
