# Adversarial Threat Model — Parallel Account-API OAuth (tester-owned)

Frozen contract under test:

- `POST /api/v1/providers/{id}/oauth/device-code` →
  `{provider, user_code, verification_uri, verification_uri_complete|null,
  expires_in, interval}`
- `GET /api/v1/providers/{id}/oauth/status` →
  `{provider, status: pending|ready|expired|denied|unpaired, expires_in|null}`
- `DELETE /api/v1/providers/{id}/oauth` → `204` idempotent revoke-then-delete.
- Only `parallel` is supported; every other provider id → `404`.
- Balance flows via existing dashboard `latest_quota` as AUTHORITATIVE USD
  remaining-only (`limit` null).
- Bearer tokens live ONLY in SecretStore (OS keyring); metadata only in
  `runtime_settings`; status is fingerprint-only.

## Threats → attacks → covering tests

| # | Threat | Attack | Expected | Tests |
|---|--------|--------|----------|-------|
| T1 | Bearer/access/refresh token leaks into logs | Trigger every OAuth error path with sentinel tokens while `caplog` captures all records | No sentinel substring in any log record, error body, or response | `test_adv_oauth_leakage.py::test_no_token_material_in_logs_and_errors`, `adv_oauth_security.feature` |
| T2 | Token leaks into API responses / DB rows / fixtures | Connect, poll, error, revoke; then scan all response bodies, `runtime_settings` rows, quota rows, usage metadata, and checked-in fixture files | Fingerprint-only status; metadata rows contain no secret; fixtures hold sentinels only | `test_adv_oauth_leakage`, security feature |
| T3 | Disconnect deletes the vault key without revoking server-side | DELETE oauth with a connected stub server | Revoke endpoint is hit BEFORE the SecretStore delete; 204 | `test_adv_oauth_lifecycle.py::test_revoke_before_delete_ordering`, lifecycle feature |
| T4 | Disconnect is not idempotent (second DELETE 500s / re-revokes hot) | DELETE twice + concurrent DELETEs | Every DELETE → 204; no exception; revoke not hammered | `test_disconnect_idempotent`, lifecycle feature |
| T5 | Thundering herd on refresh (N concurrent reads → N token refreshes) | N concurrent status/dashboard reads with an expiring token | Single-flight: exactly 1 refresh call | `test_refresh_single_flight` |
| T6 | Refresh skew ( readers use a token being rotated / expired token served) | Expire token mid-read; concurrent reads during rotation | No 401 surfaces to callers; post-rotation reads use the new token | `test_refresh_skew` |
| T7 | 401/invalid-grant hot-loop (client retries forever against a dead grant) | Stub 401 invalid-grant on token/balance; poll status repeatedly | Status → `unpaired`; refresh/poll call counts stay bounded | `test_invalid_grant_goes_unpaired_without_hotloop` |
| T8 | Device-flow `denied` swallowed as pending forever | Stub `access_denied` on poll | Status → `denied` | lifecycle + device feature |
| T9 | Device-flow `expired` swallowed as pending forever | Stub `expired_token` on poll | Status → `expired` | lifecycle + device feature |
| T10 | `slow_down` / `interval` ignored (poll hammering) | Stub `slow_down`, short-interval device code, rapid status polls | Poll spacing honours interval and backs off after `slow_down` | `test_device_interval_and_slow_down_honored` |
| T11 | Float money math (101 cents → 1.00999… USD) | Balance cents 101/1/2/0 through dashboard | Decimal-exact USD, floor at zero, `limit` null | `test_adv_oauth_balance`, balance feature |
| T12 | Postpaid/invoice accounts fabricated as a balance | Balance with `will_invoice=true` | `remaining` None (unknown), never 0 or fabricated | balance tests + feature |
| T13 | Wrong precedence (seed/manual masks live balance) | Enable seed + manual anchor, then connect live balance | `balance > seed > manual` wins on dashboard | `test_balance_precedence_over_seed_and_manual` |
| T14 | Loose schemas accept/reflect extra keys (token smuggling) | POST device-code with extra body key; inspect every OAuth response key set | 422 on extra input; exact response key sets (extra=forbid both directions) | contract tests + device feature |
| T15 | TTL / failure-backoff ignored (balance poll per request) | Rapid dashboard reads; failing-then-healthy balance stub | ≤1 vendor call in TTL; backoff after failure | `test_balance_ttl_and_failure_backoff` |
| T16 | Tests touch the live network | Socket guard + stub transport assert in every adversarial test | Any non-loopback egress fails the test | `oauth_stubs.install_network_guard` autouse fixture + security feature |
| T17 | Non-parallel provider gains OAuth surface | device-code/status/DELETE for exa/tavily/… | 404 for every non-parallel id | contract tests + device feature |

