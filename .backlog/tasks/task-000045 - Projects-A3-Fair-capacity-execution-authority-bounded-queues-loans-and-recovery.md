---
id: TASK-000045
title: >-
  Projects A3 - Fair capacity: execution authority, bounded queues, loans and
  recovery
status: Done
assignee:
  - '@codex'
created_date: '2026-10-26T09:47:00Z'
updated_date: '2026-11-09T12:32:00Z'
labels:
  - projects-first
  - step-2-api
milestone: m-2
dependencies:
  - TASK-000042
documentation:
  - doc-000003
  - doc-000005
  - doc-000002
priority: high
type: feature
ordinal: 44000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Shared pools need one dispatch authority and a fair scheduler so projects can borrow idle capacity without exceeding the pool or starving each other. It changes the same execution path as A2, so it starts after A2 merges. Design: local plan sections 7.3-7.6 (doc-000002).

Step rules and the shared Definition of Done: doc-000003. Card map and worktree rules: doc-000005. Do not start before every dependency is Done and merged into feature/project. When you start, record your own implementation plan in Backlog after researching the current code.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 One execution authority dispatches all REST and MCP work; MCP forwards with the original verified credential, deadline and trace context; an authority outage fails predictably with no direct provider bypass; a second authority for a borrowed pool fails before execution.
- [x] #2 Queues are bounded per project and in total by count, bytes, wait time and concurrency; canceled or expired queued calls never reach a provider or consume rate attempts; queue wait is reported separately from provider latency.
- [ ] #3 With loans disabled, behavior equals strict caps; with loans enabled, project A alone can reach the pool limit, A and B approach 4:6 service under continuous equal demand within a documented bound, the pool never exceeds its rate envelope, and a returning project is served without preemption or starvation.
- [ ] #4 Infeasible base allocations are rejected; a project with zero guaranteed share follows an explicit best-effort policy.
- [ ] #5 Rate exhaustion, spend exhaustion, queue saturation and invalid credentials return distinct errors; provider Retry-After is respected.
- [ ] #6 Authority restart does not restore an unsafe full rate bucket or settle native funds twice; isolation and pool limits hold under mixed REST/MCP contention.
<!-- AC:END -->

## Definition of Done
<!-- DOD:BEGIN -->
- [ ] #1 Tests of the changed layer pass, plus ruff/mypy (backend) or lint/typecheck/depcruise/knip/build (frontend) with no new findings.
- [ ] #2 Tests use fake providers and temporary databases; security assertions are rewritten to the new model, never weakened or dropped without a replacement.
- [ ] #3 No secret material (passwords, API keys, provider keys, OAuth grants) appears in responses, logs, traces or test output.
- [ ] #4 If the card changes the request path, the routing-latency check passes: FreeSearch adds under 80 ms at p95 per provider, end to end, over REST and MCP. Database read counts are a diagnostic, not a limit.
<!-- DOD:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
A3 orchestration: reuse fenced authority persistence; API hosts execution, MCP forwards credentials/deadline/trace. Implement bounded weighted DRR queues, strict/loan caps, feasible allocations, distinct failures and conservative restart. Developer edits src only; tester edits tests only; reviewer read-only. Maximum three calls per role. Verify all six AC, backend checks and REST/MCP latency before Done. Preserve A1 scope and existing task edits.

User direction: defer routing-latency optimization and final latency gate to the user. Continue all other story fixes, adversarial review and validation within existing three-call budgets. Preserve latency evidence and leave latency DoD unchecked; do not claim it passed.

Round 2 sequence: tester alone corrects fixtures/synchronization and adds regressions for reviewer P1-P13 while production stays frozen; tester freezes completed tests before developer call 2 starts. Developer then fixes all production defects against fixed tests. Final reviewer call reserved after implementation/verification; latency remains deferred.

