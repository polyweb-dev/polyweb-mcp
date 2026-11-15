---
id: TASK-000071
title: Restore Exa monthly budget and manual credits at runtime startup
status: To Do
assignee: []
created_date: '2026-11-14T11:37:00Z'
labels: []
dependencies: []
priority: high
type: bug
ordinal: 60000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Since aae1b63 (TASK-000042) the runtime no longer calls ExaAdapter.set_monthly_budget or hydrate_quota (src/polyweb/adapters/exa.py), so Exa budget and manual-credit settings are saved but have no effect on routing or quota.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 Configured Exa monthly budget and manual credits are applied to the adapter when the runtime generation is composed
- [ ] #2 Exa quota state is hydrated from the repository on startup
- [ ] #3 Integration test proves a configured budget changes the effective Exa quota
<!-- AC:END -->
