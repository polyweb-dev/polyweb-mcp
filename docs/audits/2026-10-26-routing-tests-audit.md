# Backend routing, execution, capacity, and test audit

Date: 2026-10-26. Checkout observed: `07d5e9b` (`Merge pull request #52 ... projects/pf-routing-latency`). Research fragment for the API/backend audit; no implementation or Backlog changes.

## Scope and interpretation

This fragment owns routing, execution, retries, quotas, concurrency, and backend test consolidation. A1 identity, A4 credential/OAuth administration, A5 settings/activity, and the schema receive **integration handoffs**, not a second independent redesign. No UI work is proposed. A2 and A3 are still To Do: their missing capabilities below are implementation requirements and existing-code replacement opportunities, not claims that those cards have regressed.

Priority: **P1** protects authorization, attribution, accounting, or the release gate; **P2** reduces maintenance/runtime cost or repairs misleading tests. Findings distinguish demonstrated source behavior from tests still needed. Source references use the observed checkout's line numbers.

Read: root `AGENTS.md`; backend-code-structure and backend-code-quality skills; Backlog overview, execution and finalization instructions; full PF/D1/A2/A3 cards; A1/A4/A5 acceptance criteria; shared `doc-000001` through `doc-000007`; archived P03/P04/P08 contracts and evidence. Current delivery rules and D1 supersede historical rollout/migration machinery. Historical security, exact accounting, isolation, and provider behavior remain requirements unless explicitly superseded.

`TASK-000022`, `000027`, and `000030` through `000033` are absent from this local Backlog working copy. Their detailed AC numbers cannot be verified here; the retained design is available in doc-000002 sections 7.1–7.6. Do not invent acceptance numbers for those unavailable cards. Archived files were read without editing after CLI lookup did not expose those historical records.

## RT-01 — One execution service must replace duplicated transport orchestration

**P1; A2 #1, #7; A3 #1; historical P04 #1–#3. Confirmed divergence.**

Evidence:

- `src/freesearch/routers/api.py:769` `_plan_route` and `:897` `_dispatch` own REST planning/execution; `_dispatch` loops at `:937` and advances on `ProviderOperationError` at `:961`.
- `src/freesearch/mcp/server.py:674` `_route_adapter` returns `candidates[0].adapter` at `:712`; `:715` `_search_response` and `:746` `_fetch_response` call `tracked_call` once.
- `api.py:725` `_routing_state` and `mcp/server.py:497` `_route_state` repeat batch health/quota collection, fallback reads, and error tolerance. MCP imports `_schedule_quota_refresh` from the REST router at `server.py:506` and provider-mask resolution from the control router at `:551`.
- REST's `_dispatch` docstring still describes no cross-adapter retry, although its implementation now advances on normalized provider errors. `tests/unit/routers/test_api.py:249` `test_dispatch_uses_one_candidate` raises **RuntimeError**, so it does not contradict the normalized-error fallback tests at `:419` and `:478`.
- `tests/integration/mcp/test_server.py:693` `test_mcp_single_attempt_preserves_tool_error` intentionally exercises first-attempt MCP behavior across fallback settings, using `_FailStub`; this must be reconciled by error category, not silently deleted as a duplicate.

**Minimal replacement/removal:** introduce one typed execution service in `services/execution.py` for verified context → binding plan → attempt execution → result/fusion, composed with focused typed strategy/repository/adapter contracts. REST and MCP retain parsing, status/ToolError translation, and lifecycle composition. Move the actual algorithms; an `ExecutionService` that delegates permanently to both competing old implementations would retain the duplication. Remove the duplicated planning/dispatch/state-collection branches after cutover. Put quota-refresh scheduling in a service/runtime owner so services never need a router dependency. Ranking/fusion can be deterministic methods on typed strategy objects, supported by small pure helpers; no function-only constraint is intended.

**Surviving tests and validation:** move the assertions from `test_dispatch_uses_one_candidate`, `test_dispatch_chained_fallback_on_provider_error_succeeds_second`, and `test_dispatch_chained_fallback_on_provider_error_all_fail` into shared execution tests. Preserve RuntimeError fail-fast, normalized provider-error fallback, first-only, `allow_fallback=false`, max-attempt limits, exhausted-chain terminal error, and require/prefer semantics. Keep a transport test on **each** surface for REST error mapping and MCP ToolError behavior, including the existing MCP test's raw-failure case. Add normalized-error parity for search and fetch; source asymmetry is verified, but identical requests have not been run through both transports in this audit. Preserve the fanout BDD feature's partial failure, total failure, allow-list, and no-eligible scenarios.

## RT-02 — Carry one trusted attempt identity through D1 writers

