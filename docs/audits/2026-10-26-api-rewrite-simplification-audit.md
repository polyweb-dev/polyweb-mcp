# API rewrite: simplification, responsibility and schema audit

Date: 2026-10-26. Audited commit: `07d5e9bbf3fe94a74f997d00c5a364f124c63b1f`, branch `projects/api-layer-rewrite`.

## 1. Scope and conclusion

This is a research and implementation handoff for **the backend/API layer only**. It does not implement the A cards, change production code, modify Backlog, or audit the UI. The user explicitly asked for logical abstractions rather than abstractions added for their own sake.

The best reduction is to remove competing authorities and obsolete compatibility paths: one principal model, one scoped authorization service, one execution workflow shared by REST and MCP, one credential-generation runtime, and one atomic admission/settlement boundary. Keep provider-specific normalization and cost semantics where they differ. Reuse the settled D1 repositories instead of building another persistence architecture beside them.

Large files are investigation targets, not proof of bloat. **The target is a strongly typed, object-oriented backend:** cohesive domain/application services, encapsulated state and invariants, typed repository/adapter contracts, dependency injection and polymorphism where behavior varies. Shared base classes and generics are valid when they express a real common contract. Small deterministic helper functions can support those objects. Neither a class nor a function is bloat merely because of its form.

Missing A-series behavior is **planned work**, not automatically a regression in the merged D1 schema. Findings distinguish existing duplication, obsolete compatibility, unconnected schema seams and new behavior required by the cards. A proposed deletion is conditional on its stated replacement and verification; no production or test deletion was made during this audit.

## 2. Requirements and precedence

The orchestrator directly read all five API cards, PF and D1 through the Backlog CLI. The implementation contract is:

- **A1 — TASK-000041:** identity, scoped RBAC, project API keys, last active administrator protection and audited lifecycle changes.
- **A2 — TASK-000042:** one project-scoped execution service, verified attribution, credential bindings and atomic strict pool/project caps.
- **A4 — TASK-000043:** multiple credentials, per-credential OAuth, private/shared ownership, grants, pools and allocation ceilings.
- **A5 — TASK-000044:** effective settings, safe copy, project trace policy/retention and project-scoped activity reads.
- **A3 — TASK-000045:** one execution authority, bounded queues, optional fair loans, distinct failures and restart recovery. It depends on A2.
- **PF — TASK-000039:** under 80 ms added routing latency at p95 for every supported provider/operation over REST and MCP with instant fake adapters. Warm search and fetch are measured separately; Brave fetch is unsupported. Database reads are diagnostic, not a pass/fail budget.
- **D1 — TASK-000040:** one `0001_alpha_baseline`, settled ownership and repositories, rejection of other database revisions, no role/superuser columns and no duplicate pool balance storage.

Read `doc-000003` and `doc-000005` first when implementing. They replace the old phase delivery order; D1 permits A1/A2/A4/A5 to proceed against its merged schema, and A3 follows A2. Each card owns its services, router and MCP modules; `routers/api.py` and `mcp/server.py` should become registration/composition files. A1 owns authentication/principals and fixtures. The schema is settled: an additive migration is an exception coordinated by the integration owner, not a default refactoring tool.

`doc-000001`, `doc-000002`, `doc-000004` and D1's `doc-000007` supply design and verification details. `doc-000006` and archived cards are historical evidence; their old table counts, migration heads, role bridges and phase ordering are not instructions to recreate obsolete compatibility.

### Historical behavior that must survive

Archived cards P00 (`TASK-000017`), P01 (`000018`), P02 (`000019`), P03 (`000020`), P04 (`000021`) and P08 (`000024`) were checked for their acceptance criteria. Retain these semantics:

1. One internal installation account; stable human UUIDs and local/WorkOS identity constraints, without implementing cloud login or WorkOS workflows.
2. Deny-by-default, common scoped RBAC; an explicit system administrator assignment confers no implicit project-content membership. Project creation and first active administrator are atomic; concurrent demotion, removal and account deactivation retain an active human administrator through API and CLI paths.
3. Immutable verified project context; settings provenance, revision conflict detection, cross-process invalidation and the distinction among omitted, false, null, empty and reset-to-inherit.
4. Trusted attribution on usage and root/child/fanout spans; system security events remain system-scoped.
5. Multiple labelled credentials; private isolation, explicit system grants and one shared ciphertext; generation compare-and-set and delete-wins tombstones.
6. P08 also added **slot-bound encryption and master-key rotation**: moved ciphertext must fail authentication, envelopes carry a key ID, retired keys can decrypt during operator rekey, and rekey must not print secrets. Do not remove this while removing obsolete provider singleton dispatch.
7. Preserve provider-native request options and precedence, strict validation of unknown fields, normalized results/content, optional provider metadata, bounded content, unsupported-operation rejection and failure redaction. `PROVIDER_API.md` describes those useful contracts, but its anonymous-execution paragraph is superseded by A1/A2.
8. Preserve priority/preference/pinning/fallback and fanout fusion, partial failures, deterministic ranking/deduplication, per-attempt rate units, exact Decimal native-funds/CRD accounting, truthful unknown/stale balances, provider Retry-After and bounded retry/circuit behavior.
9. Preserve human session security: public registration cannot grant privileges; JWT/session validation, refresh rotation/replay revocation, browser-origin/cookie restrictions, login throttling, body caps and sanitized errors remain valuable when legacy account roles disappear.
10. Preserve encrypted-vault confinement, secret-free logs/responses/traces, client header isolation, transport ownership and shutdown cleanup; temporary databases and fake providers remain mandatory for ordinary tests.

Deliberately superseded behavior includes old database adoption/import/backfill, global admin/developer/agent account classifications, anonymous downstream execution, account-only visibility of project traces and provider-name singleton credentials. Upstream **keyless provider access is different from anonymous FreeSearch access**: retain supported keyless rails behind authenticated, scoped execution and applicable shared pools.

Do not treat the old P03 preview-until-release acceptance wording as authority to keep an alternate anonymous/global execution workflow permanently. Preserve the coordinated release gate; remove preview branches only when their remaining callers and the new API contract have been accounted for.

