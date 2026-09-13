# CLEANUP.md

Audit date: 2026-09-13. Baseline commit: `cfbfefdab47ca6da556d40c99868753ff429c75d`.

Grounded ONLY on `CLEANUP_AUDIT.md`. Rejects and defers in that audit are NOT approved.
The prior `-1400 lines / -12 deps` target is replaced by measured per-slice results.
Moving a package to `devDependencies` is manifest hygiene, not removal.

## Phase 0 — manifest rule

Before each slice, record exact files, symbols, consumers (prod + test + public exports + mocks/patch paths), and behavior preserved. No `etc.` manifests. Capture focused test outcomes pre-change. Decide public compatibility separately from internal cleanup.

## Phase 1 — approved small slices

All below are redirect-before-delete, atomic, one slice at a time.

### 1.1 Compatibility shims (import migration, then delete)

- `freesearch-ui/src/services/api/backendTypes.ts` → canonical domain owners.
- `freesearch-ui/src/types/freesearch.ts` → canonical owners.
- `freesearch-ui/src/services/quotaDisplay.ts` (2-line re-export) → `@/domains/dashboard`.
- `freesearch-ui/src/components/quota/manualQuotaMath.ts` (re-export shim; tests import through it) → `features/quota/model/manualQuotaMath.ts`, update test imports/mocks, keep tests.
- Common UI shims (`freesearch-ui/src/components/ui/*`, `freesearch-ui/src/components/common/*` compat re-exports) → `@/shared/ui/*`; enumerate every consumer first.
- `freesearch-ui/src/components/search/SearchPlayground.tsx` pure rename shim → update callers/tests, then delete.
- Preserve legitimate public barrels and layer boundaries.

### 1.2 `BackendUnitKind` → `UnitKind`

- `freesearch-ui/src/shared/api/units.ts#L7-L10` aliases exactly `UnitKind`. Migrate wire-type consumers and `backendTypes` exports atomically, then delete alias.

### 1.3 `cn` pass-through

- `freesearch-ui/src/lib/utils.ts` is exactly `export { cn } from "cn"`. Redirect consumers to the same `cn` package. Do not substitute a different class-merging library or change style semantics.

### 1.4 `DialogFooter` (conditional)

- `freesearch-ui/src/shared/ui/dialog.tsx` `DialogFooter` is a deletion candidate only once no consumer/export contract requires it. Keep parent dialog, focus/keyboard, and accessibility behavior. Treat Sidebar controlled props separately (not approved here; narrowing a tested contract).

### 1.5 Retry constant

- Eight sets agree on `{429, 500, 502, 503, 504}` across `src/freesearch/infrastructure/resilience.py` and adapters. Introduce one immutable infrastructure constant. Retain provider-specific error mapping and retry/cooldown behavior.

### 1.6 Narrow date parser

- Share invalid/non-string → `None` behavior; preserve naive/offset/microsecond handling. Do NOT absorb Firecrawl billing-period parsing (assigns UTC to naive dates) into the shared helper.

### 1.7 Latency formatter pair only

- `formatLatency` + `formatUsageP95` may share one formatter. Do NOT unify date-only local dates, timestamp dates, hourly en-US 12-hour times, invalid fallbacks, or the two percent policies (manual always 1 decimal; dashboard omits trailing `.0`).

### 1.8 `Z` → `fromisoformat` simplification

- `pyproject.toml` confirms Python `>=3.12,<3.14`: remove redundant `replace("Z","+00:00")` where it only handles ISO `Z`. Retain exception handling, input checks, timezone policy; exercise valid `Z`, offsets, naive dates, invalid inputs.

### 1.9 Test-only provider defaults

- Consolidate `DEFAULT_PROVIDERS` (test-only) with fixtures and genuinely identical builders only. Keep distinct behaviors: generic `FakeAdapter` (`tests/conftest.py:22`), routing adapter (`tests/unit/services/test_routing.py:36`), monitoring stub (`tests/integration/services/test_monitoring.py:48`), OAuth stub (`tests/integration/services/oauth/conftest.py:58`, incl. disabled quota capability).

### 1.10 Tooling manifest hygiene

- Move `dependency-cruiser`, `knip` to `devDependencies` after build-environment check. Keep `shadcn` installed: `freesearch-ui/src/index.css` imports `shadcn/tailwind.css`. Both Stryker packages are already `devDependencies`. Measure installed/bundle effect; reclassification ≠ removal.

