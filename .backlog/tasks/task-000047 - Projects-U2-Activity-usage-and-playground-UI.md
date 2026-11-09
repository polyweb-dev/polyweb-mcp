---
id: TASK-000047
title: Projects U2 - Activity, usage and playground UI
status: Done
assignee:
  - '@devin'
created_date: '2026-10-26T09:47:00Z'
updated_date: '2026-11-09T12:32:00Z'
labels:
  - projects-first
  - step-3-ui
milestone: m-1
dependencies:
  - TASK-000042
  - TASK-000044
documentation:
  - doc-000003
  - doc-000005
  - doc-000002
  - doc-000008
priority: high
type: feature
ordinal: 46000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Activity, usage, dashboard and the playground must show only the selected project's data. Design: local plan sections 8 and 9 (doc-000002).

Step rules and the shared Definition of Done: doc-000003. Card map and worktree rules: doc-000005. Do not start before every dependency is Done and merged into feature/project. When you start, record your own implementation plan in Backlog after researching the current code.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 Activity, usage, dashboard and playground under a project route show only that project's data.
- [x] #2 Switching projects cancels in-flight requests and ignores late results.
- [x] #3 The playground runs through the human session and never stores an API key in browser state.
- [x] #4 Activity lists newest-first traces with operation and outcome filters and cursor pagination. The list retains its filters and loaded rows after trace detail closes.
- [x] #5 Activity detail retains the results, provider-attempt and span-timeline views, with failures and timing. It explains absent or redacted payloads without a global lookup.
<!-- AC:END -->

## Definition of Done
<!-- DOD:BEGIN -->
- [ ] #1 Tests of the changed layer pass, plus ruff/mypy (backend) or lint/typecheck/depcruise/knip/build (frontend) with no new findings.
- [x] #2 Tests use fake providers and temporary databases; security assertions are rewritten to the new model, never weakened or dropped without a replacement.
- [x] #3 No secret material (passwords, API keys, provider keys, OAuth grants) appears in responses, logs, traces or test output.
- [x] #4 If the card changes the request path, the routing-latency check passes: FreeSearch adds under 80 ms at p95 per provider, end to end, over REST and MCP. Database read counts are a diagnostic, not a limit.
<!-- DOD:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
Research findings (2026-10-31): POST /search and POST /fetch take a project_id and, with a human JWT, require one where the caller is an active member. The global GET /api/v1/traces is gone; Activity reads GET /api/v1/projects/{id}/traces (limit 1-100, default 50; operation search|fetch; outcome success|partial|error; opaque project-bound cursor; response {items, generated_at, next_cursor}) and GET /api/v1/projects/{id}/traces/{trace_id} (summary plus input, tagged output, spans; 404 for a foreign or unknown trace). Usage reads GET /api/v1/projects/{id}/usage and /dashboard (both {project_id, totals[], recent_usage[], generated_at}). The project provider view GET /api/v1/projects/{id}/providers lists effective_operations per provider type (needs providers.read, which project_member holds). Project permissions: search.execute, fetch.execute, traces.read, usage.read, providers.read. Trace payloads can be metadata-only or redacted by the project trace policy, so input and output can be null. The UI Redux store (playground drafts, results, execution status) is one store per account, persisted under freesearch:playground:v1:{accountId}; the search and fetch runners live in the account-level FreeSearch composition and do a client-side fallback walk over the global provider list.