## 3. Evidence and limitations

The initial checkout was clean. CodeGraph was used before indexed source exploration; targeted direct reads filled omitted symbol ranges. The audit inventories all backend Python files and test areas, with deeper source/call-path inspection of the execution, identity, settings, credentials, accounting and infrastructure seams. Detailed specialist findings are in the companion reports linked below. This is a broad architectural audit, not a claim that every branch of every provider SDK was executed.

Inventory at the audited commit, counting physical lines including comments/blanks:

- `src/freesearch`: **101 Python files, 43,591 lines**. Adapters: 6,772; services: 9,520; persistence: 11,596; routers: 4,444; MCP: 1,238; models: 4,463; infrastructure: 3,356; configuration: 1,781; CLI: 390; package root: 31.
- `tests`: **218 Python files, 91,516 lines**. These are source sizes, not collected test-case counts.
- Backend Gherkin: **29 feature files, 214 Scenario definitions and 17 Scenario Outline definitions**. Outline rows and tags change executable counts; do not quote these as executed cases.
- AST comparison found a few exact function-body clones. It excluded decorators and therefore cannot establish test redundancy by itself. A simple upward-import scan found no services/persistence/models/infrastructure imports of routers/MCP; this limited result does not prove every architecture boundary.

Checks performed by the orchestrator:

```text
uv run --no-sync ruff check src tests
  All checks passed.
uv run --no-sync mypy
  Success: no issues found in 102 source files.
backlog doctor
  No duplicate IDs, self-referential dependencies or dependency cycles.
```

Four adapter test functions, including all their parameters, were run: **12 passed**. The two Tavily service tests proposed as duplicate/survivor in RT-08 also ran against their explicit temporary-database fixtures: **2 passed**. The routing specialist ran routing, rate and resilience unit suites: **129 passed**. These are separate focused runs, not a full-suite qualification. A fake-only Firecrawl constructor/cost probe confirmed the SDK-double-dependent pricing behavior described in ARCH-02. No live provider, live database or credential was used.

The formatting-only check `uv run --no-sync ruff format --check src tests` reports four existing unformatted files: `persistence/limit_repository.py`, `routers/control.py`, `services/provider_limits.py` and `services/rate_limits.py`; 315 files are already formatted. No formatting was applied. Ruff lint and MyPy passing does not mean the formatting gate is clean.

The full backend suites and live PF checks were not rerun for this documentation audit. PF's latest **recorded**, post-D1 baseline has 1,050 successful offline requests but a failing latency gate: REST search p95 81–98 ms, REST fetch 86–102 ms, MCP search 107–124 ms and MCP fetch 106–126 ms. Those are ticket evidence, not measurements from this audit. The PF card remains In Progress with criterion 2 unchecked.

D1's recorded full-suite result was 3,047 passed, 23 failed and 6 errors, including known obsolete-role fixture failures and five `main()` tests that select the checkout database. This is historical evidence; do not report it as the current run or use it to excuse new failures. Step 2 ends only when all backend tests pass.

## 4. Minimum coherent structure

The following responsibilities should be expressed through cohesive typed objects and their contracts. Reuse the named existing modules where suitable. One class may own a coherent lifecycle; split classes when their responsibilities, dependencies or reasons to change differ. A separate file or interface for every helper is not required.

### 4.1 Authentication and authorization

Authentication verifies a human session or an opaque project API key and produces one immutable discriminated principal. The common RBAC service resolves current scoped authority. A verified `ProjectContext` is explicit input to project work, not an optional filter and not trusted trace baggage.

Keep the existing human password/session machinery. Remove role-derived account privileges from the public and runtime contracts. If the authentication library requires a compatibility property, isolate it in the library adapter and derive it from the common RBAC service; it must not reappear as a general authority source or response field.

Key lifecycle owns entropy, prefix/verifier handling, constant-time verification, expiry/default/null semantics, rotation overlap and scoped audit events. This deserves a focused service because it owns secret lifetime and authorization, not a generic CRUD controller. Persistent MCP calls revalidate credentials and scope on every execution; after queue wait, dispatch checks current permissions again.

### 4.2 Shared execution workflow

REST and MCP parse their transport envelopes and call the same `execute_search(context, request, deadline)` / `execute_fetch(...)` workflow. A typed request/plan can carry credential/binding/pool identity and correlation/attempt IDs without duplicating them in loosely typed dictionaries.

The shared execution service owns binding resolution, route planning, fanout/fallback, attempt lifecycle and result fusion through typed collaborators. Route selection and fusion can be strategy objects with deterministic methods, with small pure helpers underneath. Separate implementations or a common base are useful when search/fetch policies actually vary; share their common attempt lifecycle rather than duplicating it in both hierarchies.

Scope and caller selection are checked before routing/provider access. A2 introduces one shared service but does **not**, by itself, make independent processes a fair scheduler. A3 adds a single dispatch authority and bounded per-project queues; MCP forwards to that authority with the original credential, deadline and trace context, with no direct-provider outage bypass.

### 4.3 Credential runtime and vendor adapters

Distinguish provider type, credential instance, grant, binding and upstream pool. They are real identities with different ownership. Cache adapter/client state by credential ID, generation and relevant transport configuration. Do not mutate a global provider adapter for each project or place secret values in a cache key.

`ProviderAdapter` is a justified external boundary: eight vendors implement the same search/fetch/cost surface with materially different payloads. Keep vendor mapping and normalization there. A registry can construct a credentialed adapter with explicit injected secrets; it does not select project permissions or own capacity.

Credential runtime owns generation invalidation, closing retired adapters and shared-client lifetime. OAuth lifecycle is keyed by credential identity/generation, with stale-flow/refresh fences. Neither a provider-name singleton nor a generic multi-purpose resource manager expresses that lifecycle correctly.

### 4.4 Capacity and accounting

Keep rate attempts, native funds reservations/finalization, project spend and concurrency distinct. One atomic repository operation checks/debits all applicable pool/project constraints immediately before an actual vendor attempt. Reservation retries reuse their attempt ID; a new vendor retry gets a new one and reenters the scheduler in A3. Uncertain receipt retains the rate debit; native-funds settlement remains idempotent.