**P1; A2 #2–#4, #7; A1 #5–#7; A4 #1, #4–#5; historical P04 #1–#3 and P08 #1–#5. Planned alignment gap.**

`monitoring.py:411` `tracked_call` receives `ExecutionAttribution`, but `:491` `_admit_call` does not receive it. `models/provider_limits.py:507` `LimitCallContext` and `:520` `LimitAdmission` lack project, actor, binding, credential, upstream-pool, and logical-request identity. `persistence/limit_repository.py:1370` `_admission_values`, `:1387` `_admission_from_row`, and `:1405` `_insert_rate_attempt` therefore cannot round-trip D1 consumer attribution. D1 already added nullable `project_id`, `credential_id`, `binding_id`, `upstream_pool_id`, and `request_id` to admission/rate rows (`persistence/limit_rows.py:136` `LimitAdmissionRow`; doc-000007).

`persistence/storage.py:884` `record_usage` accepts credential/binding/pool IDs, but `monitoring.py:294` `record_response_telemetry` and `:363` `_record_failure_usage` do not pass them. Project/actor usage attribution already exists; the missing identity is the selected execution resource. Do not replace that established ownership boundary with request-body values or trace baggage.

**Minimal replacement/removal:** use one immutable Pydantic attempt contract containing the verified context/attribution, logical request ID, unique attempt ID, selected binding, credential generation, and upstream pool link. Pass it explicitly to execution, admission, settlement, telemetry, and recovery. Replace repeated provider-name/auth-mode argument reconstruction with that contract; do not create a separate loosely typed wrapper at every layer. `pool_id` currently also means a native balance identifier such as `tavily:keyed:credit`; keep that distinct from D1's UUID `upstream_pool_id`.

**Schema handoff:** D1 admissions/rate-attempt tables have **no actor_type/actor_id columns**, whereas A2 #2 requires actor attribution on every admission/rate attempt. Filling nullable D1 fields alone cannot satisfy it. Agree with the schema owner whether an immutable, durable attempt link supplies the actor for every row (including failed/denied attempts), or whether a small additive revision is necessary under doc-000003's exception rule. Do not claim those columns already exist, or attach a shared pool to an arbitrary owning project. Existing `execution_dispatches` stores actor identity, but its use and coverage cannot simply be assumed for every admission.

**Surviving tests and validation:** retain `tests/integration/routers/test_project_trace_attribution.py:132` `test_concurrent_two_project_requests_keep_full_ownership`, `tests/integration/mcp/test_trace_attribution.py:103` `test_concurrent_two_project_tool_calls_keep_full_ownership`, and the spoof/rejection tests in `tests/integration/adversarial/test_execution_scope.py`. Extend them to assert selected resource IDs and trusted actor linkage on success, failure, fallback, fanout, retries, and persistent MCP calls. These tests protect different transport/export boundaries; none is a deletion target.

## RT-03 — Provider name is not a credential, binding, or pool identity

**P1; A2 #3–#5; A4 #1, #2, #4; historical P08 #1–#5. Planned alignment gap.**

`services/routing.py:59` `select_route` indexes health/quota by adapter name and calls `:169` `_reject_duplicate_names`. Two Tavily bindings with distinct credentials still have provider name `tavily`, so the current routing input rejects precisely the multi-credential case A2 needs. `infrastructure/resilience.py:525` `_breaker` keys circuits by its provider string. `mcp/server.py:510` and `api.py:735` build state maps from provider names. Poll single-flight is keyed by `(id(repository), id(adapter))` in `monitoring.py:719` `_poll_one_quota`, but cached observations are still read through `latest_quota(adapter.name)`.

**Minimal replacement/removal:** extend the real route candidate with binding/credential identity and resolved pool links. Replace `_reject_duplicate_names`' provider-level uniqueness rule with duplicate **binding** validation; retain provider type as capability/vendor selection. Cache immutable adapters by credential ID, generation, and transport configuration; never mutate one shared adapter with project settings. Key credential failures/circuits by credential identity, rate constraints by upstream pool/bucket, and genuine provider-wide outages explicitly. Pool-sharing and credential isolation are distinct rules.

**Surviving tests and validation:** replace the provider-name-only expectation in `tests/unit/services/test_routing.py:482` `test_duplicate_adapter_names_are_rejected` with duplicate binding rejection plus two credentials of the same provider being eligible. Preserve the existing deterministic ranking, missing/unknown quota, capability filtering, and input-immutability tests in that file. Keep `tests/unit/infrastructure/test_resilience.py:427` `test_429_cooldown_is_provider_keyed` and `:576` `test_circuit_breaker_is_provider_keyed` as distinct-key isolation tests, updating their key meaning; add same-credential generation replacement and two credentials sharing one upstream pool. These assertions migrate with identity semantics; they are not discarded.

