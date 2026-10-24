---
id: TASK-000029
title: Projects P14 - Project trace policy and retention jobs
status: To Do
assignee: []
created_date: '2026-10-24T15:54:00Z'
updated_date: '2026-10-24T15:57:00Z'
labels:
  - projects-first
  - phase-p14
  - parallel-retention
milestone: m-1
dependencies:
  - TASK-000021
  - TASK-000005
references:
  - src/freesearch/persistence/otel_exporter.py
  - src/freesearch/infrastructure/observability.py
  - src/freesearch/persistence/storage.py
  - freesearch-ui/src/features/activity
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
ordinal: 1500
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Trace detail, privacy and retention must be configurable per project without disabling mandatory security audit or deleting another project's records.

Phase: P14. Execution lane: parallel-retention. Milestone: Projects 2 - Project-first release.

Dependency gate: P04 (TASK-000021), P12 (TASK-000005)
Do not implement or mark In Progress until every dependency is Done, merged into the integration branch, and its acceptance evidence is available. Priority and phase numbers never override this gate. Parallel work is permitted only where the dependency graph and shared-file ownership allow it.

Accepted scope from plan section 10 / P14:

Add project sampling, detail, redaction, retention resolution, and scoped cleanup jobs.
Keep security audit retention and system export destinations under system policy.
Add project policy controls and effective-policy summaries.

Cross-phase constraints:
User-approved constraints: one human account type; one common scoped RBAC service; system/project roles are assignments, not account types. Preserve internal UUIDs and local/WorkOS storage constraints without implementing WorkOS/cloud features. Use one internal installation account. Project tokens can expire or have no expiration. Support private and explicitly shared credential instances. Strict pool/project caps are the default; fair loans require their later phase. Use a fresh alpha database; do not migrate/import old history, humans, settings or secrets. Never use the live database or real provider credentials for tests. Desktop UI only; local environment controls ports.

Verification expectations:
Use deterministic sampling/retention fixtures for two projects and mandatory audit events. Exercise cleanup jobs and settings read-only behavior; run affected backend/frontend checks.
Use the managed verification specification for required quality commands and test placement. Record objective evidence before completion.

Before code work, read AGENTS.md and applicable skills, use CodeGraph for indexed code, inspect current implementation and record the task implementation plan through Backlog. The referenced design is context; this future ticket intentionally has no speculative implementation-plan field.

Documentation: local .agents/communication/projects-feature-plan.md, sections 4-10 for design and scope, section 11 for ordering. The managed specification documents are durable copies for checkouts where the gitignored local plan is absent. Use the execution-index document for exact phase-to-ticket IDs and ready-work commands.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 Effective project sampling, detail, redaction and retention policies stay within typed system constraints.
- [ ] #2 Exporter destinations and mandatory audit retention remain under system policy.
- [ ] #3 Different projects receive their own new trace behavior and scoped retention cleanup.
- [ ] #4 A retention or purge operation cannot delete another project's trace spans.
- [ ] #5 Membership, token, credential grant, allocation and settings security events survive optional request sampling changes.
- [ ] #6 Project policy controls expose effective provenance without sensitive credential or payload leakage.
<!-- AC:END -->

## Definition of Done
<!-- DOD:BEGIN -->
- [ ] #1 All phase acceptance criteria have objective test or review evidence recorded in Backlog before Done.
<!-- DOD:END -->
