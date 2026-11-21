---
id: TASK-000088
title: Set balance must not report success when the routing write is refused
status: To Do
assignee: []
created_date: '2026-11-16T10:50:00Z'
updated_date: '2026-11-16T11:29:00Z'
labels:
  - backend
dependencies: []
priority: high
type: bug
ordinal: 74000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
**Review verdict:** real bug. Set balance can return 200 while the routing write was refused, so an Exa or Keenable key stays blocked. The race window is small and needs a concurrent key rotation, so a real hit is rare. User decision: confirmed real bug, priority High.

## Background
TASK-000070 / PR #78 restores quota state when Polyweb builds an adapter for a credential. A scoped Set balance (`PUT /api/v1/providers/{provider}/manual-quota` with `credential_id` or `pool_id`) does these steps in order:
1. It resolves the scope (key or shared pool) with the key's current credential generation.
2. It projects the manual record into the native limit pool (`limits.apply_manual_anchor`).
3. It writes a scoped routing snapshot (`repository.record_quota`) so a rebuilt adapter reads the new balance and not an older vendor 402 zero.
4. It retires the cached adapters of the scope, saves the runtime setting, and returns 200.
DELETE does the same steps with a clear (anchor `None`).

## Current vs intended behavior (head 20405293f7440f4f0b30363646c074d54add4816)
- `src/polyweb/routers/control.py:346` calls `_record_scope(...)`. `src/polyweb/services/manual_quota.py:276-304` resolves the scope. A shared pool scope takes its generation from `members[0]`.
- `control.py:348` calls `_notify_manual_anchor` -> `project_manual_record` -> `limits.apply_manual_anchor` (`src/polyweb/services/manual_quota.py:337-339`). **The native write has no generation check.** `_scoped_anchor_pool` copies the stored pool's generation (`src/polyweb/services/provider_limits.py:366-369`), and the snapshot has no `credential_id`, so `_current_generation` (`src/polyweb/persistence/limit_repository.py:3365-3378`) accepts it.
- Only the routing write checks the generation. `manual_quota.py:343` calls `await repository.record_quota(..., credential_generation=scope.observation.credential_generation, newest=True)` and **discards the result**. `src/polyweb/persistence/storage.py:1377-1386` returns `False` when the credential is missing, inactive, or has another generation.
- `manual_quota.py:359-360` then calls `retire(set(scope.credential_ids))`. The route saves the setting (`manual_quota.py:187-190`) and returns 200.
- A vault rotation (`POST /api/v1/account/vault/keys/{key_id}/rotate`, `src/polyweb/routers/vault_keys.py:87`) calls `advance_generation` (`src/polyweb/persistence/credentials.py:742-773`). It does not touch quota snapshots. The adapter cache key includes the generation, and `latest_quota` has no generation filter (`storage.py:1453-1458`). So the rebuilt generation N+1 adapter hydrates from the old 402 zero.
- DELETE (`control.py:375`) has the same discarded result: the native pool is cleared, but the routing snapshot keeps the old manual value.

Intended: when the routing write is refused, the API returns 409 before it retires adapters or saves the setting. The operator never sees a success that did not take effect.

## Scenario (reproduced)
The Opus review ran `/tmp/probe_88.py` (real temporary database, offline adapters, real rotate endpoint):
1. Block the key the way a vendor 402 does.
2. Resolve the manual-quota scope (generation 1).
3. Rotate the key through `POST /api/v1/account/vault/keys/{id}/rotate` (generation 2).
4. Send PUT with the generation-1 scope.

Probe output:
```
exa:      PUT 200, routing write [False], retired, native 10, routing 0, setting saved, rebuilt adapter blocked: True
keenable: same -> blocked: True
brave/tavily/parallel/firecrawl: write [False], 200, but rebuilt adapter not blocked
control (scope resolved after rotate), exa/keenable: write [True], routing 10, not blocked
```
User outcome: the operator sees 200 and GET shows the record, but the Exa or Keenable key stays blocked. Nothing tells the operator to retry. Brave, Tavily, Parallel and Firecrawl also get a refused write and a 200, but their rebuilt adapters were not blocked in the probe.

