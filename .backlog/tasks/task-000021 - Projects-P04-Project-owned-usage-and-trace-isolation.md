---
id: TASK-000021
title: Projects P04 - Project-owned usage and trace writers
status: In Progress
assignee:
  - '@devin'
created_date: '2026-10-24T15:54:00Z'
updated_date: '2026-10-25T18:46:00Z'
labels:
  - projects-first
  - phase-p04
  - parallel-a
milestone: m-0
dependencies:
  - TASK-000020
references:
  - src/freesearch/persistence/storage.py
  - src/freesearch/persistence/otel_exporter.py
  - src/freesearch/services/monitoring.py
  - src/freesearch/infrastructure/observability_asgi.py
documentation:
  - doc-000001
  - doc-000002
  - doc-000003
  - doc-000004
  - doc-000005
  - .agents/communication/projects-feature-plan.md
  - .backlog/docs/doc-000005 - Projects-execution-index-start-here.md
priority: high
type: feature
ordinal: 500
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Current activity is account-scoped and usage lacks project ownership. Teammates need collaborative project activity without exposing another project's records.

Phase: P04. Execution lane: parallel-a. Milestone: Projects 1 - Foundation.

Dependency gate: P03 (TASK-000020)
Do not implement or mark In Progress until every dependency is Done, merged into the integration branch, and its acceptance evidence is available. Priority and phase numbers never override this gate. Parallel work is permitted only where the dependency graph and shared-file ownership allow it.

Accepted scope from plan section 10 / P04:

Tasklet A adds non-null project ownership to usage and execution traces, with corresponding writer changes.
Keep actor attribution and distinguish system audit events. No historical data backfill is necessary.

Restructure note (2026-10-25): Tasklet B (scoped dashboard, activity detail, pagination and export reads) moved to TASK-000034. P05 depends only on this card. Phase P04 is complete only when this card and TASK-000034 are Done. P08 and P11A run in parallel: allocate Alembic revisions serially and serialize edits to storage.py and database_migrations.py.

Cross-phase constraints:
User-approved constraints: one human account type; one common scoped RBAC service; system/project roles are assignments, not account types. Preserve internal UUIDs and local/WorkOS storage constraints without implementing WorkOS/cloud features. Use one internal installation account. Project tokens can expire or have no expiration. Support private and explicitly shared credential instances. Strict pool/project caps are the default; fair loans require their later phase. Use a fresh alpha database; do not migrate/import old history, humans, settings or secrets. Never use the live database or real provider credentials for tests. Desktop UI only; local environment controls ports.

Verification expectations:
Test project ownership on usage and trace writes with two projects and concurrent and fanout fake calls, including root/child span attribution and system audit events. Run relevant observability integration and adversarial suites.
Use the managed verification specification for required quality commands and test placement. Record objective evidence before completion.

Before code work, read AGENTS.md and applicable skills, use CodeGraph for indexed code, inspect current implementation and record the task implementation plan through Backlog. The referenced design is context; this future ticket intentionally has no speculative implementation-plan field.

Documentation: local .agents/communication/projects-feature-plan.md, sections 4-10 for design and scope, section 11 for ordering. The managed specification documents are durable copies for checkouts where the gitignored local plan is absent. Use the execution-index document for exact phase-to-ticket IDs and ready-work commands.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 New project usage and execution traces have non-null project ownership plus the required actor and request attribution.
- [x] #2 Root and child spans retain trusted project attribution during concurrent and fanout operations.
- [x] #3 System audit events remain explicitly system-scoped; no legacy-data backfill is introduced.
<!-- AC:END -->

