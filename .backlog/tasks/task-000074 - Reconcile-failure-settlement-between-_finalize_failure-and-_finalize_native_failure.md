---
id: TASK-000074
title: >-
  Reconcile failure settlement between _finalize_failure and
  _finalize_native_failure
status: In Progress
assignee:
  - '@devin'
created_date: '2026-11-14T11:37:00Z'
updated_date: '2026-11-15T14:41:00Z'
labels: []
dependencies: []
type: bug
ordinal: 63000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
src/polyweb/services/monitoring.py: _finalize_failure and _finalize_native_failure settle an exception whose .error payload is not a ProviderError differently. _finalize_failure reads .details on a str/dict payload, the AttributeError is swallowed by suppress(Exception) in _finalize_capacity_path, and the admission stays reserved; a duck-typed payload is forwarded to record_failure. _finalize_native_failure records an uncharged local failure. Production never reaches _finalize_failure (ExecutionService always passes reserve, so the charger path runs); only tests use the legacy path. PR #74 left the helpers unmerged because it was a behaviour-neutral cleanup PR, not because merging was rejected on merit.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 _finalize_failure keeps only its limits/admission None guard and delegates to _finalize_native_failure, so one rule records every failure
- [ ] #2 A .error payload that is not a ProviderError (str, dict, duck-typed object with .details) is recorded on both paths as the same uncharged local-call-failure ProviderError and the admission is released, not left reserved
- [ ] #3 A real ProviderError (with and without charge details) settles exactly as before on both paths
- [ ] #4 Unit regression test in tests/unit/services/test_monitoring.py fails before the fix for the intended reason and passes after
- [ ] #5 Integration tests that settled capacity through the test-only legacy path (attributed_tracked_call with limits and no reserve) are moved to the production charger path or removed; every removed test names its surviving test
- [ ] #6 ruff and mypy clean on changed files; api-unit, api-integration and api-bdd pass on Woodpecker at the head SHA
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. Unit regression test first: tests/unit/services/test_monitoring.py drives _finalize_capacity_path (charger=None) and _finalize_native_failure with str, dict and duck-typed .error payloads plus a real ProviderError control; confirm legacy cases fail before the fix.
2. Fix: _finalize_failure keeps the limits/admission None guard and delegates to _finalize_native_failure.
3. Test refactor: inventory integration tests that use attributed_tracked_call with limits and no reserve (test_keenable_limits, test_tavily_limits, test_quota_units, test_a2_execution_regressions, integration test_monitoring, test_genuine_adapter_proofs). Move each to the production charger path (ExecutionService / reserve hooks), or remove it when production-path coverage already exists, naming the survivor.
4. Verify: new unit file + touched test files locally (single integration files allowed locally for fail/pass), ruff + mypy; api-unit, api-integration, api-bdd on Woodpecker at the head SHA.
5. Agents: implementation by Devin Claude Opus 5.5 (medium); separate Devin Opus 5.5 (medium) review; GPT-6 Sol only for a hard bug. No UI changes.
6. PR body per .agents/skills/pull-request-message.
<!-- SECTION:PLAN:END -->
