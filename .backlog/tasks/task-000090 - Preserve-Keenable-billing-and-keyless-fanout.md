---
id: TASK-000090
title: Preserve Keenable billing and keyless fanout
status: To Do
assignee: []
created_date: '2026-11-16T10:51:00Z'
updated_date: '2026-11-16T11:26:00Z'
labels:
  - backend
dependencies: []
priority: low
type: bug
ordinal: 76000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
**Review verdict:** N1 is hardening, not a bug against the vendor contract: no documented Keenable HTTP response triggers it. N17/auth is a latent bug that PR #78 introduced: a keyless 402 aborts the whole fanout request, but the vendor documents no keyless 402. Priority Low.

## Background
TASK-000070 / PR #78 reads Keenable billing from HTTP responses as well as MCP metadata. For keyed calls, the adapter publishes vendor `credits_remaining` and paid-use facts, so a rebuild does not replace them with a local estimate. A keyed insufficient-credits 402 also ends fanout. Keyless Keenable stays unmetered for credits and uses only its per-IP rate limits. Polyweb calls only the REST endpoints `/v1/search`, `/v1/fetch` and their `/public` forms (`src/polyweb/adapters/keenable.py:65,74-76`).

## N1: billing-envelope selection (hardening)
Current, `src/polyweb/adapters/keenable.py:454-458`:
```
raw = payload.get("usage") if payload else None
if not isinstance(raw, dict):
    raw = payload.get("_meta", {}).get("keenable/usage") if payload else None
if not isinstance(raw, dict):
    return Decimal("1"), False, {}
```
Any top-level `usage` dictionary wins, even without billing keys. Probe (`/tmp/t70_probe_090.py`):
- `{"usage":{"duration_ms":12}, "_meta":{...credits 3, paid, remaining 500}}` -> `(1, False, {})`. The metadata is lost.
- Documented HTTP `usage` -> `(1, True, {..., credits_remaining:'99120'})`. Correct.
- `{"usage":{"credits":None}}` -> ValueError -> `invalid_response`. This matches the strict rule.
Reachability: the vendor docs (docs.keenable.ai/credits) say a REST response ends with a `usage` object `{sku, amount, credits, paid, credits_remaining}`. `_meta["keenable/usage"]` is the MCP envelope. A body with a non-billing `usage` dictionary and an MCP `_meta` together is undocumented. The fix is cheap defensive hardening.

Intended: accept top-level `usage` only when it has a billing key (`credits`, `amount`, `paid` or `credits_remaining`). Otherwise use the MCP envelope. Documented HTTP billing keeps precedence. `{"credits": null}` still raises.

## N17/auth: keyless 402 escapes fanout (latent, introduced by PR #78)
Path:
1. A fanout leg fails, and `KeenableAdapter._http_error` (`keenable.py:748-755`) maps **any** 402 to `quota_exhausted`, in keyed and keyless mode alike.
2. `_escapes_fanout` (`src/polyweb/services/execution.py:253-261`) -> `_terminal_out_of_credits` (`:240-250`) -> `_terminal_quota_402` (`src/polyweb/services/monitoring.py:1225-1232`). It checks `error.provider in ("tavily", "firecrawl", "exa", "keenable")` but not the auth mode.
3. `execution.py:2560-2561` re-raises, so the whole request fails. REST returns `402 {"detail":"HTTP 402","provider":"keenable"}` (`src/polyweb/routers/api.py:854-859`).
At the merge base, `"keenable"` was not in that provider tuple, so PR #78 introduced this. Probe:
```
N17 mode=keyless  code=quota_exhausted escapes_fanout=True quota_after_error=False
N17 mode=keyed    code=quota_exhausted escapes_fanout=True quota_after_error=True
```
Scenario: no Keenable key is configured -> a fanout search reaches `/v1/search/public` -> the vendor returns 402 -> the whole request fails with 402, even when Tavily or Exa legs succeed.
Why it is latent: the vendor errors page lists keyless limits as **429** (`public_rate_limit_hourly`, `public_rate_limit_per_second`). Each documented 402 has a billing code (`insufficient_credits` for keyed; `payment_required`, `payment_rejected`, `settlement` for x402/ZeroClick only). None is documented for `/public`.

