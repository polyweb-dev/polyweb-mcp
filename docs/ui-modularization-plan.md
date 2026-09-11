# UI modularization plan

Scope: `freesearch-ui` production UI, its unit/component tests, browser BDD tests, and frontend tooling. Planning audit dated 2026-09-11. No application refactor is included in this document. Existing backend work is outside scope.

## Recommendation

Keep the current React/Vite application and reorganize it around business ownership and user-facing features. Extract cohesive components and pure functions first; split shared state only after behavior is characterized. Do not introduce a monorepo, a new state library, a new router, or a design-system replacement as part of this refactor.

A component describes a piece of the screen; a hook manages React state/lifecycle; a plain function transforms data; an API module talks to the server. A feature assembles these for a user task. A domain owns business data used by several features. Directory moves alone do not establish these boundaries.

## Verified baseline

| Check | Audit result |
| --- | --- |
| `pnpm depcruise` | Pass: 114 modules, 367 dependencies; current rules check cycles, unresolved imports and orphans, not feature boundaries. |
| `pnpm knip` | Fails on unused `canonicalDashboardFixture` export in `src/test/backendFixtures.ts:324`; also reports configuration hints. Investigate actual fixture consumers before deleting anything. |
| `pnpm lint` | Exit 0, but 64 warnings: 38 multi-component, 9 function length, 7 file length, 6 complexity, 2 Fast Refresh, 1 nested callbacks, 1 unused variable. |
| `pnpm typecheck` | Pass; this uses `tsconfig.vitest.json`, which disables unused-local/parameter checks. It does not replace production or E2E checking. |
| `pnpm build` | Pass; Vite warns that the main JavaScript chunk exceeds 500 kB. Consider route splitting separately after state lifetime and appearance are protected; do not raise the warning threshold to hide it. |
| `pnpm typecheck:e2e` | Pass. |
| `pnpm test` | Fails: 50 files, 785 tests, 761 pass and 24 fail. Rerunning the two failing files reproduced all 24 failures. |
| Browser acceptance | Inspected 13 feature files / 73 scenarios and 7 committed Chromium PNG baselines. Browser suite was not executed in this audit; no visual equivalence claim is made. |
| Trial production check with `--noUncheckedIndexedAccess --exactOptionalPropertyTypes` | 11 diagnostics. Flags were passed on the command line; configuration was not changed. |

The code-quality skill describes packages/apps boundaries that do not exist here. The checked-in frontend configuration is the baseline for this plan.

Before refactoring, repair the existing test baseline in a separate commit. Twenty-three failures in `parallelOAuthPairing.test.tsx` occur at structural selectors using `closest("div.grid")` and nested `div.border`; their OAuth assertions are not reached. Replace those selectors with scoped semantic queries that identify the same provider row and retain every downstream assertion. One failure at `SettingsKeyVault.k1.test.tsx:626` expects `min-w-[1280px]` while the current DOM uses `min-w-[960px]`. Check the intended current layout and browser baseline before resolving that discrepancy: do not blindly change either the UI or the expectation to make the test pass. Establish green behavior tests before beginning structural changes.

## Main findings and specific extractions

Line counts below are ESLint counts excluding blank/comment lines where configured, not physical file lengths.

