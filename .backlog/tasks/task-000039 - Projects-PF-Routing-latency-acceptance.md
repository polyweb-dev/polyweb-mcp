---
id: TASK-000039
title: Projects PF - Routing-latency acceptance
status: To Do
assignee: []
created_date: '2026-10-26T09:47:00Z'
labels:
  - projects-first
  - step-2-api
  - latency
milestone: m-0
dependencies: []
documentation:
  - doc-000003
  - doc-000005
  - doc-000004
priority: high
type: feature
ordinal: 23000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
FreeSearch is only useful as a router if it adds little latency. Earlier feature work let routing latency spike and it had to be recovered afterwards, so latency is an acceptance criterion from the start of the rebuild and this check lands first. Design: local plan section 13 (doc-000004).

Step rules and the shared Definition of Done: doc-000003. Card map and worktree rules: doc-000005. Do not start before every dependency is Done and merged into feature/project. When you start, record your own implementation plan in Backlog after researching the current code.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 An end-to-end test per provider, with instant fake adapters, measures the time FreeSearch adds to route a warm search and a warm fetch over REST and MCP; p95 stays under 80 ms.
- [ ] #2 The same run reports database reads per request as a diagnostic; read counts are not a pass/fail limit, and the fixed read-count assertion in test_auto_route_plan_read_budget becomes a report.
- [ ] #3 Existing live-provider tests (backend @live BDD, UI @live Playwright, routing latency report) run only when explicitly selected, never in the default suites, and report per-provider added latency separately from provider time.
- [ ] #4 One documented command runs the live performance checks for a later CI job.
<!-- AC:END -->

## Definition of Done
<!-- DOD:BEGIN -->
- [ ] #1 Tests of the changed layer pass, plus ruff/mypy (backend) or lint/typecheck/depcruise/knip/build (frontend) with no new findings.
- [ ] #2 Tests use fake providers and temporary databases; security assertions are rewritten to the new model, never weakened or dropped without a replacement.
- [ ] #3 No secret material (passwords, API keys, provider keys, OAuth grants) appears in responses, logs, traces or test output.
- [ ] #4 If the card changes the request path, the routing-latency check passes: FreeSearch adds under 80 ms at p95 per provider, end to end, over REST and MCP. Database read counts are a diagnostic, not a limit.
<!-- DOD:END -->
