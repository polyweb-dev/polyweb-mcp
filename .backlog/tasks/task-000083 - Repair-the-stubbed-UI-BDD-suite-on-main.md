---
id: TASK-000083
title: Repair the stubbed UI BDD suite on main
status: To Do
assignee: []
created_date: '2026-11-15T17:14:00Z'
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
priority: high
type: bug
ordinal: 67000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
CI gates only the 10 `@smoke` UI BDD scenarios (`scripts/ci/run-ui-bdd.sh` defaults `PLAYWRIGHT_GREP` to `@smoke`), so the wider stubbed suite has drifted unnoticed. Running all `@stub` scenarios on CI shows it is badly red on main: Woodpecker ui-bdd #126 (main, c7f0845, `PLAYWRIGHT_GREP=@stub`) and #125 (branch task-000002-playground-activity-details, same selection) fail identically: 106 of 260 failed, 154 passed, 29.4 min on one worker. Reports: Gitea generic package `polyweb-ui-bdd`, versions `pipeline-125-r1-*` and `pipeline-126-*`.

Known causes so far:
- `GET /api/v1/projects/{id}/routing/order` (read by the Playground through `getProjectOrder` and `projectOrderProviders`) has no route in `polyweb-ui/tests/steps`. Unstubbed calls fall through the Vite proxy to the disposable real API that `run-ui-bdd.sh` starts on a fresh database, which knows only keyless providers, so the Playground picker offers only Auto, All providers and Keenable and every `I pin the playground provider to "<name>"` step times out.
- Other failure groups in the #125 report: about 35 `toBeVisible`, 20 30-second timeouts, 16 strict-mode violations where `getByRole(button, { name: /Credit details for Tavily/i })` (also Brave) resolves to 2 elements, 15 `toContainText`, 7 `toHaveCount`.
- Root-cause analysis from two investigator agents (TASK-000002 thread) is to be appended to this task.

TASK-000002 enables multi-worker BDD runs and keeps its own scenarios green; it does not fix these pre-existing failures.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 Every app API path requested during `@stub` scenarios is intercepted by a stub route, so no `@stub` scenario reaches the real API through the Vite proxy
- [ ] #2 All `@stub` scenarios pass on CI with `PLAYWRIGHT_GREP=@stub`, with each change to a failing scenario explained as a stale test or a real UI defect
- [ ] #3 Real UI defects found by the repair (for example duplicate Credit details buttons) are fixed or tracked as their own tasks
- [ ] #4 The CI ui-bdd gate runs the full stubbed suite, or the PR records why a subset stays the gate
<!-- AC:END -->
