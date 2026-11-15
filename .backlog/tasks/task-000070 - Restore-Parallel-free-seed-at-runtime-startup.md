---
id: TASK-000070
title: Restore provider quota state at runtime startup
status: In Progress
assignee:
  - '@devin'
created_date: '2026-11-14T11:37:00Z'
updated_date: '2026-11-15T18:27:00Z'
labels: []
dependencies: []
priority: high
type: bug
ordinal: 59000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Since aae1b63 (TASK-000042) adapters are built lazily per credential in ExecutionService._lease_adapter (services/execution.py) instead of eagerly at compose time. The old startup wiring (_apply_parallel_seed in mcp/server.py before aae1b63) looped over eagerly built adapters; that list is now always empty, so saved quota settings are never applied and hydrate_quota is never called.

Verified effects:
- Parallel: set_free_seed / hydrate_quota never called; the API-key free seed is dead config.
- Exa: set_monthly_budget / set_manual_starting_credits / hydrate_quota never called; budget and manual credits are dead config (control.py:335 loops over the empty adapter list).
- Brave / Keenable: hydrate_quota never called; in-memory counters reset on every restart AND every adapter rebuild (settings or credential change).
- Worse than a reset: a fresh adapter's ESTIMATED usage_snapshot overwrites a correct stored pool row (limit_repository apply_snapshot only rejects older or Tavily-specific observations), so the DB funds gate admits calls past the real cap, and a keyed Keenable key exhausted by a vendor 402 is unblocked again.
- Keenable keyed responses carry usage.credits_remaining (free + purchased, may lag or be absent) and usage.paid (https://docs.keenable.ai/credits); _reported_usage drops credits_remaining. apply_keenable_auth_mode loops over the empty adapter list (api.py:653, mcp/server.py:150).
- Hydration reads are unscoped: latest_quota(name) reads only unattributed rows and list_provider_usage sums all keys of a provider, while snapshots and usage rows now carry credential_id/pool_id.
- Manual unblock (PUT /api/v1/providers/{id}/manual-quota) is provider-wide and does not clear adapter latches (_hard_exhausted, _soft_zero).
- Stale docstring routers/api.py:601-606 and comment mcp/server.py:170-172.

Trust order for a key's remaining quota: vendor report (balance API, Brave headers, Keenable usage.credits_remaining, vendor 402) > human record (manual credits/anchor) > configured cap (Exa budget, Parallel free seed) > local count from the DB ledger. Remaining = newest trusted fact minus usage recorded after it. REST is the single executor in normal deployments (MCP forwards to the API); standalone MCP uses the same ExecutionService path.

Related: TASK-000077 owns Parallel OAuth pools, real Parallel per-call cost and the Parallel OAuth balance. TASK-000076 owns the Quotas page layout. Merged from former TASK-000071 and TASK-000072.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 When an adapter is built (startup, restart, settings change or credential change), each key's remaining quota is computed from the database: the newest trusted fact for the key's balance owner (vendor report, vendor 402, manual record or configured cap) minus the usage recorded after that fact
- [ ] #2 A local estimate never raises a key's remaining quota above the newest trusted fact in the same period, and never unblocks a key that a vendor 402 exhausted
- [ ] #3 For Brave, Exa, Parallel, Keenable, Tavily and Firecrawl, a blocked key becomes usable again when a newer vendor report proves new credits, when an admin records new credits for that key, or at the provider reset. A manual record clears both the stored denial and the in-memory adapter block at the blocked key's scope (credential row, or pool row for a pooled key)
- [ ] #4 PUT /api/v1/providers/{provider_id}/manual-quota accepts an optional key or pool scope. Without a scope it applies to the provider's only eligible key, so the existing Set balance dialog unblocks single-key providers with no UI change. With several keys and no scope it keeps today's provider-level behaviour and does not guess
- [ ] #5 Tavily: after a 402, a same-month /usage report unblocks the key only when it proves new funds (a credit or allowance increase against the balance saved at the 402, or a provider-issued timestamp after the 402). Reports without that proof stay rejected, so the existing stale-poll and cached-positive 402 protections keep passing
- [ ] #6 The saved Exa monthly budget and manual credits apply to Exa keys. When the period's recorded spend reaches the limit, Polyweb denies the next Exa call. Recording manual credits also clears Exa's soft-zero block
- [ ] #7 The saved Parallel free seed applies to Parallel API-key credentials. Parallel OAuth balance and real per-call cost stay in TASK-000077
- [ ] #8 Brave and Keenable usage counted before a restart or a settings change still counts after it
- [ ] #9 Usage and balances are tracked per key. Keys in one shared pool share one balance
- [ ] #10 Keenable without a key stays unmetered: only the per-IP rate limits apply
- [ ] #11 Keenable with a key: the auth mode comes from the credential. The adapter stores usage.credits_remaining and usage.paid from each billed response as a vendor fact. Use past the free allowance with credits left counts as paid use and does not block the key. A 402 insufficient_credits blocks the key until AC #3 applies. When credits_remaining is absent, the local count is the estimate
- [ ] #12 Integration tests against a real database prove AC #2, #3, #4, #5, #6 and #8, and each test fails before the fix
- [ ] #13 The routers/api.py compose docstring and the mcp/server.py startup comment describe the real behaviour
- [ ] #14 No UI changes. The per-key Set balance action and the user guide with screenshots are in TASK-000076. The quota API marks each number as vendor-confirmed or estimated
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. Tests first (fail before fix): Exa budget enforced after compose (tests/integration/routers/test_manual_quota.py); Brave/Keenable usage survives restart and settings change (tests/integration/services/test_quota_units.py); estimate cannot override a vendor fact or revive a 402; per-key manual record unblocks; Keenable credits_remaining stored; Parallel set_free_seed/hydrate unit coverage (tests/unit/adapters/test_parallel.py).
2. Adapter preparation helper in services/provider_runtime.py, called from ExecutionService._lease_adapter once per built adapter: apply Parallel seed and Exa budget/credits from ProviderConfig, hydrate_quota scoped to the key's balance owner (pool if pooled, else credential), record the snapshot if changed.
3. Scope hydration reads: optional credential/pool filter on list_provider_usage and use the scoped latest_quota.
4. Trust-order guard in limit_repository.apply_snapshot (generalise the Tavily-only rule): ESTIMATED snapshots may only lower remaining below the newest trusted fact in the period and never clear a terminal 402.
5. Per-key manual unblock: scope parameter on the manual-quota route; clears the stored denial and the adapter latch (_hard_exhausted, _soft_zero).
6. Keenable: keep usage.credits_remaining in _reported_usage and publish it as an observed fact; derive auth mode from the credential at lease time instead of the empty route list.
7. Fix stale docstring and comment. Narrow local runs (unit + one integration file); Woodpecker for the full integration and behave (not @live and not @latency) suites, at most 20 runs in total.

8. Tavily recovery: keep the 402 baseline (balance, credential generation); accept a same-month vendor_api snapshot only with proof of new funds; clear the adapter clamp only after the repository accepts it. Keep test_402_preserved_despite_positive_cached_balance and the stale-poll tests; deliberately update test_usage_snapshot_after_terminal_clamps_positive_to_zero for the proven-credit case only; add repository, integration and BDD recovery cases.
9. Manual-quota scope: optional credential/pool scope on PUT/DELETE manual-quota; infer the single eligible key when omitted; route the record through ProviderLimitsService to the scoped NativePoolRow and clear the cached adapter's latch (_hard_exhausted, _soft_zero, Tavily clamp).
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Slice A (46d5cef, d0dd41b, 2c5dd1d): build-time adapter preparation (prepare_adapter_quota via CredentialAdapterCache.lease prepare hook), scoped hydration reads, local-estimate guard in apply_snapshot. CI #118 api-unit, #119 api-integration, #120 api-bdd green. Review found Exa 429 latch (blocker) and Brave vendor_headers bypass (major), plus 6 minor items.
Round 2 (5ca2c63..c043751): all 8 review findings fixed; manual-quota optional credential_id/pool_id query scope with single-owner inference (OAuth/keyless excluded); scoped record replaces the 402 row, becomes the routing snapshot and retires cached adapters; Tavily same-month recovery only with proof of new funds vs the stored pre-402 baseline; Keenable keyed credits_remaining stored as a vendor_api fact, keyed 402 writes a terminal row, auth mode from the credential; vendor_confirmed flag on USD balance models. Deliberate contract change: Exa 429 no longer means exhausted funds (test_exa_quota.py, test_quota_units.py, quota.feature). CI #127 unit green; #128/#129 failed on adv_oauth_balance (no-scope record hit an OAuth key), fixed in c043751; #133 api-integration, #134 api-bdd, #136 api-latency (added p95 89.9-104.6 ms) green. CI runs used: 9 of 20.

Final review (2f56883..c043751) found F1 blocker: the Tavily 402 baseline was the locally debited balance, so a stale /usage report repeating the last vendor balance unblocked the key. Round 3 (edd16a2..7334ca3): baseline = newest vendor report of the month (store) / last month /usage figures (adapter), proof strictly greater; also fixed a real production bug where a terminal 402 was dropped as older than a concurrent call's debit; DELETE manual-quota clears only manual records; stale hydration skips record_quota for a retired adapter; scoped Exa records keep provider-wide credits; Keenable credits_remaining survives a scoped sync and rebuild. CI #138 api-integration (1754), #139 api-bdd (276), #140 api-unit (2293) green. CI runs used: 12 of 20. Orchestrator re-ran the F1 probe on 7334ca3: passes. F6 filed as TASK-000084.
<!-- SECTION:NOTES:END -->
