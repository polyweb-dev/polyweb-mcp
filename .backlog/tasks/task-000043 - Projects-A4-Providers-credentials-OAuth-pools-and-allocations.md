---
id: TASK-000043
title: 'Projects A4 - Providers: credentials, OAuth, pools and allocations'
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
ordinal: 27000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Projects need several credentials per provider, private or explicitly shared, plus per-credential OAuth and system-managed upstream pools and allocations. Design: local plan sections 4.5, 4.6 and 5 (doc-000001, doc-000002).

Step rules and the shared Definition of Done: doc-000003. Card map and worktree rules: doc-000005. Do not start before every dependency is Done and merged into feature/project. When you start, record your own implementation plan in Backlog after researching the current code.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 The merged P08 guarantees hold on the new schema: several labelled credentials per provider, private credentials never cross projects, one shared credential serves granted projects without a second secret copy, delete-wins tombstones and generation checks.
- [ ] #2 Two Parallel OAuth connections coexist; disconnecting or expiring one leaves the other usable; an old refresh cannot restore a disconnected grant; removing permission during a device flow stops completion and leaves no active flow.
- [ ] #3 Only system administrators manage shared credentials, grants, pools, pool links and allocation ceilings; no project edit raises a system ceiling.
- [ ] #4 Available providers (credential present and granted) and enabled providers (project choice) resolve separately as in plan section 4.6.
- [ ] #5 Provider responses show credential labels and pool ownership but never secrets or another project's usage.
<!-- AC:END -->

## Definition of Done
<!-- DOD:BEGIN -->
- [ ] #1 Tests of the changed layer pass, plus ruff/mypy (backend) or lint/typecheck/depcruise/knip/build (frontend) with no new findings.
- [ ] #2 Tests use fake providers and temporary databases; security assertions are rewritten to the new model, never weakened or dropped without a replacement.
- [ ] #3 No secret material (passwords, API keys, provider keys, OAuth grants) appears in responses, logs, traces or test output.
- [ ] #4 If the card changes the request path, the routing-latency check passes: FreeSearch adds under 80 ms at p95 per provider, end to end, over REST and MCP. Database read counts are a diagnostic, not a limit.
<!-- DOD:END -->
