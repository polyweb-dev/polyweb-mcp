---
id: TASK-000031
title: Projects P17 - Bounded queues with strict allocations
status: To Do
assignee: []
created_date: '2026-10-24T15:54:00Z'
updated_date: '2026-10-24T15:57:00Z'
labels:
  - projects-first
  - phase-p17
  - serial-fairness
milestone: m-2
dependencies:
  - TASK-000030
references:
  - src/freesearch/services/provider_limits.py
  - src/freesearch/models/provider_limits.py
  - src/freesearch/routers/api.py
  - src/freesearch/mcp/server.py
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
ordinal: 1800
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Bounded queues are needed before idle-capacity loans so waiting work cannot exhaust memory and expired/canceled work cannot spend provider quota.

Phase: P17. Execution lane: serial-fairness. Milestone: Projects 3 - Fair capacity.

Dependency gate: P16 (TASK-000030)
Do not implement or mark In Progress until every dependency is Done, merged into the integration branch, and its acceptance evidence is available. Priority and phase numbers never override this gate. Parallel work is permitted only where the dependency graph and shared-file ownership allow it.

Accepted scope from plan section 10 / P17:

Add the queue interface, project and global bounds, deadline cancellation, dispatch hooks, and queue metrics.
Keep strict caps and loans disabled. Retain atomic admission at actual dispatch.
Document the loss of queued, nondispatched requests on process restart.

Cross-phase constraints:
User-approved constraints: one human account type; one common scoped RBAC service; system/project roles are assignments, not account types. Preserve internal UUIDs and local/WorkOS storage constraints without implementing WorkOS/cloud features. Use one internal installation account. Project tokens can expire or have no expiration. Support private and explicitly shared credential instances. Strict pool/project caps are the default; fair loans require their later phase. Use a fresh alpha database; do not migrate/import old history, humans, settings or secrets. Never use the live database or real provider credentials for tests. Desktop UI only; local environment controls ports.

Verification expectations:
Use virtual time for count/byte saturation, deadlines, cancellation before/after dispatch, permission removal, retry delays, shutdown and queue-restart semantics.
Use the managed verification specification for required quality commands and test placement. Record objective evidence before completion.

Before code work, read AGENTS.md and applicable skills, use CodeGraph for indexed code, inspect current implementation and record the task implementation plan through Backlog. The referenced design is context; this future ticket intentionally has no speculative implementation-plan field.

Documentation: local .agents/communication/projects-feature-plan.md, sections 4-10 for design and scope, section 11 for ordering. The managed specification documents are durable copies for checkouts where the gitignored local plan is absent. Use the execution-index document for exact phase-to-ticket IDs and ready-work commands.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 Per-project and total queue count, byte, wait-time and concurrency bounds are explicit and enforced.
- [ ] #2 Admission into a queue is separate from the final atomic debit at actual dispatch.
- [ ] #3 Queued work rechecks token/role/grant/project state and deadline before provider execution.
- [ ] #4 Canceled or expired queued work never reaches a provider or consumes a rate attempt.
- [ ] #5 Queue overload produces bounded behavior and distinct diagnostics; queue wait is separate from provider latency.
- [ ] #6 Strict caps remain enabled and capacity loans remain disabled; restart behavior for nondispatched work is documented.
<!-- AC:END -->

## Definition of Done
<!-- DOD:BEGIN -->
- [ ] #1 All phase acceptance criteria have objective test or review evidence recorded in Backlog before Done.
<!-- DOD:END -->