### 1.11 Hugeicons coordinated removal

- Live use is `freesearch-ui/src/shared/ui/dialog.tsx` (close icon), not just a shim. Replace with Lucide, remove `@hugeicons/react` + `@hugeicons/core-free-icons`, update `freesearch-ui/components.json` `icon-library` and the dependency assertion in `freesearch-ui/src/components/layout/Sidebar.test.tsx`. Verify dialog/modal behavior + build.

## Phase 2 — constrained deduplication (behavior tests required)

### 2.1 Manual-quota input validators only

- Share duplicated checks between `ManualQuota` and `ManualQuotaUpdate` via small shared base/helper. Exclude `ManualQuotaResponse` (validates remaining/optional percent, lacks window validator). Preserve model names/schemas, field locations, optional handling, `TypeError`→`ValueError` conversion. Do not change client validation.

### 2.2 Quota mapping consolidation

- Consolidate repeated normalization only. Preserve: latest-snapshot-as-whole incl. `null` must not resurrect older balance (`freesearch-ui/src/features/quota/model/quotaDetails.ts:32` `quotaValues`); `resolveQuota` keyless/OAuth state; `quotaDisplay` account/missing-budget/unknown-limit/hourly/shared-pool distinctions; native decimal strings; provider explanations; observed confidence; dates/windows. `domains/dashboard/model/quotaDisplay.ts` already centralizes much presentation.

### 2.3 Borrowed transport (conditional)

- Extract only with explicit timeout/lifecycle policy parameter. You.com/Tavily reassert phase timeouts; Parallel delegates without. Preserve caller-owned client/pool lifetime, header isolation, no-op close. Do not silently unify timeout policy.

### 2.4 Shared clipboard hook

- Must support both modes: transient (`features/playground/model/useResultPreview.ts`) and sticky + availability/rejection handling (`features/oauth/model/usePairingFlow.ts`). Report async success, restart/clear timers, cleanup on unmount. Existing rejection/timer issues are separate fixes with regression checks.

### 2.5 Switch swap (conditional)

- Keep `freesearch-ui/src/shared/ui/Switch.tsx` checked/change API, generated label IDs, description wiring, disabled state, role/name, focus styles, form behavior. Adapt Base UI Root/Thumb behind existing interface; run a11y/component tests. Base UI already installed.

### 2.6 Registry + factory joint move

- Do NOT inline `adapter_factory`. Optional: move registry + factory together to an adapter-owned module shared by REST/MCP. Preserve locking, creation/cleanup, secret-add-to-probe. Keep `playgroundExecuteAction`/fetch-action boundaries, `app/AppProviders.tsx` composition, `ToastContainer` view purity (deprioritized).

## Phase 3 — OPTIONAL, NOT APPROVED

Requires explicit compatibility scope + dedicated validation each. Do not batch.

- Cache application API removal + forward schema migration (or documented retention). Never edit `src/freesearch/persistence/migrations/versions/0001_legacy_baseline.py:93`. Preserve upgrade of unrelated rows/indexes/decimals/revision state; locking/backup/adoption.
- Old `McpSurface` / `UnsupportedOperationError` exports (`mcp/__init__.py`, surface/adapter tests). Retain active tool schemas/behavior at `mcp/server.py:303` before retiring surface-specific tests.
- Unused logging setup (`infrastructure/logging.py:29-53`). Verify startup/external imports; keep `redact_secrets` + regression coverage.
- Unused capability fields. Review serialized/schema consumers; keep `ProviderAdapter.health`, `ProviderHealth`, connection testing.

OUT OF BATCH: estimate-cost API retirement, provider-ID migration, settings merger, persistence replacement.

## KEEP list (12 — not redundant)

