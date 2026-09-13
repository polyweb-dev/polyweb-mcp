# Audited cleanup plan

Audit date: 2026-09-13. Baseline commit: `cfbfefdab47ca6da556d40c99868753ff429c75d`.

Scope: audit the supplied trim plan and propose behavior-preserving cleanup. This document does not authorize or implement feature removal. Only this Markdown file was created by the audit.

## Audit conclusion

The original plan mixes useful deduplication with contract changes, behavior changes, and a persistence rewrite. Do not execute its Phase 1 as a blanket list of safe deletions. Replace the claimed `-1400 lines, -12 dependencies` target with measured results from individually verified changes; moving a dependency to devDependencies is not removing it.

CodeGraph MCP was used to inspect symbols, source, callers, and test relationships. Three delegated workstreams reviewed backend code, frontend code, and dependencies/persistence; the coordinating audit checked quota contracts, test doubles, and verification configuration. Source reads supplemented missing or explicitly stale graph results and unindexed configuration. No source was refactored or dependencies changed. The dependency audit ran isolated migration, secret-resolution, and installed-SDK tests: **18 passed**. Its Knip run found one existing unused export, recorded below. The full validation commands later in this document remain future implementation gates.

## Important behavior to preserve

1. **Exact manual-quota arithmetic and form feedback.** `freesearch-ui/src/features/quota/model/manualQuotaMath.ts:1` explicitly promises decimal strings, BigInt arithmetic, half-up rounding, and no exponential notation. `remainingPercent1dp` must not become unchecked `Number()+toFixed(1)`. `validateManualQuotaFields` also enforces a positive allowance and field-level errors; backend `ManualQuota` permits zero (`src/freesearch/models/contracts.py:436`), for which the percentage is unknown. These validators serve different boundaries and are not equivalent.
2. **Quota provenance and source precedence.** `quotaValues` in `freesearch-ui/src/features/quota/model/quotaDetails.ts:32` selects a latest snapshot as a whole, including nulls; null must not silently resurrect an older balance. `resolveQuota` supplies keyless and OAuth state. `quotaDisplay` distinguishes account balances, missing budgets, unknown limits, hourly windows, and locally observed shared pools. Consolidate repeated mapping while retaining these distinctions.
3. **Wire compatibility and privacy.** `QuotaSnapshot._serialize_compat` (`src/freesearch/models/contracts.py:208`) conditionally omits compatibility fields, and quota metadata is excluded from serialization. Backend percentage computation does not justify deleting legacy handling or exposing internal metadata. Decimal values remain strings at the API/UI boundary; bounded display percentages may be formatted separately.
4. **Independent test scenarios.** The generic `FakeAdapter` (`tests/conftest.py:22`), routing adapter (`tests/unit/services/test_routing.py:36`), monitoring stub (`tests/integration/services/test_monitoring.py:48`), and OAuth stub (`tests/integration/services/oauth/conftest.py:58`) are not interchangeable duplicates. They differ in capabilities, failures, clocks, usage recording, and quota ownership. Share genuinely identical builders while keeping explicit scenario-specific behavior; especially retain the OAuth stub's disabled quota capability.
5. **Credential redaction.** `src/freesearch/infrastructure/resilience.py:92` implements broader sanitization than `logging.redact_secrets`: compound credential names, quoted values containing spaces, Basic/Bearer credentials, and structured details. Replacing it with the simpler function can expose credentials. For example, masking only the first token after `Authorization: Basic ...` leaves the credential behind. A shared redactor must preserve the stronger behavior and known-secret masking, not merely reuse the shorter implementation.

## Dependency and entrypoint decisions