Final correction batch: reviewer3 reproduced14 remaining production findings. Orchestrator applies independently adjudicated small fixture/lifecycle/arithmetic fixes first; then developer final3 edits production against newly frozen tests. No reviewer calls remain; orchestrator verifies final evidence without declaring unresolved AC complete.

User authorized one additional correction loop plus one planner run on 2026-10-30. Planner first settles minimal actual-capacity ownership/accounting contract for idle-pool admission race; then developer production-only implementation, tester tests-only verification, reviewer read-only adversarial check, sequenced to avoid moving targets. Preserve all prior valid invariants and regressions, no latency work or unrelated rewrite.

Extra-loop approved contract: synchronously allocate actual concurrency grant, stage at most one unstarted grant per pool, deliver asynchronously, count ALL pending/admission waiting entries. Remove hypothetical dispatchability exemptions. Atomic net admission-to-queue ownership transfer, independent authority/project/pool bounds incl zero; idempotent cleanup across callback/cancel/expiry/shutdown. Preserve DRR and start barrier, no enqueue rate/native debit, conservative uncertainty after send. Sequence developer -> tester -> reviewer with frozen handoffs.
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Orchestration correction: freeze tester round-1 test edits and finish with a fixed manifest/failure report. Developer completes production implementation against stable existing tests and static checks, then hands back. Orchestrator/reviewer adjudicate a fixed source-and-test snapshot; later corrections are batched per role to avoid chasing changing shared files.

Tester round 1 completed and tests frozen. Reported provisional failures: continuous fairness (fixture demand exceeds configured max), pool-total queue saturation (two refusals rather than one), Retry-After and missing-header retry tests (no retry), restart uncertain-row assertion, failures/recovery file hang. Latency suite unverified. Coverage gaps: MCP forwarding deadline/trace assertions, local spend exhaustion; outage test may patch unused seam. Results were collected during source edits and are not final evidence. Wait for developer handoff before read-only adversarial review of fixed snapshot; adjudicate test defects separately from production defects. Calls used: developer 1/3, tester 1/3, reviewer 0/3.

Developer round 1 completed; source and tests frozen for reviewer round 1. Developer reports ruff format/check and mypy pass, 25 targeted regression/persistence tests pass. A3 latency reportedly 214-240 ms p95, fails 80 ms gate; not waived as pre-existing. Implementation includes automatic one-retry path. Reviewer will adjudicate clock/fixture assumptions, feasibility enforcement (including create vs update), authority/fencing/recovery, true MCP forwarding and global bounds, and identify minimal production/test corrections. Calls used D1/T1/R1 after review launch.

Reviewer round 1 running (Codex GPT 6.1 Sol, High), both implementation and tests frozen. User explicitly deferred latency work; reviewer steered to remaining story correctness and coverage.

Reviewer attempt 1 failed before findings with transport error: Responses WebSocket messages must have type response.create. Retrying same Codex GPT 6.1 Sol High; this consumes reviewer call 2/3. No latency work: explicitly deferred to user. Production/tests remain frozen pending review.

Review confirmed P1 fairness 20:20; P2 nondurable absolute ceiling after restart; P3 global/project bounds across pools and unbounded waiters; P4 unused wait default; P5 canceled grant leak; P6 stale dispatch policy; P7 missing end-to-end/send deadline checks; P8 takeover skips recovery; P9 feasibility bypass on create/pool tightening; P10 topology/trace/deadline forwarding; P11 collapsed forward errors; P12 retry inconsistency; P13 queue wait included in provider latency. Tester fixture and synchronization errors adjudicated separately. Reviewer calls 2/3 including failed transport attempt; developer1/3 and tester1/3.

Tester call2 ended mid-handoff without final manifest/results. Source stayed frozen. Orchestrator found added fairness/feasibility/recovery/global-count/queued-policy regressions, but ruff reports six findings incl undefined second_rows in topology test. Real HTTP forwarding and other coverage still unfinished. Use tester final call3 to complete/freeze tests before developer call2; do not claim partial tests validated. Budgets D1/T2/R2 before final tester launch.

