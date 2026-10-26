---
id: TASK-000045
title: >-
  Projects A3 - Fair capacity: execution authority, bounded queues, loans and
  recovery
status: To Do
assignee: []
created_date: '2026-10-26T09:47:00Z'
labels:
  - projects-first
  - step-2-api
milestone: m-2
dependencies:
  - TASK-000042
documentation:
  - doc-000003
  - doc-000005
  - doc-000002
priority: high
type: feature
ordinal: 29000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Shared pools need one dispatch authority and a fair scheduler so projects can borrow idle capacity without exceeding the pool or starving each other. It changes the same execution path as A2, so it starts after A2 merges. Design: local plan sections 7.3-7.6 (doc-000002).

Step rules and the shared Definition of Done: doc-000003. Card map and worktree rules: doc-000005. Do not start before every dependency is Done and merged into feature/project. When you start, record your own implementation plan in Backlog after researching the current code.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 One execution authority dispatches all REST and MCP work; MCP forwards with the original verified credential, deadline and trace context; an authority outage fails predictably with no direct provider bypass; a second authority for a borrowed pool fails before execution.
- [ ] #2 Queues are bounded per project and in total by count, bytes, wait time and concurrency; canceled or expired queued calls never reach a provider or consume rate attempts; queue wait is reported separately from provider latency.
- [ ] #3 With loans disabled, behavior equals strict caps; with loans enabled, project A alone can reach the pool limit, A and B approach 4:6 service under continuous equal demand within a documented bound, the pool never exceeds its rate envelope, and a returning project is served without preemption or starvation.
- [ ] #4 Infeasible base allocations are rejected; a project with zero guaranteed share follows an explicit best-effort policy.
- [ ] #5 Rate exhaustion, spend exhaustion, queue saturation and invalid credentials return distinct errors; provider Retry-After is respected.
- [ ] #6 Authority restart does not restore an unsafe full rate bucket or settle native funds twice; isolation and pool limits hold under mixed REST/MCP contention.
<!-- AC:END -->

## Definition of Done
<!-- DOD:BEGIN -->
- [ ] #1 Tests of the changed layer pass, plus ruff/mypy (backend) or lint/typecheck/depcruise/knip/build (frontend) with no new findings.
- [ ] #2 Tests use fake providers and temporary databases; security assertions are rewritten to the new model, never weakened or dropped without a replacement.
- [ ] #3 No secret material (passwords, API keys, provider keys, OAuth grants) appears in responses, logs, traces or test output.
- [ ] #4 If the card changes the request path, the routing-latency check passes: FreeSearch adds under 80 ms at p95 per provider, end to end, over REST and MCP. Database read counts are a diagnostic, not a limit.
<!-- DOD:END -->
