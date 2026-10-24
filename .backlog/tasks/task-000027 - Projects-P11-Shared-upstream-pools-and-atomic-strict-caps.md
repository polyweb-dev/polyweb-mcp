---
id: TASK-000027
title: Projects P11 - Shared upstream pools and atomic strict caps
status: To Do
assignee: []
created_date: '2026-10-24T15:54:00Z'
updated_date: '2026-10-24T15:57:00Z'
labels:
  - projects-first
  - phase-p11
  - serial-join
milestone: m-1
dependencies:
  - TASK-000006
  - TASK-000024
  - TASK-000025
  - TASK-000026
references:
  - src/freesearch/services/provider_limits.py
  - src/freesearch/services/rate_limits.py
  - src/freesearch/persistence/limit_repository.py
  - src/freesearch/persistence/limit_rows.py
  - src/freesearch/models/provider_limits.py
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
ordinal: 1200
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Multiple projects and multiple keys share real upstream capacity. Project limits must not multiply the provider allowance or race between REST/MCP processes.

Phase: P11. Execution lane: serial-join. Milestone: Projects 2 - Project-first release.

Dependency gate: P07 (TASK-000006), P08 (TASK-000024), P09 (TASK-000025), P10 (TASK-000026)
Do not implement or mark In Progress until every dependency is Done, merged into the integration branch, and its acceptance evidence is available. Priority and phase numbers never override this gate. Parallel work is permitted only where the dependency graph and shared-file ownership allow it.

Accepted scope from plan section 10 / P11:

Add explicit upstream pools, credential links, and project allocations with loans disabled.
Generalize atomic rate and native funds admission across project and upstream constraints.
Replace process-local check-then-record paths for enforceable limits in both REST and MCP.
Split pool schema and identity from atomic enforcement into separate tasklets.

Cross-phase constraints:
User-approved constraints: one human account type; one common scoped RBAC service; system/project roles are assignments, not account types. Preserve internal UUIDs and local/WorkOS storage constraints without implementing WorkOS/cloud features. Use one internal installation account. Project tokens can expire or have no expiration. Support private and explicitly shared credential instances. Strict pool/project caps are the default; fair loans require their later phase. Use a fresh alpha database; do not migrate/import old history, humans, settings or secrets. Never use the live database or real provider credentials for tests. Desktop UI only; local environment controls ports.

Verification expectations:
Use a virtual clock and real independent SQLite connections/processes. Test strict windows, multiple keys, simultaneous transports, retries, store failure, native funds and exactly-once settlement.
Use the managed verification specification for required quality commands and test placement. Record objective evidence before completion.

Before code work, read AGENTS.md and applicable skills, use CodeGraph for indexed code, inspect current implementation and record the task implementation plan through Backlog. The referenced design is context; this future ticket intentionally has no speculative implementation-plan field.

Documentation: local .agents/communication/projects-feature-plan.md, sections 4-10 for design and scope, section 11 for ordering. The managed specification documents are durable copies for checkouts where the gitignored local plan is absent. Use the execution-index document for exact phase-to-ticket IDs and ready-work commands.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 Explicit upstream pool identity follows the documented vendor account/project/key/IP scope, not an automatic one-pool-per-key assumption.
- [ ] #2 Project allocations default to strict caps with capacity loans disabled.
- [ ] #3 Project and all shared rate/funds constraints are checked and debited atomically immediately before actual provider dispatch.
- [ ] #4 For a strict shared 10/s pool with A=4/s and B=6/s, A stops at 4/s even when B is idle, under the configured exact window semantics.
- [ ] #5 Concurrent processes and multiple keys cannot multiply a shared pool allowance.
- [ ] #6 Retrying one reservation is idempotent; a genuinely new upstream attempt is charged separately and retains its project.
- [ ] #7 Unavailable authoritative storage rejects new constrained execution; uncertain upstream receipt does not refund rate units.
- [ ] #8 Native balance/CRD precision, existing terminal quota errors and finalization semantics remain correct; reusable provider-tier presets in TASK-000003 remain separate follow-up work.
<!-- AC:END -->

## Definition of Done
<!-- DOD:BEGIN -->
- [ ] #1 All phase acceptance criteria have objective test or review evidence recorded in Backlog before Done.
<!-- DOD:END -->