User requested tester stop at next safe boundary and save durable takeover progress for a replacement tester. Steered running tester call3 to preserve edits, stop its own test processes, write tests/fixtures/a3_tester_handoff.md with manifest/results/exact resume step, then freeze. No next subagent or production work authorized until user resumes. Latency remains deferred.

PAUSED at user request after tester safe-point completion. Durable checkpoint: tests/fixtures/a3_tester_handoff.md. Branch projects/api-layer-rewrite head ef6b07bcac04a0624c524a172946f3552ff01db3. Tester reports ruff check tests passes; real forwarding tests6 pass; bounded queue tests8 pass/3 fail; cancellation regression fails on durable concurrency settlement. Remaining test coverage/runs and exact resume instructions in checkpoint. Tests and production frozen; developer call2 NOT started. Budgets used D1/3 T3/3 R2/3 incl reviewer transport failure. No further test runs/edits/subagents until explicit user instruction; latency deferred. Card remains In Progress with criteria unchecked, not completed.

User explicitly resumed tester from safe-point checkpoint. Launch replacement tester with same OpenCode CommandCode GLM 5.3 Flash Max, continuation of interrupted work beyond original three tester calls at user request. Production remains frozen; developer round2 not started. Resume checkpoint next-actions only; do not repeat completed runs or latency work. Developer/reviewer remaining budgets unchanged.

Tester checkpoint continuation completed; tests frozen and handoff updated at tests/fixtures/a3_tester_handoff.md. Reports combined recovery/fairness/forwarding22 pass7 fail, topology4 pass1 fail; previous bounded8 pass3 fail retained. ruff check tests passes. Funds denial/idempotency strengthened; cancellation assertions corrected to retain durable uncertainty after send. P2 continuation reproduces base-vs-ceiling refusal identity, NOT extra dispatch in that fixture; original reviewer reproduction still separate evidence. Remaining correctness gaps include true API trace continuation, end-to-end deadline/send races, tool refusal/retry distinctions and complete provider timing. Developer round2 NOT started. Paused after tester-only resume; await user instruction for next subagent. Latency remains deferred.

User resumed full loop. Launch developer call2/3 using frozen tester continuation and full reviewer P1-P13 batch. Production editing now authorized, tests remain frozen. Final reviewer call3 reserved; developer call3 available for remaining production defects. Latency explicitly deferred. Preserve conservative uncertain concurrency; fix all AC gaps rather than only currently failing tests.

Developer call2 completed; source frozen. Reports ruff/mypy clean, unit2048 pass1skip, router/MCP414pass, integration services577pass8fail; full suite timed out98pct (not a completed pass). A3 focused44pass with3deselected. Developer disputes8 failures as invalid test/fixtures: A2 guarantees100 vs pool1 (four cases), routing zero-capacity pool invalid base100 (one), global-byte contradictory payload setup, recovery assertions after closing reopened runtime, finite fairness totals incompatible4:6. Final reviewer call3 will independently adjudicate all8 and audit P1-P13 production fixes. No latency.

Final review requests changes: repeated-acquisition recovery bypass; blocked-head/admission global budgets; delivered grant cancellation; eligible/zero-share/per-pool DRR; local ceiling stale accounting and loans toggle bucket identity; unsent deadline debit; ingress deadline coverage; concurrent/scoped feasibility; OAuth token state; real runner retry deadlock/budget503RetryAfter; upstream429mapping; trusted real trace parent/Activity; complete per-send timing. Orchestrator fixed adjudicated8 test setups (feasible A2/routing reservations, unit fairness88demand/grant release, byte700 pinned sizes/concurrency2/lifetime assertions, recovery live-resource lifetime/immediate repeated acquisition). Targeted A2/routing8pass30deselected; lint five touched files passes. Tests frozen for final developer3; no new tester/reviewer calls. Latency deferred.

