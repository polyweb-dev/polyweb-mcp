---
id: TASK-000074
title: >-
  Reconcile failure settlement between _finalize_failure and
  _finalize_native_failure
status: Done
assignee:
  - '@devin'
created_date: '2026-11-14T11:37:00Z'
updated_date: '2026-11-15T17:08:00Z'
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
- [x] #1 _finalize_failure keeps only its limits/admission None guard and delegates to _finalize_native_failure, so one rule records every failure
- [x] #2 A .error payload that is not a ProviderError (str, dict, duck-typed object with .details) is recorded on both paths as the same uncharged local-call-failure ProviderError and the admission is released, not left reserved
- [x] #3 A real ProviderError (with and without charge details) settles exactly as before on both paths
- [x] #4 Unit regression test in tests/unit/services/test_monitoring.py fails before the fix for the intended reason and passes after
- [x] #5 Integration tests that settled capacity through the test-only legacy path (attributed_tracked_call with limits and no reserve) are moved to the production charger path or removed; every removed test names its surviving test
- [x] #6 ruff and mypy clean on changed files; api-unit, api-integration and api-bdd pass on Woodpecker at the head SHA
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

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Filed TASK-000078 to remove the test-only legacy settlement branch after this task. Implementation delegated to Devin Claude Opus 5.5 (medium); CI budget 15 triggers total (implementer max 8).

Implementer round 1: e3f0d27 (unit test), d24ed40 (fix), ed8c94d (moved 9 integration tests to the production charger path via tests/fixtures/execution.py::production_capacity_hooks; none removed). Unit test before fix: 3 failed (str/dict/duck legacy cases), after: 12 passed. CI at ed8c94d: api-unit #109, api-integration #110, api-bdd #111 green. CI triggers used: 3/15. Review round 1 started.

Review round 1 (separate Devin Opus 5.5 medium): approve with nits, no blockers. Fixed in 0d4877b: fixture now uses a fresh attempt id per send like production (was: first send reused the context id), and the docstring names the production seams it mirrors (_strict_spec no-pool branch, _AttemptSeam._admit, _AttemptSeam.release). Kept: exact kwargs asserts in the unit test (they pin AC#3). Fixture fidelity confirmed for no-pool legs; using the real _AttemptSeam would need a full leg and seeded DB (1-2 days) for no observed gain. Local: 87 passed across the unit file and the moved integration files. CI at 0d4877b: api-unit #112 success, api-integration #113 success, api-bdd #114 pending. Intentional remaining differences: error=None branch only reachable on the native path; legacy guards limits/admission None; pool settlement only on the charger path (TASK-000078 removes the legacy branch).

Final CI at head 6955e02: api-unit #115, api-integration #116, api-bdd #117 green. CI triggers used: 9/15. PR: https://github.com/polyweb-dev/polyweb-mcp/pull/76

PR #76 review (thiocyanate-agent, verdict concerns, no blockers) addressed: A1 skill step 3 now names the suites and requires passing workflow; A2 TASK-000078 premise corrected (unit test legacy cases and ProviderLimitsService.admit in scope); A3 _finalize_failure docstring now says it delegates to the native rule, redundant guard recorded in TASK-000078; A4 dead attempt_id parameter removed from _charged_search; A5 uncharged unit cases assert semantic no-charge (exact kwargs kept only for the charged case); A7 unit module docstring states the error=None branch is unreachable from the legacy path; Q3 comment on the 429 test explains why it stays on tracked_call. A6 intentional difference added: the legacy path settles only an Exception (non-Exception BaseException skips settlement there), while the charger path settles any BaseException. Not changed by decision: skill stays in this PR; deleting _finalize_failure now (TASK-000078 scope); legacy/native unit cases kept (legacy cases are the regression signal); fixture docstring kept. Re-checked fail-before at e3f0d27's monitoring.py: same 3 legacy cases fail; after: 30 passed (unit file + a2 file).
<!-- SECTION:NOTES:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
_finalize_failure (legacy reserve=None path) now keeps only its limits/admission guard and delegates to _finalize_native_failure (d24ed40), so both paths settle every Exception by the same rule. Before, a str/dict .error payload raised AttributeError inside suppress(Exception) and left the admission reserved, and a duck-typed payload was forwarded as a ProviderError and could be charged. Production never reached that path (ExecutionService always passes reserve), so the impact was test-only. Evidence: tests/unit/services/test_monitoring.py (12 cases on both paths) fails 3 legacy cases before the fix and passes after. No integration test settles through the legacy path any more: attributed_tracked_call adds production capacity hooks (tests/fixtures/execution.py::production_capacity_hooks) and the 402 sibling test runs through ExecutionService.search; 9 tests moved, none removed, no assertion weakened. Remaining intentional differences: error=None only reaches the native path; the legacy path settles only Exception, not other BaseException; pool settlement only on the charger path. PR #76 review findings addressed. Follow-up: TASK-000078 removes the legacy branch, its unit cases and ProviderLimitsService.admit.
<!-- SECTION:FINAL_SUMMARY:END -->