| Current file | Problem | Proposed destination / extraction |
| --- | --- | --- |
| `src/context/FreeSearchContext.tsx:200` | Provider function is 549 lines; owns provider management, keys, routing, execution, telemetry and toasts. | Small domain providers and command hooks, composed by `app/AppProviders.tsx`; retain `useFreeSearch` temporarily as an adapter. |
| `src/components/search/SearchPlayground.tsx:33` | 598-line component, complexity 29. | `features/playground/ui/PlaygroundPage.tsx`, composer, search results, result card, fetch result, request options and waterfall components; `model/usePlaygroundController.ts` for interaction coordination. Extract by actual semantic UI sections, retaining JSX/classes. |
| `src/components/quota/QuotaAnalytics.tsx:288` | Page complexity 23, 528-line file, many embedded components and exported helper. | `features/quota/ui/QuotaPage.tsx`, quota cards, totals/table/empty-state components; move pure calculations to quota model modules. Keep `services/quotaDisplay.ts` a single shared source for display semantics. |
| `src/components/quota/ManualQuotaModal.tsx` | 367-line file with multiple components. | Modal shell, form sections and field components under `features/quota/ui`; retain and relocate existing `useManualQuota` and `manualQuotaMath` rather than duplicating them. |
| `src/components/oauth/OAuthPairingModal.tsx` | 415-line file, 150-line flow hook, mixed helper/component exports. | `features/oauth/model/usePairingFlow.ts`, pure flow helpers, dialog and state-specific panels under `ui`; preserve the separate existing `useOAuthPairing` responsibility until their lifecycles are understood. |
| `src/components/settings/SettingsProviders.tsx` | 449-line file containing page, rows, details and controls. | `features/settings/ui/providers/` with page/section, row, detail modal and cohesive controls. Provider data/commands belong to `domains/providers`. |
| `src/components/layout/StatusBar.tsx:8` | 201-line function, complexity 20. | `app/layout/StatusBar.tsx` composing status sections; pure status-summary calculation in a model helper. Preserve sticky in-flow positioning. |
| `src/components/layout/Sidebar.tsx` and `src/App.tsx` | Mixed shell components; navigation ownership partially lives in Sidebar. | `app/layout/`, `app/routes.ts`, `app/DashboardShell.tsx`, `app/AppProviders.tsx`. Route identifiers belong to app routing rather than a visual component. |
| `ActivityStream`, `ProviderRanks`, `RouteSimulator`, `RoutingStrategy`, `SettingsKeyVault`, `PillTabs` | Multiple components per file; simulator also exceeds function limit. | Extract named sibling components in their owning module; keep reusable tab primitives in `shared/ui`. |
| `src/components/routing/routingUtils.ts:21` | Complexity 14. | Named business predicates and policy helpers in routing model; retain decision ordering and test all outcomes. |
| `src/services/api/freesearchApi.ts:24` | Request complexity 14; `return body as T` trusts arbitrary JSON. | `shared/api/http.ts` for transport/error normalization; domain endpoint adapters and wire types; runtime decoding is a separate compatibility-tested change. |
| `src/services/api/{backendTypes,mappers,providerCatalog}.ts`, `src/types/freesearch.ts` | Broad central ownership creates future coupling. | Split types and mappers by providers, routing, dashboard, execution and quota. Keep provider catalog with provider domain; generic HTTP code must not import it. |
| `src/test/{backendFixtures,fetchMock}.ts` | Fixture file length and mock complexity warnings; helpers fall outside current test exemptions. | Split fixtures and mock request handling by endpoint/domain with a small central dispatcher, retaining response fidelity. |

## Target structure and dependency rules

```text
src/
  app/                 # startup, route table, shell, provider composition
    layout/
  domains/
    providers/         # catalog, statuses, keys, priorities, provider commands
    routing/           # persisted routing config and routing policy
    dashboard/         # authoritative usage, totals and quota snapshots
    execution/         # search/fetch commands, results, errors, request mapping
  features/
    playground/
    routing/
    quota/
    activity/
    settings/
    oauth/
  shared/
    api/               # HTTP transport and generic error handling
    ui/                # reusable, business-independent primitives
    notifications/     # toast state and rendering
    lib/               # genuinely general small helpers
  test/                # shared test setup and typed endpoint fixtures
tests/
  features/            # preserve Gherkin acceptance scenarios
  steps/               # BDD wiring and typed support
  snapshots/           # approved browser baselines
```

Within a domain or feature use `ui/`, `model/`, and `api/` only when that module needs them. Do not create empty layers or a directory for every function. Colocate unit/component tests with their production owner; keep cross-feature acceptance tests under `tests/`.

