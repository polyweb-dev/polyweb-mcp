---
id: TASK-000002
title: Replace Playground Raw JSON inspection with Activity details popup
status: In Progress
assignee:
  - '@devin'
created_date: 2026-10-15 22:19
updated_date: '2026-11-15T18:21:00Z'
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
<!-- SECTION:NOTES:END -->