Reuse established exact-amount and transaction code. Extend it with D1 attribution and pool identities. Avoid a second cache of authoritative balances or a second independent limiter for MCP. The fair scheduler chooses eligible order; the atomic store still enforces hard limits. These responsibilities should cooperate rather than each implementing reservation rules.

### 4.5 Settings, telemetry and jobs

One settings resolver owns typed inheritance/provenance/revisions; transactional copy uses an explicit allowlist of copyable configuration. A general object copier over persisted rows would be a dangerous abstraction.

Trace/usage read services require project scope in their signatures and opaque cursors. Mandatory security audit uses the scoped audit repositories independently of optional trace sampling. Retention selects one project and data class per run. Keep shared-pool facts and system audit separate from project payload access.

Monitoring should record outcomes and build projections. It should not remain the accidental owner of vendor dispatch, admission, settlement, health mutation and every provider-specific quota policy. Extract only the execution/attempt responsibilities that create competing authority; keep coherent telemetry helpers together.

### 4.6 Principles for useful typed OOP abstractions

- **Use typed contracts at architectural boundaries.** Define focused `Protocol` or abstract-base contracts for repositories, credential verification, provider adapters, admission and execution strategies where consumers need substitution or dependency inversion. Use Pydantic models/value objects and explicit enums/unions for data and state transitions; avoid untyped dictionaries as the internal domain API.
- **Use base classes and generics for genuine common behavior.** A typed repository base can share session access, mapping or optimistic-write mechanics; a service base can share a coherent lifecycle. Keep domain operations explicit. A generic `get(id)` must not bypass a project-scoped contract, and an optional `project_id=None` must not silently grant installation-wide access. A shared base should strengthen these guarantees rather than erase them.
- **Prefer composition when responsibilities vary independently.** Execution can compose authorization, a routing strategy, a credential runtime and admission. Inheritance is appropriate where implementations are substitutable under the same behavioral contract; avoid a base service that accumulates unrelated auth, serialization, vendor and persistence hooks merely because multiple services use them.
- **Judge delegation by its architectural purpose, not its line count.** A one-line method may provide a stable typed application boundary, hide persistence details or permit substitution. Keep it when that purpose is clear. Collapse forwarding layers only when they expose the same contract and dependencies without an ownership or dependency-direction benefit.
- **Encapsulate algorithms in cohesive objects when that clarifies ownership or variation.** Routing, credit calculation and result fusion may use typed policy/strategy objects. Their methods should remain deterministic where possible; private functions or static helpers are compatible with OOP. Avoid deep inheritance for an algorithm whose behavior does not vary, not classes as a category.
- **Keep deployment scope separate from programming style.** The initial single-authority topology does not require Redis/Kafka or cloud/SSO workflows. Such infrastructure is neither required nor forbidden by OOP; it needs a requirement from the cards. Preserve narrow extension seams without implementing deferred systems.
- **Remove competing models and authorities.** Converge old/target principals, settings and credentials after caller cutover. Share stable vendor mechanics through a base class or composed collaborator when appropriate, while retaining vendor-specific semantics and readable call paths.

### 4.7 Suggested typed object boundaries

These are proposed responsibilities/interfaces, not claims that these exact classes already exist or a requirement to introduce a new class for each line:

- An `ExecutionService` composes typed authorization, routing, credential and admission dependencies and owns the request/attempt lifecycle used by REST and MCP.
- A credential-verification contract returns a discriminated verified principal; the scoped authorization service returns an immutable `ProjectContext`. Neither transport implements its own role policy.
- A routing-strategy contract consumes typed candidate/health/capacity inputs and returns a typed execution plan. Provider adapters implement the shared vendor-operation contract.
- An admission contract owns atomic reservation/finalization semantics through a scoped repository; a transaction runner or unit-of-work object owns session/commit/rollback lifetime where shared mutation mechanics justify it.
- Focused project, credential, settings and activity repositories expose explicitly scoped operations. A generic base can implement common mechanics without becoming a public cross-project CRUD escape hatch.
- A credential runtime and an execution authority/scheduler encapsulate their actual mutable caches, generations, queues and lifecycle. Typed calculation/fusion policies can be composed where their variation or ownership warrants a separate contract.

This is the OOP restructuring goal. The reductions proposed below remove duplicate implementations and unsafe boundaries while preserving or improving typed encapsulation; they do not impose a function-first architecture.

## 5. Additional verified adapter and test findings

### ARCH-01 — P1: singleton construction and compatibility re-exports obstruct credential ownership

**Evidence:** `adapters/registry.py:1–10` documents construction shared by REST/MCP but compatibility re-export through `mcp.server`; `:71–115` constructs one adapter per provider config, relies on constructor credential lookup described in its docstring, catches every construction exception and continues. Current adapters such as Parallel (`parallel.py:134–146`) require explicit keys. These responsibilities no longer line up with A2/A4's credential-instance runtime.

**Action:** retain a small provider-type constructor map; change its input to explicit credential material plus safe runtime configuration supplied by the credential service. The A2 runtime selects binding/credential identities and owns generations. Delete provider-name bulk construction and MCP re-export/patch compatibility after REST/MCP and their fixtures use the canonical registry. Do not add a registry interface solely to mock dictionary lookup. Replace broad catch-and-skip with typed missing/invalid-credential outcomes and sanitized diagnostics for actual construction failures.

**Protected contract:** A2.1/.3/.4/.7, A4.1/.4/.5; P08 private/shared isolation; keyless supported rails and independent operation enablement. Validate two same-provider credentials, grant removal, rotation, typed construction failure, old-generation cleanup and shared client ownership. A constructor dictionary remaining after this change is useful, not bloat.

### ARCH-02 — P1: Firecrawl runtime behavior depends on the type of a test double

**Evidence:** `adapters/firecrawl.py:243–245` sets `_supports_credit_quota = sdk_client is None or type(sdk_client) is object` to accommodate legacy injected doubles. `capabilities:285`, `estimate_cost:650`, `usage_snapshot:748` and `quota_after_error:846` branch on it. The estimate path returns zero with "pricing unavailable on legacy SDK surface". `tests/unit/adapters/test_firecrawl.py:1730–1734` explicitly preserves this legacy fake behavior.

