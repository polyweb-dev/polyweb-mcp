---
id: TASK-000083
title: Repair the stubbed UI BDD suite on main
status: To Do
assignee: []
created_date: '2026-11-15T17:14:00Z'
updated_date: '2026-11-15T17:24:00Z'
labels:
  - ui
  - testing
  - ci
dependencies: []
references:
  - .woodpecker/ui-bdd.yaml
  - scripts/ci/run-ui-bdd.sh
  - polyweb-ui/tests/steps/backendStub.ts
  - polyweb-ui/tests/steps/projectStub.ts
documentation:
  - doc-000009
priority: high
type: bug
ordinal: 67000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
CI gates only the 10 `@smoke` UI BDD scenarios (`scripts/ci/run-ui-bdd.sh` defaults `PLAYWRIGHT_GREP` to `@smoke`), so the wider stubbed suite has drifted unnoticed. Running all `@stub` scenarios on CI shows it is badly red on main. Woodpecker ui-bdd #126 (main, c7f0845, `PLAYWRIGHT_GREP=@stub`) and #125 (branch task-000002-playground-activity-details, same selection) fail the same 106 of 260 scenarios (154 passed, 29.4 min on one worker). Reports: Gitea generic package `polyweb-ui-bdd`, versions `pipeline-126-*` and `pipeline-125-r1-*`.

doc-000009 groups the 106 failures into 20 root causes with a per-scenario inventory. Most failures are stale steps after UI copy, markup and locator changes; for example, `Balance history` became `View balance history`, and an Add key dialog submit was renamed. A few may be real product defects: a failed dashboard or provider refresh clears the state already displayed, and the unsupported-tool tooltip has no accessible role.

The Playground provider-pin steps fail because the project routing-order stub (`polyweb-ui/tests/steps/vaultStub.ts`) builds the order from assigned pools plus keyless Keenable. A scenario that seeds no pool therefore sees only Keenable. The first guess that this endpoint was unstubbed and fell through to the real API was wrong.

TASK-000002 runs the BDD suite on multiple workers and keeps its own scenarios green; it does not fix these pre-existing failures.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 Every app API path requested during `@stub` scenarios is intercepted by a stub route, so no `@stub` scenario reaches the real API through the Vite proxy
- [ ] #2 All `@stub` scenarios pass on CI with `PLAYWRIGHT_GREP=@stub`, with each change to a failing scenario explained as a stale test or a real UI defect
- [ ] #3 Real UI defects found by the repair (for example duplicate Credit details buttons) are fixed or tracked as their own tasks
- [ ] #4 The CI ui-bdd gate runs the full stubbed suite, or the PR records why a subset stays the gate
<!-- AC:END -->