| Original proposal | Audited decision | Evidence and required preservation |
| --- | --- | --- |
| Replace aiosqlite, SQLAlchemy, and Alembic with sqlite3 | **Defer as a separate architecture project.** | `SQLiteRepository.open` in `src/freesearch/persistence/storage.py` upgrades the DB and creates an async `sqlite+aiosqlite` engine. Repository operations use SQLAlchemy sessions/ORM; migration environment and revisions also require SQLAlchemy. The raw sqlite3 inspector is not a replacement implementation. Preserve async lifecycle, transactions, migration locking, backup, adoption, and historical upgrades. |
| Remove exa-py, firecrawl-py, tavily-python | **Reject: active runtime dependencies.** | `src/freesearch/adapters/exa.py`, `firecrawl.py`, and `tavily.py` construct `AsyncExa`, `AsyncFirecrawl`, and `AsyncTavilyClient` and call SDK operations. HTTP helpers coexist with these clients. Keep dependencies unless a separately tested SDK replacement is implemented. |
| Remove python-dotenv in favor of pydantic-settings | **Keep for now.** | `src/freesearch/infrastructure/secrets.py` directly uses `dotenv_values`; credential lookup preserves process environment, then `.env`, then keyring precedence. Loading ordinary settings does not replace this resolver. Any future consolidation must preserve precedence, reload behavior, and secret handling; a transitive installation is not grounds to omit a directly imported dependency. |
| Collapse database_cli.py into main(argv) | **Keep the entrypoint boundary; optional argv is independent.** | `pyproject.toml` publishes `freesearch-db = freesearch.persistence.database_cli:main`. The module implements documented status/upgrade behavior and migration-safety messages. Moving it changes import paths without removing that responsibility. |
| Replace Hugeicons with Lucide | **Good coordinated dependency-removal candidate.** | The live use is `freesearch-ui/src/shared/ui/dialog.tsx`, not merely its compatibility shim. Replace the close icon, then remove both `@hugeicons/react` and `@hugeicons/core-free-icons`. Update `freesearch-ui/components.json`'s icon-library setting and the dependency assertion in `src/components/layout/Sidebar.test.tsx`; otherwise generation/tests retain the old requirement. Verify dialog/modal behavior and build. |
| Move dependency-cruiser, knip, shadcn, stryker to devDependencies | **Mostly manifest hygiene; partly already done.** | Move dependency-cruiser/Knip. Keep shadcn installed for builds: `freesearch-ui/src/index.css` imports `shadcn/tailwind.css`, so it is not just an unused generator. Both Stryker packages are already devDependencies. Builds must install development dependencies; these moves do not themselves reduce the browser bundle or lockfile. |

The dependency audit also confirmed that pydantic-settings itself depends on python-dotenv in `uv.lock`; dropping the explicit declaration would not remove the installed package. QUOTA.md section 7 documents Alembic's schema authority and migration safety requirements, and README.md documents the database CLI. Preserve those operational contracts when considering any future replacement.

## Backend cleanup decisions

Paths in this section are relative to `src/freesearch/` unless stated otherwise.

