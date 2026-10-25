---
id: TASK-000025
title: Projects P09 - Binding-aware routing and account observations
status: To Do
assignee: []
created_date: '2026-10-24T15:54:00Z'
updated_date: '2026-10-25T14:51:00Z'
labels:
  - projects-first
  - phase-p09
  - parallel-b
milestone: m-1
dependencies:
  - TASK-000022
  - TASK-000024
  - TASK-000035
references:
  - src/freesearch/adapters/registry.py
  - src/freesearch/services/routing.py
  - src/freesearch/services/provider_limits.py
  - src/freesearch/infrastructure/resilience.py
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
ordinal: 1000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Credential instances are useful only if routing, health, quotas and breaker state identify the selected credential and its real upstream pool correctly.

Phase: P09. Execution lane: parallel-b. Milestone: Projects 2 - Project-first release.

Dependency gate: P05 (TASK-000022), P08 (TASK-000024), P11A (TASK-000035)
Do not implement or mark In Progress until every dependency is Done, merged into the integration branch, and its acceptance evidence is available. Priority and phase numbers never override this gate. Parallel work is permitted only where the dependency graph and shared-file ownership allow it.

Accepted scope from plan section 10 / P09:

Add multiple project bindings per provider and credential-aware adapter resolution.
Migrate health, native quota observations, limit catalog links, and breaker keys to the correct credential or shared pool scope.
Retain project attribution separately from upstream balance ownership.

Restructure note (2026-10-25): Also waits for TASK-000035. Key shared health, native quota observations, limit catalog links and breaker state to the TASK-000035 pool identities where the upstream scope is shared, so P11 does not rekey them.

Cross-phase constraints:
User-approved constraints: one human account type; one common scoped RBAC service; system/project roles are assignments, not account types. Preserve internal UUIDs and local/WorkOS storage constraints without implementing WorkOS/cloud features. Use one internal installation account. Project tokens can expire or have no expiration. Support private and explicitly shared credential instances. Strict pool/project caps are the default; fair loans require their later phase. Use a fresh alpha database; do not migrate/import old history, humans, settings or secrets. Never use the live database or real provider credentials for tests. Desktop UI only; local environment controls ports.

Verification expectations:
Use multiple fake credentials of one provider and shared-pool fixtures. Cover explicit binding selection, fanout, generation changes, grant removal and failure isolation.
Use the managed verification specification for required quality commands and test placement. Record objective evidence before completion.

Before code work, read AGENTS.md and applicable skills, use CodeGraph for indexed code, inspect current implementation and record the task implementation plan through Backlog. The referenced design is context; this future ticket intentionally has no speculative implementation-plan field.

Documentation: local .agents/communication/projects-feature-plan.md, sections 4-10 for design and scope, section 11 for ordering. The managed specification documents are durable copies for checkouts where the gitignored local plan is absent. Use the execution-index document for exact phase-to-ticket IDs and ready-work commands.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 A project can bind multiple credentials of one provider, with independent permitted operation enablement and priority.
- [ ] #2 Effective access intersects provider capability, system policy, grant/ownership, project choice, principal permission and health.
- [ ] #3 Adapter selection uses credential identity/generation without mutating a shared adapter with per-project settings.
- [ ] #4 Credential failures do not disable unrelated credentials; provider-wide failures and project-local errors retain separate scope.
- [ ] #5 Shared credentials retain one shared native balance/pool state, while each consumer receives correct project usage attribution.
- [ ] #6 Explicit route/binding and existing fallback behavior stay correct in REST and MCP.
<!-- AC:END -->

## Definition of Done
<!-- DOD:BEGIN -->
- [ ] #1 All phase acceptance criteria have objective test or review evidence recorded in Backlog before Done.
<!-- DOD:END -->
