---
id: TASK-000002
title: Replace Playground Raw JSON inspection with Activity details popup
status: Done
assignee:
  - '@devin'
created_date: 2026-10-15 22:19
updated_date: '2026-11-15T22:27:00Z'
labels: []
dependencies:
  - TASK-000047
documentation:
  - doc-000008
type: enhancement
ordinal: 11000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
In Playground, users should open the associated Activity details in a popup instead of inspecting raw JSON.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 The Inspect Raw JSON action is replaced by a View Details button.
- [x] #2 The button opens the matching Activity details in a popup.
- [x] #3 The popup uses the same project-scoped trace inspector as Activity. Missing or metadata-only traces explain unavailable details without a global lookup.
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. Transport: add requestJsonWithHeaders to shared/api/client.ts; apiService.search returns the body plus the X-Trace-Id header (32 lowercase hex, else null).
2. Execution domain: SearchResponse gains optional traceId; mapSearchResponse and useSearchRunner carry it into the persisted playground result.
3. Activity feature: add useProjectTraceDetail + ProjectTraceDetails, which load one trace through the project route and render the existing TraceDetailDialog. No trace id shows 'No trace was recorded for this request' with no list or global read; 404 and metadata-only keep the existing inspector copy.
4. Playground: replace Inspect raw JSON (viewer + Copy JSON) with a View details button that opens a TraceDetails slot. app/ProjectWorkspace composes the activity component into the playground (no feature-to-feature import). Remove the raw JSON/copy state from the controller.
5. Tests: client header unit test, mapper/runner tests, SearchResults and PlaygroundPage integration tests (traced, untraced, missing), update the Playground parity BDD scenario and stub, update docs/dashboard/playground.md.
6. Verify: targeted vitest, then pnpm depcruise, knip, lint, typecheck, test, build; ui-bdd on CI.

7. Scope added by the owner: run the UI BDD suite with multiple Playwright workers (and sharding if useful) so CI saturates the spot workers; scenarios that need live calls or depend on earlier scenarios stay serial. Informed by two investigator agents (Devin GPT-6 Sol, Claude Opus 5.5).

8. Keep this feature's BDD coverage green: View details moved to its own Auto-routed scenario that does not depend on the provider-pin step broken on main. Pre-existing suite failures go to TASK-000083.
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Implemented per plan. Playground reads X-Trace-Id from POST /search (requestJsonWithHeaders), stores traceId on the result, and View details opens ProjectTraceDetails (Activity TraceDetailDialog) composed in app/ProjectWorkspace via a render slot (no feature-to-feature import). No trace id, 404, metadata-only and missing traces.read each explain the absence without a list/global read. Added beyond AC: traces.read permission message instead of a 403 error.
Evidence: vitest ProjectPlaygroundPage.test.tsx 'ProjectPlaygroundPage View details' (5 cases), SearchResults.test.tsx 'SearchResults View details', polywebApi/client/useSearchRunner tests; touched + sampled files 315/315 pass. Gate: typecheck, typecheck:e2e, lint (2 pre-existing warnings in untouched files), depcruise, knip clean.
UI review (Devin Claude Opus 5.5, screenshots in /tmp/task2-ui-review): PASS, no blocker/major. Minor/nits are all in the shared inspector or existing styles (dialog height changes between tabs, bar vs trace latency differ, plain ghost button like the old raw JSON toggle).

CI ui-bdd @stub on main (#126) and on this branch (#125) fail identically (106/260); root cause includes the unstubbed GET /routing/order. Tracked separately as TASK-000083.

Owner decisions (2026-11-15): seed Alpha pools for the parity scenario; parallel = fullyParallel + CI workers + @serial one-worker project + 10 s actionTimeout, no retries, no sharding; measure worker count on CI (6 vs 12); keep @smoke as the default gate (full @stub gate moves to TASK-000083). Implemented in c653983; CI at that head: ui-bdd @stub w6 #141, @stub w12 #142, @smoke #143, ui-quality #144. Investigator reports: Sol (root causes, doc-000009), Opus (parallel safety: 10 timing-sensitive scenarios tagged @serial; zero real-API traffic from @stub scenarios).

Worker measurement (261 stubbed scenarios, 16-vCPU spot worker): 1 worker 29.4 min (#126 main), 6 workers 5.6 min (#148), 12 workers 3.7 min (#142); all three fail the same 106 pre-existing scenarios (TASK-000083), no parallel-only failure. Default set to 12 in run-ui-bdd.sh (c690de0). Parity scenario fixed: seeded Brave pool + steps aligned with current result UI (fbe1e2d); both activity-trace-detail scenarios pass on #149. Final head-SHA runs queued: ui-quality #150, ui-bdd @smoke #151, feature #152, @stub at default workers #153.

Owner request (2026-11-15): restore copying as Copy JSON in the shared trace popup ("if a trace can be inspected, why can't it be copied?"). TraceCopyJsonButton (ghost sm, shared useClipboard with resetAfterMs 2000 and no optimistic flag, so Copied shows only after a successful write) sits at the end of the Results/Timeline switch row through a new TraceInspectionWorkspace actions slot. It copies JSON.stringify(trace, null, 2) of the decoded TraceDetail; metadata-only traces copy their null input/output. Only in the ready state, so Activity and the Playground both get it. Tests: TraceDetailDialog.test.tsx 'TraceDetailDialog Copy JSON'; BDD steps added to 'Playground View details opens the project trace inspector'. Docs: dashboard/activity.md and dashboard/playground.md.
<!-- SECTION:NOTES:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
Replaced the Playground's Inspect raw JSON toggle with View details. It reads the X-Trace-Id of the search and opens the Activity TraceDetailDialog through the project trace route only, composed by the app shell so Playground never imports the Activity feature. Untraced calls, foreign traces (404), metadata-only traces and callers without traces.read each get an explanation, never a list or global lookup.

Owner-added scope: the UI BDD suite now runs fully parallel on CI (PLAYWRIGHT_WORKERS default 12, local 1). Ten timing-sensitive scenarios run in a one-worker @serial project, and the action timeout is 10 s. The full stubbed run took 29.4 min on 1 worker (#126), 5.6 min on 6 (#148) and 3.6 min on 12 (#153), with no new failures. This feature's BDD scenarios pass: the new View details scenario, and the parity scenario after seeding its pool and updating outdated steps.

Verification at c690de0: ui-quality #150 (all vitest, lint, types, build), ui-bdd @smoke #151, this feature's scenarios #152, and the @stub diagnostic #153 (105 failures, all pre-existing). Visual review with screenshots by a separate agent: PASS.

Follow-ups: TASK-000083 repairs the 105 pre-existing stubbed BDD failures on main (doc-000009). The reviewer's minor pre-existing UI notes are listed in PR #77 and are untracked until the owner decides.
<!-- SECTION:FINAL_SUMMARY:END -->
