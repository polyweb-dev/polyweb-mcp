---
id: TASK-000057
title: 'Projects UI design pass: unify shell, pages and controls (unslop)'
status: In Progress
assignee:
  - '@devin'
created_date: '2026-11-07T01:00:00Z'
updated_date: '2026-11-09T00:36:00Z'
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
- [ ] #1 One neutral graphite token ramp, hairline borders and one accent drive every page
- [ ] #2 Every workspace page uses the shared PageHeader, and tables, inputs, selects and row-action menus share one style
- [ ] #3 The sidebar shows one project switcher with readable full names, one project section group and one System group
- [ ] #4 Project overview shows setup state, usage figures, route order and recent activity
- [ ] #5 Project Providers shows one route-order table instead of a two-table card per provider type
- [ ] #6 Project Settings shows each value once, with the default and limit as quiet hints
- [ ] #7 Frontend unit tests, lint, typecheck, knip, depcruise and build pass
- [ ] #8 An independent judge rates every page before and after the pass
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
<!-- SECTION:NOTES:END -->
