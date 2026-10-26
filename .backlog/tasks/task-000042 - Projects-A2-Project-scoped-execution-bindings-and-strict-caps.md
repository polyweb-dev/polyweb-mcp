---
id: TASK-000042
title: Projects A2 - Project-scoped execution, bindings and strict caps
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
ordinal: 26000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Every search and fetch must run inside one verified project, use that project's credential bindings and respect shared pool and project caps, identically over REST and MCP. Design: local plan sections 4.5, 4.6, 5 (ownership of operational data), 7.1 and 7.2 (doc-000001, doc-000002).

Step rules and the shared Definition of Done: doc-000003. Card map and worktree rules: doc-000005. Do not start before every dependency is Done and merged into feature/project. When you start, record your own implementation plan in Backlog after researching the current code.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 REST and MCP use one shared execution service and give identical project attribution and provider decisions for the same request.
- [ ] #2 Every usage row, trace span (root, child and fanout), admission and rate attempt carries the verified project and actor; attribution never comes from caller input or trace baggage.
- [ ] #3 A project can bind several credentials of one provider and pin or fan out across them; it can use only its private credentials and system credentials explicitly granted to it.
- [ ] #4 Health, quota observations, limit links and circuit breakers are keyed to the credential or the shared pool; one credential failing does not disable an unrelated credential.
- [ ] #5 Strict caps hold atomically across processes and transports: concurrent requests never exceed a pool or project window, keys in one pool share one allowance, and in the 4/6 example project A stops at 4/s while B is idle.
- [ ] #6 A capacity-store failure rejects new constrained execution; retries never duplicate a reservation or skip a new attempt charge.
- [ ] #7 No provider call happens before scope, permission, binding and capacity checks pass.
<!-- AC:END -->

## Definition of Done
<!-- DOD:BEGIN -->
- [ ] #1 Tests of the changed layer pass, plus ruff/mypy (backend) or lint/typecheck/depcruise/knip/build (frontend) with no new findings.
- [ ] #2 Tests use fake providers and temporary databases; security assertions are rewritten to the new model, never weakened or dropped without a replacement.
- [ ] #3 No secret material (passwords, API keys, provider keys, OAuth grants) appears in responses, logs, traces or test output.
- [ ] #4 If the card changes the request path, the routing-latency check passes: FreeSearch adds under 80 ms at p95 per provider, end to end, over REST and MCP. Database read counts are a diagnostic, not a limit.
<!-- DOD:END -->
