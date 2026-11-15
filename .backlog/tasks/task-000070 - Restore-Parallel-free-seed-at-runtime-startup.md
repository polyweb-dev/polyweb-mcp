---
id: TASK-000070
title: Restore provider quota state at runtime startup
status: To Do
assignee: []
created_date: '2026-11-14T11:37:00Z'
updated_date: '2026-11-15T12:41:00Z'
labels: []
dependencies: []
priority: high
type: bug
ordinal: 59000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Since aae1b63 (TASK-000042) the runtime no longer applies saved quota settings or hydrates quota state when the runtime generation is composed. Settings are saved but have no effect, and locally counted usage resets on every restart. Affected providers:

- Parallel: ParallelAdapter.set_free_seed and hydrate_quota (src/polyweb/adapters/parallel.py) are never called, so the configured free-seed is never applied.
- Exa: ExaAdapter.set_monthly_budget and hydrate_quota (src/polyweb/adapters/exa.py) are never called, so monthly budget and manual-credit settings have no effect on routing or quota.
- Brave / Keenable: BraveAdapter.hydrate_quota and KeenableAdapter.hydrate_quota (src/polyweb/adapters/brave.py, keenable.py) are never called, so monthly usage resets to zero on restart and the providers can be over-used past their caps.

The compose docstring in src/polyweb/routers/api.py (~603) still says quota state hydrates at compose time and is stale.

Fix all four in one place in the runtime composition path so the wiring stays consistent. Merged from former TASK-000071 and TASK-000072.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 Configured Parallel free-seed is applied to the adapter when the runtime generation is composed
- [ ] #2 Configured Exa monthly budget and manual credits are applied to the adapter when the runtime generation is composed
- [ ] #3 Parallel, Exa, Brave and Keenable quota state is hydrated from the repository on startup
- [ ] #4 Integration test proves a configured Exa budget changes the effective Exa quota
- [ ] #5 Restart test proves counted Brave and Keenable usage survives a runtime rebuild
- [ ] #6 routers/api.py compose docstring matches the actual startup behaviour
<!-- AC:END -->