## RT-04 — A new vendor retry must receive new atomic admission

**P1; A2 #5–#6; A3 #2–#3, #5; doc-000002 §§7.1–7.2, 7.6. Confirmed call structure; runtime accounting reproduction pending.**

`tracked_call` admits once at `monitoring.py:438` and invokes the adapter at `:440`. `adapters/youcom.py:144` `search` calls `ResilientRunner.run`, while `infrastructure/resilience.py:538` `_attempt` invokes the operation repeatedly at `:558` within one admitted adapter call. Thus inner vendor retries have no fresh `tracked_call` admission. Conversely, retrying a **storage reservation** must reuse the same attempt ID, not consume twice.

**Minimal replacement/removal:** move retry scheduling/admission ownership to the shared executor, or give the runner one explicit typed attempt executor invoked for every actual upstream operation. Remove the ungated inner retry loop from the constrained execution path after this seam is in place. Avoid adding an outer retry loop while leaving SDK/runner retries active underneath. Keep error normalization, bounded backoff, jitter, and circuit-breaker mechanics in infrastructure; they do not own project authorization. A3 retries reenter the same fair scheduler and logical deadline.

**Surviving tests and validation:** preserve `tests/unit/infrastructure/test_resilience.py:156` `test_retries_each_default_retryable_status_code`, `:348` `test_retry_after_seconds_override_calculated_backoff`, `:367` `test_retry_after_http_date_resolves_against_wall_clock`, `:498` `test_retry_reevaluates_cooldown_extended_by_concurrent_429`, and `:1729` `test_runner_uses_normalized_retry_after_for_429`. The behavioral assertions move only if retry ownership moves. Keep provider-specific terminal-quota tests, especially Brave feature B15 and Tavily T18–T22. Add a fake vendor that returns 429 then success: two actual starts, two distinct attempt debits under one logical request and project, exact Retry-After, and one settlement per actual charge. Repeat a reservation write with the same attempt ID: no extra debit. Cancellation during backoff must prevent the next start.

## RT-05 — Generalize the real atomic accounting seam, not its precheck facade

**P1; A2 #5–#7; A3 #3, #6; D1 #7–#8. Planned generalization plus a confirmed provider-specific boundary.**

`services/rate_limits.py:69` `admit` explicitly decides without consuming. `services/provider_limits.py:363` `admit` performs rate/funds checks, builds a reservation, and calls the repository. `persistence/limit_repository.py:494` `reserve` rechecks only when `record.provider == "tavily"` at `:512`; `_tavily_rate_denial` (`:1643`) only examines minute reservations. This established Tavily accounting seam is valuable but is not an atomic project/shared-pool limiter for all providers/windows. `ProviderLimitsService.admit` also returns a `local_only` admission when storage is absent (`:407`); `_admit_call` skips an unsupported catalog record (`monitoring.py:503`). Constrained production execution cannot inherit these synthetic/test escape paths.

**Minimal replacement/removal:** replace the Tavily-only hard-cap recheck branch with an explicit all-applicable-constraints admission transaction for project allocation, shared pool, operation window, and funds, using the real pool links. Serialize/retry the write transaction safely and bound contention retries. Reuse exact Decimal debit logic, durable attempts, reservation IDs, and provider-specific settlement rules. Keep optimistic prechecks only when they provide useful planning/error details; do not let them authorize dispatch. Restrict no-store/unpriced synthetic behavior to explicit unconstrained test composition. Do not introduce a second in-memory counter as the authoritative limiter.

**Surviving tests and validation:** retain `tests/integration/persistence/test_limit_repository.py:398` `test_tavily_reserve_rechecks_rate_and_funds_atomically`, `:156` `test_reserve_finalize_release_exactly_once`, `:296` `test_finalize_exact_payment_is_not_an_overspend`, and `:347` `test_finalize_real_overspend_stays_visible`. Keep `tests/integration/services/test_provider_limits.py:157` `test_concurrent_rate_never_overspends`, but strengthen its permissive `status_code in (402, 429)` to the reason dictated by controlled input. Add independent SQLite connections/processes and mixed REST/MCP admission; two keys in one pool; two operations; A=4/B=6/shared=10 with B idle and with both active; idempotent same-attempt storage retry; capacity-store failure with zero vendor calls. Also race duplicate finalization: the existing exactly-once test is sequential and does not establish cross-process settlement safety. Preserve native-funds/CRD accounting separately from rate-attempt charges.

## RT-06 — Separate accounting outcomes from best-effort monitoring

**P1; A2 #2, #6; A3 #2, #6; historical P04 #1–#3. Confirmed responsibility mixture and documented cancellation tradeoff.**