Final developer3 reports unit+services2633pass1skip, routers/MCP/adversarial429pass, persistence424pass, focused85pass, ruff/mypy clean. Orchestrator independently found remaining AC2 race:5 simultaneous idle pool submissions each600bytes claim same hypothetical free concurrency slot; bound1queued/1000bytes/concurrency1 results active1/waiting4/2400bytes/refusals0. Durable reproducer tests/unit/services/test_execution_authority.py::test_simultaneous_idle_pools_cannot_share_one_free_dispatch_slot fails1in1.99sec; lint/format pass. Fix requires actual atomic dispatch ownership for exemption, not per-head hypothetical availability. Existing occupied-capacity probes miss this race. Developer/reviewer3calls exhausted, no additional agents launched. Checkpoint updated. AC2 and DoD remain incomplete, card In Progress. Latency deferred.

Extra-loop budgets authorized: planner1, developer1, tester1, reviewer1. Prior loop evidence and checkpoint preserved. Starting planner read-only (Codex GPT6.1Sol High) before any code changes.

Planner completed/reproduced original race plus pool override bypass/cross-pool overcount and callback/shutdown ownership gaps. Planner1/1 used; extra developer1/1 starts next, tester/reviewer reserved. Do not change admission lock mechanism (probe counted correctly). Exact existing reproducer assertions preserved.

Extra developer completed source-only ownership fix; exact simultaneous idle regression passes. Reports fairness12pass, recovery/topology15pass, mixed/forward9pass, A2/routing/adversarial64pass and static clean. Bounded10pass1fail: telemetry fixture expects B pending although pool has free capacity; tester to adjudicate/set actual pool concurrency1 preserving timing assertions. Source frozen; extra tester run next adds planner boundary manifest, no production edits. Extra budget P1/D1 used, T1/R1 reserved before launch.

Extra tester completed: fixed sequence70pass0fail (23unitownership,11bounded,12fairness,15recovery/topology,9mixed/forward). Original idle5pool reproducer unchanged. Corrected P13 test only by pool max_concurrency1 to create realwait; exact2000ms and provider timing assertions preserved. Added22 deterministic planner boundary items; touched test format/lint clean. Source/tests frozen; extra reviewer1/1 now starts, planner/developer/tester consumed. Latency deferred.

Extra loop complete. Reviewer independently confirmed original5pool race fixed, unchanged reproducer and telemetry assertions; found smaller false saturation after accepted grant started before runner resumed. Orchestrator applied minimal stage-barrier retirement without releasing active concurrency and added exact red/green regression. Combined run initially exposed returning-project burst6>5; liveness fallback now grants UNIT_COST instead of full quantum, keeping assertions. Final combined71pass75.69sec. Final Ruff src/touched tests, format4files, MyPy128source, diffcheck pass. BDD final gate260pass1fail83skip; exact failure observability.feature:29 duplicate provider exception fixed by removing redundant explicit recording inside auto-recording span; exact scenario rerun1pass6steps. Follow-up fanout/observability pytest26pass. Original full BDD invocation is NOT reported as pass. AC2 checked; other story claims/latency not upgraded solely from queue tests. All extra agents complete, no commits/PRs. Residual inherited idle-state retention and failure-injection coverage limits documented in checkpoint.
<!-- SECTION:NOTES:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
The queue over-admission race and completed-start-barrier false rejection are fixed. Actual synchronous grants own capacity; asynchronous delivery preserves scheduling, all pending/admission work counts once, scoped bounds and cleanup are covered. Final queue/fairness sequence71pass; follow-up fanout/observability26pass; static checks clean. Non-live/non-latency BDD gate260pass1failure; duplicate exception recording corrected and exact failing scenario passes on rerun (no claim of a subsequent full-suite pass). AC2 verified. A3 remains In Progress: latency gate explicitly deferred to user, wider recorded coverage limitations retained. Work preserved uncommitted; no further subagents started.
<!-- SECTION:FINAL_SUMMARY:END -->