**Reproduced without network:** for the same `SearchRequest(limit=10)`, explicit fake key and HTTP MockTransport, an ordinary injected SDK instance reports `quota=False`, cost `0 credits`; an injected `object()` reports `quota=True`, cost `2 CREDIT`.

**Action:** update fake SDKs to the supported SDK contract, then remove this type-based capability/pricing branch. Where a quota transport genuinely differs, inject the narrow transport/capability explicitly rather than infer it from a Python test object. Cost estimates must come from request/vendor semantics regardless of SDK injection. Preserve real missing-key handling and caller-owned versus adapter-owned SDK cleanup; those are distinct invariants.

**Protected contract:** A2.5/.7, A4.4, historical exact cost/admission and no-network test isolation. Rewrite `test_usage_snapshot_missing_key_or_unsupported_returns_none`'s legacy-fake portion, retain the missing-key part, and prove fake/real-shaped SDKs produce identical cost/capabilities for identical configuration. Do not weaken admission expectations to keep the old fake passing.

### ARCH-03 — P2: share exact adapter mechanics with functions; preserve vendor parsers

**Evidence:** AST-identical `_error` bodies exist in Brave `:839`, Firecrawl `:913`, Keenable `:684`, Tinyfish `:507` and You.com `:339`. Exa `:747` and Tavily `:959` share the extended form with safe details. Identical `_parse_error_record(index)` bodies exist in Brave `:95`, Keenable `:92`, Parallel `:117`, Tinyfish `:50` and You.com `:56`.

**Action:** consolidate the two shared mechanics: normalized safe provider-error construction and malformed-item index records. They can be protected methods on the existing adapter base or a small typed collaborator; helper functions are also suitable implementation details. Choose based on the common adapter contract and dependencies, without adding a separate inheritance level just for two methods. Retain `ProviderOperationError` sanitization and `raise ... from None` at vendor catches. Remove repeated bodies after callers migrate.

Do not merge all `_http_error`, quota parsing, SDK model conversion, URL comparison or response normalization into one generic decoder: their semantics differ. In particular, search fusion canonicalization deliberately strips tracking and normalizes URLs, whereas fetch-response matching in `_youcom_support.py:178` preserves path/query/fragment significance. Similar-looking URL code is not sufficient deletion evidence.

**Protected contract:** A4.5 and shared DoD secret confinement; partial malformed-item filtering, result cap after filtering and useful vendor metadata. Existing adapter tests should continue proving vendor-specific behavior; helper tests alone do not prove it.

### ARCH-04 — P2: consolidate identical test machinery without deleting input coverage

**Brave:** `tests/unit/adapters/test_brave.py:401–414::test_search_rejects_malformed_payloads` and `test_brave_edges.py:83–105::test_malformed_results_and_page_age_map_to_invalid_response` have identical bodies but cover **different** payloads. The first has `{}` and `{"web": {}}`; the second has `web=[]`, `web="not-a-mapping"` and `results="not-a-list"`. Both assert `invalid_response`, nonretryable and no exception cause. The helpers also duplicate representative payloads and HTTP-client setup.

**Action:** one named malformed-envelope parameter matrix containing all **five** cases and a common Brave fixture. Preserve contaminated caller headers in the helper, so transport isolation coverage remains possible. Delete the second function only after its three inputs and assertions move to the surviving matrix. Do not delete `test_brave_edges.py` wholesale: sparse defaults, numeric page-age, fetch no-I/O and other cases are distinct.

**Firecrawl:** `test_firecrawl.py:1171::test_search_non_numeric_or_negative_credits_raise_invalid_response` has four inputs (`"1"`, `True`, `-1`, `-0.5`); `:1188::test_search_non_finite_credits_raise_invalid_response` has three (`NaN`, positive/negative infinity), with the same execution/assertion body.

**Action:** one seven-case invalid-credit matrix using explicit case IDs. Delete the duplicate function only after moving all three nonfinite inputs. Retain `:1202::test_search_fractional_credits_are_preserved_exactly` and `:1217::test_search_zero_credits_are_a_valid_usage_event`: valid fractional/zero behavior is not redundant with rejection tests.

**Verification run:** these four functions produced **12 passing cases**. A pure consolidation must still collect and pass 12 corresponding cases. This removes two repeated function bodies and duplicate setup, not acceptance coverage. It is a small, proven maintenance reduction, not a justification for a numerical test-removal target.

### ARCH-05 — P1/P2: include background sync and manual anchors in the identity cutover

**Evidence:** `services/limits_sync.py:112::sync_provider` selects by provider name, `_adapter_for:265` returns the first matching adapter, and `_credential_generation:271` takes the maximum generation across that provider's pools. Local failure/throttle dictionaries at `:77–78` also use provider strings. With multiple credentials, a provider name and maximum generation do not identify the selected credential/pool. `services/manual_quota.py:32::manual_quota_key` stores `manual_quota:<provider>`; its read/write/clear operations at `:59/:84/:100` therefore express one provider-wide anchor.

**Action:** carry resolved credential/generation/pool identity into sync jobs, claims, completion CAS and local caches, using the actual upstream polling boundary. A pool shared by credentials must not be polled/debited as independent balances, while unrelated credentials must not suppress one another's legitimate refresh. Reuse `LimitSyncService`'s lease, cadence, stale-result and backoff logic; avoid a second worker framework. Replace provider-wide manual-anchor selection with an explicit permitted pool/credential observation operation where the vendor/account boundary requires it. Keep manual input clearly estimated and separate from project allocation authority; never copy it as part of project settings or duplicate its balance per binding.

**Preserve/verify:** A2.4/.5, A4.1/.3/.5 and A5.2. Preserve `tests/integration/services/test_limits_sync.py`'s stale-generation, same-owner active-claim, two-scheduler single-winner, cadence, failure-keeps-balance and old-poll-cannot-replace-terminal cases; add two same-provider credentials, generation rotation during a poll, and one shared pool. Retain `tests/integration/routers/test_manual_quota.py` and the manual-quota BDD flow's exact arithmetic, clearing and estimated provenance with the new resource scope. These are future verification gates; these suites were inspected selectively and not run in this audit.