## Rarity and other triggers
- The window is the gap between the scope read and the routing write (a few SQLite transactions). A real hit needs the key owner to rotate the key while an admin records a balance.
- A refused write also occurs when the key is deleted during the request. That case does no harm.
- In a shared pool, the scope generation comes from `members[0]`. A rotation of the first member also refuses the write for the whole pool record.

## Evidence
- Owner approval review N2 (/tmp/t70_pr78_approval.md): "`record_quota`'s bool is discarded ... Check the result and raise 409."
- Sol (/tmp/t70_sol_report.md) confirms N2 as a real rotation race.
- Opus code-path review (/tmp/t70_cardrev_000088.md): real bug, low-probability race, reproduced with the probe above.

## Suggested minimal approach
- When `record_quota` returns `False` on a scoped path, raise `ManualAnchorRejectedError` (`src/polyweb/models/provider_limits.py:876`). `control.py:447-455` already maps it to 409. Raise it before `retire(...)` and before the setting write, for PUT and DELETE.
- The native anchor is written before the routing write. Two options are acceptable: roll back the native write after a refusal, or check the credential generation before (or inside) the native write. A leftover native anchor after a 409 does little harm because the retry overwrites it.
- Unscoped paths return at `manual_quota.py:340-341` and must not change.

Do not change:
- The unscoped multi-owner path, single-owner inference, and REST payload shapes.
- Provider-wide Exa credits and budgets, keyless Keenable (excluded at `manual_quota.py:281`), and the Tavily AC #15 proof rule.
- The existing 409/503 semantics and the rule that DELETE does not clear a vendor 402 without a manual record.
- Out of scope: the settings-write failure after a successful projection (N3). TASK-000095 owns it. Do not require a full transaction across the native pool, the routing snapshot and the setting.

## Testing notes
- Closest home: `tests/integration/routers/test_manual_quota.py` (real temporary database, offline adapters). `tests/integration/services/test_provider_runtime.py` has the adapter-rebuild helpers.
- Write a deterministic test: resolve the scope, rotate the key through the endpoint, then send PUT with the old scope. Parametrize it over Exa and Keenable so it shows the user-visible block, not only the `False` result. Add the DELETE variant.
- Before the fix, expect 200 and a blocked rebuilt adapter. After the fix, expect 409, no saved setting, no retirement, or a usable key.
- `test_set_balance_unblocks_the_only_key_of_a_provider` (`test_manual_quota.py:596`) already covers the normal success path. Keep it green as a regression guard.
- Per AGENTS.md: unit tests run locally. Integration and BDD suites run on Woodpecker CI. You can run one offline integration file locally to see the test fail and then pass. No new BDD flow is necessary.

## References
- PR: https://github.com/polyweb-dev/polyweb-mcp/pull/78
- Source task: TASK-000070. N3 follow-up: TASK-000095 (settings-write failure returns 503 and a retry converges).
- Related, not part of this fix: TASK-000076 (per-key UI), TASK-000086 (split search/fetch pool resolution).
- Reviews: /tmp/t70_pr78_approval.md (N2), /tmp/t70_sol_report.md, /tmp/t70_cardrev_000088.md.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 A scoped PUT whose routing write (`record_quota`) is refused returns 409 before any adapter is retired and before the runtime setting is saved.
- [ ] #2 A scoped DELETE whose routing write is refused returns 409 before any adapter is retired and before the runtime setting is cleared.
- [ ] #3 The API never returns 200 or 204 for a Set balance operation whose routing write was refused.
- [ ] #4 A deterministic regression test (resolve scope -> rotate key through the endpoint -> PUT with the old scope) on Exa or Keenable shows that the key is usable afterward or that the request returned 409. It fails before the fix.
- [ ] #5 The fix either rolls back the native anchor after a refusal or checks the credential generation before the native write. Either approach is acceptable.
- [ ] #6 REST shapes, unscoped multi-owner behavior, single-owner inference, vendor-402 deletion protection, scoped Exa isolation, keyless Keenable, and the Tavily AC #15 rule do not change. The existing successful Set balance tests still pass.
<!-- AC:END -->