## Definition of Done
<!-- DOD:BEGIN -->
- [x] #1 All phase acceptance criteria have objective test or review evidence recorded in Backlog before Done.
<!-- DOD:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
User decisions (2026-10-25): keep /search and /fetch routes clean; project_id travels in the request body (SearchRequest/FetchRequest, also the MCP tool arguments); NOT NULL project ownership with no unscoped/system category on usage/trace rows; alpha - migration recreates usage_events and trace_spans empty (history discarded, no backfill); Playground lives inside a project route and sends that project's id (UI wiring is P06/P06B; P04 is backend only).
1. Contracts: models/observability.py adds ActorType(human|project_token), frozen ExecutionAttribution(project_id, actor_type, actor_id), TraceAttribute PROJECT_ID/ACTOR_TYPE/ACTOR_ID (reserved). SearchRequest/FetchRequest gain required project_id: UUID.
2. Migration 0008_project_owned_telemetry: drop+recreate usage_events and trace_spans with project_id CHAR(36) NOT NULL FK projects.id, actor_type CHECK, actor_id NOT NULL; usage_events adds trace_id; all spans (root and child) carry ownership. Keep existing indexes; add project-leading indexes. database_migrations.py metadata + head literals updated.
3. Writers: SQLiteRepository.record_usage(event, *, attribution, trace_id) requires attribution; tracked_call/record_response_telemetry/_record_failure_usage and REST/MCP fanout aggregated rows pass it explicitly. SQLiteSpanExporter persists ownership per span; unattributed spans are dropped (never forged), batch continues; write_trace_spans rejects unattributed records.
4. Trusted trace attribution: per-request attribution cell created by use_observability; bind_execution_attribution() is called only by the execution boundary after context resolution, stamps the root span, and a SpanProcessor stamps every later span on start (fanout tasks inherit the cell). Caller-supplied reserved attributes are stripped. Rebinding to another project fails closed.
5. Execution boundary: services/execution_scope.py resolves verified principal + body project_id via ScopedAuthorizationService (live search.execute/fetch.execute decision, active non-archived project) before routing, admission, or provider I/O. REST: 401 no credential, 404 unknown/foreign project, 403 missing permission, 409 archived. MCP: same decisions as generic tool errors; anonymous MCP and anonymous REST execution end (project tokens arrive in P07 and must match body project_id).
6. Verification: two projects, concurrent and fanout fake-adapter calls; root/child span attribution; usage attribution; reserved-attribute spoof rejection; rejection before side effects; provider_limit_events stay system-scoped (no project column); migration/schema tests; update existing tests to authenticate and send project_id. Run ruff, mypy, focused unit/integration, observability + adversarial suites, and affected BDD.
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
P04 implementation evidence (2026-10-25, uncommitted on projects/p04-usage-trace-writers).
Scope decisions (user): body project_id on SearchRequest/FetchRequest (REST /search,/fetch and MCP search/fetch keep clean routes); NOT NULL ownership, no unscoped/system category on usage/trace rows; migration recreates usage_events/trace_spans empty; anonymous REST/MCP execution removed now (pulled forward from P15A); Playground will live inside a project route (UI wiring = P06/P06B, not done here).
Src: models/observability.py (ActorType, ExecutionAttribution, ownership TraceAttributes), models/contracts.py (required project_id), migration 0008_project_owned_telemetry (project_id NOT NULL FK projects.id, actor_type CHECK, actor_id NOT NULL on both tables; usage_events.trace_id; project-leading indexes), database_migrations.py, storage.py record_usage(attribution required), services/monitoring.py tracked_call(attribution required), infrastructure/observability.py (per-request attribution cell, bind_execution_attribution fail-closed rebinding, _AttributionSpanProcessor stamps every span on start, caller ownership keys stripped, private _OtelSpan._stamp_ownership), otel_exporter.py (ownership per span, unattributed spans dropped, write_trace_spans rejects unattributed), services/execution_scope.py (live context + archived + authorize before routing/admission/provider I/O), routers/api.py, mcp/server.py, mcp/auth.py, infrastructure/auth_asgi.py (/search,/fetch now require Bearer; 1 MiB body cap kept).
AC1 evidence: tests/integration/persistence/test_owned_telemetry.py (6) - NOT NULL/FK/CHECK, attribution+trace_id persistence, attribution required; test_project_trace_attribution usage-row assertions.
AC2 evidence: tests/integration/routers/test_project_trace_attribution.py::test_concurrent_two_project_requests_keep_full_ownership (real app+middleware+OTel+SQLite exporter, 2 users x 2 projects x 4 concurrent calls incl. fanout with failing provider; every root/child span owned by requester, one project per trace, usage trace_id maps to same-project trace, aggregated+failure rows owned correctly); tests/integration/mcp/test_trace_attribution.py (MCP equivalent); tests/unit/infrastructure/test_observability.py (+4: spoofed ownership keys stripped across span/set_attributes/annotate_root/add_event, rebinding raises); adversarial test_adapter_ownership_spoofing_keeps_bound_project.
AC3 evidence: adversarial test_provider_limit_events_stay_system_scoped (no project column, system audit event writes without project); no backfill - migration recreates tables empty.
Boundary evidence: tests/integration/adversarial/test_execution_scope.py (15): REST 401/404 unknown/404 non-member/404 suspended/403/409 archived/422 on /search and /fetch with zero usage/trace/rate-attempt/admission rows (positive control armed), MCP anonymous/unknown/non-member/no-permission/archived with zero side effects, revocation follow-up 404.
Verification: ruff check src tests pass; mypy 97 files pass; ruff format --check on changed files pass. pytest tests/unit: 1890 passed, 1 skipped, 1 failed (baseline UserRole.DEVELOPER debt test_provision_account_uses_safe_manager_and_returns_projection). pytest tests/integration: 870 passed, 3 skipped, 17 failed, 6 errors - all in the pre-change baseline (27 failed/6 errors before; role_matrix/limits_api/manual_quota/observability_api/monitoring/auth_api/encrypted_secrets set_role debt, test_auto_route_plan_read_budget); zero new failures. behave: 10 failed/26 errors, identical scenario list to baseline.
Known behaviour: rejected requests (401/404/403/409/422) leave no trace rows (unattributed roots dropped, never forged). MCP fanout has no per-provider child spans and no aggregated usage row (pre-existing REST/MCP asymmetry, P05). Reads (activity/dashboard/usage) still unscoped - P04B.
Follow-ups for main checkout (not edited here per worktree rule): P05 TASK-000022 AC text says explicit project execution routes - now body project_id selector; P15A TASK-000004 anonymous execution removal already done here; P06/P06B must send project_id from the /p/:projectId route - Playground/UI /search,/fetch calls return 422 until then. Migration 0008 lands before P08 per merge rule.
<!-- SECTION:NOTES:END -->