| Original proposal | Audited decision | Conditions and evidence |
| --- | --- | --- |
| Delete cache metadata model, row, and CRUD | **Conditional cleanup, not schema-blind deletion.** | No service/router/MCP consumers were found, but there are storage tests and a root public export. `persistence/migrations/versions/0001_legacy_baseline.py:93` creates the table/index. Remove application code only after deciding public API compatibility; retain the old table explicitly or add a forward migration. Never edit migration history to pretend the table never existed. |
| Delete McpSurface and UnsupportedOperationError | **Conditional public-API removal.** | FastMCP registers its own search/fetch tools in `mcp/server.py:303`; the older surface is exported through `mcp/__init__.py` and exercised by surface/adapter tests. Internal runtime removal appears viable, but downstream Python imports are not disproven by the graph. Retain tool/adapter behavior tests at the active API before retiring old surface-specific tests. |
| Delete estimate_cost and seven overrides | **Defer pending explicit API/product decision.** | `adapters/base.py:43` exposes an abstract extension contract, `CostEstimate` is public, and pricing tests in `tests/integration/services/test_quota_units.py` assert behavior. Lack of current production callers does not make pricing semantics or custom-adapter compatibility disposable. Preserve pricing helpers still used by telemetry/quota. |
| Delete cost_estimate/health capability fields | **Contract-sensitive; split from operations.** | No production gate reading `health` was found, but it is a model field. Review serialized/schema consumers before removing it. Keep `ProviderAdapter.health`, `ProviderHealth`, and connection testing, which calls health directly. Couple the cost flag decision to the estimate-cost API decision. |
| Delete configure_logging and SecretRedactionFilter | **Low-priority conditional delete.** | `infrastructure/logging.py:29-53` has no observed production setup caller. Verify startup/configuration and external imports before removing this optional logging API. Keep secret redaction and its regression coverage. |
| Inline adapter_factory | **Keep, or relocate with its registry.** | `routers/control.py:_ensure_provider_adapter` uses it to construct newly configured adapters under a lock. Inlining would expose MCP's private registry. A boundary improvement is moving registry and factory together to an adapter-owned module shared by REST and MCP. Preserve locking, creation/cleanup, and secret-add-to-probe behavior. |
| Merge retry status sets | **Good small deduplication.** | Eight sets agree on `{429, 500, 502, 503, 504}` across resilience/adapters. Use one immutable infrastructure constant; retain provider-specific error mapping and retry/cooldown behavior. |
| Merge published-date parsers | **Good with a narrow shared contract.** | Share invalid/non-string-to-None behavior and preserve naive/offset/microsecond handling. Do not absorb Firecrawl's billing-period parsing, which assigns UTC to naive dates, into an allegedly equivalent helper. |
| Remove Z replacement before fromisoformat | **Good small simplification.** | `pyproject.toml` confirms Python `>=3.12,<3.14`. Remove the redundant replacement where it only handles ISO `Z`; retain exception handling, input checks, and timezone policy. Exercise valid Z, offsets, naive dates, and invalid inputs. |
| Merge three borrowed HTTP transports | **Conditional: implementations differ.** | You.com and Tavily reassert phase timeouts; Parallel delegates without that step. Preserve caller-owned client/pool lifetime, header isolation, and no-op transport close. Parameterize a difference if necessary; do not silently apply one provider's timeout policy to all. |
| Deduplicate quota validators into helper/mixin | **Narrow the scope.** | `ManualQuota` and `ManualQuotaUpdate` duplicate fields/window checks. `ManualQuotaResponse` additionally validates remaining/optional percent and lacks that window validator. Preserve model names/schemas, validation field locations, optional handling, and TypeError-to-ValueError conversion. Prefer a small shared base/helper over a mixin spanning unrelated models. |
| Replace resilience redaction with logging helper | **Reject as written.** | See credential-redaction risk above. If consolidating, move the richer sanitizer into an independent infrastructure module and preserve literal-secret masking; verify recursive sanitization and do not introduce an import cycle. |
| Replace SecretStore and MemorySecretStore with concrete keyring | **Reject.** | `infrastructure/secrets.py:44-55,104-147` defines an active injection boundary used by secret resolution, app/control composition, and OAuth. Preserve isolated memory-backed tests and callers without OS-keyring access. Consolidating genuinely duplicate memory fakes is separate. |
| Merge Settings and ProviderConfigSettings | **Defer direct merger; share foundations only if useful.** | `configuration/provider_config.py:173-203` uses custom decoding, `enable_decoding=False`, and hidden input errors; `configuration/config.py` has different global settings/caching. A direct merge risks an import cycle and changes validation/error secrecy. Preserve invalid JSON, unknown providers, float rejection, precedence, and cache reset. |
| Replace all decimal hygiene with parse_decimal | **Partly already done; retain boundary-specific conversion.** | Strict domain parsing already has multiple callers, including Parallel seed parsing. Configuration must reject JSON floats, while vendor helpers such as Tavily `_quota_number` intentionally convert floats via `Decimal(str(value))`. Do not impose one coercion policy on domain input, vendor payloads, and persisted values. Preserve `allow_negative` and exception translation. |
| Replace all test doubles with one factory | **Deduplicate construction selectively.** | Preserve the distinct monitoring, routing, OAuth, and generic fake behaviors listed above. Avoid a universal configurable fake that obscures which behavior each test actually covers. |

## Frontend cleanup decisions

Paths in this section are relative to `freesearch-ui/src/`.

