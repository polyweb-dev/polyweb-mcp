---
id: TASK-000091
title: Keep pool usage history consistent across membership changes
status: To Do
assignee: []
created_date: '2026-11-16T10:52:00Z'
updated_date: '2026-11-16T11:29:00Z'
labels:
  - backend
dependencies: []
priority: low
type: bug
ordinal: 77000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
**Review verdict:** latent and minor. The pool ledger stops counting a departed member's pre-join usage, but nothing is lost overall: the rows go back to the key's own ledger. The trigger needs a rare same-month sequence. The current behavior can be a valid product rule, and the docstring overstates it. Priority Low.

## Background
TASK-000070 / PR #78 rebuilds adapter estimates from each balance owner's usage ledger for the current period. A shared upstream pool shares one balance across its member credentials. The PR also counts unpooled usage that members recorded before they joined, so a key that moves into a pool does not raise the pool's remaining estimate. The query derives that attribution from **current** membership.

## Current behavior (head 20405293f7440f4f0b30363646c074d54add4816)
- `src/polyweb/persistence/storage.py:1210-1220`: for a `pool_id`, the query builds `members = select(CredentialPoolLinkRow.credential_id).where(CredentialPoolLinkRow.pool_id == str(pool_id))` and counts `UsageEventRow.pool_id == str(pool_id)` OR (`pool_id IS NULL` AND `credential_id IN members`).
- After `delete_link` (`src/polyweb/services/pools.py:315`) unlinks a credential, its pre-join unpooled rows no longer match the pool. Pool-tagged rows stay in the pool.
- **The departed rows go back to the key's own ledger:** the credential branch counts `credential_id == X AND pool_id IS NULL` (`storage.py:1221-1225`).
- A transfer (relink through the `put_link` upsert, `src/polyweb/persistence/pools.py:573-590`) moves the pre-join rows to the new pool. This is current behavior.
- The docstring at `storage.py:1198-1200` says "so the pool never under-counts". That is true only for current members.
- A link change alone does not rebuild an adapter. The cache key is provider, credential, generation, token generation and config fingerprint (`src/polyweb/services/execution.py:1594-1600`), not membership. A restart, settings change or rotation rebuilds it; `_observation_upstream_pool` (`execution.py:1112`) then reads the current link.
- Exa sums the ledger with no anchor: `self._spend = sum(...)` (`src/polyweb/adapters/exa.py:381-390`). Brave mostly hides the edge, because an anchored hydrate subtracts only rows after the latest trusted fact.

## Scenario (reproduced)
The Opus review ran a throwaway probe (real SQLite, an Exa pool with keys a1 and a2):
1. Key a1 spends $2 unpooled in the current UTC month.
2. a1 joins the pool. The pool estimate includes the $2, as PR #78 intends.
3. a1 spends $1 tagged with the pool. a2 spends $1 tagged with the pool.
4. a1 leaves the pool (unlink). No refund or period reset occurs.
5. A remaining member's adapter (a2) is rebuilt (for example after a restart).
```
PROBE joined: pool ledger=4 a2 rebuilt spend=4
PROBE left:   pool ledger=2 a2 rebuilt spend=2  a1 own ledger=2
```
The pool loses $2 of spend and a1's own ledger counts those $2 again. Under a "retained liability" rule, the pool now under-counts by at most one key's pre-join spend for the month. It clears at the month reset or at the next vendor fact.

When it happens: all in one UTC month, (a) a key is used unpooled, (b) it joins a pool, (c) it leaves or transfers, (d) a remaining member's adapter is rebuilt, and (e) the owner has no trusted anchor newer than the pre-join rows.

## Product question
Today's rule is "current membership defines attribution". Under that rule the behavior is consistent. If a pool models one vendor account, a "retained liability" rule is more correct, but it needs new history (stamp `pool_id` at join time, or membership intervals) and a migration.

**Cheapest valid outcome:** keep the current membership rule, fix the docstring at `storage.py:1198-1200` so it states the rule exactly, and pin the current behavior with a departure test. Choose retained liability only if the owner decides that the pool keeps the pre-join liability.

## Evidence
- Owner approval review N12 (/tmp/t70_pr78_approval.md), rated low.
- Sol (/tmp/t70_sol_report.md) confirms it and separates pre-join unpooled rows from pool-tagged rows.
- Opus code-path review (/tmp/t70_cardrev_000091.md): latent and minor, reproduced with the probe above.

## Constraints
- Keep explicit pool-tagged usage, period boundaries, operation filters, per-key isolation, and legacy unattributed-row safety. Count each event once in a pool query.
- Do not change vendor-fact precedence, the Tavily AC #15 rule, REST shapes, manual-quota 409/503 semantics, or keyless Keenable (its hydrate reads unscoped, `src/polyweb/adapters/keenable.py:494`).
- Do not fold the split search/fetch pool defect (TASK-000086) into this card.

## Testing notes
- Closest home: `tests/integration/services/test_provider_runtime.py`, next to `test_pooled_key_counts_its_usage_from_before_it_joined_the_pool` (`:1210`), which covers entry, not departure.
- Use Exa as the estimate-only owner. Use a real temporary database, fixed event times, and pool-tagged usage as a control. Rebuild the remaining member's adapter after the link change.
- Repository query coverage can use `tests/integration/persistence/test_sqlite_repository_aggregates.py`.
- Per AGENTS.md: unit tests run locally. Integration and BDD suites run on Woodpecker CI. You can run one offline integration file locally. No new BDD flow is necessary.

## References
- PR: https://github.com/polyweb-dev/polyweb-mcp/pull/78
- Source task: TASK-000070 AC #8 and #9. Related: TASK-000086 (split operation pools), TASK-000077 (Parallel OAuth and cost tracking).
- Reviews: /tmp/t70_pr78_approval.md (N12), /tmp/t70_sol_report.md, /tmp/t70_cardrev_000091.md.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 A product decision defines pre-join usage attribution after join, leave, rejoin, and transfer, including treatment of existing history, before implementation changes. Keeping the current membership rule is a valid decision.
- [ ] #2 Pool ledger totals and estimate-only balances follow that decision across membership changes and adapter rebuilds without silent loss or duplicate counts of attributable events.
- [ ] #3 A deterministic real-database regression on an Exa pool covers departure and a rebuild of a remaining member, with pool-tagged usage as a control. It asserts where the departed key's pre-join rows count (pool, key, or both) after leaving and after a transfer. If the rule changes current behavior, record the failure before the fix and the pass after it.
- [ ] #4 The `list_provider_usage` docstring (storage.py:1198-1200) states the chosen attribution rule exactly and no longer claims that the pool never under-counts unless that is true.
- [ ] #5 Period and operation filters, unrelated credential/pool balances, trusted vendor facts, and legacy unattributed-row safety remain correct.
<!-- AC:END -->