1. Project sections. Add to PROJECT_SECTIONS, in sidebar order: Overview, Playground ("playground", any of search.execute or fetch.execute), Activity ("activity", traces.read), Usage ("usage", usage.read), Members, API keys. Extend the registry so a section can name several permissions with any-of semantics (permissions: readonly string[]); keep canAccessProjectSection the single gate for nav and routes.
2. Global routes. Remove Playground and Activity from the global Primary nav and routes. /playground and /activity redirect to the same section of the validated last project, else /projects. Rename the global "Usage" link (the installation provider-usage page at /usage, system.settings.read) to "Provider usage" so it never shares a name with the project Usage link.
3. Project-scoped playground store. Move AppStoreProvider from the account composition to the project playground scope, keyed by accountId:projectId. Persist under freesearch:playground:v2:{accountId}:{projectId} with schema version 2. Discard the legacy v1 account key on load; never migrate it to a project. Two tabs on different projects never share drafts or results.
4. Project execution. Search and fetch runners move out of the account-level FreeSearch composition into the project playground scope. Every request body carries project_id from the URL. The request uses the human session (shared transport, in-memory access token) and never reads, stores or sends a project API key. Each runner owns an AbortController: unmount and project switch abort in-flight requests, and a late result never dispatches. The client-side fallback walk is removed; routing sends mode auto/require/fanout with allow_fallback true and the server routes across the project bindings. Keep the Tavily 402 rule (show the backend message, no retry). Remove runSearch/runFetch and the usage-event/dashboard-refresh coupling from the global FreeSearch context.
5. Playground provider picker. Eligible providers come from the project provider view (effective_operations contains the mode), labelled with the static catalog names. Without providers.read, or with an empty view, the picker offers Auto (and All for search) only. A mode the caller lacks permission for is disabled.
6. Activity. Project-scoped list newest first, page size 50, filters Operation (All, Search, Fetch) and Outcome (All, Success, Partial, Error) held in the URL query (?operation=&outcome=), "Load more" appends the next cursor page, a filter change resets to page one, and closing the detail keeps filters, loaded rows and scroll. Detail reads the project trace route and keeps the existing results, provider-attempt and span-timeline views with failures and timing. When input and output are both null, the detail explains: "This trace stored metadata only. The project's trace policy did not capture the query or the results." When only the output is null on a success, it says the results were not stored. No global settings lookup. A 404 shows "This trace is not available in this project."
7. Usage and dashboard. Project Usage page reads /usage: totals per provider and operation (units with unit kind) and the recent ledger (provider, operation, units, status, latency, time), labelled as this project's usage only. The project overview shows a compact usage summary from /dashboard. Neither shows shared provider quota or health.
8. Isolation. Every project read uses the scoped-resource pattern keyed by accountId:projectId, so a switch aborts requests and ignores late results (AC 2).
9. Tests. Colocated Vitest tests for every new or changed module. Rewrite the BDD scenarios of playground and activity to project routes (activity-traces, activity-trace-detail, playground-persistence, playground-search-empty-state, provider-search-fetch, and the @live playground features, which select the project by name). Add stub scenarios for project switch cancellation, Activity filters plus Load more plus retention after detail close, the metadata-only explanation, and the absence of any fs_live_ key in browser storage after playground use. Gate: pnpm test (maxWorkers 6), lint, typecheck, typecheck:e2e, depcruise, knip, build, the Playwright stub suite compared with the post-U1 baseline.
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
2026-10-31 verification (branch chore/local-e2e-provider-seed, on top of U1 f692f48):
- Vitest: 171 files, 2191 tests, exit 0 (--maxWorkers 6). lint 0 errors (21 pre-existing warnings), typecheck, typecheck:e2e, depcruise 0 errors (3 pre-existing orphans), build pass; knip only pre-existing findings.
- New stub BDD: project-playground 5/5 (project_id on a Bearer session, no API key anywhere, v2 per-project key only, project-switch abort with no late result, two-tab draft isolation, legacy /playground and /activity redirects), project-activity-usage 3/3 (Outcome filter in URL, Load more by cursor, filters and 61 rows kept after detail close, metadata-only / results-not-stored / not-in-project copy, project-only usage tables). playground-persistence 3/3 incl. in-flight search surviving a section switch.
- Full @stub|@visual suite: 171 passed / 90 failed before the final test fixes, versus 161 / 91 after U1; 0 regressions after two test-side race fixes. activity-traces and activity-trace-detail rewritten to the current detail UI: 29/31 pass twice. 2 stay failing because the current UI dropped the behavior before U2: summary cell padding of at least 15px (now 11.25px) and a separate bounded scroll region for the snippet.
- Decisions: the playground store and execution scope live at project level (a section switch keeps an in-flight request; a project switch aborts it). The client-side fallback walk is removed; the server routes across project bindings with allow_fallback true. The global "Usage" link is renamed "Provider usage". Legacy v1 playground keys are deleted, not migrated.
- DoD 1 stays open for the same reason as U1: pre-existing e2e failures in other areas (provider-credits, routing, keenable, parallel-oauth, visual baselines) and the 2 activity scenarios above.
<!-- SECTION:NOTES:END -->