`monitoring.py:411` `tracked_call` currently owns admission, vendor invocation, failure settlement, usage, health, cooldown, terminal balance updates, and quota projection. Its success path awaits accounting settlement before best-effort usage/health. Telemetry helpers deliberately swallow repository errors (`:294`, `:339`); that policy must not spread to capacity authority or settlement.

`monitoring.py:578` `_release_cancelled_admission` documents that cancellation after a vendor charge can release funds and understate committed spend until the next poll. That existing tradeoff cannot become A3's uncertain-dispatch/restart policy. A queued cancellation, definite pre-I/O failure, and an unknown upstream outcome are different lifecycle states.

**Minimal replacement/removal:** make the executor own the admission/dispatch/outcome state machine, while monitoring records a typed, sanitized outcome. Move `_admit_call`, `_finalize_failure`, and cancellation settlement out of monitoring once the executor owns their behavior. Keep independent telemetry-write failure isolation. Replace unconditional post-dispatch cancellation release with the D1 dispatch/recovery model: cancel a queued item without a rate debit; release definite pre-I/O reservations; retain uncertain rate consumption and concurrency until a supported resolution. Do not claim the provider was uncharged from a local CancelledError.

**Surviving tests and validation:** retain `tests/integration/services/test_monitoring.py:405` `test_usage_write_rejection_does_not_skip_healthy_health`, `:590` `test_adapter_failure_records_degraded_and_preserves_rest_and_mcp_errors`, `:637` `test_telemetry_failure_never_breaks_rest_request`, and the privacy tests at `:667`, `:703`. Split/replace `:1956` `test_cancelled_tracked_call_releases_admission` with explicit pre-dispatch release and post-dispatch uncertain-outcome cases, retaining its no-phantom-reservation assertion where non-dispatch is proven. Keep the D1 lease/takeover tests listed in RT-07. Validate repeated cancellation, shutdown during vendor I/O, settlement-write failure, and restart without duplicate native debit or unsafe concurrency release.

## RT-07 — Reuse D1 authority persistence; add one bounded scheduler after A2

**P1; A3 #1–#6; A2 #5–#7; D1 #3, #7. Future A3 work, not a current regression.**

`persistence/execution_authority.py:246` `ExecutionAuthorityRepository` already provides lease acquisition (`:252`), renewal (`:323`), fenced dispatch recording (`:398`), and recovery state. The inspected REST/MCP dispatch paths still invoke adapters locally; the repository is not itself a running execution authority or fair queue.

**Minimal replacement/removal:** host the concrete shared execution runtime at one authority. REST submits locally; MCP forwards with the original verified credential, deadline, and trace context, then the authority revalidates. Remove the independent MCP provider-dispatch branch in the A3 topology only after forwarding/outage behavior passes. Do not replace it with two process-local fair schedulers over one shared counter. Reuse D1 leases and dispatch records rather than inventing a second lease table. Queues, deficits, cursor, and monotonic deadlines remain in memory as doc-000007 specifies; dispatch/recovery facts remain durable.

Use one stateful scheduler class because queue order, cancellation, deficits, and in-flight ownership have a real lifecycle. Keep DRR selection/cost calculations as small pure functions. Avoid a general scheduler framework, event bus, cloud coordinator, or subclasses for every vendor. Strict A2 admission remains usable independently; loans are disabled by default.

**Surviving tests:** keep all `tests/integration/persistence/test_execution_authority.py`, especially `:133` `test_second_holder_cannot_acquire_a_live_lease`, `:149` `test_record_dispatch_requires_the_current_token_and_a_live_active_lease`, `:167` `test_takeover_after_expiry_fences_and_recovers`, `:271` `test_release_never_resolves_dispatches`, `:320` `test_resolve_dispatch_is_project_scoped`, and `:378` `test_same_holder_reacquire_starts_a_new_incarnation`. They are storage invariants, not substitutes for authority/transport tests.

**Required new validation:** virtual-time unit tests for per-project and total count/bytes/wait/concurrency bounds; expired/canceled queued items produce no provider start or rate attempt; separate queue/provider timing; bounded deficits, stable tie breaks, skip-ineligible behavior; A alone borrows to ten only when enabled; continuous equal demand approaches 4:6 within a documented service-error bound; late arrival is served without preemption/starvation. Use integration tests for second-authority refusal, stale fencing, unavailable store, provider Retry-After, shutdown, rollback clocks, and restart with unresolved attempts. Keep rate exhaustion, spend exhaustion, saturation, and invalid credentials distinct. Do not assert exact 4/6 successes in every trailing second: the DRR guarantee is dispatch service under sustained eligible demand.

## RT-08 — A concrete same-layer duplicate can be deleted

**P2; A2 #5–#7; protected Tavily T13, T18–T20 and shared security/accounting DoD. Confirmed assertion coverage.**

