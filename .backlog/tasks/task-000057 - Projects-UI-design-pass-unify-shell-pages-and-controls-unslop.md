---
id: TASK-000057
title: 'Projects UI design pass: unify shell, pages and controls (unslop)'
status: Done
assignee:
  - '@devin'
created_date: '2026-11-07T01:00:00Z'
updated_date: '2026-11-09T11:38:00Z'
labels:
  - frontend
  - ui
dependencies: []
references:
  - docs/UI-ENHANCEMENTS.md
priority: high
ordinal: 40000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
The Projects UI (TASK-000046..48) works but reads as clunky: two navigation systems stacked in the sidebar, page headers that differ per page, ad-hoc tables, forms and selects, a near-empty project overview, a bloated per-provider Providers page, and duplicated values on project Settings. The owner asked for an unslop pass that keeps the teammate's API and behaviour, uses T3 Code as the craft baseline, and is reviewed by an independent judge with 1-10 page ratings.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 One neutral graphite token ramp, hairline borders and one accent drive every page
- [x] #2 Every workspace page uses the shared PageHeader, and tables, inputs, selects and row-action menus share one style
- [x] #3 The sidebar shows one project switcher with readable full names, one project section group and one System group
- [x] #4 Project overview shows setup state, usage figures, route order and recent activity
- [x] #5 Project Providers shows one route-order table instead of a two-table card per provider type
- [x] #6 Project Settings shows each value once, with the default and limit as quiet hints
- [x] #7 Frontend unit tests, lint, typecheck, knip, depcruise and build pass
- [x] #8 An independent judge rates every page before and after the pass
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. Baseline screenshots of all pages and an independent judge rating. 2. Tokens and shared primitives: graphite ramp in index.css, button variants, PageHeader, panel/table/field classes, row action menu. 3. Shell: project switcher, compact nav rows, System group, account menu holds Account. 4. Project pages: overview, projects list, members, API keys, providers, settings, usage, activity, playground. 5. System pages: credentials, capacity, accounts, account; header and casing fixes on routing, provider usage, provider settings. 6. Update unit tests and run the frontend gates. 7. Judge re-rates the after screenshots; fix the findings.

Lane r4-ufc-budget-2: recurring UTC provider budgets with original-window settlement; shared budget form; USD UI contracts; focused migration, rollover, API, UI and quality checks.
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Baseline judge (Codex GPT 6.1 Sol, high): 4.5/10 overall; screenshots in .runtime-tmp/shots/before. Kept the pinned Carbon Black palette (carbon-black-theme tests) and the Playground's accepted PG-S* specs; added supporting tokens and fs-* component classes in index.css (moved h1-h4/p/code defaults into @layer base so utilities win). New shared primitives: Section, EmptyState, StatusDot, RowActionsMenu, Stat, FactList, formatTime. Reworked shell (project switcher, 32px rows, System group, Admin renamed Accounts), Overview (stats, recent activity, route order), Projects table + side create form, Members, API keys (menu row actions, side issue form), Providers (route-order table + keys table; removed ProviderTypeSection/ProviderBindingsTable/ProviderCredentialsTable/CredentialRowActions), Settings (one value per row, hints, sentence-case saves), Usage, Activity, System credentials, Capacity, Accounts, Account, and PageHeader on Routing/Provider usage/Provider settings. Gaps found: no API path for a keyless Keenable credential (422 on empty secret); delegate wrote an empty encrypted secret into freesearch.dev.db to test. Unit tests for shell and project pages updated (25 files, 550 pass); lint 0 errors, typecheck and build pass; knip/depcruise only pre-existing unused files.

After judge (Codex GPT 6.1 Sol, high): 6.5/10 overall, up from 4.5 (screenshots in .runtime-tmp/shots/after and /final). Final round applied: visible Add route per key row with a priority hint, member menu divider between role and membership actions, Settings column capped at 960px, API key empty-state guidance, Capacity pool empty state and primary Add pool, outline View details in Activity, kill-switched keyless providers marked in the No key yet line. Provider tests and Playwright-BDD steps/features updated (bddgen and typecheck:e2e pass; browser e2e not run - CI). Full unit suite earlier in the round: 194 files, 2290 tests pass. Follow-ups from the judge (not done): global Routing simulation-only wording, Provider usage card stack to a table, Provider settings cascade copy, metric time ranges and unit labels (Playground Units), Activity row identity and metadata-only trace dialog default, Playground control order, role per project in lists, keyless credential API.