| Original proposal | Audited decision | Conditions |
| --- | --- | --- |
| Delete seven type/API re-export shims and UI compatibility shims | **Good import-migration candidates, not caller-free deletes.** | `services/api/backendTypes.ts`, `types/freesearch.ts`, `services/quotaDisplay.ts`, and common UI shims still have consumers. Enumerate every target, redirect production/test imports and mocks to the appropriate owner, then remove the pure shim. Include `components/quota/manualQuotaMath.ts`, whose tests currently import through it. Preserve legitimate public barrels and layer boundaries. |
| Delete catalog, DEFAULT_PROVIDERS, and mergeProviderStatus | **Split the proposal. Keep production metadata and merging.** | `shared/api/catalog.ts` supplies names, descriptions, base URLs, auth-header names, and capabilities absent from `BackendProviderStatus`. `mergeProviderStatus` in `services/api/mappers.ts` uses those values. `mapProviderRows` in the provider domain also filters unknown IDs and orders rows. `DEFAULT_PROVIDERS` is test-only and can be consolidated with fixtures separately. To eliminate production metadata duplication, first extend backend contracts/decoders and define unknown-provider/loading behavior. |
| Remove manual-quota validation | **Reject as a safe deletion.** | Preserve field feedback, save gating, decimal syntax, positive allowance policy, and server validation. Share tests of common rules if useful; do not silently equate different rules. |
| Replace BigInt percent math with Number/toFixed | **Reject as proposed.** | Keep `remainingPercent1dp`'s exact decimal parsing, half-up rounding, zero/invalid handling, and clamp. Its existing tests are in `components/quota/manualQuotaMath.test.ts`. Retain exact draft preview even if persisted percentages come from the backend. |
| Collapse four quota layers into quotaDisplay | **Consolidate repeated normalization only.** | Keep snapshot selection separate from presentation where this makes precedence explicit. Preserve latest null values, observed confidence, OAuth/keyless state, dates/windows, unknown limits, native decimal strings, and provider-specific explanations. The code already centralizes much presentation in `domains/dashboard/model/quotaDisplay.ts`. |
| Remove provider-ID aliases | **Defer to an explicit compatibility migration.** | `domains/providers/api/idMapping.ts` maps UI `youcom` to backend `you`; mapping is live across execution, health, credentials, and priority operations. Choose one internal ID only with a complete migration of API boundaries, selection/state, routing/dashboard keys, assets, and tests. Keep external aliases as needed. |
| Remove Sidebar controlled props and DialogFooter | **Treat separately.** | `DialogFooter` is a deletion candidate after checking exports/consumers. Sidebar controlled behavior is exercised by tests even though production mounts it without those props; removing it intentionally narrows a component contract. Do not classify that as an untested no-op or delete accessibility coverage along with it. |
| Remove BackendUnitKind alias | **Good mechanical candidate.** | `shared/api/units.ts:7-10` aliases exactly `UnitKind`; migrate wire-type consumers and `backendTypes` exports atomically before deleting it. |
| Replace custom Switch with Base UI | **Conditional implementation swap, not wholesale markup deletion.** | Preserve `shared/ui/Switch.tsx`'s checked/change API, generated label IDs, description wiring, disabled state, role/name, focus styles, and form behavior. Base UI is already installed; adapt Root/Thumb behind the existing interface and run accessibility/component tests. |
| Unify date/percent/latency formatting | **Merge only equal semantics.** | `formatLatency` and `formatUsageP95` can share the same formatter. Date-only local dates, timestamp dates, hourly en-US 12-hour times, and invalid-value fallbacks differ. Manual percentages always show one decimal; dashboard percentages omit trailing `.0`. Use explicit formatting policies, not one unconditional Intl formatter. |
| Replace clipboard/timer paths with useClipboard | **Useful after preserving distinct feedback behavior.** | `features/playground/model/useResultPreview.ts` uses transient copied state; OAuth `usePairingFlow` checks availability/rejection and retains copied state until reset. A shared hook should report async success, support transient/sticky feedback, restart/clear timers, and clean up on unmount. Treat existing rejection/timer problems as fixes with their own regression checks. |
| Delete cn shim | **Good mechanical candidate.** | `lib/utils.ts` is exactly `export { cn } from "cn"`. Redirect consumers to that same package. Do not substitute a different class-merging library or change style semantics. |
| Inline SearchPlayground, AppProviders, ToastContainer, and execution actions | **Split by responsibility and payoff.** | Remove the pure `SearchPlayground` rename shim after updating callers/tests. Keep `app/AppProviders.tsx`'s provider composition and nesting. ToastContainer's small binding protects shared view purity; deprioritize its removal. Keep `playgroundExecuteAction`/fetch action boundaries: they own validation, eligibility, payloads/timeouts, and result state; inlining enlarges an already substantial controller and harms testability. |

## Revised execution order

### Phase 0 — establish the exact cleanup manifest

Record the current baseline and targeted symbols, including test consumers and public exports. Capture focused test outcomes before changing behavior. Replace the original approximate shim counts and line estimates with an explicit list. Decide public compatibility separately from purely internal cleanup.

### Phase 1 — small, behavior-preserving changes

1. Redirect imports and remove pure compatibility shims, `BackendUnitKind`, and the `cn` pass-through in small atomic slices.
2. Remove `DialogFooter` only once no remaining consumer/export contract requires it; keep its parent dialog/accessibility behavior.
3. Share the identical retry constant, compatible publication-date parser, and latency formatter. Remove redundant ISO-Z replacement independently.
4. Consolidate test-only provider defaults and genuinely identical fixture construction.
5. Reclassify development-only tooling dependencies after checking the build environment. Measure installed/bundle effects rather than counting reclassification as package removal.

### Phase 2 — constrained deduplication with behavior tests

1. Share the identical manual-quota input validators without changing response schemas or client validation.
2. Consolidate quota input mapping while retaining latest-snapshot precedence, unknown values, provenance, manual draft precision, and OAuth/keyless presentation.
3. Extract borrowed-transport mechanics only with explicit timeout/lifecycle policy.
4. Introduce a shared clipboard hook with both feedback modes; optionally swap the Switch control while keeping its accessible wrapper contract.
5. Consider moving adapter registry/factory ownership out of MCP if it simplifies the REST/MCP dependency direction. Avoid inlining domain actions into controllers.

