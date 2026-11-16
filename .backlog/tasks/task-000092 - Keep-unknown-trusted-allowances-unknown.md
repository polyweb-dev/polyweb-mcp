---
id: TASK-000092
title: Keep unknown trusted allowances unknown
status: To Do
assignee: []
created_date: '2026-11-16T10:52:00Z'
updated_date: '2026-11-16T11:27:00Z'
labels:
  - backend
dependencies: []
priority: low
type: bug
ordinal: 78000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
**Review verdict:** latent. `_bounded_estimate` does keep an estimate's allowance under a trusted source when the trusted allowance is unknown. The only real producer is a mixed Parallel pool (OAuth `vendor_api` plus a seeded API key). This behavior predates PR #78. Priority Low.

## Background
TASK-000070 / PR #78 prevents a local quota estimate from increasing a trusted remaining balance. A lower estimate can stay useful, so the repository stores it under the trusted source and keeps the trusted allowance and reset information. An allowance is the vendor or operator cap, not the remaining balance. An unknown trusted allowance means that the vendor did not state a cap.

## Current vs intended behavior (head 20405293f7440f4f0b30363646c074d54add4816)
Path: `LimitsSyncService._sync_claimed` (`src/polyweb/services/limits_sync.py:228`) -> `apply_snapshot` -> `_store_snapshot` (`src/polyweb/persistence/limit_repository.py:631`) -> `_effective_observation` (`:3430`):
- `_preserve_known_values` (`:2676`) fills only a missing snapshot allowance from the row.
- `_trusted_ceiling` (`:3303-3329`) applies only to `local_ledger` estimates under a `_TRUSTED_SOURCES` row (`:345`) with a known remaining in the same period.
- `_bounded_estimate` (`:3332-3352`) copies `source` and `reset_at`, then:
```
trusted_allowance = _decimal(row.allowance_text)
if trusted_allowance is not None:
    update["allowance"] = trusted_allowance
```
When the trusted allowance is None, the estimate keeps its own allowance (the configured free seed). A cap then appears under a trusted source such as `vendor_api`, but the vendor did not state it. Confidence stays estimated, so `vendor_confirmed` stays false (`src/polyweb/models/quota_api.py:89-96`).

Intended: an unknown trusted allowance stays unknown in the bounded-estimate path.

## The only producer
Every trusted writer that shares a pool with a `local_ledger` writer sends an allowance, except one:
- Brave `vendor_headers` needs a vendor limit, so the allowance is known.
- Keenable `vendor_api` always sends a numeric allowance.
- `manual_anchor` requires an allowance (`ManualQuota.allowance`, `Decimal(ge=0)`).
- Exa `vendor_402` uses the same limit as its estimate. With no limit, the remaining is also None, so no ceiling applies.
- **Parallel OAuth `vendor_api` sends no allowance** (`src/polyweb/services/parallel_oauth_adapter.py:28-38`). An OAuth credential normally has its own `#cred:` pool and never emits `local_ledger`. So the case needs a shared `#pool:` with a Parallel OAuth credential and a Parallel API key with a free seed. No guard against that mix was found in `services/pools*.py`, but the review did not prove that the UI or API allows it.

## Scenario (probe A, `/tmp/probe_000092.py`, pure helpers)
1. Create one shared pool with Parallel OAuth credential O and API-key credential K (free seed S).
2. Sync O first into a fresh pool. The row becomes `vendor_api`, remaining X, allowance None.
3. Sync K in the same month with an estimated remaining <= X.
4. The row becomes `vendor_api`, remaining <= X, allowance S, confidence estimated.
5. The balance view shows cap S beside source `vendor_api`, but the vendor did not state it.
```
A bounded: vendor_api 9 1000 estimated
```
The value is the configured seed (configuration), not a random guess. This is the behavior from before PR #78: before the A2 fix, the estimate allowance always won. A2 fixed the known-allowance case and left the None case unchanged.

## Known limitation, out of scope (probe B)
If K syncs first, the row becomes `local_ledger` with allowance S. O's next report then inherits S through `_preserve_known_values` and is stored as `vendor_api`, **authoritative**, so `vendor_confirmed=true` with the same cap:
```
B vendor after estimate: vendor_api 10 1000 authoritative ceiling: None
```
This card does not fix that path. `_preserve_known_values` is the "failed sync keeps the last valid values" contract that Tavily and other providers depend on. If the owner cares, open a separate card.

## Evidence
- Owner approval review N11 (/tmp/t70_pr78_approval.md).
- Sol (/tmp/t70_sol_report.md) partly confirms it and notes that confidence stays estimated.
- Opus code-path review (/tmp/t70_cardrev_000092.md): latent, keep at Low.

## Suggested minimal approach
- In `_bounded_estimate`, set `update["allowance"] = _decimal(row.allowance_text)` without the condition.
- Keep the accepted lower remaining, trusted source, reset handling and estimated confidence. Keep known numeric allowances, including zero.
- Do not change `_preserve_known_values`, vendor-confirmed semantics, trust order, terminal-402 protection, the Tavily AC #15 rule (Tavily emits no `local_ledger`), the Keenable free tier, or manual-quota 409/503 semantics.

## Testing notes
- Unit home: `tests/unit/persistence/test_limit_repository.py` (it already imports private helpers). Build a trusted row with allowance None and an estimate with a numeric allowance. Before the fix the result carries the seed. After the fix the allowance is None.
- Add a zero-allowance control. `_decimal("0")` is safe only through the `is not None` check.
- Real-store control: `tests/integration/persistence/test_limit_repository.py::test_bounded_estimate_keeps_the_trusted_allowance` (`:1180`).
- Per AGENTS.md: unit tests run locally. Integration and BDD suites run on Woodpecker CI. No new BDD flow is necessary.

## References
- PR: https://github.com/polyweb-dev/polyweb-mcp/pull/78
- Source task: TASK-000070 AC #2 and #14. Related: TASK-000076 (UI shows balance and provenance), TASK-000077 (Parallel OAuth and cost tracking). No UI change belongs here.
- Reviews: /tmp/t70_pr78_approval.md (N11), /tmp/t70_sol_report.md, /tmp/t70_cardrev_000092.md.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 Through the bounded-estimate path (`_bounded_estimate`), an accepted lower estimate cannot introduce a numeric allowance when the trusted row has no known allowance, even if the estimate supplies a cap.
- [ ] #2 Known trusted allowances, including zero, remain intact. Accepted lower remaining values, estimated confidence, source/reset behavior, and terminal-402 protection retain their existing contracts.
- [ ] #3 A focused unit regression fails before the fix with the seed cap and passes after it with allowance None. Existing known-allowance coverage still passes.
<!-- AC:END -->
