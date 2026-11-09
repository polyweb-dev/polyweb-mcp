---
id: TASK-000039
title: Projects PF - Routing-latency acceptance
status: In Progress
assignee:
  - '@devin'
created_date: '2026-10-26T09:47:00Z'
updated_date: '2026-10-26T15:58:00Z'
labels:
  - projects-first
  - step-2-api
  - latency
milestone: m-0
dependencies: []
documentation:
  - doc-000003
  - doc-000005
  - doc-000004
priority: high
type: feature
ordinal: 23000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
FreeSearch is only useful as a router if it adds little latency. Earlier feature work let routing latency spike and it had to be recovered afterwards, so latency is an acceptance criterion from the start of the rebuild and this check lands first. Design: local plan section 13 (doc-000004).

Step rules and the shared Definition of Done: doc-000003. Card map and worktree rules: doc-000005. Do not start before every dependency is Done and merged into feature/project. When you start, record your own implementation plan in Backlog after researching the current code.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 Routing latency is measured at the backend API with Python Behave end-to-end scenarios; no Playwright or UI tests are added for it.
- [ ] #2 For every provider, with instant fake adapters, a warm search and a warm fetch over REST and MCP add under 80 ms of FreeSearch routing time at p95.
- [x] #3 Existing latency tests (tests/integration/latency/test_routing_latency.py and the backend @live Behave scenarios) are reused where they already measure this; only the gaps are rewritten.
- [x] #4 The same run reports database reads per request as a diagnostic; read counts are not a pass/fail limit, and the fixed read-count assertion in test_auto_route_plan_read_budget becomes a report.
- [x] #5 Backend @live Behave scenarios run only when explicitly selected, never in the default suites, and report per-provider added latency separately from provider time.
- [x] #6 One documented command runs the live performance checks for a later CI job.
<!-- AC:END -->

## Definition of Done
<!-- DOD:BEGIN -->
- [ ] #1 Tests of the changed layer pass, plus ruff/mypy (backend) or lint/typecheck/depcruise/knip/build (frontend) with no new findings.
- [x] #2 Tests use fake providers and temporary databases; security assertions are rewritten to the new model, never weakened or dropped without a replacement.
- [x] #3 No secret material (passwords, API keys, provider keys, OAuth grants) appears in responses, logs, traces or test output.
- [ ] #4 If the card changes the request path, the routing-latency check passes: FreeSearch adds under 80 ms at p95 per provider, end to end, over REST and MCP. Database read counts are a diagnostic, not a limit.
<!-- DOD:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. Shared latency fixtures (tests/fixtures/latency.py, latency_reports.py, latency_servers.py), extracted from tests/integration/latency/test_routing_latency.py and reused by both the pytest file and the Behave steps.
2. Real servers: create_app (REST) and build_http_app(create_server) (MCP Streamable HTTP) served by uvicorn on 127.0.0.1 with OS-assigned ports and temporary SQLite databases. Clients call over TCP.
3. Gate value is server-side added time: a ServerTimer ASGI middleware measures from request arrival until the last response byte, minus provider time. Provider time comes from wrapping the adapter instance's bound search/fetch methods. Client overhead and DB reads are reported only.
4. Offline feature tests/bdd/features/routing_latency.feature (@latency, default suite): 8 providers x search/fetch x REST/MCP, Brave fetch N/A, 5 warmup + 30 measured, p95 < 80 ms asserted.
5. Live feature tests/bdd/features/live/routing_latency_live.feature (@live @latency, opt-in): real adapters with harness-env keys, per-provider skip, pacing to vendor rate windows, provider vs added time reported, p95 < 80 ms asserted.
6. MCP/REST parity (production): create_server with an injected repository now starts and stops the limit service like create_app. Added shutdown_injected_observability as the teardown seam.
7. pyproject [tool.behave] default_tags = ["not @live"]; README documents uv run behave --tags="@live and @latency".
8. test_auto_route_plan_read_budget: warm SELECT limit replaced by a printed report.
9. Opt-in pyinstrument profiling (FREESEARCH_LATENCY_PROFILE=1) to find latency causes.
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Latency findings (2026-10-26, Windows, commit eacafc8-dirty). The check measures correctly: an adversarial tester confirmed it with separate-process clients, without instrumentation, with request gaps, and with Selector vs Proactor loops; a 350 ms provider delay moves only provider time. The offline gate FAILS today on all 30 rows: server-side added p95 is 107-180 ms (REST 107-133, MCP 128-180) and p50 is 88-134 ms. Client overhead p50: REST 4.5 ms, MCP 7.9 ms.
Causes from pyinstrument profiles (test_reports/routing_latency_offline_{rest,mcp}_profile.*), cProfile and ablation:
- Provider-limit admission and settlement in tracked_call: ProviderLimitsService.admit -> LimitRepository.reserve, then record_success -> LimitRepository.finalize. Removing admission drops REST p50/p95 from ~105/121 to ~64/80 ms, so it costs about 44 ms per request. This is the largest single stage.
- SQLAlchemy ORM overhead: about half of server CPU (Session.execute and Session.get in greenlets). About 211 aiosqlite calls per warm REST request (123 without admission). Commits are cheap (~3 per request at ~0.5 ms).
- Auth: BearerAuthMiddleware -> AuthService.verify_token -> SessionJWTStrategy._resolve -> UserManager.get, about 15 ms.
- Execution scope and authorization: resolve_execution_scope -> resolve_project_context, about 10-15 ms.
- Route planning (_routing_state/_route_state, ~5 ms), the middleware stack, and MCP SDK jsonschema validation.
- Trace flush/export (~23-25 ms) runs after the response, so it is not counted.
DB reads per request: 26-33 on both transports (diagnostic). The old test_auto_route_plan_read_budget limit (<=16) was already exceeded at HEAD (warm SELECTs = 30).
User decision: do not optimise now. Keep this record and measure again after the database changes (TASK-000040 schema and repositories) land.
Other notes:
- Live latency has run only for keyless Keenable (FREESEARCH_RUN_LIVE=1). Keyed providers are unverified because no keys were used.
- uvicorn timeout_graceful_shutdown=5 in the harness works around a Windows Proactor ConnectionResetError that hangs wait_closed(); production run_http_server may be affected too.
- Remaining injected-MCP gap: initialize_provider_configs is not called on the injected path (REST calls it).

Re-measured after rebasing onto feature/project 62e6bc0, which includes TASK-000040. All 1050 offline requests return ok. Server-side added p95: REST search 81-98 ms, REST fetch 86-102 ms, MCP search 107-124 ms, MCP fetch 106-126 ms. Before TASK-000040 the range was 107-180 ms. The gate still fails; REST is near the 80 ms line, and MCP is about 20 ms higher than REST.
Agreed with the user: merge this check first, so the API cards (TASK-000041, 000042, 000043, 000044, 000045) inherit it as Definition of Done #4. Criterion #2 is met when those cards make the gate green; the remaining slow stages (admission, auth, scope) are in their code.
Problems already on feature/project, not caused by this card:
- tests/fixtures/auth.py promote_account uses the obsolete role 'developer'. This causes errors in control, monitoring and observability.
- The MCP main() dispatch tests fail when the repo-root freesearch.db predates the alpha baseline.
<!-- SECTION:NOTES:END -->