Already safe (assert, do not fix):
- `record_terminal_402` (`src/polyweb/services/provider_limits.py:677-691`) needs a record with a `native_pool_id`. Keyless records have `native_pool_id=None`, so no terminal credit denial is written.
- `quota_after_error` (`keenable.py:612-614`) acts only in keyed mode.
- A keyed 402 that aborts fanout is the intended "pre-binding contract" for all four providers. Only the keyless case is in scope.

## Evidence
- Owner approval review N1 and N17 (/tmp/t70_pr78_approval.md).
- Sol (/tmp/t70_sol_report.md) partly confirms N1 and confirms the conditional auth-mode gap.
- Opus code-path review (/tmp/t70_cardrev_000090.md): N1 hardening, N17/auth latent. Both reproduce with pure probes, so failing-before unit tests are cheap.

## Suggested minimal approach
- N17/auth: in `KeenableAdapter._http_error`, return `quota_exhausted` for 402 only when `self._auth()[0] == _KEYED`. In keyless mode, return `http_error` (not retryable), so the leg is handled per leg. A REST fetch of a keyless 402 then maps to a **502** `http_error` response (`api.py:881-889`), not a 402.
- N1: select top-level `usage` only when it carries a billing key, as described above.

Do not change:
- The shared predicates `_terminal_quota_402`, `_terminal_out_of_credits` and `_escapes_fanout`. `routers/api.py`, Tavily, Firecrawl and Exa use them.
- Keyed `insufficient_credits` 402 terminal behavior, Tavily AC #15, manual-quota 409/503 semantics, REST shapes for other providers, exact Decimal values, paid-use semantics, keyless per-IP rate limits.
- TASK-000084 owns the process-wide auth-mode rail. Do not carry the auth mode to every terminal decision here. TASK-000079 owns reset dates and TASK-000080 owns separate search/fetch rate windows.

## Testing notes
- Put both regressions in `tests/unit/adapters/test_keenable_limits.py`, next to `test_http_usage_object_keeps_credits_remaining_and_paid` (`:464`).
- N1: unrelated top-level `usage` plus valid metadata; assert exact charge, paid flag and remaining. Keep the malformed-billing cases.
- N17: keyless 402 -> `http_error`, `_escapes_fanout` False; keyed 402 -> `quota_exhausted`, `_escapes_fanout` True.
- Add one fanout case in `tests/unit/services/test_execution.py` only if the per-leg outcome needs proof.
- Per AGENTS.md: unit tests run locally. Integration and BDD suites run on Woodpecker CI. Do not call live providers.

## References
- PR: https://github.com/polyweb-dev/polyweb-mcp/pull/78
- Source task: TASK-000070. Related: TASK-000084 (auth-mode rail), TASK-000079, TASK-000080.
- Reviews: /tmp/t70_pr78_approval.md (N1, N17/auth), /tmp/t70_sol_report.md, /tmp/t70_cardrev_000090.md.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 An unrelated top-level usage object does not hide valid MCP billing metadata. Exact charged credits, paid status, and vendor credits_remaining survive response parsing.
- [ ] #2 Genuine top-level HTTP billing keeps precedence, and malformed billing values (for example `{"credits": null}`) still produce the normalized invalid_response error rather than a silent fallback.
- [ ] #3 A keyless Keenable 402 fails only that fanout leg (non-terminal), and the other legs still return results. A keyed Keenable 402 stays terminal. No terminal credit record is written for the keyless case (already true; assert it). A REST fetch that gets a keyless 402 returns the documented 502 http_error response.
- [ ] #4 Regression tests fail before the envelope and auth fixes and pass after them, including a keyless/keyed contrast and exact billing assertions.
- [ ] #5 These existing tests keep passing: `test_spent_free_allowance_without_a_vendor_balance_stays_unknown`, `test_http_usage_object_keeps_credits_remaining_and_paid`, and the Tavily AC #15 tests in tests/integration/persistence/test_limit_repository.py. The shared terminal-402 predicates do not change.
<!-- AC:END -->