## Oracle vs implementation

`oauth_stubs.py` holds the TEST ORACLE: stub vendor HTTP, sentinel secrets,
and the `cents_to_usd` expectation. Adversarial tests compare the developer's
HTTP-observable behaviour against the oracle; they never import developer OAuth
internals (opportunistic `importlib` probes only, and only to sharpen failure
messages). If a finding below turns out to be a contract flaw rather than an
implementation bug, it will be reported as such instead of forcing green.

## Round-1 findings (implementation: src/freesearch/parallel_oauth.py)

Status after realignment: pytest 42 passed / 4 failed, Behave adv-oauth 24/24
passed. The 4 failures are genuine implementation behaviors, each reproduced
with file:line + assertion in the listed test.

- F-stale-invoice (major): `balance_to_snapshot` returns None for
  will_invoice orgs without recording anything, so a previously recorded
  AUTHORITATIVE snapshot stays newest forever and the dashboard keeps quoting
  a prepaid balance for an invoice-billed org.
  Test: tests/adversarial/test_adv_oauth_balance.py::test_invoiced_poll_does_not_leave_stale_authoritative.
- F-stale-unpair (major): a 401 clears the vault and marks unpaired, but the
  last AUTHORITATIVE snapshot stays newest, so routing/dashboard keep steering
  on funds the dead pairing can no longer see (nothing ever overwrites it
  while unpaired).
  Test: tests/adversarial/test_adv_oauth_balance.py::test_unpair_does_not_leave_stale_authoritative.
- F-destructive-restart (major): POST .../oauth/device-code while paired
  revokes and deletes the live access/refresh pairing before the replacement
  code is approved; an abandoned re-pair leaves the operator unpaired.
  Test: tests/adversarial/test_adv_oauth_lifecycle.py::test_restart_while_paired_kills_live_pairing.
  Needs a contract ruling (confirm destructive intent vs gate/confirm param).
- F-device-invalid-grant (major, bounded harm): a 400 invalid_grant on the
  device-code poll maps to generic transient-pending (stays pending up to the
  ~30 min device window, re-hitting the vendor each interval), while the same
  code on the refresh path unpairs at once. Recommend mapping to expired.
  Test: tests/adversarial/test_adv_oauth_contract.py::test_device_invalid_grant_unpairs_instead_of_pending.

Round-2 re-verification (2026-09-11): all four fixes confirmed in code and
behavior. F1/F2 now record conditional ESTIMATED-unknown tombstones (only
when the newest row is AUTHORITATIVE); F3 gates re-pairing with 409 before any
vendor HTTP or state change; F4 maps device-poll invalid_grant to expired with
terminal stickiness. Adversarial pytest 46/46 (finding tests rewritten to the
rulings), adv-oauth BDD 24/24, dev suites 38+13 green, ruff+mypy clean.
Single-flight barrier-raced 3x stable. DB hygiene: uuid names + per-scenario
cleanup in both harnesses. No new findings; sign-off recommended below.

Notes (not failures): smuggled device-code body keys are ignored, not 422
(no request model exists in the frozen shape; values never surface); the
vendor interval is honoured via cached pending reads; refresh and balance
polls are single-flight; 400-invalid_grant refresh and 401 balance both
unpair with bounded vendor calls; dashboard balance rows appear only after a
bounded poll runs (dashboard reads alone never poll).
