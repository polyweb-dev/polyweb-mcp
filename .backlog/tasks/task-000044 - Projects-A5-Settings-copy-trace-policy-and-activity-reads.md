---
id: TASK-000044
title: Projects A5 - Settings, copy, trace policy and activity reads
status: To Do
assignee: []
created_date: '2026-10-26T09:47:00Z'
labels:
  - projects-first
  - step-2-api
milestone: m-0
dependencies:
  - TASK-000040
documentation:
  - doc-000003
  - doc-000005
  - doc-000001
  - doc-000002
priority: high
type: feature
ordinal: 28000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Settings, settings copy, trace policy, retention and activity reads must respect project scope and system constraints. Design: local plan sections 4.7, 4.8 and 9 (doc-000001, doc-000002).

Step rules and the shared Definition of Done: doc-000003. Card map and worktree rules: doc-000005. Do not start before every dependency is Done and merged into feature/project. When you start, record your own implementation plan in Backlog after researching the current code.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 Effective settings resolve defaults, then project overrides, then system constraints, with per-field provenance, revision conflicts and reset to inherit.
- [ ] #2 Settings copy offers preview and apply, is transactional and audited, keeps inheritance, rejects unavailable private credentials, and never copies API keys, membership, secrets, balances, usage, traces, limiter state or privileges.
- [ ] #3 Project trace policy (sampling, detail, redaction, retention) applies only to that project's new traces within system policy; mandatory audit events ignore sampling.
- [ ] #4 A project's retention job deletes only that project's data.
- [ ] #5 Activity, dashboard, usage, export and cursor reads are project-scoped; guessed trace ids and cursors cannot cross projects.
<!-- AC:END -->

## Definition of Done
<!-- DOD:BEGIN -->
- [ ] #1 Tests of the changed layer pass, plus ruff/mypy (backend) or lint/typecheck/depcruise/knip/build (frontend) with no new findings.
- [ ] #2 Tests use fake providers and temporary databases; security assertions are rewritten to the new model, never weakened or dropped without a replacement.
- [ ] #3 No secret material (passwords, API keys, provider keys, OAuth grants) appears in responses, logs, traces or test output.
- [ ] #4 If the card changes the request path, the routing-latency check passes: FreeSearch adds under 80 ms at p95 per provider, end to end, over REST and MCP. Database read counts are a diagnostic, not a limit.
<!-- DOD:END -->
