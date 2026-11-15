---
id: TASK-000078
title: Remove the test-only legacy settlement branch from tracked_call
status: To Do
assignee: []
created_date: '2026-11-15T14:44:00Z'
updated_date: '2026-11-15T17:08:00Z'
labels: []
dependencies:
  - TASK-000074
type: chore
ordinal: 67000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
src/polyweb/services/monitoring.py: tracked_call accepts reserve=None together with limits. Then _finalize_capacity_path settles through _finalize_failure / limits.record_success directly, with no _CapacityCharger. Production never takes this branch: ExecutionService._tracked_attempt (src/polyweb/services/execution.py) always passes reserve from _capacity_hooks. After TASK-000074 no integration test settles through it; the only test that exercises it is the 'legacy' parametrisation in tests/unit/services/test_monitoring.py (_settle_legacy calls _finalize_capacity_path(charger=None)). ProviderLimitsService.admit is also reachable only from this branch (monitoring.py _admit_call). The limits/admission guard in _finalize_failure is already redundant: its only caller returns early on the same conditions. Remove the branch (or require reserve whenever limits is given) so only the production settlement path exists. This is a behaviour change to tracked_call's contract and must be listed as such in the PR.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 tracked_call has no settlement branch that production cannot reach; passing limits without reserve is rejected or impossible by signature
- [ ] #2 _finalize_failure and the legacy branch of _finalize_capacity_path are removed; the 'legacy' cases in tests/unit/services/test_monitoring.py are removed or retargeted to the charger path in the same change
- [ ] #3 ProviderLimitsService.admit is removed or has a production caller; its tests are updated accordingly
- [ ] #4 api-unit, api-integration and api-bdd pass on Woodpecker at the head SHA
<!-- AC:END -->