`services/credit_units.py` is a useful deterministic calculation boundary: unknown prices remain unknown (`native_to_crd:63`), confirmed charges stay exact (`priced_crd_debit:73`) and shared views count a native pool once (`project_shared_crd_views:234`, `shared_pool_funds:251`). Preserve that behavior and `tests/unit/services/test_credit_units.py`'s exact/unknown/zero/shared-pool cases. A typed credit-calculation policy may encapsulate these operations as part of the OOP restructuring; no behavior deletion is justified. Likewise, preserve `services/aggregation.py`'s fusion/URL logic and distinct ranking/deduplication assertions under the chosen typed fusion boundary.

## 6. Priority inventory and one schema exception to resolve

This is the consolidated index of specialist findings. Follow the linked reports for exact test IDs and extended evidence. **P1** means resolve with the owning A card before enabling its path; **P2** means consolidate within the card; **P3** is optional cleanup after the invariant work. These are audit priorities, not Backlog status changes.

### 6.1 P1: unify the execution and accounting authority — RT-01 through RT-07

`routers/api.py:769::_plan_route` / `:897::_dispatch` and `mcp/server.py:674::_route_adapter` / `:715::_search_response` independently orchestrate execution. REST advances through candidates for normalized provider errors; MCP selects `candidates[0]`. Replace both with A2's concrete shared service, retaining transport error translation and explicit policy tests for normalized errors versus unexpected failures. Move state gathering and quota scheduling out of router imports.

`services/routing.py:169::_reject_duplicate_names` rejects two credentials with the same provider type; `resilience.py:525::_breaker` keys by provider string. Replace provider-name runtime uniqueness with binding/credential/generation identity, and rate/balance identity with real upstream pool links. Preserve genuine provider-wide facts explicitly.

`monitoring.py:411::tracked_call` admits once around an adapter whose `ResilientRunner._attempt:538` may start the vendor multiple times. Move admission into each actual attempt and reenter A3's scheduler for retries. `limit_repository.py:494::reserve` currently rechecks atomic caps only through a Tavily-specific branch; generalize that actual transaction to every applicable pool/project/window constraint instead of putting another precheck in front of it. No-store synthetic admission must not authorize constrained production calls.

Move admission/dispatch/settlement/cancellation state ownership out of monitoring; keep best-effort telemetry failure isolation. A local cancellation after dispatch does not prove the vendor was uncharged. A3 must use D1's fenced authority and dispatch records, bounded in-memory queues and conservative unresolved-work recovery, rather than two process-local fair queues or automatic funds/concurrency release.

**Deletion gate:** shared-service parity, fresh retry charges, atomic mixed-process strict caps and cancellation/recovery tests pass; then delete both old orchestration branches and the ungated retry/cancellation paths. Preserve exact native/CRD behavior and vendor Retry-After. See RT-01–RT-07 and RT-14.

### 6.2 P1: actor attribution is not fully represented by D1 admission columns — RT-02

**Verified schema gap:** `persistence/limit_rows.py:136::LimitAdmissionRow` and `:185::RateAttemptRow` have `project_id`, `credential_id`, `binding_id`, `upstream_pool_id` and `request_id`, but **no `actor_type` or `actor_id` columns**. Their writers at `limit_repository.py:1370::_admission_values` / `:1405::_insert_rate_attempt` also omit the available consumer fields. `LimitCallContext`/`LimitAdmission` lack the selected resource identities. Usage already has actor ownership but its current telemetry calls omit credential/binding/pool identity.

A2.2 explicitly requires verified project and actor on admissions/rate attempts. Merely populating D1's nullable fields cannot establish actor attribution. D1's `execution_dispatches` contains actor identity, but a dispatch-only record does not automatically cover every admission, denied attempt or failed/pre-dispatch reservation.

**Recommended resolution:** have the integration/schema owner approve the smallest additive revision adding durable actor snapshots to admission/rate-attempt records, with the corresponding ORM/validation/serialization tests. This is simpler than inventing a second general attempt-entity subsystem solely to avoid four columns. If the owner instead chooses a normalized durable attempt link, prove an immutable, mandatory, retained actor relationship exists for **every applicable record**, including failures, before declaring A2.2 met. Do not infer the actor from a mutable key creator or request baggage.

This is a concrete exception to the settled-schema rule, not a recommendation to rebaseline or add compatibility migration chains. Coordinate the decision before A2 writers are implemented; record it through Backlog and the schema document. Preserve attribution after account removal according to the accepted tombstone/snapshot policy. No schema change was made in this audit.

### 6.3 P1: finish identity and live credential checks — API-01, API-02, API-05, SUP-01, SUP-07

Remove legacy `UserRole`/role/superuser wire contracts and duplicate target/current human models in `models/users.py`, `models/projects.py`, `routers/auth.py`, `services/users.py`, `persistence/users.py` and the user CLI. Reuse the common RBAC and human session machinery. D1's API-key repository exists; durable verification/lifecycle and human-or-machine execution integration are still needed. `execution_scope.py:57` accepts only the legacy human principal, and MCP's current optional/required human-token helpers are not a project-key verifier.

`services/credentials.py:570::resolve_for_project` advertises a live check but uses `context.allows` at `:590`; it reloads credential/grant/project state, not current actor authority. No production caller/exploit was established. Before A2 consumes this seam, choose one explicit final-dispatch authorization contract and enforce it. Stale contexts/adapter caches must not authorize a removed member, revoked key or canceled OAuth flow. Replace old auth fixtures with least-privilege assignments; do not simply promote every former developer to system administrator.

**Deletion gate:** all A1 lifecycle/persistent-MCP and last-admin assertions have scoped replacements, human refresh security remains intact and queued work rechecks actor/grant status before provider access.

### 6.4 P1: use the existing credential/OAuth schema; remove the singleton system — API-04, API-06

`routers/control.py:201::put_secret` / `:229::delete_secret` manage provider-name slots beside `CredentialService`'s labelled generation slots. `services/parallel_oauth.py:120` defines fixed slots; `:588::_load_metadata`, `:603::_save_metadata`, `:634::_persist_token_grant` and `:696::_refresh_grant` own singleton lifecycle state. Replace those identities/locks/caches with credential-scoped lifecycle using `persistence/oauth_grants.py`, preserving the useful vendor protocol/parsers.

