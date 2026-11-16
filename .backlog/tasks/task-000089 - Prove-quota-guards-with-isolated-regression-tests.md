---
id: TASK-000089
title: Prove quota guards with isolated regression tests
status: To Do
assignee: []
created_date: '2026-11-16T10:50:00Z'
updated_date: '2026-11-16T11:26:00Z'
labels:
  - backend
dependencies: []
priority: low
type: task
ordinal: 75000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
**Review verdict:** test gap. Each guard is correct at head 20405293. No production bug was found. N4-N7 are cheap, real gaps that let a regression through without a test failure. Most of N15 is a nitpick. This card changes tests only.

## Background
TASK-000070 / PR #78 restores per-credential quota state and prevents stale estimates from replacing trusted balances. A transaction guard protects hydration writes. The limit store separates a rejected record from an accepted record with no value change. Tavily keeps its adapter clamp until the store accepts proof of new funds. Existing tests cover the main paths, but several independent guards can regress without a failure.

## Test gaps and code evidence (head 20405293f7440f4f0b30363646c074d54add4816)
- **N4 (most useful).** `prepare_adapter_quota` (`src/polyweb/services/provider_runtime.py:211-230`) reads `quota_marker`, hydrates, then calls `record_quota(..., guard=QuotaWriteGuard(marker=marker, still_current=still_current))`. `QuotaWriteGuard.holds` (`src/polyweb/persistence/storage.py:392-396`) first checks `still_current`, then returns `latest == self.marker`. `still_current` becomes False only after `retire_credential_adapters` (`src/polyweb/services/execution.py:982-985`). That call is in-process only (`src/polyweb/routers/control.py:437`). `polyweb-api` and `polyweb-mcp` are separate processes (`pyproject.toml:28,30`). So a Set balance on the API process never retires the MCP process's adapter, and the marker is the only thing that stops a stale MCP hydration (API records, MCP hydrates, no retirement). The race test `tests/integration/services/test_provider_runtime.py:1140-1207` writes the row and also retires the adapter (`:1192-1193`), so a mutation of `holds` to `return True` still passes. No test in `tests/` uses `QuotaWriteGuard` or `quota_marker`. A fake-session probe gives `holds(newer row, still_current=True) -> False` and `holds(same row) -> True`, which is correct today.
- **N5.** On a second identical PUT, `_write_stamp` (`src/polyweb/persistence/limit_repository.py:3381`) restamps and `remaining` is equal, so the outcome is UNCHANGED (`:691`). `record_manual_anchor` returns `None` only for REJECTED (`:789-791`), so the response is 200. No test sends the same PUT twice. There is only "Clearing twice" for DELETE (`tests/integration/routers/test_manual_quota.py:251`).
- **N6.** `src/polyweb/services/limits_sync.py:387-396` calls `stored_hook(snapshot)` only when the stored source and observation instant match. If the hook ran unconditionally, `usage_snapshot_stored` (`src/polyweb/adapters/tavily.py:1121-1139`) would clear the terminal state and load the unclamped `_pending_quota`. The recovery test (`tests/integration/services/test_tavily_limits.py:692-696`) checks only the store and admission after the stale poll. **Admission still denies**, because the store keeps `vendor_402`. So the impact of this regression is limited to the adapter's in-memory quota view (clamp and quota cache), not admission.
- **N7.** `control.py:393-396` uses `scope = explicit or inferred`. In `tests/integration/routers/test_manual_quota.py:1071-1153`, both keys share the only balance owner, so the explicit `pool_id` request at `:1134-1138` also succeeds through inference if explicit resolution disappears. With a second owner, `inferred` is None and the response `pool_id` would be None, so the test would catch it.
- **N15 (mostly nitpicks).**
  - 429: `tests/integration/services/test_quota_units.py:2496-2497` accepts `latest is None or latest.remaining != Decimal("0")`. Line 2498 is the private `_soft_zero` check. Pinning the exact stored state is a small improvement.
  - Zero balance: `tests/integration/persistence/test_limit_repository.py:1040-1066` does not assert whether the `"0"` report was accepted (only the no-balance case asserts `partial_accepted is False`). Lines 1069 and later belong to the next test.
  - Operator stamp (`test_limit_repository.py:1204-1253`): **this case is not flaky.** `_write_stamp` returns `max(row_observed, now)`, and FIXED_AT (2026-03-10) is always earlier than the wall clock. No change is needed.
  - `_adapter_blocked` (`test_manual_quota.py:486-499`) reads private adapter fields. Each provider has a different public signal, so a rewrite is optional.
  - `test_cached_adapter_is_prepared_once` (`test_provider_runtime.py:947-972`) asserts `calls == 1`. This correctly protects once-per-build behavior. Keep it.