Enforce with Dependency Cruiser and restricted-import rules:

1. `app` may compose features and domains. Features may consume domain public APIs and shared code. Domains may consume shared code. No upward imports.
2. No feature-to-feature imports. Settings can host OAuth through app-supplied composition slots; genuinely shared provider UI belongs to provider domain, not a generic shared folder.
3. Default to no domain-to-domain imports. Coordinate routing configuration, execution completion and dashboard refresh in app composition through narrow typed inputs/callbacks. If a concrete dependency is necessary, document the acyclic edge explicitly.
4. Import another module through its small `index.ts` public entry point. Inside that module use direct imports, never its own barrel. Avoid a global barrel that re-exports the entire application.
5. `shared/ui` must not import API clients, business contexts, provider catalogs, or feature types. A provider logo containing business identity belongs in `domains/providers/ui`; the underlying image primitive can remain shared.
6. Production code must not import test fixtures. Include test imports in architecture analysis with appropriate entry points, without declaring tests dead code.
7. Match both aliases and relative imports. Verify each new restriction rejects a representative forbidden edge and allows intended composition before enabling it broadly.

## State and React rules

Extract `mapProviderRows`, `updateProviderFromWire`, `overlayDashboardQuotas`, priority patch calculation, request builders and optimistic usage-event builders before changing state ownership. Keep their existing semantics.

The quota overlay joins providers and dashboard data: its final owner should be an app composition selector with narrow typed inputs, rather than making the provider domain import dashboard internals. Likewise, move the StatusBar's routing policy dependency into routing's public model API, and supply OAuth actions to the quota page from an app-level usage-page composition. These address actual existing cross-feature imports.

Then introduce focused providers/hooks for providers, routing, dashboard, execution and notifications. `AppProviders` mounts them above routes so state currently surviving navigation continues to survive. Keep local input drafts, expanded rows and modal visibility with the nearest relevant feature component. Do not accidentally create one independent data store per hook consumer.

Use an adapter for the old `useFreeSearch` interface during migration. Migrate consumers one feature at a time and remove it only when no production or test consumers remain. Splitting files while retaining a single giant subscribed context is an intermediate step, not the final design. Expose narrow state/command hooks; split contexts where updates are independent. Do not add memoization everywhere without evidence.

Preserve these contracts explicitly:

- Provider/dashboard responses may arrive in either order; quota overlays must remain correct.
- Priority moves serialize writes and compensate completed writes on failure, followed by an authoritative refresh.
- Successful execution adds the current optimistic usage event and refreshes dashboard telemetry.
- Search/fetch loading, error and retained-result behavior must match the existing UI, including timeout and provider selection behavior.
- Routing update failure recovery, secret-source precedence messaging, manual quota null/404 handling and OAuth timer cleanup must survive extraction.
- Route paths `/playground`, `/routing`, `/usage`, `/activity`, `/settings`, plus root, legacy `/providers` and unknown-path redirects, remain unchanged.
- The playground composer must retain the same form/input nodes when moving from the hero state to the docked state: existing tests check node identity, input value and focus. Rendering separate replacement forms for these states would violate that contract.

