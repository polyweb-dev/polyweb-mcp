# A3 tester takeover checkpoint (TASK-000045)

Written by the FINAL tester call (3/3) on 2026-10-30, at the user-ordered safe
point. This file is an authorized exception to the tests-code-only rule (it is
a handoff document only; no Backlog or src edits were made). Nothing in here
is a substitute for the task notes; the orchestrator decides who acts next.

## Where this work lives

- Workspace: `C:\Sharath\Computer Programming\Programs\Python\polyweb_d1`
- Branch: `projects/api-layer-rewrite`
- Git head: `ef6b07bcac04a0624c524a172946f3552ff01db3` (`skill updates`)
- All test changes are working-tree only (git: none committed; the eight A3
  test/fixture files are untracked ??, latency file untouched).
- Production (`src/`), configs, docs, and Backlog are FROZEN and untouched by
  this call. Developer round 2 has NOT been started yet.
- Budgets at handoff: Developer 1/3, Tester 3/3 (this call consumed), Reviewer
  2/3 (call 2 included one failed transport attempt).
- A replacement tester or developer must be launched by the user explicitly.
  Never auto-launch.

## Role rule recap

- Tester edits TESTS ONLY (`tests/**`). Production stays frozen. No new PRs,
  commits, delegation, latency work (user deferred latency; the latency suite
  `tests/integration/latency/test_a3_authority_latency.py` is untouched and
  was NOT executed).

## Static state (verified before freeze)

- `uv run --no-sync ruff check tests --output-format=concise` -> `All checks
  passed!`
- `uv run --no-sync ruff format <file> --check` per file -> all A3 files
  formatted. Known tool bug: `ruff format --check
  tests/integration/routers/test_a3_mcp_authority_forwarding.py` crashes ruff
  (`Annotation range ... beyond the end of buffer`) while the same file in
  write mode (`ruff format <that file>`) runs fine and left it formatted.
  Treat the panic as a ruff-side renderer bug, not unformatted content.
- All edited test modules parse (`ast.parse` verified).

## Test manifest (what exists in tests/ right now)

Modified files (all preserved from call 2; nothing deleted):

1. `tests/fixtures/a3_authority.py` - shared A3 fixture/fixture-world module:
   - Round-3 edit: removed unused `AuthMode`/`LimitOperation` imports
   (immediate-fix list). Everything else preserved.
2. `tests/integration/services/test_a3_authority_topology.py` - Round-3 edits:
   - removed the unused `second_rows` assignment inside
     `test_pool_disabled_while_queued_never_dispatches`;
   - removed the stray `del second_rows` from
     `test_binding_disabled_while_queued_never_dispatches` (undefined name);
     the `ExecutionBindingMissing` assertion is preserved intact.
3. `tests/integration/services/test_a3_fair_capacity.py` - Round-3 edits:
   - sorted the local import of `DispatchGrant, _PoolQueue`;
   - removed the unused `labels` var in the unit scheduler test;
   - NEW: `_bounded_condition` helper + P5 test
     `test_canceling_a_granted_send_releases_the_concurrency_slot`
     (with a failure-time diagnostic peek of `world.authority._queues`);
   - imports: added `Callable`, `usage_event_rows`.
4. `tests/integration/services/test_a3_bounded_queues.py` - Round-3 edits:
   - formatting fixes;
   - NEW imports (`RoutingPreference`, `RecordingAdapter`,
     `parked_search_handler`, `seed_credential`, `usage_latency_ms`);
   - NEW helpers `_wait_expiry_settled`, `_wait_p3_refusals` (both fail with
     bounded messages so an unbounded queue cannot hang the suite);
   - NEW tests:
     - `test_default_queue_wait_bounds_a_backlog_when_the_allocation_sets_none` (P4)
     - `test_request_deadline_expires_queued_work_before_any_send` (P7)
     - `test_queue_wait_is_reported_separately_from_provider_latency` (P13)
     - `test_authority_bytes_bound_is_authority_wide_across_pools` (P3,
       cross-pool bytes; uses a second credential + second pool + pinned
       routing + an extended `adapter_factory` monkeypatch)
