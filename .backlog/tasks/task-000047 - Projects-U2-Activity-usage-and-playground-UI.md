---
id: TASK-000047
title: Projects U2 - Activity, usage and playground UI
status: To Do
assignee: []
created_date: '2026-10-26T09:47:00Z'
labels:
  - projects-first
  - step-3-ui
milestone: m-1
dependencies:
  - TASK-000042
  - TASK-000044
documentation:
  - doc-000003
  - doc-000005
  - doc-000002
priority: high
type: feature
ordinal: 31000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Activity, usage, dashboard and the playground must show only the selected project's data. Design: local plan sections 8 and 9 (doc-000002).

Step rules and the shared Definition of Done: doc-000003. Card map and worktree rules: doc-000005. Do not start before every dependency is Done and merged into feature/project. When you start, record your own implementation plan in Backlog after researching the current code.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 Activity, usage, dashboard and playground under a project route show only that project's data.
- [ ] #2 Switching projects cancels in-flight requests and ignores late results.
- [ ] #3 The playground runs through the human session and never stores an API key in browser state.
<!-- AC:END -->

## Definition of Done
<!-- DOD:BEGIN -->
- [ ] #1 Tests of the changed layer pass, plus ruff/mypy (backend) or lint/typecheck/depcruise/knip/build (frontend) with no new findings.
- [ ] #2 Tests use fake providers and temporary databases; security assertions are rewritten to the new model, never weakened or dropped without a replacement.
- [ ] #3 No secret material (passwords, API keys, provider keys, OAuth grants) appears in responses, logs, traces or test output.
- [ ] #4 If the card changes the request path, the routing-latency check passes: FreeSearch adds under 80 ms at p95 per provider, end to end, over REST and MCP. Database read counts are a diagnostic, not a limit.
<!-- DOD:END -->
