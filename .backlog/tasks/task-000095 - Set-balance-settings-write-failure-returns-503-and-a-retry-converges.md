---
id: TASK-000095
title: Set balance settings-write failure returns 503 and a retry converges
status: To Do
assignee: []
created_date: '2026-11-16T11:25:00Z'
labels:
  - backend
dependencies: []
priority: low
type: bug
ordinal: 81000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
**Review verdict:** real but latent and minor. A settings-write failure after a successful projection gives an unhandled 500, and GET disagrees with the stored balances until a retry. One retry fixes it. It needs a SQLite write failure directly after a successful write to the same database.

## Background
TASK-000070 / PR #78 changed Set balance (`PUT /api/v1/providers/{provider}/manual-quota`) so the quota projection runs before the runtime-setting write. This fixed an older partial write (a saved setting with no projection). It also made the mirror case possible: a projection with no saved setting. Split from TASK-000088 (owner finding N3), which now covers only the refused routing write (N2).

## Current vs intended behavior (head 20405293f7440f4f0b30363646c074d54add4816)
- PUT: `src/polyweb/routers/control.py:348-350` calls `_notify_manual_anchor(...)` (native pool, routing snapshot, adapter retirement). Then `control.py:351-353` calls `persist_manual_quota(...)`, which calls `await repository.set_runtime_setting(...)` at `src/polyweb/services/manual_quota.py:187-189`.
- DELETE: `control.py:375` projects the clear first. Then `control.py:376` calls `clear_manual_quota(...)`, which calls `set_runtime_setting(..., None)` at `manual_quota.py:209`.
- Only `_notify_manual_anchor` is wrapped (`control.py:438-461`, 409 for `ManualAnchorRejectedError`, 503 for other errors). The setting write is not wrapped, so its failure is an unhandled exception and the client gets **500**.

Intended: a settings-write failure returns 503 (the documented "retry" status), and one retry makes GET, the native balance and the routing snapshot agree.

## Scenario (reproduced)
The Opus review (/tmp/t70_cardrev_000088.md) made `set_runtime_setting` raise for `manual_quota:*` keys:
```
PUT:    500 | GET None | native 10 | routing 10   -> retry 200, GET record OK
DELETE: 500 | GET 10   | native None | routing None -> retry 204, GET None
```
1. An admin sends Set balance for a key.
2. The projection succeeds: native pool and routing snapshot hold 10.
3. The setting write fails (for example SQLite lock timeout, disk full, I/O error).
4. The client gets 500. GET returns no record, but the effective balance is 10.
5. A retry returns 200 and all three views agree.
For DELETE, the effective anchor is gone, but GET still returns the old record until a retry.

Impact: the API does not report success, and after a failed PUT the effective state is the state the operator wanted. Only GET disagrees until the retry.

## Evidence
- Owner approval review N3 (/tmp/t70_pr78_approval.md): "A `set_runtime_setting` failure after a successful projection leaves an anchor the API does not report."
- Sol (/tmp/t70_sol_report.md) confirms the partial PUT/DELETE state and rates it a follow-up.
- Opus code-path review (/tmp/t70_cardrev_000088.md): real but latent and minor. It recommends an outcome-based fix (503 and retry convergence), not full atomicity.

## Suggested minimal approach
- Map a failure of the setting write in PUT and DELETE to the same generic 503 that `control.py:456-461` uses ("retry"). Keep the log line.
- Make sure that a retry of the same PUT or DELETE converges. The current probe shows that it does. Keep that property.

Do not change:
- The 409 path for a refused record (TASK-000088) and the existing 503 detail text.
- REST shapes, unscoped multi-owner behavior, scoped Exa isolation, keyless Keenable, and the Tavily AC #15 rule.
- **Out of scope:** a full transaction across the native pool, the routing snapshot and the runtime setting. That is a cross-repository refactor for a rare failure that a retry fixes.

## Testing notes
- Closest home: `tests/integration/routers/test_manual_quota.py`. The existing 503 case at `:1285-1294` monkeypatches `apply_manual_anchor`. Use the same style to make `set_runtime_setting` fail for `manual_quota:*` keys only.
- For PUT and DELETE: assert 503 (fails before the fix with 500), then remove the fault, retry, and assert that GET, the native pool and the routing snapshot agree.
- Per AGENTS.md: unit tests run locally. Integration and BDD suites run on Woodpecker CI. You can run one offline integration file locally to see the test fail and then pass. No new BDD flow is necessary.

## References
- PR: https://github.com/polyweb-dev/polyweb-mcp/pull/78
- Source task: TASK-000070. Split from TASK-000088 (N2, refused routing write).
- Related: TASK-000094 (SQL parameters in error logs on the same route).
- Reviews: /tmp/t70_pr78_approval.md (N3), /tmp/t70_sol_report.md, /tmp/t70_cardrev_000088.md.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 When the runtime-setting write fails after a successful projection, PUT /manual-quota returns 503, not 500.
- [ ] #2 When the runtime-setting write fails after a successful clear projection, DELETE /manual-quota returns 503, not 500.
- [ ] #3 After such a failure, one retry of the same request succeeds, and GET, the native balance and the routing snapshot agree.
- [ ] #4 A regression test with a failing settings write covers PUT and DELETE. It fails before the fix (500) and passes after it.
- [ ] #5 The 409 path, the existing 503 detail, REST shapes, unscoped multi-owner behavior and the Tavily AC #15 rule do not change. A full transaction across the three writes is not required.
<!-- AC:END -->
