---
id: TASK-000033
title: Projects P19 - Cross-process recovery and operational qualification
status: To Do
assignee: []
created_date: '2026-10-24T15:54:00Z'
updated_date: '2026-10-25T14:51:00Z'
labels:
  - projects-first
  - phase-p19
  - serial-fairness
milestone: m-2
dependencies:
  - TASK-000032
  - TASK-000038
references:
  - src/freesearch/routers/api.py
  - src/freesearch/mcp/server.py
  - src/freesearch/services/provider_limits.py
  - src/freesearch/persistence/limit_repository.py
documentation:
  - doc-000001
  - doc-000002
  - doc-000003
  - doc-000004
  - doc-000005
  - .agents/communication/projects-feature-plan.md
  - .backlog/docs/doc-000005 - Projects-execution-index-start-here.md
priority: high
type: task
ordinal: 2000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Fair service and strict accounting need proof under runtime recovery and mixed-transport contention before the final capacity-loan milestone is considered stable.

Phase: P19. Execution lane: serial-fairness. Milestone: Projects 3 - Fair capacity.

Dependency gate: P18 (TASK-000032), P15 (TASK-000038)
Do not implement or mark In Progress until every dependency is Done, merged into the integration branch, and its acceptance evidence is available. Priority and phase numbers never override this gate. Parallel work is permitted only where the dependency graph and shared-file ownership allow it.

Accepted scope from plan section 10 / P19:

Exercise authority restart, native funds reconciliation, provider throttles, credential rotation, policy edits, and cancellation under load.
Publish the supported deployment topology, scaling limits, failure responses, and rollback procedure.
Define acceptance targets for queue latency and throughput from measured capacity.

Restructure note (2026-10-25): Also waits for TASK-000038 so the fair-capacity milestone qualifies against the released strict project-first configuration.

Cross-phase constraints:
User-approved constraints: one human account type; one common scoped RBAC service; system/project roles are assignments, not account types. Preserve internal UUIDs and local/WorkOS storage constraints without implementing WorkOS/cloud features. Use one internal installation account. Project tokens can expire or have no expiration. Support private and explicitly shared credential instances. Strict pool/project caps are the default; fair loans require their later phase. Use a fresh alpha database; do not migrate/import old history, humans, settings or secrets. Never use the live database or real provider credentials for tests. Desktop UI only; local environment controls ports.

Verification expectations:
Run targeted recovery/load experiments with fake providers and temporary authoritative storage, plus relevant full suites. Record measured admission/queue latency and supported limits; avoid live secrets and paid provider calls.
Use the managed verification specification for required quality commands and test placement. Record objective evidence before completion.

Before code work, read AGENTS.md and applicable skills, use CodeGraph for indexed code, inspect current implementation and record the task implementation plan through Backlog. The referenced design is context; this future ticket intentionally has no speculative implementation-plan field.

Documentation: local .agents/communication/projects-feature-plan.md, sections 4-10 for design and scope, section 11 for ordering. The managed specification documents are durable copies for checkouts where the gitignored local plan is absent. Use the execution-index document for exact phase-to-ticket IDs and ready-work commands.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 Mixed REST/MCP contention, provider throttles, credential rotation and policy edits preserve project isolation and configured pool limits.
- [ ] #2 Authority restart, clock rollback and store failure cannot restore an unsafe full bucket or duplicate native funds settlement.
- [ ] #3 Unknown upstream dispatch outcomes receive a conservative documented accounting/recovery policy.
- [ ] #4 Operational guidance records topology, capacity limits, queue/deadline behavior, failure responses and rollback steps.
- [ ] #5 Measured queue latency and throughput support explicit acceptance targets rather than assumed performance.
- [ ] #6 The existing local-auth and project-token workflows still pass; cloud infrastructure remains deferred.
<!-- AC:END -->

## Definition of Done
<!-- DOD:BEGIN -->
- [ ] #1 All phase acceptance criteria have objective test or review evidence recorded in Backlog before Done.
<!-- DOD:END -->