5. `tests/integration/routers/test_a3_mcp_authority_forwarding.py` - largest
   Round-3 change (real MCP -> HTTP forwarder -> API chain):
   - `seed_key_project_with_pool` gained optional `max_queued_requests` /
     `max_queue_wait_ms` kwargs (additive; old callers unchanged);
   - NEW infrastructure:
     - `_parking_handler(parks)` + `_ParkedSend` (parks the API host's sends);
     - `RecordedHop` / `RecordingApi` (ASGI wrapper recording every forwarded
       exchange: headers, statuses, request/response bodies capped 4KB);
     - `forwarding_settings` (settings with `execution_authority_url` +
       `execution_forward_timeout_seconds`, patched into
       `polyweb.mcp.server.get_settings`);
     - `install_asgi_hop` (subclasses the module's `ExecutionForwarder` so it
       rides `httpx.ASGITransport` over the real `create_app` API);
     - `_wait_until`, `_tool_refusal`, `_tool_success`, `_queue_depth`,
       `forwarded_search_hop`, `last_search_hop`, `_trace_root_rows`.
   - NEW tests:
     - `test_forwarded_tool_call_verifies_credential_deadline_and_trace`
       (credential == Bearer key, deadline exact-band forwarded unmodified,
       x-trace-id == tool root trace id via shared trace db after
       `shutdown_injected_observability`, one fenced dispatch with the
       key's actor, one usage row, one provider send);
     - `test_unreachable_authority_fails_a_tool_call_closed`
       (dead loopback port: two calls, no send/dispatch/usage/secret);
     - `test_forwarded_call_surfaces_the_queue_wait_expiry_with_wire_retry_after`
       (allocation `max_queue_wait_ms=1500`, held first send, second queued
       call expires at the bound: wire 429 + positive Retry-After + one safe
       capacity category at the tool, zero sends/usage beyond the held call);
     - `test_forwarded_call_surfaces_spend_refusal_and_never_forwards_unverified`
       (flat pooled USD allowance zero: wire 402 with NO Retry-After header,
       `provider spend is exhausted` at the tool, and an unverified stdio key
       refuses locally with `authentication is required` and never hops).

Untouched (call-2 artifacts, unmodified this call):
- `tests/integration/services/test_a3_failures_recovery.py` (funds/retry/
  restart/takeover; the strengthening edit listed below was NOT made),
- `tests/integration/services/test_a3_mixed_transport_contention.py`,
- `tests/integration/latency/test_a3_authority_latency.py` (deferred),
- `tests/integration/services/test_a2_execution_regressions.py`,
  `test_a2_adversarial_execution.py`, `tests/unit/services/test_a2_*`.

## Executed runs this call (do NOT rerun these same commands before editing)

1. `uv run --no-sync pytest tests/integration/routers/test_a3_mcp_authority_forwarding.py -q`
   -> 6 passed in 11.59s (final state; an earlier iteration failed only on
   invalid settings URLs/base_url and a result-shape assumption, both fixed).
2. `uv run --no-sync pytest tests/integration/services/test_a3_bounded_queues.py -q`
   -> 8 passed, 3 failed in 28.40s:
   - FAILED `test_authority_queue_count_bound_is_authority_wide_across_pools`
     (pre-existing call-2 test, runs FIRST in the file so later new tests
     cannot have affected it) - message "the authority-wide queued bound
     saturated neither second wave" (line ~480) - expected production failure
     (P3 global count across queues).
   - FAILED `test_default_queue_wait_bounds_a_backlog_when_the_allocation_sets_none`
     (NEW P4, line ~548) - "the default queue wait must bound a backlog whose
     allocation set no explicit max_queue_wait_ms (P4)" - expected production
     failure.
   - FAILED `test_authority_bytes_bound_is_authority_wide_across_pools`
     (NEW P3, line ~768) - "the authority-wide queued-bytes budget must refuse
     the cross-pool overflow..." - expected production failure.
   - NEW P7 and P13 tests PASSED (both are verified current behavior, kept as
     regression locks: P7 through `service.search(..., deadline=...)`; P13
     requires metadata `queue_wait_ms == 2000` exact and `latency < 1500`).
3. `uv run --no-sync pytest "tests/integration/services/test_a3_fair_capacity.py::test_canceling_a_granted_send_releases_the_concurrency_slot" -q`
   -> FAILED in ~12.6s (three runs; last two with the diagnostic message).
4. `uv run --no-sync ruff check tests` -> All checks passed (final state).
5. `uv run --no-sync ruff format <each A3 file>` -> formatted (one
   write-mode run; the `--check` crash is documented above).

Not executed this call (avoid re-running before any edit you make):
`tests/unit/services/test_a2_*`, full `tests/unit tests/integration` suite
(never run in this round), Behave, and the latency suite.

## Expected production failures vs test defects

Expected production failures (leave FAILING for developer round 2; the tests
are the specification):

1. P4 default wait: `_PoolQueue._wait_seconds` (src/polyweb/services/
   execution_authority.py line ~280) only considers
   `policy.max_queue_wait_ms` and `policy.deadline`; the queue's
   `default_max_wait_ms` (authority-level, stored at line 183/592, threaded
   into `_pool_queue` at line ~820) is never applied, so a backlog whose
   allocation sets neither wait nor deadline never expires. Evidence by the
   failing P4 test above.
2. P3 global count across queues: the authority-wide one-slotted queued
   request bound is only checked per `(pool, operation)` queue
   (`_PoolQueue._check_bounds`, line ~240-253), so a second queue admits work
   beyond the authority total. Evidence: the failing pre-existing count test.
3. P3 global bytes across queues: same root cause for bytes
   (`_queued_bytes_total` is per-queue at line 276). Evidence: the failing
   bytes test.
4. P5 canceled granted send: after canceling a granted call whose provider
   send is parked, the fair queue decrements its in-memory slot (diagnostic
   showed `inflight=0 pool_inflight=0 pending=0`) but the DURABLE strict
   reservation of the canceled attempt is never settled: the next granted
   waiter is refused with
   `LimitDeniedError('pool:<uuid>: rate_limited: local concurrency cap is
   full; vendor call skipped')` from `reserve_strict`'s
   `_open_reserved_count` (persistence/limit_repository.py line ~2270).
   Leading hypothesis for the fix: `monitoring._uncertain` (services/
   monitoring.py line ~647) returns after the native `record_uncertain`
   attempt without mutating the strict wrapper/admission, and
   `contextlib.suppress` hides any store error, so the row stays `reserved`
   forever. The canceled send also leaves its dispatch row unresolved (that
   part is correct-by-design; only the capacity settle leaks).

Verified behavior (tests PASS, keep as locks; no fix needed):
- P7: a request-level monotonic deadline expires queued work before any send,
  with a typed retriable `ExecutionQueueExpired` and no debit/usage/attempt.
- P13: queue wait lands in `metadata_json.queue_wait_ms` (exact virtual
  2000ms) while `latency_ms` stays below 1500ms (separation holds).
- P10: the forwarded hop carries the verified credential byte-for-byte, the
  tool's absolute deadline band unmodified, and the tool call's trace id
  equals the forwarded `x-trace-id` (read from the shared `trace_spans`
  after `shutdown_injected_observability`).
- Outage fails closed with no send/dispatch/usage/secret; spend 402
  category on the wire without Retry-After; unverified credentials never
  hop.

## Not done (precise next actions for the next tester)

1. Funds "settle once" strengthening - EDIT
   `tests/integration/services/test_a3_failures_recovery.py`,
   function `test_local_spend_exhaustion_is_a_distinct_funds_refusal_and_settles_once`
   (ends at line ~906). After the existing denial block (the name
   `after_denial` is bound near line 874), add TWO more denial attempts in the
   `try:` (each `asyncio.wait_for(world.service.search(world.request("A",
   tag=...), attribution=..., context=...), timeout=15.0)` wrapped like the
   first refusal) and assert: both are `LimitDeniedError` with
   `refusal == "funds"` and `status_code == 402`, `_exa_pool_remaining` stays
   `Decimal("0.003")` after each, `adapter.search_calls` stays 1,
   `len(usage) == 1`, and `len(project_attempts) == 1 and len(pool_rows) == 1`
   (re-query the attempt rows after each denial). This makes "finalization
   once" exact (row uniqueness alone was ruled insufficient). Keep the
   existing assertions untouched.
2. P2 durable project ceiling after authority replacement - APPEND a test to
   the same file: `test_project_loan_ceiling_survives_authority_replacement`.
   Design (validated against the modules): spec pair A/B with base_rate=1 and
   borrow_max=2 (`limit=2000`, borrow_enabled); `world.park(False)`; serve two
   sends r1/r2 through the first authority (success expected); then
   `await world.authority.aclose()`, build a fresh `ExecutionAuthority`
   (mirroring `tests/fixtures/a3_authority.py::build_authority_world`: same
   `authority_key=AUTHORITY_KEY`, `monotonic_fn=world.monotonic.monotonic_fn`,
   `limits=` a fresh `ProviderLimitsService(world.repository.limits)` after
   `await ...initialize()`, `secret_store=world.store`) and swap
   `world.service._authority = replacement` (the seam `_AttemptSeam` reads);
   then require the r3 send to refuse with the typed ceiling denial
   (`LimitDeniedError`, `retriable` False, reasons naming
   `project:<uuid>:ceiling`) and keep `project_attempts("A") == 2` (no third
   attempt charged), `search_calls == 2`, `usage_rows == 2`. Today this will
   fail (the replacement's fresh in-memory `served` re-grants) - keep the
   failure: that is the P2 production defect to fix.
3. Run once each with a watchdog (PowerShell has no timeout cmdlet; use the
   tool call's `timeout`):
   - `uv run --no-sync pytest tests/integration/services/test_a3_failures_recovery.py -q`
   - `uv run --no-sync pytest tests/integration/services/test_a3_fair_capacity.py -q`
     (the file has never been run as a whole this round)
   - `uv run --no-sync pytest tests/integration/services/test_a3_authority_topology.py -q`
   Report new failures only; the four expected production failures above are
   already recorded.
4. A2/A9 feasibility fixture audit (do before believing any failure):
   `tests/integration/services/test_a3_fair_capacity.py` lines ~528-654
   (`test_infeasible_base_allocations_are_rejected`,
   `test_allocation_create_refuses_infeasible_base_promises`,
   `test_pool_capacity_tightening_refuses_infeasible_promises`,
   `test_zero_share_requires_the_explicit_best_effort_flag`) - confirm the
   fixtures use the REAL `PoolAllocationRepository.create` /
   `UpstreamPoolRepository.update_pool` seams and the schema's feasibility
   invariant; correct only fixture-side invalidity, never the production
   invariant.
5. Optional wire-shape completion (P11 tail): an
   `ExecutionQueueSaturated`-typed refusal (from `_PoolQueue._check_bounds`
   count/bytes bound, message "the execution queue count bound is full") over
   the real MCP->API hop. The earlier attempted variant (parked head +
   `max_queued_requests=1` + a third call) ended up refused by the DURABLE
   strict concurrency gate (429 "local concurrency cap is full") instead of
   the queue bound; to hit the queue bound deterministically, saturate the
   queue count through `_check_bounds` with `max_queued_requests=1` and make
   sure the durable gate stays at `project_max_concurrency >= 2` while the
   in-memory slot is held (parked), or use two projects whose combined demand
   trips the pool-total bound only. Do NOT force it through local-host-only
   assertions.
6. Potential follow-up (reviewer P12 tail) if time permits: the MCP
   forwarded 429 dropped its Retry-After seconds at the TOOL surface (the
   forwarder `_post` maps 429 to one static message without reading the
   header). If the ruling requires preserving Retry-After through MCP, the
   assertion would have to demand an attribute the public seam currently
   lacks - according to the brief "Do not demand invented public APIs"; leave
   this to adjudication.

## Established seams, helpers, and pitfalls (learned by runs)

- Settings: `polyweb.configuration.config` URL validator accepts plain
  http only for LOOPBACK hosts; use `https://api-authority.test` style URLs
  for the chain tests (the ASGI transport intercepts anyway). Build settings
  with `tests.fixtures.auth.test_settings(execution_authority_url=...)` and
  patch `polyweb.mcp.server.get_settings` (or import once as
  `rig_test_settings` - do NOT import `test_settings` unaliased at module
  level, pytest would collect it as a test).
- MCP tool results: `server.call_tool` returns a TUPLE `(content, payload)`
  on success and RAISES (fastmcp `ToolError`/RuntimeError) on refusal - use
  `_tool_success`/`_tool_refusal` from the routers file rather than guessing
  shapes.
- The REST app under ASGI transport does NOT run its lifespan on its own:
  enter it with `async with app.router.lifespan_context(app):` before calls
  and rely on the app's composition for `ExecutionService(host_authority
  True)` + injected adapters (create_app with `[adapter]` + `repository` +
  `secret_store` + `auth_service`).
- Timing pitfall: the MCP forwarding default timeout 1.25s becomes the
  API-side queue deadline; anything waiting in the queue longer than that
  expires. For chain tests that QUEUE work, call `forwarding_settings(...,
  forward_timeout_seconds=30.0)` (the queue-expiry test does exactly this and
  drives expiration via the allocation's `max_queue_wait_ms=1500`).
- `RecordedHop`/`RecordingApi` capture request/response BODIES (bounded
  200-4000 chars), which the queue-expiry test uses to identify WHICH call was
  refused (`"mcp-late" in hop.request_body`). The bodies contain the query and
  project id only - no secrets; do not print credential bytes.
- API-side queue peek: `app.state.execution._authority._queues[(pool_id,
  CredentialOperation.SEARCH)]._projects[project_id].pending` (sync, bounded
  polling only; same narrow-private precedent as `a3_authority`'s
  `queued_waiters`).
- Flush seam for trace assertions: `await shutdown_injected_observability(
  server)` (public mcp.server seam) before closing the repository, then read
  `trace_spans` with plain `sqlite3` (helper `_trace_root_rows`).
- Adapter registry: `polyweb.services.execution.adapter_factory` is a
  CHECKER `(name) -> builder | None`; production calls
  `build_adapter_with_secret(factory, client, secret, ...)` which invokes the
  builder as `factory(client, api_key=<SecretStr>)`. To add a synthetic
  credential, wrap the checker (see `extended_adapter_factory` inside the
  P3-bytes test) and keep the extra SECRET -> RecordingAdapter mapping with
  `parked_search_handler(world)` assigned to the extra adapter.
- Bound helpers fail with bounded messages naming the production defect - do
  not convert them into unlimited waits.
- Park handler timeouts are 10s real; the released parks live in
  `world.parks` (release() releases ALL, including dead ones - harmless).
- `uv run backlog ...` works only when invoked as plain `backlog ...` (the
  `uv run` spawn fails); no Backlog actions were taken this round.
- PowerShell lacks `&&`; the session standard is `;` or separate calls. Avoid
  Unix-only pipe tools (`tail`, `grep` exist but behave differently).

## Temporary artifacts and process cleanup

- No background processes were started by this session (all pytest runs were
  foreground and completed). No stray test databases (pytest tmp_path lives
  under the OS temp dir); no sockets/ports opened beyond the OS-assigned
  debug ports closed inside their tests (`with socket.socket()` blocks).
- This checkpoint file is the ONLY non-test artifact.

## Freezing statement

- TESTS ARE FROZEN at head `ef6b07b` (working tree). The next tester may
  append new tests per the list above but must re-verify `ruff check tests`
  before freezing again. Production remains FROZEN for the next developer
  call; the developer call 2 has NOT been started.

Checkpoint absolute path:
`C:\Sharath\Computer Programming\Programs\Python\polyweb_d1\tests\fixtures\a3_tester_handoff.md`

STOPPED AT SAFE POINT; TESTS FROZEN

# A3 tester CONTINUATION record (user-authorized resume beyond the 3 tester calls)

Written by the resumed tester call on 2026-10-30 (the user explicitly restarted
tester work from this checkpoint: "continue now, let the tester start from
where they left off"). Everything ABOVE this line is the round-3 record and
remains valid; this section is the continuation's own record. The same rules
held: tests-only edits (`tests/**` plus this authorized handoff file), zero
production/Backlog edits, no latency work, no commits, no new subagents.

## What this continuation did (checkpoint "Not done" items 1-4 + adjudications)

1. FUNDS SETTLE-ONCE strengthened (item 1) in
   `tests/integration/services/test_a3_failures_recovery.py`
   `test_local_spend_exhaustion_is_a_distinct_funds_refusal_and_settles_once`:
   after the existing denial block the test now performs TWO further denial
   sweeps (`spend-short-again`, `spend-short-last`, each bounded with
   `asyncio.wait_for(..., timeout=15.0)`) and asserts per sweep: typed
   `LimitDeniedError`, `refusal == "funds"`, `status_code == 402`,
   `_exa_pool_remaining == Decimal("0.003")`, `search_calls == 1`,
   `len(usage) == 1`, `len(project_attempts) == 1 and len(pool_rows) == 1`.
   Existing assertions untouched. RUNS GREEN against frozen production.
2. P2 DURABLE PROJECT CEILING test appended (item 2): NEW
   `test_project_loan_ceiling_survives_authority_replacement` in the same
   file. Geometry: pool limit 2000; both allocations base_rate=1,
   borrow_max=2, weight=1; `park(False)`; two sends served through the first
   authority (base then loan, exactly 2 attempts/usage/calls); `await
   world.authority.aclose()`; fresh `ExecutionAuthority` over the same
   repository with fresh initialized `ProviderLimitsService`, same
   AUTHORITY_KEY, same injected monotonic_fn; `world.service._authority`
   swapped; third send must refuse typed (`LimitDeniedError`, `refusal=="rate"`,
   429, retryable False, `LOCAL_RATE_DENIAL_CODE`) with a reason naming the
   PROJECT CEILING (`project:<id>:…:ceiling`), and charge no third send
   (attempts == 2, usage == 2, calls == 2). FAILS, by design, as P2 evidence.
   IMPORTANT adjudication update recorded below: the predicted
   "replacement re-grants a send" did NOT reproduce -- the third demand is
   instead refused DURABLY, but by the re-classified base window (see P2
   below), which is why the assertion pins the ceiling IDENTITY of the
   refusal rather than demanding an execution.
3. UNVERIFIED FILES RUN with watchdogs (item 3), final combined run
   (production frozen):
   `uv run --no-sync pytest
   tests/integration/services/test_a3_failures_recovery.py
   tests/integration/services/test_a3_fair_capacity.py
   tests/integration/routers/test_a3_mcp_authority_forwarding.py -q`
   -> 22 passed, 7 failed in ~51s (all 7 = production-defect evidence; none
   are test defects). Separately:
   `uv run --no-sync pytest tests/integration/services/test_a3_authority_topology.py -q`
   -> 4 passed, 1 failed (~8.6s; the 1 failure is the P6-style
   disabled-pool evidence below). Static: `uv run --no-sync ruff check
   tests --output-format=concise` -> All checks passed; `ruff format` (write
   mode only) applied to the three edited files; all edited files AST-parse.
4. FEASIBILITY FIXTURE AUDIT performed (item 4, reviewer P9/A2-A9): all four
   feasibility cases in `test_a3_fair_capacity.py`
   (`test_infeasible_base_allocations_are_rejected`,
   `test_allocation_create_refuses_infeasible_base_promises`,
   `test_pool_capacity_tightening_refuses_infeasible_promises`,
   `test_zero_share_requires_the_explicit_best_effort_flag`) use the REAL
   repository seams with MATCHING signatures, verified against
   `src/polyweb/persistence/pools.py` (create 639, update 684
   `_require_feasible` 794, update_pool 425, schema CHECK
   `project_pool_allocations_zero_rate_best_effort` line 184). NO fixture-side
   invalidity found; nothing corrected. Adjudication: `create` and
   `update_pool` skip `_require_feasible` => the two failures are REAL
   production defects (P9 create/tighten bypass), the update-path case and
   the schema-CHECK case genuinely pass.
5. P11 WIRE SATURATION test ADDED (optional item 5, DONE):
   `test_forwarded_call_surfaces_the_queue_saturation_with_wire_retry_after`
   in `tests/integration/routers/test_a3_mcp_authority_forwarding.py`.
   `seed_key_project_with_pool` gained one ADDITIVE kwarg
   `max_concurrency: int | None = None` (old callers unchanged). Recipe that
   actually trips the queue bound deterministically: held first forwarded
   send (parks), allocation `max_queued_requests=1` AND `max_concurrency=1`
   (the project cap makes the parked head non-dispatchable so
   `_PoolQueue._check_bounds` counting includes it), second forwarded
   call waits queued, third forwarded call is refused by the QUEUE COUNT
   BOUND. Locked wire facts: `mcp-saturated` hop is 429 with positive
   Retry-After, response body names "queue count bound is full", verified
   key rode the hop, no extra send, no usage beyond the parked send, and
   the parked and queued calls still serve after release (2 sends, 2 usage).
   RUNS GREEN against frozen production. NOTE: with max_concurrency omitted
   the third call was instead refused by the durable POOL concurrency gate
   (`pool_concurrent_cap` 429) -- a different, valid denial; the bound-trip
   needs the project cap, do not remove it.
6. P5 WAS RESHAPED (this is the continuation's largest adjudication, ordered
   by the reviewer continuation ruling). The round-3 test
   `test_canceling_a_granted_send_releases_the_concurrency_slot` DEMANDED
   that canceling an already-parked (already-dispatched) send frees durable
   concurrency so the next waiter dispatches. That demand is WRONG per the
   ruling: canceling an already-sent uncertain send must NOT automatically
   free durable concurrency merely because the task canceled. Source
   evidence backing the conservative hold:
   - `persistence/limit_repository.py` reserve_strict docstring lines
     ~2231-2239 ("only settlement or an explicit release frees a slot")
     and `_open_reserved_count` docstring ~2321-2334 (an expired-but-
     unsettled row cannot prove the upstream call never happened) plus its
     count predicate: `(state=="reserved" AND NOT dispatch_completed) OR
     (state=="finalized" AND outcome=="uncertain")` -- an uncertain-
     finalized send KEEPS holding the slot by design.
   - `services/monitoring.py` `_uncertain` ~647 records the retained debit
     ("A cancellation retains an uncertain send's debit" tracked_call
     docstring ~770-774).
   The round-3 failure was therefore adjudicated a TEST defect (over-broad
   expectation), not a production leak, and the tests now are:
   - `test_canceling_a_dispatched_send_conserves_durable_concurrency`
     (replaces the old test): cancel the parked a1 -> assert the scheduler's
     OWN in-memory slot frees (bounded condition on `queue._inflight` /
     `_inflight_pool` reaching 0; the cancel must never wedge the queue),
     the follow-up waiter is refused with the typed durable capacity denial
     (`LimitDeniedError`, `refusal=="rate"`, 429, "concurrency cap is full",
     reasons naming `concurrent_cap`), no second send
     (starts == ["a1"], search_calls == 1), the canceled attempt keeps its
     own charge (attempts == 1, usage == [], one dispatch row resolved
     "uncertain" -- read via a bounded row-settle poll because resolution is
     off the critical path). GREEN against frozen production.
   - `test_canceling_a_queued_call_never_grants_or_charges` (NEW, the
     pre-send side): cancel a call while it is still QUEUED (deterministic:
     the only slot is held by the parked a1) -> zero started sends from it,
     no attempt, no usage, no dispatch row, queue depth returns to 0
     immediately, and a follow-up call is still served. GREEN.
   REMAINING P5 GAP (documented, not testable without production seams):
   canceling a GRANTED attempt between its durable reservation and
   `record_dispatch` cannot be reproduced deterministically in-process
   (there is no await boundary a test can synchronize on between the
   scheduler granting and the queue attempt's inline reservation); the
   implementation's `_release_capacity` path for "provably never reached
   the vendor" executes on that window. If a defect lives there it needs a
   production-side hook or a contention worker to observe.

## Production-defect evidence list after this continuation (frozen, for the developer)

All 8 failures in the final combined run + topology run are real, separated,
non-flaky production-defect reproductions (run twice; stable):

- P1 fairness (2 tests, same mechanism):
  `test_pool_queue_weighted_drr_unit_shares_under_continuous_backlog`
  (unit ` _PoolQueue` isolation: first ten-start cycle served (5,5), not the
  documented 4:6) and
  `test_continuous_equal_demand_serves_documented_four_six_shares`
  (integration: same (5,5) in every asserted window). The scheduler's own
  docstring (`services/execution_authority.py` `_next_grant` lines ~374-386,
  order "B,A,B,A,B,B,A,B,A,B") documents exactly 4:6 per cycle -- the code
  contradicts its own documented bound. This corroborates the reviewer's
  "P1 fairness 20:20".
- P2 ceiling identity after authority replacement:
  `test_project_loan_ceiling_survives_authority_replacement` -- the
  replacement DENIES the over-ceiling demand (no third send: attempts ==
  2, usage == 2, calls == 2 verified), but with
  `reasons=['project:<p>:<pool>:search']` -- the durable per-project BASE
  window -- because the fresh scheduler's in-memory `served` reset to 0
  re-CLASSIFIES the demand as a base grant (`_base_grant` ->
  `state.served < policy.base_rate`). The hope the checkpoint recorded
  ("replacement re-grants a send") does NOT reproduce with base_rate=1 /
  borrow_max=2: the durable base window catches any first send through the
  replacement. The real P2 defect shape is: after restart the scheduler
  loses the loan-vs-base classification and the ceiling denies through an
  incidental window identity instead of the project ceiling. Fix direction
  makes `served` (or the loan-vs-base class) durable so the refusal names
  the project ceiling (`project:<id>:ceiling` shape); the test accepts both
  the scheduler denial and the durable loan-ceiling bucket
  (`project:<id>:<pool>:<op>:ceiling`), never the base window bucket.
- P8 takeover skips recovery (NEW, strong): rewritten
  `test_takeover_with_unresolved_work_stays_in_recovery_before_dispatch`.
  The old crash simulation (cancel the parked send) was a TEST defect: a
  cancel is an in-process outcome and resolves the attempt itself, so the
  takeover had NOTHING to recover and the run "served during recovery" for
  a wrong reason. The rewritten simulation abandons the parked send and the
  runtime exactly as a stopped process (release the lease row through the
  repository like the restart test; NO cancel, NO aclose of the service),
  closes the old SQLite connection, and reopens over the same file. Verified
  stable behaviors: the takeover DOES fence the crashed attempt uncertain
  (rows -> `uncertain` under the old token), the during-recovery send is
  served by the reopened authority (`refusal is None`, search_calls becomes
  2) -- i.e. the recovery pause DOES NOT hold. SOURCE ROOT CAUSE (direct
  read evidence, `src/polyweb/persistence/execution_authority.py`):
  `_acquire` decides the RECOVERING state from
  `if await self._mark_uncertain(authority_key=authority_key,
  ...)` (line ~309) where `authority_key` = `key =
  self.authority_key_for(pool_id)` -- the POOL-SCOPED key (services/
  execution_authority.py line ~648) -- while dispatch rows are WRITTEN with
  `authority_key = ledger_key or authority_key` = the BASE ledger key
  (persistence line ~464, `ledger_key=self._authority_key` from services
  line ~741). The two keys never match rows, `_mark_uncertain` returns
  False, the lease goes straight to ACTIVE; the pool-filtered
  `mark_pool_uncertain` (line ~413) marks rows later but its result does
  not drive the recovery state. The timeout-expiry variant is NOT usable
  in-process: a live authority keeps renewing until expiry (verified with a
  throwaway debug run: the lease's expires_at extended past the test's
  TTL), so a takeover probe must either release the fence (this test, like
  the restart test) or be a separate process.
- P9 feasibility bypass (2 tests, fixtures AUDITED and valid):
  `test_allocation_create_refuses_infeasible_base_promises` ("an allocation
  create overcommitting the pool was accepted") and
  `test_pool_capacity_tightening_refuses_infeasible_promises` ("pool
  capacity tightening accepted an overcommitted promise"). Root cause from
  the audit: `PoolAllocationRepository.create` (pools.py ~639) and
  `UpstreamPoolRepository.update_pool` (~425) never call
  `_require_feasible` (only `update`, ~706, does).
- P6 stale dispatch policy (topology file):
  `test_pool_disabled_while_queued_never_dispatches` -- the pool went
  DISABLED while a call was queued; the queued call still EXECUTED
  (both sends completed: failures==0). First direct run evidence for the
  reviewer's P6; the queued work must re-validate the pool's live
  enabled-state before granting/dispatching.
- P12 long Retry-After shortened to the 60 s ceiling:
  `test_retry_after_over_sixty_seconds_is_never_shortened` -- the requeue
  read `not_before == 60.0` for a vendor Retry-After of 90 s. First direct
  run evidence (this file never ran in round 3). The absent-header backoff
  test passing right next to it (`...uses_a_bounded_backoff`) proves the
  bounded-backoff path is intact; the defect is the header path being
  incapable of exceeding the ceiling.

Previously recorded and STILL standing for the developer (round-3 runs,
untouched files): P3 authority-wide queued count across pools and queued
bytes across pools (`test_authority_queue_count_bound_is_authority_wide_across_pools`,
`test_authority_bytes_bound_is_authority_wide_across_pools`), P4 default
queue wait unused (`_PoolQueue._wait_seconds` never applies the authority
default), and the mixed-transport/unit suites unverified this round
(deliberately untouched).

## Updated test manifest (deltas vs the round-3 manifest above)

1. `tests/fixtures/a3_authority.py` -- UNCHANGED since the round-3 freeze.
2. `tests/integration/services/test_a3_failures_recovery.py` -- funds test
   strengthened (two extra denial sweeps); NEW P2 ceiling test; takeover
   crash simulation corrected (test defect fix, time bound 1.3 s -> none,
   release-based simulation, `native_during` now read through the reopened
   repository). 10 tests: 7 pass, 3 fail (P12, P8, P2 -- production).
3. `tests/integration/services/test_a3_fair_capacity.py` -- the P5 section
   rewritten per adjudication into two tests with bounded row-settle polls;
   the old single P5 test is REPLACED (its name asserted a demand the
   ruling rejects; its useful invariants are all preserved -- in-memory
   slot free, uncertain record, no usage settle). 12 tests: 9 pass, 3 fail
   (P1 x2, P9-tighten x1 -- production).
4. `tests/integration/routers/test_a3_mcp_authority_forwarding.py` --
   `seed_key_project_with_pool` +`max_concurrency` kwarg; NEW P11 wire
   saturation test. 7 tests, ALL PASS.
5. `tests/fixtures/a3_tester_handoff.md` -- this continuation section
   (authorized handoff exception only).
6. UNTOUCHED this continuation: `tests/integration/services/
   test_a3_authority_topology.py`, `tests/integration/services/
   test_a3_bounded_queues.py`, `test_a3_mixed_transport_contention.py`,
   `tests/unit/services/test_a2_*`, and the latency suite (deferred).

## Reviewer P1-P13 coverage statement (state after the continuation)

- P1 fairness: covered and FAILING (two tests, unit + integration) -- do not
  claim fixed without both green.
- P2 nondurable absolute ceiling: covered and FAILING on the refusal
  IDENTITY (ceiling-named denial) with exact no-third-charge facts; the fix
  must make the loan-vs-base classification or served count durable.
- P3 global bounds: count and bytes covered (bounded queues file; pre-
  recorded failures stand). Unbounded waiters: not additionally probed here.
- P4 default queue wait: covered (pre-recorded failure stands).
- P5 canceled grant: reshaped per the ruling -- conservative hold LOCKED
  (green) + pre-send queued cancel (green) + the reservation-vs-dispatch
  window documented as not deterministically testable in-process. Any
  "settle on cancel" fix to the already-sent case must NOT be made: tests
  forbid automatic freeing there.
- P6 stale dispatch policy: first direct evidence recorded (topology, 1
  failing).
- P7 request deadline / end-to-end: green regression locks (P7 test in
  bounded queues pre-verified; unchanged).
- P8 takeover recovery: covered and FAILING for the right reason now, with
  the two-key source root cause above.
- P9 feasibility create/tighten: covered and FAILING (audit confirms the
  fixtures are valid, the seams skip the invariant).
- P10 MCP forwarding credential/deadline/trace: green tests exist. STATED
  LIMITATION (user-directed nuance): the P10 test proves the forwarded
  `x-trace-id` equals the TOOL CALL's root trace id (MCP root == forwarded
  hop header). It does NOT prove API-side trace CONTINUATION (the API's own
  spans sharing/following that trace id). That remaining gap stays OPEN.
- P11 collapsed forward errors: now LOCKED as green wire behavior for the
  queue-saturation shape (typed 429 + Retry-After + the wire body naming
  the count bound + the bounded tool category). The forwarder's tool-side
  CATEGORY remains shared across the saturated/expiry/rate family -- demanding
  a finer tool attribute would require a public seam that does not exist
  (left to adjudication, no invented APIs).
- P12 Retry-After: the >60 s shortening is covered and FAILING (new direct
  evidence). The absent-header backoff and the 30 s deferral remain green.
  The MCP Retry-After-at-the-tool surface remains the open optional tail
  (needs a public seam; left to adjudication).
- P13 queue wait separate from provider latency: green regression lock
  (`queue_wait_ms == 2000` exact with `latency_ms < 1500`). STATED
  LIMITATION (user-directed nuance): this single-threshold lock does not --
  and must not be claimed to -- disprove all reviewer telemetry concerns
  about full provider-timing accounting.

## Commands run this continuation (do not rerun without edits)

1. `uv run --no-sync python -c <ast parse check>` on the three edited files
   -> parsed OK.
2. `uv run --no-sync ruff check tests/integration/services/
   test_a3_failures_recovery.py tests/integration/services/
   test_a3_fair_capacity.py` -> passed (written once mid-work).
3. `uv run --no-sync pytest tests/integration/services/
   test_a3_failures_recovery.py -q` (twice: 3 failed / 7 passed, then after
   the takeover rewrite again 3 failed / 7 passed in ~20 s -- stable).
4. `uv run --no-sync pytest tests/integration/services/
   test_a3_fair_capacity.py -q` -> 4 failed, 8 passed in ~32 s
   (first whole-file run this round).
5. `uv run --no-sync pytest tests/integration/services/
   test_a3_authority_topology.py -q` -> 1 failed, 4 passed in ~8.6 s.
6. `uv run --no-sync pytest
   "tests/integration/routers/test_a3_mcp_authority_forwarding.py::test_forwarded_call_surfaces_the_queue_saturation_with_wire_retry_after"
   -q` single -> the first failure caught the durable-collision design error
   (fixed by the additive `max_concurrency` kwarg), then 1 passed.
7. `uv run --no-sync pytest tests/integration/routers/
   test_a3_mcp_authority_forwarding.py -q` -> 7 passed.
8. `uv run --no-sync pytest tests/integration/services/
   test_a3_failures_recovery.py tests/integration/services/
   test_a3_fair_capacity.py tests/integration/routers/
   test_a3_mcp_authority_forwarding.py -q` -- FIRST combined run caught a
   row-resolution race in the new queued-cancel test (raised states
   ['completed','dispatched']); fixed with a bounded settle poll inside both
   new P5 tests; SECOND combined run -> 7 failed, 22 passed in ~51 s
   (STABLE -- identical failure set and shapes to the sum of the single
   runs). Must NOT be treated as flaky: both new P5 races are synchronized.
9. `uv run --no-sync ruff check tests --output-format=concise` ->
   All checks passed. `uv run --no-sync ruff format <three files>` -> ok
   (write mode; the routers `--check` renderer panic from round 3 was not
   re-encountered because write mode was used directly).
10. NOT executed (avoid re-running unchanged files): latency suite
    (deferred to the user), behave, `tests/unit/...`, full suite,
    mixed_transport, bounded_queues (its 8/3 record stands), topology
    re-run after its (no-edit) first run.

## Cleanup statement

- All pytest runs were foreground and completed; nothing was left running.
- The single throwaway diagnosis script for the takeover question lived in
  the OS temp dir (`%TEMP%/opencode/a3_takeover_debug.py` + its scratch
  pytest tmp dir) and was DELETED after use; it never touched `tests/`.
- No commits, no PRs, no Backlog writes; production/configs/docs untouched
  (dirty shared state identical to the session start).
- This handoff file is the only non-test artifact, as before.

## Freezing statement (continuation)

- TESTS ARE FROZEN AGAIN at head `ef6b07b` (working tree, same dirty
  snapshot): ruff check tests passes; the edited files AST-parse; the
  failure set is stable across repeated runs.
- Production remains FROZEN for the next developer call (round 2, 1/3
  used). Reviewer remaining budget: 1 call (3rd). The precise P1-P9/P12/P13
  defect list above IS the developer's round-2 work list; the P5 ruling and
  the P10/P13 non-claims above bind the next claims.
- Clamp for the developer round 2: do NOT weaken or drop any green lock
  (P7/P13 locks, the conservative P5 hold test, the P11 wire saturation
  test, all A2/A9 checks); fix production against the failing set.

CONTINUATION COMPLETE; TESTS FROZEN; ORCHESTRATOR TO ASSESS COMPLETION


## Orchestrator final verification after developer call 3 (2026-10-30)

Developer and reviewer original three-call budgets are exhausted. All children
have finished. No commits or PRs. Latency remains deferred to the user.
Developer reports non-latency blocks: 2633 passed/1 skipped (unit+services),
429 passed (routers+MCP+adversarial), 424 passed (persistence), ruff/mypy clean.
These are reported results, not a substitute for the independent check below.

BLOCKER: AC2 simultaneous idle queue admission still exceeds global bounds.
Independent probe: total concurrency 1, queued count 1, queued bytes 1000;
five independent pool queues each submit a 600-byte request before any
scheduler runs. Each head is considered immediately dispatchable against the
SAME unclaimed free slot. After scheduling: inflight 1, pending 4, queued bytes
2400, refusals 0. Existing occupied-capacity tests miss this admission race.

Durable reproducer added by orchestrator:
tests/unit/services/test_execution_authority.py::test_simultaneous_idle_pools_cannot_share_one_free_dispatch_slot
Command: uv run --no-sync pytest tests/unit/services/test_execution_authority.py -q --tb=short
Result: 1 failed in 1.99s; pending 4 > bound 1. Lint and format pass for this file.
No provider I/O or DB, bounded synchronization and task cleanup.

Next correction: src/polyweb/services/execution_authority.py::_enqueue,
_would_dispatch_now, _sync_budget and _QueueBudget. Exempt a pending head from
queued accounting only when it OWNS dispatch capacity. A hypothetical free
slot cannot be exempted for every independently enqueuing pool. Ownership must
be assigned atomically before awaiting or all genuinely waiting calls counted;
preserve DRR ordering, queue-bound-zero immediate dispatch and cancellation
ownership. First run only the exact reproducer, then existing A3 count/byte,
fairness and cancellation regressions. Do not weaken the regression.

AC2 and full DoD are NOT complete. Card remains In Progress. No further
subagent calls made beyond authorized budgets. Other final production fixes
have not received an additional adversarial review; do not describe all AC
as independently verified. Latency is unverified, not passed.



# A3 TESTER EXTRA-LOOP VERIFICATION (user-authorized one extra tester call, 2026-10-30)

Written by the extra-loop tester call. Scope and rules held exactly: workspace
`C:\Sharath\Computer Programming\Programs\Python\polyweb_d1`, branch
`projects/api-layer-rewrite` head `ef6b07b` (production frozen at the
developer handoff). Tests-only edits: `tests/unit/services/
test_execution_authority.py` (manifest) and `tests/integration/services/
test_a3_bounded_queues.py` (one ordered correction), plus this authorized
checkpoint. No src/config/docs/Backlog/commit/PR/subagent actions. Latency
(`<80 ms` work/suite) remains DEFERRED and was not executed or claimed.

## What this call did

1. **Preserved the exact simultaneous idle-5-pool regression
   `test_simultaneous_idle_pools_cannot_share_one_free_dispatch_slot`
   verbatim** (imports extended in the shared header only; its body and every
   assertion byte-identical).
2. **Freeze-completed the planner boundary manifest** in
   `tests/unit/services/test_execution_authority.py`: 22 new deterministic
   items over the five loops (event/future hooks, `_settle` bounded waits,
   per-test unconditional `_reclaim`, then a zero-leak `_assert_no_ownership_leak`
   gate). No framework added; private queue/budget state used only as narrow,
   read-mostly synchronization hooks exactly where the planner allowed it.
3. **Independent adjudication of the developer's single objection
   (`test_a3_bounded_queues.py::test_queue_wait_is_reported_separately_from_
   provider_latency`)**: CONFIRMED test-precondition defect, NOT a masked
   production defect. Evidence chain read from frozen source:
   `ExecutionService._queue_policy` (services/execution.py ~1594) feeds
   `policy.pool_max_concurrency = leg.pool.max_concurrency`, and the test's
   `AuthorityPoolSpec` left that pool field `None`; each allocation declared
   only its own `max_concurrency=1`, so with A parked B was genuinely eligible
   (`budget.max_concurrency` default 100, B inflight 0 < its own cap 1,
   pool bound unchecked) and was correctly granted synchronously; `wait_queued
   ("B", 1)` therefore saw 0. The scheduler behaved correctly per the approved
   actual-grant contract. Test-only correction ordered by the brief: set
   `AuthorityPoolSpec(max_concurrency=1)` for THIS spec so the parked A send
   genuinely holds the pool's single unit; `queue_wait_ms == 2000` exact and
   `latency_ms < 1500` and every other assertion UNCHANGED. The test then
   passes, proving B's wait is real queue-backed wait, not hidden accounting.
4. Static checks (below) and the full fixed narrow verification.

## Planner case matrix -> frozen results (all PASSING locks now)

| # | Manifest case | Item | Result |
|---|---|---|---|
| 1 | Simultaneous idle 5-pool regression (1 owner, 1 pending, 600 bytes, 3 refusals) | preserved reproducer | PASS |
| 2 | Occupied global capacity: +1 waits, next refuses, owner untouched | `test_occupied_capacity_keeps_its_owner_while_a_waiter_queues_and_rest_refuse` | PASS |
| 3 | Same project, different pools: shared project count/bytes/concurrency cannot be bypassed | `test_same_project_shares_project_bounds_across_two_pools` | PASS |
| 4 | Different projects: authority totals across identities | `test_authority_totals_apply_across_project_identities` | PASS |
| 5 | Full waiting budget; independent pool still granted without waiting allowance; grants consume no waiting budget | `test_full_waiting_budget_leaves_free_capacity_for_another_pool` | PASS |
| 6 | Large `pool_max_queued_requests` cannot widen authority | `test_large_pool_override_cannot_widen_the_authority_bound` | PASS |
| 7 | Unrelated pool backlog does not consume local pool allowance (positive acceptance + own-bound refusal) | `test_unrelated_pool_backlog_never_consumes_a_pools_local_allowance` | PASS |
| 8 | Zero count bounds (project/pool/authority parameterized): actual grants admitted, real waits refused | `test_zero_waiting_count_bounds_admit_only_actual_grants[x3]` | PASS |
| 9 | Bytes 600+400 fit then +1 refused; active payload exempt | `test_queue_byte_boundary_fits_600_plus_400_and_refuses_one_more` | PASS |
| 10 | Zero-byte allowance: empty payload queues, +1 byte refuses | `test_zero_byte_allowance_queues_only_zero_payload_waiters` | PASS |
| 11 | Cancel BEFORE delivery: counters return exactly once, callback uncalled, queue healthy after | `test_canceling_a_grant_before_delivery_returns_ownership_once` | PASS |
| 12 | Cancel AFTER delivery before acceptance: grant finished once, never accepted | `test_canceling_a_delivered_grant_before_acceptance_finishes_it_once` | PASS |
| 13 | Admission callback failure (pre-first-await): full cleanup, no leaked runner, queue healthy after | `test_admission_callback_failure_returns_every_counter` | PASS |
| 14 | Preparation failure after acceptance: slot released exactly once, reusable | `test_preparation_failure_releases_the_grant_slot_exactly_once` | PASS |
| 15 | `not_before` retry: counted while sleeping, owns no capacity, unrelated progress permitted, reenters DRR; deadline still wins | `test_delayed_retry_waits_counted_then_reenters_drr_deadline_wins` | PASS |
| 16 | Cross-operation aliases: one queue/pool counters/fair order per pool; closed authority rejects immediately | `test_search_and_fetch_alias_one_queue_per_pool` | PASS |
| 17 | Best-effort grant not revoked by later guaranteed demand; guaranteed demand counted as waiting | `test_guaranteed_demand_after_a_best_effort_grant_cannot_revoke_it` | PASS |
| 18 | Shutdown: pending fails+ledger emptied (accepted unaffected) / staged unpublished finished once / delivered-unaccepted revoked once, late acceptance blocked / accepted keeps settling, closed submission rejects | `test_close_fails_pending_work...`, `test_close_finishes_a_staged_unpublished_grant_exactly_once`, `test_close_revokes_a_delivered_grant_and_blocks_late_acceptance`, `test_close_keeps_an_accepted_grant_settling_and_refuses_new_work` | PASS |
| 19 | Fairness 4:6 cycles, returning-project, blocked-project progress, zero-share policy assertions kept as-is | existing `tests/integration/services/test_a3_fair_capacity.py` (12 tests) | PASS |

## Exact commands and final results (do NOT rerun without edits)

1. Iterating (unit file only, during authoring):
   `uv run --no-sync pytest tests/unit/services/test_execution_authority.py
   -q --tb=short -x` -> fixed to converge; final state below.
2. Per-file final state (all after last edits):
   - unit: `tests/unit/services/test_execution_authority.py` -> **23 passed** (1.29s)
   - `tests/integration/services/test_a3_bounded_queues.py` -> **11 passed**
     (12.32s; was 10P/1F with the P13 precondition defect, now corrected)
   - `tests/integration/services/test_a3_fair_capacity.py` -> **12 passed**
     (25.79s)
   - `tests/integration/services/test_a3_failures_recovery.py` +
     `tests/integration/services/test_a3_authority_topology.py` ->
     **15 passed** (20.40s)
   - `tests/integration/services/test_a3_mixed_transport_contention.py` +
     `tests/integration/routers/test_a3_mcp_authority_forwarding.py` ->
     **9 passed** (16.65s)
   - `...::test_queue_wait_is_reported_separately_from_provider_latency`
     single -> 1 passed (2.02s) right after the correction.
3. ONE combined run of the planner's full fixed sequence after all edits:
   `uv run --no-sync pytest tests/unit/services/test_execution_authority.py
   tests/integration/services/test_a3_bounded_queues.py
   tests/integration/services/test_a3_fair_capacity.py
   tests/integration/services/test_a3_failures_recovery.py
   tests/integration/services/test_a3_authority_topology.py
   tests/integration/services/test_a3_mixed_transport_contention.py
   tests/integration/routers/test_a3_mcp_authority_forwarding.py -q --tb=short`
   -> **70 passed, 0 failed (73.54s)**. No watchdog-flakiness: every sync is
   event/future-based with bounded `_settle` fail-loud helpers.
4. Static (final):
   `uv run --no-sync ruff format --check tests/unit/services/
   test_execution_authority.py tests/integration/services/
   test_a3_bounded_queues.py` -> "2 files already formatted";
   `uv run --no-sync ruff check tests/unit/services/
   test_execution_authority.py tests/integration/services/
   test_a3_bounded_queues.py` -> "All checks passed!"
5. After the combined run, ONE comment-only tidy landed in the unit file;
   it was re-verified once: `tests/unit/services/
   test_execution_authority.py` -> **23 passed** (1.23s).
   No test logic changed after the combined run.

## Production-defect vs invalid-test adjudication (independent)

- **Zero new production defects found by this manifest.** Every
  ownership-boundary case in the frozen manifest PASSES against frozen
  head `ef6b07b`: actual synchronous grants, one staged grant per pool,
  all-pending waiting accounting, scoped zero/byte/count bounds, idempotent
  pending/staged/delivered/accepted cleanup, DRR + start-barrier
  preservation, and alias sharing all hold.
- **The one reported failure was adjudicated a TEST precondition defect**
  (P13 above), confirmed independently from source AND empirically
  (before/after the pool-cap correction; no assertion was weakened — the
  exact `queue_wait_ms == 2000` and provider-latency separation demands
  stand and pass).
- **Not unit-provable here (stated limitation):** the durable
  reservation/dispatch-record failure window at the attempt seam (planner
  row "reservation and dispatch-record failures") has no in-process seam in
  this unit surface; those paths remain covered by
  `tests/integration/services/test_a3_failures_recovery.py` (passing) and
  are not claimed at unit level. No durable debit assertions were made at
  unit scope.
- Durable uncertainty after send, enqueue-no-rate/native-debit, and recovery
  recording are outside this unit manifest's reachable surface (no
  repository in unit); the frozen integration files cover them.

## Budgets and next step

- Extra-loop budgets consumed: planner 1/1, developer 1/1, **tester 1/1
  (this call)**, reviewer 0/1. No further tester calls remain.
- The reviewer (read-only) follows this checkpoint, per the approved
  sequencing, against this exact frozen source+test snapshot.

## Freezing statement (extra loop)

TESTS ARE FROZEN at head `ef6b07b` (working tree). Touched this call:
`tests/unit/services/test_execution_authority.py`,
`tests/integration/services/test_a3_bounded_queues.py` (P13 pool cap only),
this checkpoint. Nothing else in `tests/**` changed; `git status` shows the
pre-existing dirty snapshot unchanged otherwise. No test processes remain
(all runs foregrounded and completed); no stray artifacts beyond this file.

EXTRA TESTER LOOP COMPLETE; TESTS FROZEN; MANIFEST ALL-GREEN AGAINST FROZEN
SOURCE; REVIEWER CALL NEXT.


## Extra-loop final orchestrator correction (2026-10-30)

Planner/developer/tester/reviewer extra calls all completed; no further agents.
Reviewer accepted the original idle-pool over-admission fix and independently
verified unchanged original regression and telemetry assertions. Reviewer found
one remaining false-saturation boundary: an accepted, started grant remained
_staged before the runner resumed, preventing another actual free slot.

Orchestrator applied the reviewer's minimal correction in _stage_next: retire
an already-started staged barrier synchronously, without finishing its grant or
releasing predecessor concurrency. Added exact deterministic regression:
tests/unit/services/test_execution_authority.py::test_started_predecessor_allows_same_pool_free_slot_before_runner_resumes
It failed before the fix with ExecutionQueueSaturated; final unit tests prove
both slots remain owned and settle independently.

A combined run exposed an intermittent returning-project burst of six instead
of the existing maximum five. The liveness escape was topping up a full weight
while another participant retained credit. Changed that escape to UNIT_COST,
consistent with its partial-quantum purpose, without changing the fairness
bounds. Added only diagnostic start-order text to the existing assertion.

Final combined fixed sequence: 71 passed in75.69sec (24ownership unit,
11bounded queues,12fairness,15recovery/topology,9mixed/forward).
ruff check src plus touched tests passes; format check3touched files passes;
mypy128source files passes; git diff --check passes. No latency work performed.

Residual nonblocking limitations from reviewer: refused distinct project IDs
retain idle project state/accounting keys; cleanup must preserve bounded DRR
remainder. Explicit attempt-seam livecheck/reservation-write/dispatch-record
failure injection is not established by generic preparation/recovery tests.
Wider mixed-wire/trace-parent evidence includes prior probes. No new production
blocker reproduced after the final correction; do not claim latency passed or
all story criteria independently proven solely from this queue test sequence.


## Final non-latency gate and handback (2026-10-30)

Completed original non-live/non-latency Behave gate once:
uv run --no-sync behave --tags="not @live and not @latency" --format progress
Result:260 scenarios passed,1failed,83skipped;1202steps passed1failed.
Exact failure observability.feature:29 duplicated one provider exception event.
Source cause: fanout call explicitly record_exception then re-raised into
ObservabilityRuntime.span which records the same exception again. Removed
only the redundant explicit try/record/re-raise in services/execution.py.
Re-ran EXACT failing scenario:1passed,6steps passed; untouched scenarios not
repeated. Do not claim the original full BDD invocation passed.
Post-fix pytest fanout/observability API files:26passed in27.94sec.
Final ruff src/touched-tests clean;4touched files format-check clean;
mypy128source files clean;diff whitespace check clean.

Queue correction verification final71passed (above) includes original
simultaneous idle race plus new accepted-start-barrier regression. Both
oversubscription and false rejection were verified; existing fairness bounds
and exact telemetry assertions retained. Rate/native accounting remains at
dispatch; no uncertain sent-work refund was introduced.

All authorized extra-loop agents completed and closed. No further agents,
commits or PRs. A3 stays open for deferred latency and recorded wider coverage
limitations. AC2 queue correction is proven by fixed boundary/integration
sequence and independent review plus final reviewer finding red/green test.
Retained-state growth and explicit attempt-seam failure injection limitations
remain recorded as nonblocking follow-up considerations, not silently fixed.