### Phase 3 — optional removals requiring explicit compatibility scope

Assess cache application API removal and a forward schema migration (or documented table retention), old `McpSurface` exports, unused logging setup, and unused capability fields separately. Each change needs an exact compatibility statement and dedicated validation. Leave estimate-cost API retirement, provider-ID migration, settings merger, and persistence replacement out of the ordinary cleanup batch.

Keep the active SDK dependencies, exact decimal arithmetic, client form validation, richer secret sanitizer, secret-store injection boundary, and production provider metadata. These are not proven redundant.

## Focused acceptance checks

| Slice | Behavior that must remain covered |
| --- | --- |
| Quota math/forms/display | Existing `components/quota/manualQuotaMath.test.ts`, quota model/display tests, and backend `tests/integration/routers/test_manual_quota.py`; tiny/large decimal strings, rounding ties, zero/overuse, invalid fields, draft preview, latest-null precedence, missing bounds, OAuth balance, and keyless hourly state. |
| Adapter shared code | All affected adapters' search/fetch/error tests; 429/5xx retry mapping, naive/Z/offset dates, phase timeouts, no credential/header cross-contamination, and a shared client still usable after closing an adapter. |
| Redaction/secrets | Existing foundation, resilience, control, and OAuth adversarial tests; Basic/Bearer and compound credentials, quoted/multiword strings, nested models/maps/bytes, literal known secrets, environment/file/keyring precedence, and in-memory injection. |
| Cache/persistence | `tests/integration/persistence/test_storage.py` and migration tests against fresh and pre-cleanup scratch databases; upgrade preserves all unrelated rows, indexes, exact decimals, and migration revision state. Exercise locking/backup/adoption if migration code changes. |
| Shim/UI cleanup | Existing component tests after import redirection, application build and type checks, dialog focus/keyboard behavior, Switch accessible name/state/disabled behavior, and applicable quota/settings/OAuth browser scenarios. |
| Factory/MCP/API changes | Adapter construction after adding a key, connection probe, disabled/no-key responses, no duplicate routes/adapters, cleanup, REST/MCP startup, and active tool schemas/behavior. |

## Verification rules for every implementation slice

- Record the exact files, symbols, consumers, and behavior being preserved. An unnamed `etc.` or a count of supposedly dead files is not a deletion manifest.
- Check CodeGraph first, then supplement uncovered dynamic registrations, package exports, console scripts, configuration, and test patch paths. Zero internal callers does not establish that a public contract is unused.
- Redirect source and test imports before removing a compatibility module. Keep behavioral tests, updating their imports and mocks; do not delete a regression test merely because its old wrapper disappears.
- Run focused existing tests for the affected behavior, then the relevant static checks. Characterize uncovered high-risk behavior before changing it. Do not couple unrelated cleanup slices.
- Preserve historical migration scripts and test only copied/scratch databases for migration work. Never use the workspace's real database as a cleanup test fixture.

## Validation limitations discovered

During this audit, the dependency subagent reported 18 passing targeted tests covering secret resolution, database migrations, and installed SDK behavior. This supports the dependency findings, not unimplemented cleanup equivalence. `pnpm knip --reporter compact` exited 1 with an existing unused export, `pickFallbackSearchProvider` in `freesearch-ui/src/domains/execution/index.ts`. That is a separate candidate requiring its own consumer check; it was not removed.

The frontend is actually rooted at `freesearch-ui/`. Its `knip.json` ignores `src/components/ui/**` and `src/shared/ui/**`, and disables type findings. A clean Knip report does not validate the proposed UI shim or type-alias deletions. Audit those paths explicitly or use a scoped audit configuration. `.dependency-cruiser.cjs` currently checks cycles, unresolved imports, and orphans; it does not enforce all the domain boundaries described by the architecture skill. Review those boundaries explicitly when moving shared code.

Use the configured scripts rather than generic commands detached from their project configuration:

```powershell
# Repository root, for backend changes
uv run ruff format --check
uv run ruff check
uv run mypy
uv run pytest tests/unit
uv run pytest tests/integration

# From freesearch-ui, for frontend changes
pnpm depcruise
pnpm knip
pnpm lint
pnpm typecheck
pnpm typecheck:e2e
pnpm test
pnpm build
pnpm test:e2e
```

Run focused tests first; use the broader relevant suite before merging its cleanup slice. Backend BDD is configured under `tests/bdd/features` in `pyproject.toml`; include applicable scenarios when public runtime behavior changes. Dependency removals also require lockfile regeneration, a clean install/build, and installed-entrypoint smoke checks.

