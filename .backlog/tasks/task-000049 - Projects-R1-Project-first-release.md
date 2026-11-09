---
id: TASK-000049
title: Projects R1 - Project-first release
status: Testing
assignee: []
created_date: '2026-10-26T09:47:00Z'
updated_date: '2026-11-09T12:39:00Z'
labels:
  - projects-first
  - release
milestone: m-1
dependencies:
  - TASK-000046
  - TASK-000047
  - TASK-000048
  - TASK-000039
documentation:
  - doc-000003
  - doc-000005
  - doc-000004
priority: high
type: feature
ordinal: 1000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
The rebuild ships to main only after a fresh-install rehearsal and a full passing test run. Design: local plan sections 12 and 13 (doc-000004).

Step rules and the shared Definition of Done: doc-000003. Card map and worktree rules: doc-000005. Do not start before every dependency is Done and merged into feature/project. When you start, record your own implementation plan in Backlog after researching the current code.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 A fresh install rehearsal with synthetic data passes: bootstrap system administrator, create project, add members, add and grant credentials, issue an API key, configure a client, see isolated activity.
- [ ] #2 All backend, frontend and desktop end-to-end suites pass, including the routing-latency check; the opt-in live performance run shows per-provider added latency within the same budget.
- [ ] #3 A PR from feature/project to main carries the release.
<!-- AC:END -->

## Definition of Done
<!-- DOD:BEGIN -->
- [ ] #1 Tests of the changed layer pass, plus ruff/mypy (backend) or lint/typecheck/depcruise/knip/build (frontend) with no new findings.
- [ ] #2 Tests use fake providers and temporary databases; security assertions are rewritten to the new model, never weakened or dropped without a replacement.
- [ ] #3 No secret material (passwords, API keys, provider keys, OAuth grants) appears in responses, logs, traces or test output.
- [ ] #4 If the card changes the request path, the routing-latency check passes: FreeSearch adds under 80 ms at p95 per provider, end to end, over REST and MCP. Database read counts are a diagnostic, not a limit.
<!-- DOD:END -->