## Scenario (test gap only)
1. Replace the marker comparison with unconditional acceptance while the adapter remains current. Existing retirement-based coverage stays green.
2. Return a conflict for an accepted-but-unchanged record. Existing single-PUT coverage stays green.
3. Notify Tavily after a rejected report. The adapter clamp lifts without proof, while admission still denies.
4. Ignore explicit pool scope when only one owner exists. The shared-pool test still selects the same owner.
These are missing regression signals, not claims that current production guards fail.

## Evidence
- Owner approval review N4-N7 and N15 (/tmp/t70_pr78_approval.md).
- Sol (/tmp/t70_sol_report.md) confirms N4-N7 and qualifies N15.
- Opus code-path review (/tmp/t70_cardrev_000089.md): test gap, no production bug, priority Low.

## Suggested approach
- Add focused tests only. Do not change production code.
- AC #1: reuse the `racing` pattern of `test_provider_runtime.py:1186-1195` without the `retire_credential_adapters` call, so `still_current` stays True and only the marker rejects the write.
- AC #3: extend `test_tavily_limits.py:692-696` to assert that the adapter quota still reports 0 after the stale poll. Add three unit cases in `tests/unit/services/test_limits_sync.py`: source mismatch (0 hook calls), instant mismatch (0), accepted report (1).
- Show the value of each new test with a deliberate fault that you then revert. Do not invent a production bug to get a failing baseline.
- Do not add clock injection or monkeypatch module `datetime` for the operator-stamp case.
- Keep AC #15, REST compatibility, the Keenable free tier and the 409/503 semantics unchanged.

## Testing notes
- Files: `tests/integration/services/test_provider_runtime.py`, `tests/integration/routers/test_manual_quota.py`, `tests/integration/persistence/test_limit_repository.py`, `tests/integration/services/test_quota_units.py`, `tests/integration/services/test_tavily_limits.py`, `tests/unit/services/test_limits_sync.py`.
- Per AGENTS.md: unit tests run locally. Integration and BDD suites run on Woodpecker CI. You can run one offline integration file locally. Do not add BDD for these branch-isolation details.

## References
- PR: https://github.com/polyweb-dev/polyweb-mcp/pull/78
- Source task: TASK-000070. Related: TASK-000088 (refused routing write), TASK-000086 (split operation pools), TASK-000087 (preparation retry backoff). This test-only work does not duplicate them.
- Reviews: /tmp/t70_pr78_approval.md (N4, N5, N6, N7, N15), /tmp/t70_sol_report.md, /tmp/t70_cardrev_000089.md.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 Regression coverage rejects a stale hydration after a newer scoped row arrives while the adapter remains current (no retirement), and fails when marker protection is deliberately bypassed.
- [ ] #2 Two identical accepted Set balance PUTs both return 200 and retain the intended record, while a truly rejected record still returns 409.
- [ ] #3 A rejected Tavily report with a source or observation-instant mismatch never lifts the adapter clamp, while accepted new-funds proof can lift it. Coverage fails if store confirmation becomes unconditional.
- [ ] #4 With at least two eligible balance owners, an explicit pool-scoped PUT changes only the named owner. The test fails if explicit pool resolution disappears.
- [ ] #5 The 429 test asserts the exact stored quota state, and the zero-balance case asserts whether the zero report was accepted. The once-per-build count assertion stays.
<!-- AC:END -->
