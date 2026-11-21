---
id: TASK-000093
title: Close quota adapters once and remove unused runtime code
status: To Do
assignee: []
created_date: '2026-11-16T10:53:00Z'
updated_date: '2026-11-16T11:29:00Z'
labels:
  - backend
dependencies: []
priority: low
type: task
ordinal: 79000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
**Review verdict:** latent bug plus cleanup. A retired adapter with an active lease can close two or three times at shutdown. No user impact today, because every adapter close is idempotent and wrapped in `suppress(Exception)`. The scheduler plumbing and Tavily helpers are dead code, not a bug. Priority Low.

## Background
TASK-000070 / PR #78 moves quota restoration to lazy per-credential adapter preparation. Limit sync now runs on demand, not through a global polling task. The adapter cache keeps retired adapters until active leases finish. The refactor leaves a duplicate-close path and some obsolete lifecycle and Tavily helper code.

## Finding 1: duplicate adapter close (latent)
Path (head 20405293f7440f4f0b30363646c074d54add4816):
- A scoped Set balance calls `retire_credential_adapters` (`src/polyweb/routers/control.py:436-445` -> `src/polyweb/services/execution.py:982-985`). The `retire_other_*` calls after a lease (`execution.py:1649-1656`) take the same path.
- `_retire_entry` (`execution.py:768-776`): when `active > 0`, the entry is marked retired and appended to `_draining`, but it stays in `_entries`.
- Shutdown (REST `src/polyweb/routers/api.py:244-247`, and the MCP last exit) calls `ExecutionService.aclose` -> `CredentialAdapterCache.aclose` (`execution.py:827-842`). `entries = [*self._entries.values(), *self._draining]` (`:831`) lists the entry twice, and `:837-839` closes it twice.
- **Late-release re-close (missed before):** after `aclose`, the late `lease.release()` -> `release` (`execution.py:721-724`) sees `retired and active == 0` -> `_drop` (`:778`) -> `_retire` (`:803`) -> a background close task calls `adapter.aclose` again.
- **Replaced-entry case:** if a new lease of the same key arrives before shutdown, the old entry is only in `_draining` (closed once by `aclose`), but the late release still closes it a second time.

Probe `/tmp/t70_probe_000093.py` against the real cache (close counts):
```
replace=False after aclose: 2          # duplicate in _entries and _draining
replace=False after 2nd aclose: 2      # repeated shutdown is fine
replace=False after late release: 3    # late-release re-close
replace=True after aclose: 1           # entry replaced in _entries by a new lease
replace=True after late release: 2     # double close even without the duplicate
control (active, not retired): 1
```
Scenario:
1. A request leases credential K's adapter.
2. An operator saves a scoped manual record for K, which retires the adapter.
3. Shutdown runs before the request ends: 2 closes.
4. The request releases its lease: a 3rd close.

Reachability: only when a request is in flight at lifespan shutdown. `uvicorn.run` (`api.py:966`) waits for requests before shutdown. Today every adapter `aclose` closes httpx clients, and an httpx 0.28.1 double `aclose` does nothing. Both close paths use `suppress(Exception)`.

Intended: each adapter closes exactly once across `aclose`, a late release, and a second `aclose`. Deduplicating `entries` alone is not sufficient, because the late release still re-closes.

## Finding 2: dead scheduler plumbing (cleanup)
- MCP (`src/polyweb/mcp/server.py`): `routes` is unused in `_start_limits_generation` (`:138`) and only passed along by `_start_injected_limits` (`:159`, `:173`). `stop = asyncio.Event()` (`:151`) and `state["limits_task"] = None` (`:156`) feed `_take_limit_cells` / `_stop_limits_task` (`:186-219`, called at `:818`, `:835`). Nothing waits on the event.
- REST (`src/polyweb/routers/api.py`): `_start_limits` (`:638`) never uses `stop`. `stop.set()` (`:684`) in `_stop_limits` (`:677-690`) has no listener. The `stop_limits` event is created at `:298` and passed at `:228`, `:253`, `:318`, `:326`, `:599`, `:614`. `app.state._limits_task` is also set at `:347`.
- Keep REST `routes`: `api.py:669-670` passes `lambda: routes` to `LimitSyncService`, so injected-adapter sync still uses it.