**Deletion gate:** two OAuth credentials coexist; late refresh/device completion loses to disconnect/permission removal; private/shared isolation, one ciphertext, tombstones, slot-bound encryption and master-key rekey pass. Keep those P08 guarantees while deleting the singleton control/adapter rebuild paths. Do not add a general OAuth-provider framework for one provider.

### 6.5 P1/P2: converge settings, reads, capture and durable audit — API-03, API-07 through API-10

Retire `routers/control.py:958::routing_policy` and `:975::persist_routing_config` as a second execution settings authority after consumers use revisioned `SettingsService`. Copy typed allowed overrides, not arbitrary persisted/resolved state; retain inheritance and reject unavailable credential references. A new generic copier is unnecessary.

`routers/observability.py:31/:49` and `services/observability.py:35/:56` still read by human ID; D1 already has `list_project_trace_summaries:790`, `get_project_trace:823`, `list_project_usage:941` and project aggregates in `persistence/storage.py`. Cut over to explicit authorized project reads, preserving shared-team visibility inside a project and blocking cross-project IDs/cursors/counts/exports.

Apply policy before capture in `infrastructure/trace_payloads.py:99/:118` and export, rather than redacting only a dashboard projection. `RetentionRunRepository` records job status but does not implement project-filtered deletion. `AuditRepository.append_system_event:195` / `append_project_event:230` already provide sanitized caller-transaction appends; integrate them with domain mutations instead of sampled traces or best-effort router callbacks. Define how denied audit events survive mutation rollback.

The repeated `BEGIN IMMEDIATE`/retry/session mechanics in project (`services/projects.py:643`), settings (`services/settings.py:588`) and credential (`services/credentials.py:880`) mutations can share one small typed transaction helper. Keep last-admin, revision and secret-slot conflict policy in the services; do not retry vendor I/O inside that helper.

### 6.6 P2/P3: concrete test reductions and corrections — API-12, RT-08 through RT-13

- **One proven same-layer duplicate:** remove `tests/integration/services/test_provider_limits.py:363::test_tavily_free_zero_denies_vendor_402_zero` after its fixture cutover. Survivor: `test_tavily_limits.py:171::test_funds_gate_terminal_vendor_402_denies` covers the same snapshot/admission and additionally asserts nonretryability. Both passed in this audit. Record a deliberate minus-one case; retain adapter→402→next-call and REST/MCP/fanout coverage.
- **One superseded BDD expectation:** retire `provider_limits.feature:12` B02, “legacy native rows survive upgrade with one migration head,” and its exclusively consumed steps. D1 rejects old databases without modification. Survivor: `database_migrations.feature:13` rejection scenario plus baseline/idempotency/byte-identical/worktree-isolation integration tests. Do not restore adoption machinery to make B02 green.
- **One vacuous oracle:** `tests/integration/services/test_rate_limits.py:126::test_vendor_observation_not_double_counted` only checks a list type. Replace with numeric headroom/persisted-attempt assertions. Do not delete the integration boundary just because a unit test checks related arithmetic.
- **One misleading concurrency label:** `tests/unit/services/test_rate_limits.py:390::test_concurrent_reservations_never_overspend` is sequential; retain the assertions with an accurate name and add/retain actual independent-connection/process races for caps.
- **Repeated expensive setup:** parameterize dev/prod Tavily boundary tests and bulk-seed exact durable attempts before the final genuine service admission/race. Retain two boundary cases and race assertions; measure improvement rather than lowering limits or mocking the decision.
- **Four identical cleanup helpers:** `_unlink_with_retries` in rate/provider/Tavily service and limit repository integration files can share one narrow test helper. All cases survive; retain Windows-safe close/cleanup behavior.
- **Misclassified tests:** `tests/unit/services/test_monitoring.py` opens real migrated SQLite. Move its cases/fixtures into the canonical integration suite with provenance and unchanged total case count. Do not delete its soft-zero, no-extra-write or single-flight assertions.
- **Small exact-body consolidation:** ARCH-04 specifies the five Brave malformed-envelope and seven Firecrawl invalid-credit cases to retain when eliminating repeated bodies. No numerical test-deletion quota follows from the test/source line ratio.

The remaining old account-role/response and singleton-OAuth tests are **contract replacements**, not proven duplicates. API-12 lists representative tests and protected invariants. No full BDD pruning is authorized without a case/assertion map; RT-14 recommends keeping all existing latency measurement boundaries.

### 6.7 P2/P3: support and small implementation cleanup — API-11, SUP-02 through SUP-06, SUP-08, SUP-09, ARCH-01 through ARCH-03

Delete REST's discarded no-op legacy-secret census (`infrastructure/encrypted_store.py:283`, called at `routers/api.py:329`) after checking its report/counters have no consumers. Keep rekey, generation slots and tombstones. Move database-path policy out of monitoring; optional CLI placement/common-argument cleanup does not need a framework. Retire record translation and rollout branches only after their actual writers/callers switch; current enablement commands and release metadata are not automatically dead.

Correct backend container port/healthcheck/authority wiring as described in SUP-08; preserve the distinction between internal ports and host publication. Update stale anonymous-execution/role/migration documentation with the owning cards. None of this calls for UI changes. ARCH-01–03 cover canonical credential construction, the reproduced Firecrawl test-double branch and small shared adapter mechanics; ARCH-05 extends the resource-identity change to sync/manual anchors. Those cleanups must not erase vendor-specific payload/response/cost differences.

## 7. Acceptance checklist for the implementation handoff

The entries below are required behavior/tests, not claims of completion. Use the specialist evidence to choose the current source seam. Every A criterion is covered explicitly so a later agent cannot declare success by deleting inconvenient tests.

### A1 — TASK-000041

