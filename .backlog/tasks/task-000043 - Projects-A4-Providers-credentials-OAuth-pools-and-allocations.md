---
id: TASK-000043
title: 'Projects A4 - Providers: credentials, OAuth, pools and allocations'
status: Done
assignee:
  - '@devin'
created_date: '2026-10-26T09:47:00Z'
updated_date: '2026-10-27T11:41:00Z'
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
- [x] #1 The merged P08 guarantees hold on the new schema: several labelled credentials per provider, private credentials never cross projects, one shared credential serves granted projects without a second secret copy, delete-wins tombstones and generation checks.
- [x] #2 Two Parallel OAuth connections coexist; disconnecting or expiring one leaves the other usable; an old refresh cannot restore a disconnected grant; removing permission during a device flow stops completion and leaves no active flow.
- [x] #3 Only system administrators manage shared credentials, grants, pools, pool links and allocation ceilings; no project edit raises a system ceiling.
- [x] #4 Available providers (credential present and granted) and enabled providers (project choice) resolve separately as in plan section 4.6.
- [x] #5 Provider responses show credential labels and pool ownership but never secrets or another project's usage.
<!-- AC:END -->

## Definition of Done
<!-- DOD:BEGIN -->
- [x] #1 Tests of the changed layer pass, plus ruff/mypy (backend) or lint/typecheck/depcruise/knip/build (frontend) with no new findings.
- [x] #2 Tests use fake providers and temporary databases; security assertions are rewritten to the new model, never weakened or dropped without a replacement.
- [x] #3 No secret material (passwords, API keys, provider keys, OAuth grants) appears in responses, logs, traces or test output.
- [x] #4 If the card changes the request path, the routing-latency check passes: FreeSearch adds under 80 ms at p95 per provider, end to end, over REST and MCP. Database read counts are a diagnostic, not a limit.
<!-- DOD:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. Keep the existing system/project credential and grant endpoints stable (paths and fields; additive fields only). Preserve all P08 guarantees: labelled multi-instance, private isolation, one shared ciphertext, delete-wins tombstones, generation CAS, slot-bound AES-GCM and rekey.
2. API-05: replace resolve_for_project's snapshot-permission claim with a credential-state-only material resolver (ownership/grant/operation/generation/slot, API key or current OAuth token). Live actor authority is A2's dispatch check, and the resolver documents that it grants nothing.
3. Per-credential OAuth service on credential_oauth_grants: device flow, poll/complete, refresh, disconnect keyed by credential id with token_generation CAS. A stale refresh or completion cannot resurrect a disconnected grant. Loss of the initiator's permission during a device flow discards tokens and leaves no active flow. Reuse the Parallel client and parsers, no generic OAuth framework.
4. Project bindings (providers.configure): create (always starts disabled), enable operations within grant ∩ capability, priority/route label, delete. Available vs enabled provider view per doc-000001 §4.6: labels, owner scope and pool ownership, never secrets, pool-wide consumption or other projects' usage.
5. System-admin-only pools, credential-pool links (provider type match) and project allocations (strict by default). No project-level edit can raise a ceiling.
6. Scoped audit events in the same transaction for credential, grant, binding, pool, link, allocation and OAuth changes. Shared serialized-transaction runner replaces the duplicated _write loops (projects, api_keys, credentials, settings). Delete the no-op legacy-secret census (API-11).
7. Deferred to A2's runtime cutover (deletion gate): provider-name singleton secret/OAuth control endpoints, parallel_oauth singleton state, registry provider-name construction, limits_sync identity, and the Firecrawl/adapter cleanups.
8. Parallel work: developer (src) implements; tester (tests) concurrently does the audit's test-only cleanups (RT-08..13, ARCH-04) and P08 tests on the frozen credential endpoints, then tests the new endpoints after the developer reports.
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Ran in parallel: developer (src) and tester (tests) worked concurrently on disjoint files. Tester phase 1 did the audit's test-only cleanups (ARCH-04 matrices, RT-08 minus-one, B02 retired, RT-09 oracle, RT-10 setup 47s->8.5s, shared unlink helper, monitoring tests moved to integration, BDD temp-dir hygiene) and P08 HTTP tests on the frozen credential endpoints. Phase 2 tested the new endpoints. Lead rulings: F1 a pending OAuth device flow ends in the same transaction as any loss of its initiator's permission (membership, role, deactivation, system-admin revoke); F2 dropped the providers-view 'shared' pool flag (leaked existence of other credentials); F3 deleted outdated P00 pool models; G1 owner-scoped list_pending_for_owner plus one named account-wide list_pending_for_account (no optional scope widening); G2 project OAuth routes return 403 for granted system credentials; G3 the CLI never creates a master key (fail closed). Accepted as designed: OAuth credentials enable no execution (Parallel balance:read scope); feasibility sums base rates across operations; no vendor revoke on credential delete. Evidence: full suite 3298 passed, 1 failed (owner-pair guard, then fixed by G1), 1 xfailed; after the final round, affected suites 419 passed, plus 76 targeted; ruff + mypy clean. DoD4: request path unchanged (execution not rewired). Deferred to A2 (deletion gate): provider-name singleton secret/OAuth control endpoints, parallel_oauth singleton and monitoring poll, registry provider-name construction, wiring resolve_material into dispatch.
<!-- SECTION:NOTES:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
Credentials, per-credential Parallel OAuth, project bindings, an available-vs-enabled providers view, and system-only pools, links and allocations, all on the D1 schema with scoped audit and the A1 404/403 rule. Replaced the snapshot-permission credential resolver with a credential-state-only resolve_material for A2. Added one shared serialized-transaction runner used by projects, api_keys, credentials and settings. Removed the no-op legacy-secret census. Singleton provider-name credential paths remain until A2's runtime cutover.
<!-- SECTION:FINAL_SUMMARY:END -->