## Finding 3: Tavily helpers (cleanup)
`_terminal_clamp` (`src/polyweb/adapters/tavily.py:1176`) is called only from `_quota_snapshot` (`:1346-1372`, call at `:1357`). No production code calls `_quota_snapshot`. Production handles the terminal state through the `_terminal_402` flag and `usage_snapshot_stored` (`tavily.py:1100-1139`). Callers outside `src/`:
- Unit tests: `tests/unit/adapters/test_tavily.py:1466-1678`.
- **BDD steps:** `tests/bdd/features/steps/provider_limits_steps.py:2783` and `:2800`. Removing the helper changes BDD steps, so the `api-bdd` workflow must run on Woodpecker CI.

## Exclusions
`_provider_record_applies` legacy branches (`src/polyweb/services/manual_quota.py:236-247`) stay reachable from `:129` and `:224`. Keep them.

## Evidence
- Owner approval review N16 (/tmp/t70_pr78_approval.md).
- Sol (/tmp/t70_sol_report.md) confirms the duplicate close and dead code, and corrects the `_provider_record_applies` claim.
- Opus code-path review (/tmp/t70_cardrev_000093.md): latent plus cleanup, reproduced with the probe above.

## Suggested minimal approach
- In `aclose`, deduplicate entries by identity and mark every taken entry closed (for example a `closed` flag), so `release` / `_drop` skip entries the cache already closed.
- Remove only proven-unused parameters, events and helper chains.
- Keep preparation cancellation, active-lease safety, close ordering, repeated shutdown safety, injected compositions, and on-demand sync.
- Do not change quota policy, the Tavily AC #15 proof rule, REST contracts, manual-quota 409/503 semantics, or adapter retry policy (TASK-000087).

## Testing notes
- `tests/unit/services/test_execution.py`: close counter. Hold a lease, retire it, `aclose`, release the lease, `aclose` again. Assert a total close count of 1. Failing-before values: 2 after `aclose` and 3 after the late release; 1 and 2 for the replaced-entry case.
- Tests to rework for the MCP removal, keeping their coverage:
  - `tests/integration/mcp/test_limits_lifecycle.py:345-357` monkeypatches `_stop_limits_task` to hold the session enter/exit race window. Give that race test another hook so it keeps the window.
  - `tests/integration/mcp/test_server.py:1000-1001` builds state with `limits_task` / `limits_stop`.
- Tavily: move meaningful quota assertions from `test_tavily.py:1466-1678` and the BDD steps to supported methods.
- Other lifecycle checks: `tests/integration/routers/test_api.py`.
- Per AGENTS.md: unit tests run locally. Integration and BDD suites (including `api-bdd`) run on Woodpecker CI.

## References
- PR: https://github.com/polyweb-dev/polyweb-mcp/pull/78
- Source task: TASK-000070. Related: TASK-000087 (retry backoff), TASK-000082 (provider connection tests).
- Reviews: /tmp/t70_pr78_approval.md (N16), /tmp/t70_sol_report.md, /tmp/t70_cardrev_000093.md.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 A retired adapter with an active lease closes exactly once in total across cache shutdown, a late lease release, and a second shutdown. This also holds when a new lease replaced the entry before shutdown.
- [ ] #2 A focused close-counter regression fails before the fix (2 then 3 closes; 1 then 2 in the replaced case) and passes after it with 1. Existing preparation cancellation and lease-safety coverage still passes.
- [ ] #3 Obsolete scheduler parameters/events (MCP routes/stop/limits_task, REST stop_limits and _limits_task) and the unused Tavily helper chain are absent, while MCP/REST startup, shutdown, injected-adapter sync, and on-demand quota sync keep their behavior. The MCP session enter/exit race test in test_limits_lifecycle.py keeps its race window through another hook.
- [ ] #4 Meaningful Tavily quota assertions from the unit tests and the BDD steps (provider_limits_steps.py:2783,2800) survive helper removal, and api-bdd passes on Woodpecker CI. Reachable legacy provider-record matching and the live REST routes callback are preserved.
<!-- AC:END -->
