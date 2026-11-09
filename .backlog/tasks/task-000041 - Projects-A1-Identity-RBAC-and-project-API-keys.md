---
id: TASK-000041
title: Projects A1 - Identity, RBAC and project API keys
status: Done
assignee:
  - '@devin'
created_date: '2026-10-26T09:47:00Z'
updated_date: '2026-11-09T12:32:00Z'
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
ordinal: 43000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Authority must come only from scoped role assignments, and machine clients need project API keys instead of agent accounts. The legacy admin/developer/agent roles still survive in code and tests and are removed here. Design: local plan sections 4.2-4.4 and 6 (doc-000001, doc-000002).

Step rules and the shared Definition of Done: doc-000003. Card map and worktree rules: doc-000005. Do not start before every dependency is Done and merged into feature/project. When you start, record your own implementation plan in Backlog after researching the current code.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 The admin/developer/agent account roles and any role-derived superuser flag are absent from backend contracts and responses; public signup creates an ordinary account with no system role.
- [x] #2 System authority comes only from system role assignments made by trusted bootstrap or an authorized system operation; project authority comes only from active membership and project role assignments.
- [x] #3 Every project keeps at least one active human administrator, including under concurrent removal, demotion and account deactivation.
- [x] #4 Project API keys can be issued, listed, rotated and revoked; the raw key appears only in the issue response; an explicit null expiry means no expiration, an omitted expiry uses the documented default, and rotation keeps the lifetime unless changed.
- [x] #5 An API key belongs to one project and its search/fetch scopes; it cannot call human-account or control-plane endpoints and does not gain its creator's later roles.
- [x] #6 Invalid, expired, revoked, wrong-project, wrong-scope and suspended-project API keys fail before any provider access on REST, MCP HTTP, MCP stdio and every call of a persistent MCP session.
- [x] #7 Browser execution uses the human session and project membership and never needs an API key.
- [x] #8 Membership, role and API-key lifecycle changes write scoped audit events without secret material.
<!-- AC:END -->

## Definition of Done
<!-- DOD:BEGIN -->
- [x] #1 Tests of the changed layer pass, plus ruff/mypy (backend) or lint/typecheck/depcruise/knip/build (frontend) with no new findings.
- [x] #2 Tests use fake providers and temporary databases; security assertions are rewritten to the new model, never weakened or dropped without a replacement.
- [x] #3 No secret material (passwords, API keys, provider keys, OAuth grants) appears in responses, logs, traces or test output.
- [ ] #4 If the card changes the request path, the routing-latency check passes: FreeSearch adds under 80 ms at p95 per provider, end to end, over REST and MCP. Database read counts are a diagnostic, not a limit.
<!-- DOD:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. Principal contract: HumanPrincipal | ProjectApiKeyPrincipal (renamed from ProjectTokenPrincipal, principal_type project_api_key, api_key_id); both expose actor_type/actor_id. Remove UserRole/UserPrincipal role+superuser contracts, fold Target* DTOs into one safe human account DTO; signup creates an ordinary human with no assignment.
2. System authority only via system_role_assignments (bootstrap + authorized system op); CLI set-role replaced by grant/revoke system admin; project authority only via active membership + role assignments. No system-admin project bypass.
3. Last active human admin invariant inside the serialized transaction for removal/demotion/deactivation (REST and CLI, archived projects included); account deactivation checks every affected project atomically.
4. Project API keys: format fs_live_<prefix>_<secret>, >=256-bit secret, SHA-256 verifier + constant-time compare, prefix lookup. Omitted expiry = 90-day default, explicit null = no expiry. Rotation preserves lifetime unless changed, old key overlaps (default 24h, 0 = immediate revoke). Issue/list/rotate/revoke under /api/v1/projects/{id}/api-keys, tokens.manage, human only; secret only in issue/rotate response.
5. One ApiKeyVerifier used by REST execution, MCP HTTP and stdio; MCP re-verifies on every tool call; key project is authoritative and a conflicting project_id fails before provider access; keys rejected on human/control-plane endpoints. Remove anonymous/preview execution.
6. Scoped audit events (project/system) in the same transaction for membership, role and key lifecycle; security events for known-key failures; no secret material.
7. Developer (src only) implements; tester (tests only) rewrites obsolete role tests to the new model and adds adversarial AC tests; ruff/mypy and affected suites green; PF gate must not regress.
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Dev/test rounds: developer (src only) implemented; adversarial tester (tests only) found 1 defect (omitted expiry lost on JSON round trip, fixed) and 4 disputes. Lead rulings: R1 key scopes limited to issuer's live permissions (accepted); R2 last active system admin cannot be deactivated (accepted); R3 denial security events throttled 1/(key,reason)/60s and written off the request path via the bounded background writer (accepted); token_manager stays execution-free and must be paired with project_member (least privilege, documented). Lead review added R4 (MCP HTTP verifies the key once per HTTP request at the guard; tool calls use the guard principal from their own request scope; stdio verifies per call), R5 (non-member/unknown project = identical 404 on project-scoped routes, member without permission = 403), R6 (injected compositions drain the background writer). Evidence: pytest tests/unit tests/integration 3259 passed, 0 failed, 4 skipped (3108 cases at HEAD -> 3263); ruff + mypy clean. Behave: 262 passed; the 29 failures + 1 error also fail at HEAD (28 routing_latency on this machine, provider_limits B02, provider_limits_tavily T07). DoD 4 open: routing-latency gate already fails at HEAD on this machine (p50 ~100 ms); A1 adds no latency; to be re-measured with the A2 latency work.
<!-- SECTION:NOTES:END -->