## Comments

<!-- COMMENTS:BEGIN -->
author: @devin
created: 2026-10-25T15:06:00Z

---

Migration merge rule (2026-10-25): this card adds an Alembic revision while another lane also changes schema. Land the migration and its database_migrations.py schema-validation change as a small first pull request. P04 lands first when P04 and P08 are both ready; otherwise the first merged migration keeps the next number. The other branch rebases, renames its revision to the following number, sets down_revision to the new head, and updates the head literal in tests/integration/persistence/test_database_migrations.py, tests/integration/persistence/test_projects.py and tests/fixtures/alpha_fixtures.py. Keep one migration head. See doc-000005, Worktrees and merging.

---
<!-- COMMENTS:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
P04 makes every new usage row and every trace span (root and child, including fanout) project-owned with non-null project_id plus actor type/id; usage rows also link their trace. Per user decision the project selector is a required body project_id on /search, /fetch and the MCP tools, verified server-side through the common RBAC service (live membership, archived check, search/fetch.execute) before any routing, admission or provider I/O; anonymous execution is removed. Ownership comes only from the trusted boundary: a per-request attribution cell plus a span processor stamps spans, caller-supplied ownership attributes are stripped, rebinding fails closed, and usage writers require explicit attribution. Migration 0008 recreates usage_events/trace_spans empty (alpha, no backfill); provider_limit_events stay system-scoped. Verified with concurrent two-project REST and MCP end-to-end tests, spoofing and rejection-before-side-effect adversarial suites; ruff/mypy clean, zero new unit/integration/BDD failures versus the recorded baseline. Risks/follow-ups: UI Playground gets 422 until P06/P06B sends project_id; P05 and P15A cards need updating from the main checkout; reads remain unscoped until P04B.
<!-- SECTION:FINAL_SUMMARY:END -->
