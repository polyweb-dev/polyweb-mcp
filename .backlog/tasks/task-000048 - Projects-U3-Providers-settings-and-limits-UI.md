---
id: TASK-000048
title: Projects U3 - Providers, settings and limits UI
status: To Do
assignee: []
created_date: '2026-10-26T09:47:00Z'
labels:
  - projects-first
  - step-3-ui
milestone: m-1
dependencies:
  - TASK-000045
  - TASK-000043
  - TASK-000044
documentation:
  - doc-000003
  - doc-000005
  - doc-000002
priority: high
type: feature
ordinal: 32000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Providers, settings, settings copy, trace policy and limits need desktop screens that follow effective permissions and never expose secrets. Design: local plan sections 4.7, 7 and 8 (doc-000001, doc-000002).

Step rules and the shared Definition of Done: doc-000003. Card map and worktree rules: doc-000005. Do not start before every dependency is Done and merged into feature/project. When you start, record your own implementation plan in Backlog after researching the current code.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 Credential, grant, binding, private-key and OAuth screens never show secret material.
- [ ] #2 Settings show provenance, inherit/reset and read-only state from effective permissions; the copy dialog previews before applying.
- [ ] #3 Trace policy controls show the effective policy within system limits.
- [ ] #4 Allocation views explain strict caps and loans; system administrators edit allocations and loan settings; projects see a read-only explanation.
<!-- AC:END -->

## Definition of Done
<!-- DOD:BEGIN -->
- [ ] #1 Tests of the changed layer pass, plus ruff/mypy (backend) or lint/typecheck/depcruise/knip/build (frontend) with no new findings.
- [ ] #2 Tests use fake providers and temporary databases; security assertions are rewritten to the new model, never weakened or dropped without a replacement.
- [ ] #3 No secret material (passwords, API keys, provider keys, OAuth grants) appears in responses, logs, traces or test output.
- [ ] #4 If the card changes the request path, the routing-latency check passes: FreeSearch adds under 80 ms at p95 per provider, end to end, over REST and MCP. Database read counts are a diagnostic, not a limit.
<!-- DOD:END -->