**Deletion target:** `tests/integration/services/test_provider_limits.py:363` `test_tavily_free_zero_denies_vendor_402_zero`.

It initializes the same Tavily service/configuration, writes a keyed Credits snapshot with remaining zero, allowance 1000 and source `vendor_402`, then expects admission status 402 and reason `credits_exhausted`.

**Existing survivor:** `tests/integration/services/test_tavily_limits.py:171` `test_funds_gate_terminal_vendor_402_denies` performs the same setup through `_snapshot` and asserts **both** those conditions plus `exc.error.retryable is False`. This is the same service/persistence boundary and the stronger assertion set. Remove only the duplicate test after confirming both run on the rewritten project/credential fixture. Expected pytest case delta: minus one, explicitly recorded.

**Keep distinct layers:** `test_pinned_second_call_after_402_denies_locally` (`test_tavily_limits.py:412`) validates the actual adapter error → terminal balance → next-call denial chain; Tavily feature T18 (`provider_limits_tavily.feature:146`), T19 (`:151`), and T20 (`:156`) validate REST, MCP, and fanout. They are not redundant with a direct service admission test and must survive.

## RT-09 — Replace weak/misleading rate tests with explicit oracles

**P2, with P1 coverage consequences; A2 #5–#6; A3 #5–#6. Confirmed test deficiencies.**

1. `tests/integration/services/test_rate_limits.py:126` `test_vendor_observation_not_double_counted` creates an observation, admits once, calls `progress`, and only asserts `isinstance(bars, list)` at `:156`. **Replace that vacuous assertion** with exact bucket identity/headroom and persisted attempts before/after a vendor observation. Keep its integration boundary. Existing survivor/oracle: `tests/unit/services/test_rate_limits.py:345` `test_local_counts_extend_vendor_without_double_count` distinguishes an old pre-observation attempt from a newer one and asserts one counted unit; strengthen the rewritten integration case to assert numeric remaining, not merely collection type. Do not delete integration coverage because the fake-backed test exists.
2. `tests/unit/services/test_rate_limits.py:390` `test_concurrent_reservations_never_overspend` is sequential: admit twice without recording, record first, admit/record third, then deny fourth. **Remove the misleading concurrency claim from its name/docstring**, retaining all assertions as a decision-versus-recording test. `test_hour_window_denies_third_attempt_with_retry_3600` (`:328`) continues to cover deterministic threshold/retry details; real atomicity remains in `test_concurrent_rate_never_overspends` and `test_tavily_reserve_rechecks_rate_and_funds_atomically`, strengthened under RT-05. No case deletion is needed.

Run both rate test files and repository race tests after rewriting; induce a deliberate duplicate-count bug and demonstrate the numeric integration oracle fails. A green sequential fake suite must never be cited as evidence of cross-process strict caps.

## RT-10 — Remove repeated boundary setup, retaining boundary cases and real races

**P2; A2 #5; historical Tavily T02–T05. Confirmed repeated setup work; speed benefit unmeasured.**

`tests/integration/services/test_provider_limits.py:308` `test_tavily_dev_bucket_mixed_ops_deny_101` makes 100 admissions; `:320` `test_tavily_prod_bucket_mixed_ops_deny_1001` makes 1,000; `:336` `test_tavily_concurrent_mixed_ops_share_bucket` preloads 99 through full service admission before racing five calls.

**Consolidation/removal targets:** replace the two duplicated dev/prod function bodies with one parameterized boundary integration test, preserving two collected cases, environment-specific limits, mixed search/fetch consumption, and denial operation. Replace the repeated full-service preload loops with a narrowly scoped fixture that bulk-seeds the exact durable attempts near the boundary. Finish with real service admissions across the last permitted/first refused boundary; do not fake the final capacity decision. The race case still races real service/repository calls. Do not expose this fixture as production API.

**Survivors:** preserve `tests/integration/services/test_tavily_limits.py:111` `test_config_apply_selects_dev_then_prod_rate` for real environment-to-catalog mapping; preserve the five-call race assertions (one winner, four 429 denials); keep end-to-end Tavily T02 at `tests/bdd/features/provider_limits_tavily.feature:13`, T03 at `:18`, T04 at `:23`, T05 at `:28`. They retain real dispatch/no-vendor-I/O and configuration contracts. Add assertions that fixture timestamps/buckets/operation units match production semantics. Measure duration before/after; do not lower published limits to make a test faster. If full-path load uncovers a unique cumulative bug, retain one explicit load test rather than several incidental setup loops.

## RT-11 — Consolidate identical cleanup plumbing, not domain test doubles

**P2; D1 #1–#2; shared DoD #2–#3. AST-confirmed duplication.**