1. SDKs: `src/freesearch/adapters/exa.py` (`AsyncExa`), `firecrawl.py` (`AsyncFirecrawl`), `tavily.py` (`AsyncTavilyClient`) — live SDK calls; HTTP helpers coexist.
2. `python-dotenv`: `src/freesearch/infrastructure/secrets.py` `dotenv_values` with precedence process env → `.env` → keyring, reload + secret handling. Transitive via `pydantic-settings` (`uv.lock`) ≠ replacement.
3. `src/freesearch/persistence/database_cli.py` entrypoint `freesearch-db = freesearch.persistence.database_cli:main` (status/upgrade + safety messages; documented in README).
4. Exact decimal math: `freesearch-ui/src/features/quota/model/manualQuotaMath.ts` BigInt, half-up, no-exponent + `components/quota/manualQuotaMath.test.ts`.
5. Client validation distinct: `validateManualQuotaFields` positive allowance + field errors; backend `ManualQuota` permits zero (`src/freesearch/models/contracts.py:436`, percent unknown).
6. Richer sanitizer: `src/freesearch/infrastructure/resilience.py:92` (compound names, quoted spaces, Basic/Bearer, structured details, literal-secret masking) over `logging.redact_secrets`.
7. `SecretStore` injection boundary (`src/freesearch/infrastructure/secrets.py:44-55,104-147`): resolution, app/control composition, OAuth, in-memory tests without OS keyring.
8. Production catalog + merging: `freesearch-ui/src/shared/api/catalog.ts` (names/descriptions/URLs/auth-headers/capabilities) + `services/api/mappers.ts` `mergeProviderStatus` + `mapProviderRows` filter/order. `DEFAULT_PROVIDERS` test-only handled in 1.9.
9. `estimate_cost` + `CostEstimate` (`src/freesearch/adapters/base.py:43`) + `tests/integration/services/test_quota_units.py` pricing; keep telemetry/quota helpers.
10. `freesearch-ui/src/domains/providers/api/idMapping.ts` `youcom`→`you` live across execution/health/credentials/priority; keep aliases pending full migration.
11. Settings decoders: `src/freesearch/configuration/provider_config.py:173-203` (`enable_decoding=False`, hidden errors) vs `src/freesearch/configuration/config.py` (different caching); preserve invalid-JSON/unknown-provider/float-reject/precedence/cache-reset.
12. `SQLiteRepository.open` (`src/freesearch/persistence/storage.py`) async `sqlite+aiosqlite` engine + SQLAlchemy sessions/ORM + migration env/revisions; preserve lifecycle/transactions/locking/backup/adoption/history. Authority: `QUOTA.md` s7, README CLI.

## Contracts appendix (must not break)

- Manual math promises decimal strings, half-up, clamp; zero/invalid handling; draft preview even if backend persists percent.
- Snapshot precedence whole incl. nulls; OAuth/keyless/hourly/unknown-limit presentation.
- `QuotaSnapshot._serialize_compat` (`src/freesearch/models/contracts.py:208`) conditional compat fields; metadata excluded; decimals as strings at API/UI boundary.
- Test doubles stay scenario-specific (capabilities/failures/clocks/usage/ownership).
- Redaction must cover Basic/Bearer split, compound/quoted/nested/bytes + known secrets, recursive.

## Verification rules (every slice)

- CodeGraph first, then supplement dynamic registrations, package exports, console scripts (`freesearch-db`), config, test patch paths. Zero internal callers ≠ unused public contract.
- Redirect source + test imports/mocks before removing a shim. Keep behavioral tests (update imports); never delete a regression test because its wrapper disappeared.
- Focused existing tests first, then relevant static checks. Characterize uncovered high-risk behavior first. One slice per change.
- Scratch/copied DBs only for migration work. Never use workspace real DB as fixture.

## Validation commands

```powershell
# Repo root, backend
uv run ruff format --check
uv run ruff check
uv run mypy
uv run pytest tests/unit
uv run pytest tests/integration
# + tests/bdd/features scenarios when public runtime behavior changes (pyproject.toml)

# From freesearch-ui, frontend
pnpm depcruise
pnpm knip
pnpm lint
pnpm typecheck
pnpm typecheck:e2e
pnpm test
pnpm build
pnpm test:e2e
```

Focused tests first; broader suite before merge. Dependency removals need lockfile regen + clean install/build + entrypoint smoke.

## Limitations

- Dependency audit: 18 targeted tests (secrets/migrations/SDKs) support dependency findings only, not cleanup equivalence.
- `pnpm knip --reporter compact` exit 1 on existing `pickFallbackSearchProvider` in `freesearch-ui/src/domains/execution/index.ts` — separate candidate, needs consumer check, not removed here.
- Frontend root is `freesearch-ui/`. `knip.json` ignores `src/components/ui/**` + `src/shared/ui/**` and disables type findings: clean Knip ≠ validation for UI shim/type deletions; audit explicitly or scoped config.
- `.dependency-cruiser.cjs` checks cycles/unresolved/orphans only; does not enforce all domain boundaries — review explicitly when moving shared code.
