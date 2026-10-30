---
id: TASK-000046
title: Projects U1 - Project shell, members and API keys UI
status: To Do
assignee: []
created_date: '2026-10-26T09:47:00Z'
updated_date: '2026-10-30T19:47:00Z'
labels:
  - projects-first
  - step-3-ui
milestone: m-1
dependencies:
  - TASK-000041
documentation:
  - doc-000003
  - doc-000005
  - doc-000002
  - doc-000008
priority: high
type: feature
ordinal: 30000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
The desktop app needs project selection, membership and API-key management driven by effective permissions instead of account roles. The merged P06 shell is the starting point. Design: local plan section 8 (doc-000002).

Step rules and the shared Definition of Done: doc-000003. Card map and worktree rules: doc-000005. Do not start before every dependency is Done and merged into feature/project. When you start, record your own implementation plan in Backlog after researching the current code.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 Navigation, routes and controls follow effective permissions from the API, never role labels; signup and administration show no account-type choice.
- [ ] #2 Permitted system users create projects and name the first administrator; project administrators manage members and roles; last-administrator refusals are explained.
- [ ] #3 API-key screens issue keys with a No expiration option, show the raw key once, list creator, expiry and last use, and rotate and revoke keys.
- [ ] #4 Two tabs in different projects never share drafts, results or access rights.
- [ ] #5 Project screens retain the shared colors, typography and controls. The selected project and active screen remain visible at 1280x800 and 1440x900.
<!-- AC:END -->

## Definition of Done
<!-- DOD:BEGIN -->
- [ ] #1 Tests of the changed layer pass, plus ruff/mypy (backend) or lint/typecheck/depcruise/knip/build (frontend) with no new findings.
- [ ] #2 Tests use fake providers and temporary databases; security assertions are rewritten to the new model, never weakened or dropped without a replacement.
- [ ] #3 No secret material (passwords, API keys, provider keys, OAuth grants) appears in responses, logs, traces or test output.
- [ ] #4 If the card changes the request path, the routing-latency check passes: FreeSearch adds under 80 ms at p95 per provider, end to end, over REST and MCP. Database read counts are a diagnostic, not a limit.
<!-- DOD:END -->