`_unlink_with_retries` has the same AST, ignoring only docstrings/locations, in:

- `tests/integration/services/test_rate_limits.py:36`;
- `tests/integration/services/test_provider_limits.py:44`;
- `tests/integration/persistence/test_limit_repository.py:39`;
- `tests/integration/services/test_tavily_limits.py:36`.

**Minimal replacement/removal:** retain one implementation in a narrow `tests/fixtures` database-lifecycle helper and import it at all four sites; delete the four local definitions and unused imports after that change. Alternatively, first prove closing owned resources makes explicit unlink unnecessary on Windows, then rely on pytest temporary-directory cleanup. Do not delete retry handling without that evidence. Keep database paths explicit and temporary; never infer the live checkout path. Do not replace focused blocking/error adapters with a universal configurable fake merely because their names look similar.

**Surviving coverage:** every existing test in these four files remains. In particular keep `test_two_unit_hour_denies_third`, `test_window_reset_restores_capacity`, `test_concurrent_rate_never_overspends`, `test_reserve_finalize_release_exactly_once`, and `test_pinned_second_call_after_402_denies_locally`. Run the four suites repeatedly on Windows and verify close-before-cleanup, no dangling scheduler tasks, and zero leaked database handles. Collected case count stays unchanged; this removal concerns helper definitions only.

## RT-12 — Move SQLite-backed monitoring tests to the integration suite

**P2; historical P04 #1–#2; A2 #4; A5 #5; backend structure skill. Confirmed classification error.**

`tests/unit/services/test_monitoring.py:57` `repo` opens a real migrated SQLite database at `:60`. Its tests at `:123` `test_effective_quotas_batch_soft_zero`, `:214` `test_effective_quotas_batch_failures_preserve_snapshot`, and `:319` `test_concurrent_quota_poll_uses_one_network_call` are integration tests despite the path. Some cases also call `seed_execution_project` and write real usage/quota rows.

**Consolidation/removal target:** merge these tests and their required fixtures into the existing `tests/integration/services/test_monitoring.py`, then delete the old unit file only after **all** parameterized cases, titles, bodies, and assertions have moved. Keep a provenance comment/group for the old path. Retain specific fixtures if sharing would entangle independent scenarios; this is classification, not a demand for a single huge fixture. Any extracted pure quota-normalization calculation can have isolated unit tests separately.

**Surviving assertions:** soft-zero earlier/equal/later-success behavior, hard-zero protection, failure preserving the prior snapshot, repeated reads causing no extra writes, and simultaneous quota polling using one network call all remain in integration coverage. Existing telemetry failure/privacy/usage tests in the destination also remain. Record collected unit and integration totals before/after: unit decreases by exactly the relocated cases, integration increases by the same amount, total unchanged. Run both suites; relocation must not silently hide tests from the phase gate.

## RT-13 — Remove the explicitly superseded legacy-adoption BDD contract

**P2; D1 #1–#2; doc-000004 §12. Confirmed contradiction with the settled alpha contract.**

**Deletion/replacement target:** `tests/bdd/features/provider_limits.feature:12`, scenario **“B02 legacy native rows survive upgrade with one migration head.”** Its steps in `tests/bdd/features/steps/provider_limits_steps.py:180` construct legacy unversioned usage/quota tables, `:210` `step_upgrade_twice` expects adoption, and `:224` `step_rows_preserved` expects preservation. That expectation contradicts D1's explicit rejection/no-import decision; it is not a security invariant to preserve.

Replace B02's obsolete legacy-import assertion with the settled rejection contract or remove the scenario in favor of the **existing** `tests/bdd/features/database_migrations.feature:13` scenario **“A database from an older revision is rejected and left unchanged.”** Keep fresh-baseline and isolated-worktree scenarios at `:7` and `:19`. The exact feature-phrase search found only B02 consumers for the four registrations at `provider_limits_steps.py:180`, `:209`, `:223`, and `:235`; remove those B02-only step definitions after the scenario replacement. Keep any separately shared migration/fixture helpers that still have callers.

**Surviving tests:** `tests/integration/persistence/test_database_migrations.py:223` `test_exactly_one_migration_revision_is_the_alpha_baseline`, `:254` `test_upgrade_database_fresh_path_with_spaces_reaches_head`, `:316` `test_upgrade_database_is_idempotent_at_head`, `:385` `test_rejected_database_raises_reset_required_and_is_not_modified`, `:437` `test_rejected_wal_mode_database_main_file_is_byte_identical`, `:670` `test_rejection_only_opens_read_only_connections`, and `:700` `test_repository_open_targets_only_selected_worktree_database`. These protect one head, idempotent baseline creation, no modification of rejected fixtures, and worktree isolation. Run them only against their temporary fixture paths. Record one deliberately removed/superseded BDD scenario; do not restore legacy migration machinery to make B02 green.