Define components at module scope, preserve keys and mounting positions, keep Hooks unconditional and top-level, keep render pure, and treat props/state as immutable. Effects synchronize external systems and must clean up timers/subscriptions/requests; event-driven work belongs in event handlers. Compute derived data instead of copying it into synchronized state. These are grounded in the [Rules of React](https://react.dev/reference/rules) and [Managing State](https://react.dev/learn/managing-state).

One component per file and the size budgets are project conventions, not React runtime requirements. Keep the existing exceptions for compound primitives under `components/ui` when relocating them to `shared/ui`; do not broaden them to feature code. Extract semantic components, not arbitrary fragments solely to meet line counts.

## Strict typing and lint enforcement

1. Preserve `strict`, `verbatimModuleSyntax`, and existing production unused checks. Add `strict` to the Node/tooling config, which currently lacks it. Keep separate production, unit-test and browser-test checks; a passing unit-test tsconfig is insufficient.
2. Enable `noUncheckedIndexedAccess` and `exactOptionalPropertyTypes` incrementally across app and tests. The trial found unchecked indexing in activity/priority code and optional-value mismatches in playground requests, quota/settings props and HTTP signals. Guard array lookups and intentionally omit absent properties; do not hide failures with non-null assertions or indiscriminate `| undefined`. TypeScript documents these semantics in its [TSConfig reference](https://www.typescriptlang.org/tsconfig/).
3. Adopt type-aware ESLint with an appropriate TS project configuration, then `no-floating-promises`, `no-misused-promises`, unsafe-operation checks, exhaustive switches and consistent type imports. Ensure colocated tests and E2E support belong to linted TS projects; do not silence project-inclusion errors with broad ignores. See [typed linting guidance](https://typescript-eslint.io/getting-started/typed-linting/).
4. For module APIs, specify props, command arguments/results and wire/domain types. Prefer inference for obvious local values. Use discriminated unions for states with mutually exclusive payloads, particularly OAuth and async operation status, after preserving existing transitions in tests.
5. Treat external JSON as `unknown`; endpoint decoders narrow it to wire types before mapping to view models. Preserve documented nullable/optional fields and tolerated responses. Introduce validation separately from file moves because rejection behavior can change functionality. Do not claim a generic `request<T>` cast validates data.
6. Keep typed fixtures using `satisfies` and typed mock signatures. Negative tests may deliberately construct invalid `unknown` payloads, but should not require broad `any` exemptions. Gradually remove the current blanket test `no-explicit-any` exemption after fixing fixtures.
7. Keep current budgets: 300 file lines, 100 function lines, complexity 12, depth 4, nested callbacks 3, parameters 4. Reach zero warnings, then enforce `eslint . --max-warnings 0`. During migration use a recorded baseline and require touched modules to be clean with no new violations; do not lower thresholds or add suppression comments to make checks pass.
8. Distinguish generated output from maintained test support. Playwright emits `tests/features-gen`, while several existing excludes name `.features-gen`; align lint/dependency/dead-code tooling with actual generated paths without excluding authored tests.

## Ordered implementation slices

| Slice | Work | Required exit condition |
| --- | --- | --- |
| 1. Baseline | Record test inventory/results, lint warnings, coverage and approved visual images; characterize gaps before structural edits. | Existing failures documented separately; behavior/appearance baseline reproducible. |
| 2. Enforce ownership | Document target rules; add import checks incrementally; establish accurate tooling/test discovery. | Rules validate actual paths and reject forbidden edges; no test disappears. |
| 3. Pure model extraction | Move types, mappers, priority/request helpers and transport error helpers, preserving logic. | Existing assertions pass; helper branch coverage and API payload semantics preserved. |
| 4. Leaf UI extraction | Separate shell/sidebar/status, activity, routing and settings child components; move reusable primitives. | Same DOM structure/classes/roles and approved screenshots; touched files meet lint budgets. |
| 5. Complex UI extraction | Split playground, quota/manual quota and OAuth into cohesive UI and controller modules, one feature per PR. | Success/error/loading/empty states, focus/keyboard behavior, and timers remain covered. |
| 6. Shared-state split | Introduce domain providers behind adapter; migrate each feature to focused hooks; remove adapter last. | Cross-route state, request ordering, rollback and refresh behavior verified. |
| 7. Typing hardening | Apply strict options and typed lint; validate external responses in a separate sub-slice. | Production, unit and E2E typechecks pass without unsafe casts or weakened negative tests. |
| 8. Final enforcement | Remove transitional exports; fix confirmed Knip issues; enforce zero-warning lint and complete dependency rules. | Full build/tests/visual comparison pass; no widened exclusions, reduced assertions or lowered gates. |

Keep mechanical moves and behavioral/type-validation changes in separate commits. Avoid incidental CSS cleanup, changing loading behavior, component-library upgrades, or endpoint changes. Small independent PRs make visual and behavioral regressions attributable and reversible.

## Test and appearance preservation policy

Keep all existing test cases, Gherkin scenarios and assertions. Update imports and mock targets only where needed; maintain a before/after mapping of moved test files and discovered test counts. A renamed suite must still execute. Never replace a user-facing integration assertion with a mocked internal helper assertion.

Several existing tests read source files directly: playground `pg-s*`/`pg-f1`, route simulator `r-sim`, provider settings `s-p*`/`p1-final`, key vault `k1`, failover `f1f2`, and app/sidebar/status contracts. They can fail after a correct extraction. Inventory each checked invariant before moving its owner: retarget source checks when the code location changes, or replace each check with an equally strong rendered DOM/class/focus assertion and explicit architecture check as appropriate. Do not simply delete failing source-based tests. Retain an app-provider integration suite for parallel bootstrap and cross-domain refresh even after redistributing focused domain tests.

Before changing each behavior, add characterization only where coverage is missing: competing dashboard/provider completion orders, partial priority rollback, timeout/failure, route persistence, modal close/unmount, and OAuth polling cleanup. Test observable UI and network payloads; use unit tests for extracted policy and mapping functions.

Capture deterministic screenshots before refactoring across routes, light/dark themes, representative viewport sizes, dialogs and meaningful loading/empty/error states. Fix time, fixtures and animation where needed. Preserve fonts/assets/CSS tokens, markup wrappers, class strings, accessibility names, keyboard/focus behavior and sticky layout. Review image differences; do not regenerate baselines merely because code moved.

The seven existing PNGs cover routing, mobile simulator/settings and selected keyboard/reduced-motion states, with a 1% pixel-difference tolerance and dynamic-content masks. Missing baselines include desktop playground/usage/activity/settings, result preview/JSON, OAuth/manual-quota dialogs and drawer states. Add these before changing their markup; do not widen the existing tolerance or masks. The current reduced-motion helper forces transitions to zero before asserting zero duration: run the semantic reduced-motion check without that override, retaining animation suppression only for deterministic image capture.

Only `@stub` and `@visual` browser scenarios receive backend interception; other scenarios require a live backend. Generate BDD specs and run deterministic, visual and live-integration groups separately with explicit environment prerequisites. A stubbed pass is not proof of live integration.

Request concurrency is a separate uncovered risk: execution currently lacks generation guards, and overlapping completions can overwrite results or clear loading prematurely. Add deferred-promise characterization tests before extracting lifecycle code. If adopting latest-request-wins or new cancellation behavior, treat that as an explicit bug-fix slice with its own assertions, not an unnoticed semantic change during modularization. The current UI buffers terminal HTTP responses; there is no streaming implementation to preserve.

For replacing source-string tests, introduce the replacement first and demonstrate that it fails on a representative deliberate regression before removing the old assertion. This is particularly valuable because twenty test/step modules read production source directly.

Required final checks from `freesearch-ui`: `pnpm depcruise`, `pnpm knip`, `pnpm exec eslint . --max-warnings 0`, `pnpm build`, `pnpm typecheck`, `pnpm typecheck:e2e`, `pnpm test`, and `pnpm test:e2e`. Check coverage using the existing Vitest coverage provider and record per-module branch coverage before/after. Preserve mutation testing scope; use targeted mutation checks for extracted decision-heavy logic and compare meaningful surviving mutants. Existing configs do not define coverage or mutation score thresholds: establish measured baselines rather than inventing a claimed current gate.

Completion means the user sees and can do the same things, existing tests are still discovered with equally strong assertions, module imports obey enforceable ownership rules, and lint/types/build/tests pass. A directory tree alone is not completion.