1. Remove legacy roles/superuser from backend contracts/responses; public signup creates an ordinary human. Rewrite fixtures to trusted role assignment rather than `developer` promotion.
2. Scope all system/project authority through active durable assignments and membership. Test no implicit system-admin project bypass and no self-escalation on signup/update.
3. Preserve the transactional last-active-human-admin invariant under concurrent removal/demotion/account deactivation, including CLI and archived projects. Verify supported account-wide mutations check every affected project atomically.
4. Issue/list/rotate/revoke keys; store prefix plus verifier only; secret appears once; omitted expiry differs from explicit null; rotation preserves lifetime unless changed and implements the defined overlap.
5. Bind keys to one project's search/fetch scopes, deny human/control-plane operations, and prove creator role changes neither expand nor remove key ownership implicitly.
6. Exercise absent/invalid/expired/revoked/wrong-project/wrong-scope/archived-project credentials before provider access over REST, MCP HTTP, stdio and repeated tool calls in a persistent session. Include permission/key change between enqueue and dispatch.
7. Preserve human-session execution with explicit project membership; no browser API key requirement.
8. Audit membership/role/key lifecycle in the correct scope without raw secrets or verifier material.

### A2 — TASK-000042

1. Both transports call the same execution workflow; test equal provider decisions, fallback/fanout semantics and project attribution for equal inputs.
2. Propagate verified project/actor into every usage row, root/child/fanout span, admission and rate attempt, with credential/binding/pool/request IDs where applicable. Ignore forged payload/baggage attribution.
3. Bind several credentials per provider; support pinning and fanout; restrict private credentials and require explicit grants for shared credentials. A provider type is not a unique runtime credential ID.
4. Scope health/circuit state to credential or pool appropriately. Test one bad credential leaves another of the same provider usable; keep genuinely provider-wide outage state explicit.
5. Atomic pool and project caps survive concurrent processes/transports and several keys in one pool. In strict 4/6 mode A alone still stops at 4/s. Preserve exact window semantics and the single shared native balance.
6. Capacity-store outage fails closed for constrained dispatch; retries of a reservation are idempotent, but a new upstream retry charges a fresh attempt.
7. Order scope/permission/binding/capacity checks before vendor access. Test provider-spy call counts of zero on every rejected path.

### A4 — TASK-000043

1. Preserve all P08 invariants listed above on D1; remove obsolete singleton dispatch, not per-instance slot binding, rekey or delete-wins protections.
2. Two Parallel OAuth grants coexist. Disconnect/expiry/refresh races affect only one credential; stale refresh cannot resurrect it. Loss of permission during device flow cancels completion and cleans active flow state.
3. System administrators alone manage shared credentials/grants/pools/links/allocation ceilings. Project settings or copy cannot expand system ceilings.
4. Available/granted and project-enabled providers remain distinct. New grants/bindings start disabled; capability/system kill switch/principal permission/current health/capacity still constrain dispatch.
5. Return permitted credential labels/pool ownership while withholding secrets and other projects' usage.

### A5 — TASK-000044

1. Resolve defaults → project overrides → system constraints, with per-field provenance, revision conflicts and reset-to-inherit. Retain omitted/false/null/empty semantics and cross-process invalidation.
2. Preview/apply settings copy through an explicit allowlist, atomically and with audit. Keep inheritance; reject unavailable private credentials. Never copy keys, memberships, secrets, balances, usage, traces, limiter state or privileges. Revalidate revisions/permissions at apply.
3. Apply project sampling/detail/redaction/retention to that project's **new** traces within system constraints; mandatory audit is never sampled away. Preserve metadata-only policy defaults and system-only exporter/encryption settings.
4. Retention selects and deletes only the explicit project's data. Tests need two projects with interleaved timestamps, not a one-project happy path.
5. Activity/dashboard/usage/export/list/detail/count/cursor access requires project scope; guessing another project's trace ID or reusing its cursor cannot cross the boundary. A system role alone does not grant payload access.

### A3 — TASK-000045, after A2

1. One authority dispatches REST/MCP. Forward original verified credentials/deadline/trace context; no provider bypass on outage. Fencing prevents a second authority serving the same borrowed pool, including stale-holder dispatch.
2. Bound per-project and total queued count/bytes/wait/concurrency. Canceled/expired queued work neither reaches vendors nor debits rate attempts. Report queue wait separately from provider time and router overhead.
3. Loans off equals A2 strict behavior. Loans on allows idle borrowing up to max/pool limits; continuously eligible equal-cost 4:6 demand approaches the documented service bound. Test returning projects and idle-deficit caps; do not require exact per-second success ratios.
4. Reject infeasible guaranteed allocations; zero-guarantee work uses explicit best-effort policy, without zero-weight arithmetic shortcuts.
5. Distinguish rate, spend, queue and credential failures; respect Retry-After and one end-to-end deadline across queue/retries/fallback.
6. Restart uses persisted lease/fencing/dispatch/attempt state conservatively: no full unsafe bucket, no double native settlement, no release of uncertain upstream concurrency just because a lease expires. Exercise mixed REST/MCP contention with temporary databases.

Every request-path slice inherits the PF latency gate and shared security DoD. A faster path that omits live revocation, shared admission or correct settlement does not pass.

## 8. Test reduction policy

Reduce repeated setup and repeated execution of the same invariant at the same layer. Preserve independent evidence at genuine boundaries.

- Deterministic policy/math/parser methods and their helpers belong in unit tests with deterministic clocks and fake transports. Test typed objects through their behavioral contracts rather than requiring a procedural implementation.
- SQLite transactions, fresh schema rejection, shared quotas, cross-process contention, last-admin protection and generation fences require integration tests using temporary databases.
- Keep a small set of end-to-end BDD journeys for core user value: scoped authenticated execution, lifecycle/isolation, representative provider/fallback/fanout and latency. New field-validation permutations do not each need a BDD scenario.
- A service unit test, transaction integration test and persistent MCP security test may all mention revocation while detecting different failures. Similar scenario names are insufficient removal evidence.
- A fixture that constructs a legacy principal or opens the checkout database must be repaired, not used as a reason to delete security assertions.
- For each deletion, record old test IDs, invariant/input set/assertions, surviving replacement IDs and actual before/after collected case counts. A consolidation preserves cases unless an obsolete contract is explicitly superseded; a genuine coverage deletion needs a stated surviving oracle.
- Do not reproduce every service policy matrix once for REST and again for MCP after A2. Keep policy coverage once at the shared service and representative transport parity, auth/session and wire/error mapping cases on both transports.
- Do not remove PF's instant-fake full transport matrix as a duplicate of route-planner microbenchmarks. They measure different costs. Keep live provider checks explicitly opt-in.

