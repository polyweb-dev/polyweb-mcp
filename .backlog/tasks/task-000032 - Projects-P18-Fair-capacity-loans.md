---
id: TASK-000032
title: Projects P18 - Fair capacity loans
status: To Do
assignee: []
created_date: '2026-10-24T15:54:00Z'
updated_date: '2026-10-24T15:57:00Z'
labels:
  - projects-first
  - phase-p18
  - serial-fairness
milestone: m-2
dependencies:
  - TASK-000031
references:
  - src/freesearch/services/provider_limits.py
  - src/freesearch/services/rate_limits.py
  - src/freesearch/models/provider_limits.py
  - freesearch-ui/src/features/quota
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
ordinal: 1900
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Projects can optionally use idle upstream capacity without starving another active project or violating the global rate envelope.

Phase: P18. Execution lane: serial-fairness. Milestone: Projects 3 - Fair capacity.

Dependency gate: P17 (TASK-000031)
Do not implement or mark In Progress until every dependency is Done, merged into the integration branch, and its acceptance evidence is available. Priority and phase numbers never override this gate. Parallel work is permitted only where the dependency graph and shared-file ownership allow it.

Accepted scope from plan section 10 / P18:

Add DRR, allocation weights, maximum rates, idle deficit limits, and per-allocation loan enablement.
Expose effective policy, borrowed starts, contention, and queue wait metrics.
Add system controls for loans and a project read-only explanation.

Cross-phase constraints:
User-approved constraints: one human account type; one common scoped RBAC service; system/project roles are assignments, not account types. Preserve internal UUIDs and local/WorkOS storage constraints without implementing WorkOS/cloud features. Use one internal installation account. Project tokens can expire or have no expiration. Support private and explicitly shared credential instances. Strict pool/project caps are the default; fair loans require their later phase. Use a fresh alpha database; do not migrate/import old history, humans, settings or secrets. Never use the live database or real provider credentials for tests. Desktop UI only; local environment controls ports.

Verification expectations:
Use deterministic virtual-time continuous-demand and late-arrival scenarios with bounded discrepancies. Validate 4:6 weighted service, strict mode, loans, retries, maximums and the exact configured global envelope.
Use the managed verification specification for required quality commands and test placement. Record objective evidence before completion.

Before code work, read AGENTS.md and applicable skills, use CodeGraph for indexed code, inspect current implementation and record the task implementation plan through Backlog. The referenced design is context; this future ticket intentionally has no speculative implementation-plan field.

Documentation: local .agents/communication/projects-feature-plan.md, sections 4-10 for design and scope, section 11 for ordering. The managed specification documents are durable copies for checkouts where the gitignored local plan is absent. Use the execution-index document for exact phase-to-ticket IDs and ready-work commands.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 Capacity loans require explicit per-allocation system permission; strict mode remains the default.
- [ ] #2 Authorized A with base 4/s and maximum 10/s can use up to a shared 10/s pool when B is idle.
- [ ] #3 Under sustained eligible equal-cost demand, A and B target 4:6 service with documented bounded discrepancy and no starvation.
- [ ] #4 The global admission limiter and each project's absolute maximum remain enforced independently from DRR service order.
- [ ] #5 Idle deficit accumulation, delayed retries, cancellation and eligibility changes cannot create unfair or unbounded future credit.
- [ ] #6 UI and metrics distinguish base entitlement, strict cap, maximum, loan state, borrowed service and queue wait.
- [ ] #7 Guarantees describe long-run dispatch fairness under available capacity, not exact every-second counts or successful provider throughput.
<!-- AC:END -->

## Definition of Done
<!-- DOD:BEGIN -->
- [ ] #1 All phase acceptance criteria have objective test or review evidence recorded in Backlog before Done.
<!-- DOD:END -->