Other service/arithmetic BDD scenarios are **not blanket deletion candidates**. Pure conversion permutations can migrate to unit tests later only with an assertion-by-assertion map; transport/security/funds/queue stories remain acceptance coverage. This audit does not provide such a complete map for all provider scenarios and therefore does not authorize deleting them.

## RT-14 — Preserve the actual latency gate and remove no diagnostic on speculation

**P1; PF #1–#6, especially #2–#4; every API card's shared DoD #4. Existing failing baseline, not attributed to this audit.**

`tests/bdd/features/routing_latency.feature:19` measures every supported provider's warm search/fetch over REST/MCP, server-added p95 under **80 ms**; Brave fetch is unsupported/N/A in the harness. PF records post-D1 p95 REST search 81–98 ms, REST fetch 86–102 ms, MCP search 107–124 ms, MCP fetch 106–126 ms, with successful requests but a failing latency gate. Those are **ticket-reported measurements**, not a run reproduced here. PF explicitly deferred optimization until schema work and then passed the gate obligation to the API cards.

`tests/integration/latency/test_routing_latency.py:478` `test_rest_search_latency` and its companion in-process mixes/reporting are diagnostic coverage; the real TCP Behave suite uses shared fixtures under `tests/fixtures/latency*.py`. `tests/integration/routers/test_api.py:326` `test_auto_route_plan_read_budget` now reports reads. Sharing fixtures across these paths is already useful consolidation; their different timing boundaries are not proof of duplicate tests.

**Minimal action:** profile the new shared execution path and remove repeated policy/state loading through a request-scoped plan where safe. Keep scope/grant/capacity checks, fresh revision handling, telemetry redaction, and crash accounting. Do not add a generic cache that authorizes stale membership/keys/grants. Keep reads as a diagnostic, not a fixed cap; do not raise 80 ms, pool REST/MCP percentiles, skip slow providers, or remove the default offline gate. No latency test deletion is recommended by this fragment.

**Validation:** rerun the same offline TCP matrix after each execution-path change, with temporary databases and instant providers; report server added/provider/client/queue timing separately. Keep live checks opt-in only (`uv run behave --tags="@live and @latency"` is the documented live command; **not run here**). Include deterministic non-blocking quota-poll tests such as `tests/integration/routers/test_api.py:191` `test_request_does_not_wait_for_quota_poll` and `tests/integration/services/test_tavily_limits.py:294` `test_held_usage_poll_adds_no_search_extract_delay`; they pin a causal property that a noisy p95 aggregate cannot replace.

## A1–A5 integration handoffs and implementation order

1. **A1 / TASK-000041:** supplies verified human/API-key principals and fixture APIs to RT-01/02/07. Protect #1–#8, especially #5–#6 persistent-call scope/revocation checks and #7 human-session execution. `services/execution_scope.py:57` currently resolves through `human_principal`; do not insert token handling ad hoc in each transport. Keep no-provider-access rejection tests and rewrite old role fixtures through the A1 owner rather than reviving admin/developer/agent storage shims.
2. **A2 / TASK-000042:** owns RT-01–RT-06. Land a transport-neutral concrete service with binding identity, trusted attempt attribution, strict atomic pool/project caps, fresh per-attempt retry admission, and fail-closed constrained storage. Protect #1–#7. Do not wait for fair borrowing to enforce strict caps.
3. **A3 / TASK-000045:** follows A2 and adds RT-07's authority, queue, DRR loans, and recovery; protect #1–#6. Reuse the executor rather than recreating its policy in the scheduler. Queued work rechecks credentials, active membership/project, grants, binding/settings revisions, and capacity immediately before dispatch.
4. **A4 / TASK-000043:** supplies stable binding/credential-generation/pool-link resolution and allocation administration. Protect #1–#5 and all archived P08 #1–#8 guarantees: explicit grants, private isolation, one shared encrypted secret, delete-wins generations, slot binding, rekey/no-leakage, and independent OAuth connections. Coordinate adapter lifetime/cache keys and credential-versus-pool failure scope with RT-02/03/05. Allocation edits may not raise system ceilings or reset consumed allowance.
5. **A5 / TASK-000044:** supplies effective settings and trace policy without introducing a second execution policy path. Protect #1–#5 and historical P03 #1–#5: revisioned inheritance, false/null/empty/reset distinctions, safe transactional copy, project-only retention, scoped reads/cursors. Copy must never copy limiter state, balances, API keys, grants, or scheduling authority. Queue wait and provider latency remain separate fields/measurements, and mandatory audit survives trace sampling.