There is no evidence here for deleting a fixed percentage of tests. The meaningful target is fewer duplicated fixtures and fewer independent implementations of the same policy, with the acceptance matrix still executable.

## 9. Implementation order and deletion gates

This is a proposed handoff sequence within the existing cards, not a new ticket lifecycle or a replacement for recording each implementation plan in Backlog.

1. **Agree the small shared contracts first (A1/A2/A4/A5 owners):** discriminated principal, immutable verified context, selected binding/credential/pool identity, attempt ID/deadline and normalized failure codes. Use existing D1 enums/rows/repositories and resolve section 6.2's actor-attribution exception with the schema owner. Do not let parallel cards create four competing versions of these contracts.
2. **A1:** cut authentication, guards, CLI and auth fixtures over together. Remove the old role DTOs/bridges and legacy global role matrices only when their scoped security replacements pass. Keep session/cookie/throttle tests.
3. **A4 in parallel:** connect credential/binding/pool/OAuth services to D1, preserve P08 storage guarantees, expose metadata-only control responses. Remove provider-name singleton OAuth/secret control paths after no execution/control caller uses them.
4. **A5 in parallel:** connect project reads/settings/copy/policy/retention to D1. Remove account-only trace and installation-wide project read paths only after two-project cursor/export/retention tests pass. Explicit system aggregate APIs can remain with system authorization and sanitized projections.
5. **A2:** establish the common execution/attempt workflow and credential runtime, then atomic scoped strict admission. Delete REST/MCP duplicate orchestration and legacy provider runtime state after parity, attribution, concurrency and retry tests pass. Reuse vendor parsers/cost code.
6. **A3 after A2 merges:** add authority forwarding, bounded queues, scheduler and recovery using D1 lease/dispatch repositories. Keep strict mode and scheduler admission behind the same authoritative attempt boundary; remove any direct MCP vendor execution path.
7. **After each slice:** rerun affected unit/integration/security tests, Ruff/MyPy and the PF instant-fake gate for changed request paths. Once the API layer converges, run all backend tests plus default Behave. Keep live tests opt-in and never use the checkout's database to make `main()` tests pass.

Do not defer latency until the end: PF identifies admission, authentication and scope resolution as expensive stages. Consolidate repeated reads within a **single verified operation/transaction** where correct, project only needed columns, and profile representative transport paths. Persistent auth/authority state may change between calls, so a process-wide permissions cache without sound revision invalidation is not a simplification.

Keep only the canonical registrations in `routers/api.py`/`mcp/server.py` as services move out. This makes each card reviewable and avoids repeated cross-card rewrites of the composition roots. Every reduction should remove a previous path at the same time its replacement becomes authoritative.

## 10. Specialist evidence

Detailed API/schema, routing/test and noncritical backend-support reviews are incorporated through the following companion reports. Use their exact source/test evidence with this synthesis's acceptance and deletion gates; none marks Backlog criteria complete. The support report includes orchestrator corrections to the initial research findings.

- [API/schema and identity audit](2026-10-26-api-schema-audit.md).
- [Routing, accounting and backend tests audit](2026-10-26-routing-tests-audit.md).
- [Backend support, configuration and historical-contract audit](2026-10-26-backend-support-audit.md).

### Coverage disposition by backend area

All backend Python directories and backend test directories were inventoried. Source review was focused by invariant/call path, not every line; the distinction below prevents an inventory being mistaken for a proof of dead code.

- **Routers/MCP/composition:** deep execution/auth/credential/settings/activity review; replace duplicate business decisions, retain transport parsing/error mapping and lifecycle registrations. Main entrypoint isolation remains an implementation test fix.
- **Services:** deep project/RBAC/settings/credentials/OAuth/routing/monitoring/rate/funds review; background sync/manual anchors inspected for identity alignment; pure credit/fusion functions retained. The findings cover every service subsystem, without claiming every branch was read.
- **Persistence/models:** D1 ownership/table/repository map and critical actor/binding/pool/key/OAuth/audit/authority seams reviewed. Retain explicit scope, constraints, Decimal formats, baseline validation, read-only rejection and conservative recovery; do not remove schema tests merely because ORM metadata tests also exist.
- **Adapters:** all eight providers inventoried; source/contract focus on construction, injection, retries, transport ownership, normalized errors, Firecrawl compatibility, selected parsers and options. No complete vendor SDK dead-code or current vendor-pricing verification is claimed. Provider-specific behavior/tests remain until a specific equivalence or obsolete contract is proved.
- **Infrastructure/configuration/CLI:** reviewed auth/browser/trace/vault/resilience/client/policy seams and support composition. Retain cryptographic/session/body-cap/redaction/ownership protections; shared-mechanics cleanup is narrow and evidence-based. Logging/date/transport helpers are not blanket deletion targets.
- **Tests/BDD/harness:** broad inventory plus detailed identity/settings/credential/accounting/routing/trace/authority and selected provider suites. Exact safe candidate, superseded scenario, weak oracles, duplicated setup and classification fixes are named above. No exhaustive removal map for every BDD/provider parameter was produced; therefore none is authorized by this report.
- **Scripts/deployment/docs:** backend operational setup reviewed selectively; preserve worktree port/data isolation. No new platform-script or container-build project is required by this audit. UI, cloud workflows, live secrets/databases and live vendor benchmarking are excluded.

## 11. Handoff completion criteria

The coding agent should finish with one principal/authorization path, one shared execution workflow and authority, credential/pool-correct state, explicit project repository reads and a smaller set of canonical fixtures. It must preserve the 31 A-series acceptance criteria, D1 schema guarantees and the historical behaviors listed here, with no unexplained loss of security or accounting assertions.

The report does not promise a line-count or latency reduction before implementation and measurement. It identifies where code can be removed, which responsibilities should become authoritative, and the evidence required to make each removal safe.