Lane r4-ufc-budget-2 completed: provider budgets use day/week/month (default month), exact USD API fields, shared BudgetFields/NumericField and shared usage text. Revision 0007 follows 0006, converts legacy date ranges to monthly settings and keeps history; persisted reservation window keys isolate rollover and late finalize/release. USD UI wire types and spend_usd replace CRD conversions; native vendor credits remain. Validation: 560 affected Vitest cases, 30 backend unit cases, 78 focused SQLite/API/service cases plus the affected control-API test, 74 offline Behave scenarios across focused runs; Ruff, touched-source MyPy, TS, ESLint, BDD generation, build pass. Depcruise has zero errors; Knip retains only documented KpiCard.tsx and lib/utils.ts baseline. Live DB backed up to .runtime-tmp/orch/db-backup/freesearch.dev.db.pre-budget2; copy upgrade integrity check ok; only API 8011 restarted and live schema/revision verified. No commit/push/stash/reset.

Round 4 (owner feedback 2026-11-08/09), orchestrated with independent reviewers.
- Product: personal key vault per admin account; pools cut from vault keys (one project each; Search/Fetch operations; request rate; USD budget per day/week/month; overcommit on); one transferable Provider owner per project; roles Project admin / Developer with 9 permission switches; trace policy Metadata only / Full (default Full), keep all traces; per-project Search and Fetch orders with Free first / Lowest cost / Custom on the project Providers page; System Providers is a catalog; System Keys, Capacity, Accounts, Routing page/simulator and global /api/v1/users routes removed; USD only for budgets and spend (decision 18).
- Backend: Alembic revisions 0003 (vault + RBAC conversion), 0004 (pool limits), 0005 (pool budget), 0006 (keyless system credentials), 0007 (provider budget period day/week/month). New GET /api/v1/provider-prices; /crd-grants -> /budgets with *_usd fields; per-key quota routes owner-scoped (ruling R9).
- UI reviews (Opus 5.5, independent): 7.3 -> 8.2 -> 8.6 -> 8.8 -> 8.9 -> 9.0 -> 9.1 (.runtime-tmp/orch/r4/review-r4*.md; screenshots r4/shots3..shots9).
- Code reviews: six per-feature reviews found 1 blocker, 8 major, 19 minor; all fixed (security: fetched-JSON secret scrubbing in Full traces, owner-scoped per-key quotas, archived-project access expansion; budgets: request-specific pricing, free keyless $0, exact manual USD; contracts: migrated per-op limits, legacy trace defaults). Pedantic tests removed per owner rule.
- Verification: Vitest 2,473 pass; typecheck, lint, depcruise, knip (baseline only), build, BDD generation pass; backend unit 2,191 pass; offline Behave 258 pass / 0 fail; CI (Woodpecker) api-integration #47 1,655/0, api-bdd #45 288/0, api-latency #46 pass (p95 93.8 ms). Commits f2e3ff2..f4b0479 on feature/ui-quality-r4 (pushed).
- Open items: merge separate Search/Fetch provider budgets on Quotas into one (deferred); key-wide contention splitting (deferred); vault API lacks key last-used; possibly dead provider-view backend fields; Exa usage API needs a service-account key; STE scan findings in two operator docs; build chunk > 500 kB warning; duplicate backlog id TASK-50 noticed (not changed).

Owner confirmed 2026-11-09: merged via PR #64 (into chore/local-e2e-provider-seed), PR #61 (into feature/project) and on to main; branches cleaned up to main only.
<!-- SECTION:NOTES:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
Round-4 UI quality pass and owner feedback features on feature/ui-quality-r4: vault keys and pools replace system keys/capacity, per-project Search/Fetch provider order, two-role RBAC with permission switches and a Provider owner, simplified trace policy, USD-only budgets with day/week/month periods, and removal of the Accounts and Routing pages. Independent Opus UI review reached 9.1/10 (from 7.3) across all pages, dialogs and menus; six per-feature code reviews were fixed; local gates and CI integration, BDD and latency pass. Awaiting owner confirmation before Done; open items are listed in the implementation notes.
<!-- SECTION:FINAL_SUMMARY:END -->