Apply test cleanups independently where behavior is already covered, or with the owning card when contracts change. No removal above is permission to weaken isolation, leakage, terminal quota, exact Decimal, cancellation, or rate/recovery assertions. Step 2 finishes only when the complete backend suites pass; D1-era higher-layer failures are tracked baseline evidence, not permanent allowed failures.

## Evidence actually produced in this audit

- Read-only Backlog commands: `backlog instructions overview`, `task-execution`, `task-finalization`; `backlog task view TASK-000039/000040/000042/000045 --plain` (separate calls), plus A1/A4/A5; `backlog doc list --plain` and `backlog doc view doc-000001` through `doc-000007 --plain`. Historical unavailable task lookups reported “not found”; archived contracts were then read directly without mutations.
- CodeGraph was used before indexed source lookup. Queries covered dispatch/state collection, admission and serialization, rate/provider services, retry mechanics, routing identity, execution scope, D1 authority, and named tests. Its broad graph responses sometimes surfaced unrelated UI neighbors; those were not used as audit evidence. Targeted `rg -n` inventories located test titles/feature IDs and details omitted from capped graph source output; no grep-first source reconstruction or reindex was performed. Initial wildcard `rg` for `provider_limits*.feature` was rejected by Windows; the corrected `rg -g 'provider_limits*.feature' ...` inventory succeeded. A guessed `search_dispatch.feature` did not exist and was not cited as evidence.
- `.venv\Scripts\ruff.exe check --no-cache` over the eight routing/rate/provider/monitoring/scope/limit-repository/authority/resilience source files and six named rate/monitoring/limit/authority test files: **All checks passed**. This is scoped static evidence, not repository-wide type or quality qualification.
- `$env:PYTHONDONTWRITEBYTECODE = '1'` followed by `.venv\Scripts\python.exe -B -m pytest -p no:cacheprovider tests/unit/services/test_routing.py tests/unit/services/test_rate_limits.py tests/unit/infrastructure/test_resilience.py -q`: **129 passed in 1.65s** (pytest-reported duration). No dependency installation or server startup.
- Read-only Python AST comparison of the four `_unlink_with_retries` functions in RT-11: **one identical group of four**, excluding docstrings and source locations.
- Artifact QA: **14 unique finding IDs**; **34 fully qualified path:line references** checked for existing paths and in-range lines; no trailing whitespace. Additional shortened references inherit the file named in their paragraph. The exact B02 feature-phrase search confirmed only that scenario consumes its four step registrations.
- No integration/BDD/server/live-provider/latency run, full MyPy, or full-suite baseline was produced here. No claim of runtime reproduction for the admission/retry race findings. Ticket-reported D1/PF failures remain separately attributed.

After implementation, run focused tests first, then the repository's backend gates with explicitly isolated test configuration: `uv run ruff check src tests`, `uv run mypy`, `uv run pytest tests/unit`, `uv run pytest tests/integration`, and default non-live `uv run behave tests/bdd/features`. First isolate the known main()/entry-point tests that otherwise select the checkout's database, as recorded in D1; a full-suite command is not permission to read the live database. The PF offline TCP scenarios necessarily start fixture servers and are deferred to an implementation validation run authorized for that purpose.

## Inspected and excluded paths

Directly inspected source/symbol areas: `src/freesearch/routers/api.py`, `mcp/server.py`, `services/{routing,execution_scope,monitoring,rate_limits,provider_limits}.py`, `infrastructure/resilience.py`, `persistence/{limit_repository,limit_rows,storage,execution_authority}.py`, and representative real adapter retry call sites in `adapters/{youcom,firecrawl}.py`. This is a focused responsibility/contract audit, not a whole-repository dead-code proof.

Test inspection covered `tests/unit/services/{test_routing,test_rate_limits,test_monitoring}.py`, `tests/unit/routers/test_api.py`, `tests/unit/infrastructure/test_resilience.py`, `tests/integration/services/{test_provider_limits,test_rate_limits,test_tavily_limits,test_monitoring}.py`, `tests/integration/persistence/{test_limit_repository,test_execution_authority,test_database_migrations}.py`, REST routing/fanout/attribution, MCP server/attribution, adversarial execution scope, the legacy in-process latency diagnostics, root fixtures, and provider-limit/monitoring/fanout/migration/latency feature contracts and relevant steps. Source inspection of large files was symbol-focused; inventory alone is not asserted as complete line-by-line review.

Excluded: all UI changes/tests, live `freesearch.db` and its side files, `.env` contents, real secrets/credentials, installs, running application servers, external vendor verification, benchmark reproduction, and source/Backlog mutations. Provider documentation is treated as a checked-in historical contract, not a freshly verified statement of current vendor pricing. The only authored artifact for this fragment is this Markdown file; concurrent work by the other audit owner is left intact.
