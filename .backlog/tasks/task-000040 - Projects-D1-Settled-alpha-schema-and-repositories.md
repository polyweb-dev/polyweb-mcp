---
id: TASK-000040
title: Projects D1 - Settled alpha schema and repositories
status: To Do
assignee: []
created_date: '2026-10-26T09:47:00Z'
labels:
  - projects-first
  - step-1-database
milestone: m-0
dependencies: []
documentation:
  - doc-000003
  - doc-000005
  - doc-000002
  - doc-000001
  - doc-000004
priority: high
type: feature
ordinal: 24000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
The alpha keeps no compatibility with old databases, contracts or account roles. Settling the whole schema once, including fair capacity, lets the API cards run in parallel against it instead of serializing migrations. Design: local plan sections 4.2-4.5, 5 and 12 (doc-000001, doc-000002, doc-000004).

Step rules and the shared Definition of Done: doc-000003. Card map and worktree rules: doc-000005. Do not start before every dependency is Done and merged into feature/project. When you start, record your own implementation plan in Backlog after researching the current code.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 One baseline Alembic revision replaces all existing revisions; a fresh database upgrades to it and passes schema validation and SQLite foreign-key integrity checks.
- [ ] #2 A database at any other revision is rejected with an actionable reset message and is not modified.
- [ ] #3 The schema contains every plan section 5 table plus the persisted state the plan needs for API keys, bindings, per-credential OAuth, pools and allocations (base rate, max rate, weight, concurrency, queue limits, loan switch), trace policy and retention, scoped audit events, the execution-authority lease and recovery; state the plan keeps in memory (queue contents, scheduler deficits) is documented as not persisted.
- [ ] #4 A Backlog schema document lists every table and column with its ownership category (project, system, shared credential, shared pool); no system or shared-pool row is attached to an arbitrary project.
- [ ] #5 Human accounts store identity, authentication provider, status and the TASK-000001 profile fields (username, first name, last name); no role, account-type or superuser column exists.
- [ ] #6 Project API keys store a lookup prefix and a verifier digest, never a recoverable secret; a null expires_at means no expiration.
- [ ] #7 Allocations default to strict caps with loans disabled; credentials link to upstream pools per operation; a pool balance is stored once per pool, never per credential or project.
- [ ] #8 Repository methods for project-owned data require a project id; none silently reads across projects.
<!-- AC:END -->

## Definition of Done
<!-- DOD:BEGIN -->
- [ ] #1 Tests of the changed layer pass, plus ruff/mypy (backend) or lint/typecheck/depcruise/knip/build (frontend) with no new findings.
- [ ] #2 Tests use fake providers and temporary databases; security assertions are rewritten to the new model, never weakened or dropped without a replacement.
- [ ] #3 No secret material (passwords, API keys, provider keys, OAuth grants) appears in responses, logs, traces or test output.
- [ ] #4 If the card changes the request path, the routing-latency check passes: FreeSearch adds under 80 ms at p95 per provider, end to end, over REST and MCP. Database read counts are a diagnostic, not a limit.
<!-- DOD:END -->
