---
id: TASK-000041
title: Projects A1 - Identity, RBAC and project API keys
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
ordinal: 25000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Authority must come only from scoped role assignments, and machine clients need project API keys instead of agent accounts. The legacy admin/developer/agent roles still survive in code and tests and are removed here. Design: local plan sections 4.2-4.4 and 6 (doc-000001, doc-000002).

Step rules and the shared Definition of Done: doc-000003. Card map and worktree rules: doc-000005. Do not start before every dependency is Done and merged into feature/project. When you start, record your own implementation plan in Backlog after researching the current code.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 The admin/developer/agent account roles and any role-derived superuser flag are absent from backend contracts and responses; public signup creates an ordinary account with no system role.
- [ ] #2 System authority comes only from system role assignments made by trusted bootstrap or an authorized system operation; project authority comes only from active membership and project role assignments.
- [ ] #3 Every project keeps at least one active human administrator, including under concurrent removal, demotion and account deactivation.
- [ ] #4 Project API keys can be issued, listed, rotated and revoked; the raw key appears only in the issue response; an explicit null expiry means no expiration, an omitted expiry uses the documented default, and rotation keeps the lifetime unless changed.
- [ ] #5 An API key belongs to one project and its search/fetch scopes; it cannot call human-account or control-plane endpoints and does not gain its creator's later roles.
- [ ] #6 Invalid, expired, revoked, wrong-project, wrong-scope and suspended-project API keys fail before any provider access on REST, MCP HTTP, MCP stdio and every call of a persistent MCP session.
- [ ] #7 Browser execution uses the human session and project membership and never needs an API key.
- [ ] #8 Membership, role and API-key lifecycle changes write scoped audit events without secret material.
<!-- AC:END -->

## Definition of Done
<!-- DOD:BEGIN -->
- [ ] #1 Tests of the changed layer pass, plus ruff/mypy (backend) or lint/typecheck/depcruise/knip/build (frontend) with no new findings.
- [ ] #2 Tests use fake providers and temporary databases; security assertions are rewritten to the new model, never weakened or dropped without a replacement.
- [ ] #3 No secret material (passwords, API keys, provider keys, OAuth grants) appears in responses, logs, traces or test output.
- [ ] #4 If the card changes the request path, the routing-latency check passes: FreeSearch adds under 80 ms at p95 per provider, end to end, over REST and MCP. Database read counts are a diagnostic, not a limit.
<!-- DOD:END -->
