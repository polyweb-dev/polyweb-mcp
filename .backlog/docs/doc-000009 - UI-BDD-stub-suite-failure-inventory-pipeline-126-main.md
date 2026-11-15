---
id: doc-000009
title: UI BDD stub suite failure inventory (pipeline 126, main)
type: other
created_date: '2026-11-15T17:24:00Z'
updated_date: '2026-11-15T18:14:00Z'
---
# UI BDD stub suite failure inventory

Source: Woodpecker ui-bdd #126 (main, c7f0845, `PLAYWRIGHT_GREP=@stub`): 106 of 260 scenarios failed, 154 passed, 29.4 min on one worker. Branch run #125 (task-000002, 3fd3669) failed the same 106 scenarios. Reports: Gitea generic package `polyweb-ui-bdd`, versions `pipeline-126-*` and `pipeline-125-r1-*`.

Analysis by an investigator agent (Devin GPT-6 Sol) on 2026-11-15 for TASK-000002; the repair is TASK-000083. It is a static analysis of the report and source, with no browser re-run, so confirm each group before you fix it.

Correction to the first hypothesis: `GET /api/v1/projects/{id}/routing/order` IS stubbed (`polyweb-ui/tests/steps/vaultStub.ts`). The stub builds the order from assigned pools plus keyless Keenable, so a scenario that seeds no pool sees only Keenable in the Playground picker. The static audit found no unstubbed endpoint that explains a failure. `getProviderLimits` and `updateProviderLimit` have no stub, but they also have no callsite.

## Root-cause groups (scenario count)

1. Project order contains only Keenable (8): pinned search/fetch scenarios and the Playground parity scenario. Seed the pools the scenario pins, or let the order fixture offer them.
2. Unscoped `Credit details for <provider>` locator matches the card and the Key balances row (17). The step locator is stale; scope it to the intended surface.
3. Balance-bar accessible name renamed from `credit units remaining` to `<provider> balance remaining` (10).
4. Non-reporting rails no longer render a card (7). The test helper only knows the retired article/listitem shapes.
5. Credential-replacement fixture changes only `secret_presence`, not the dashboard rail (1).
6. A failed refresh clears the previously displayed state (3). Possible app defect: `DashboardContext.tsx` and `useProviderStatus.ts` catch blocks clear their data.
7. Quota actions moved or were renamed, for example `Balance history` became `View balance history` (6).
8. Older quota copy and DOM assumptions (15): `Credit mode` became `Balance type`, `Credits left` became `Balance left`, `<s>` elements are gone, and others.
9. Column and cell contracts changed (Activity list, trace summary, usage totals).
10. Trace stage names and the raw-data disclosure changed (5): `Route selection` became `Provider selection`; raw data is now an `AdvancedSection` button, not `<details>`.
11. Trace score, latency and number formatting changed (4).
12. Viewport and snippet-scroll assertions conflict with the desktop-only policy (3).
13. Trace notice punctuation (1).
14. Project API-key locators predate the current row and menu (4): `Rotate key`/`Revoke key`.
15. Vault Add key dialog submit was renamed from `Save key` to `Add key` (2).
16. Vault pool controls and the order row were conflated (2).
17. Sidebar identity policy changed (5): email is no longer shown beside the name.
18. Stale sidebar CSS-token assertions (2).
19. Projects empty-state punctuation (2).
20. Five single legacy assertions (retired-path redirect, copy punctuation, tooltip role, `Enabled` vs `On`, switch state).

Possible product defects to rule on, not only stale tests: group 6 (state lost on refresh error), the unsupported-tool tooltip role (group 20), and the narrow-viewport overflow (group 12, out of scope because only desktop is supported).

## Scenario inventory

```
TOTAL 106
01_project_order_only_keyless: 8
  activity-trace-detail | Playground cards, inspector, and waterfall share one presentation | f0e32473
  provider-credits | U7-T14 Out-of-Credits 402 reaches the user at once | 3d630371
  provider-quota-display | Tavily out-of-Credits 402 reaches the user at once | 2b6008d0
  provider-search-fetch | Brave pinned search returns stubbed results or an honest error | 9c679767
  provider-search-fetch | Parallel pinned fetch returns stubbed content or an honest error | decf4d6c
  provider-search-fetch | Parallel pinned search returns stubbed results or an honest error | 99fb43d4
  provider-search-fetch | Tinyfish pinned fetch returns stubbed content or an honest error | 1e80225f
  provider-search-fetch | Tinyfish pinned search returns stubbed results or an honest error | 8083176e
02_double_credit_controls_unscoped_step: 17
  provider-credits | U7-B08 Shared funds pool two operations with local-only grants | f37a37c3
  provider-credits | U7-T05 Shared pool serves search and extract with one minute window | 4883ffc3
  provider-credits | U7-T07 Paid overage continues under pay-as-you-go | bdf53da5
  provider-credits | U7-T12 USD appears once the disclosure is open | d35c085b
  provider-credits | U7-T13 Prod rail shows 1000 RPM headroom with Retry-After | 7a875a44
  provider-credits | U7-T16 Dev consumed headroom shows 90 of 100 requests per minute | 7758b719
  provider-credits | U7-T17 Prod consumed headroom shows 900 of 1,000 requests per minute | 2b233976
  provider-credits | U7-T18 Confirmed prod ceiling shows unknown headroom before dashboard confirms | 36d7b79d
  provider-credits | U7-T19 Deferred dashboard still shows confirmed ceiling at once | 2914fd4c
  provider-credits | U7-T28 Narrow viewport keeps Tavily details inside the viewport | 4308b690
  provider-credits | U7-T29 Fractional USD and USD keep fractions while long zeros trim | b1ba9475
  routing | Tavily card quota details keep Escape and focus return at a narrow viewport | f7872cce
  routing | Tavily card quota details show consumed dev headroom without a PATCH | 95621f8b
  routing | Tavily card quota details show consumed prod headroom without a PATCH | a35dcc03
  routing | Tavily card tier changes from dev to prod without reload with immediate confirmed ceiling | 13efe58f
  routing | Tavily card tier changes from prod to dev without reload with immediate confirmed ceiling | 020a19af
  routing | Tavily card tier keeps the confirmed ceiling while the dashboard refresh is deferred | b1a6edf4
03_renamed_balance_bar: 10
  keenable-card | K09 Keenable keyed funds bar color at 0 capacity | cab02d19
  keenable-card | K09 Keenable keyed funds bar color at 100000 capacity | 7f745a0a
  keenable-card | K09 Keenable keyed funds bar color at 25000 capacity | 575f7e88
  keenable-card | K09 Keenable keyed funds bar color at 50000 capacity | f64aec34
  keenable-card | K09 Keenable keyed funds bar color at 75000 capacity | 6686a0f5
  provider-credits | U7-B01 Finite card shows one bar with 90 percent and funds | a522d728
  provider-credits | U7-B06 One debit refresh moves 4500 to 4495 | fbf1ed62
  provider-credits | U7-B16 Late older dashboard response cannot restore old funds | 505c0ac2
  provider-credits | U7-T15 Brave card stays in USD beside the Tavily card | 949402f9
  provider-quota-display | Brave finite credits render one bar with exact funds | 9cb412c6
04_unknown_keyless_no_card: 7
  provider-credits | U7-B03 Unknown balance price tier and reset show no invented text | c8f7006b
  provider-credits | U7-B04 Known funds without allowance show amounts but no bar | f378a660
  provider-credits | U7-T04 Keyless access reports no Credits quota and no invented headroom | ec030cd7
  provider-credits | U7-T26 Keyless card shows keyless access without numeric rate | 97a89ca0
  provider-credits | U7-T31 Unknown Tavily balance shows no invented bar or rate | a00b5e99
  provider-quota-display | Unknown credits render no invented bar or funds | 69d065f3
  routing | Tavily card tier with keyless access shows compact text and sends no PATCH | 514f392b
05_credential_replacement_fixture_mismatch: 1
  routing | Tavily card tier converges after credential replacement during a delayed PATCH | e13a2fa7
06_failed_refresh_clears_existing_data: 3
  provider-credits | U7-T24 Confirmed save stays after refresh failure | ca340970
  routing | Tavily card tier keeps the saved value when refresh fails after save | 5cf64238
  routing | Tavily card tier with missing PATCH readback shows Confirmation unavailable | 4f81f9a1
07_obsolete_quota_actions: 6
  keenable-card | K09 Keenable actions and details control stay reachable with Escape return | ce90eff1
  provider-credits | U7-B12 Grant modal search-only save with version and period | 5c19061d
  provider-credits | U7-B13 History modal pages cursors with correct facts | d7bbcc46
  provider-credits | U7-B17 Grant manual and history modals trap and return focus | 648bb224
  provider-credits | U7-T08 Grant converts both directions and keeps stored USD | e7c4eb69
  provider-credits | U7-T09 History shows native Credits balances | e1497710
08_old_quota_copy_or_markup: 15
  keenable-card | K09 Keenable search and fetch rate rows share one hourly pool | 5df6228e
  keenable-card | K10 Keenable request counts show whole numbers with strike free and no funds bar | d5ffb682
  provider-credits | U7-B05 Free state shows no invented finite funds | d790e11a
  provider-credits | U7-B09 Brave fetch absent shows no fetch row | 35282f21
  provider-credits | U7-B10 USD manual modal saves 5.00 allowance with 4.12 balance | 8970be0f
  provider-credits | U7-B15 Page keeps USD totals and OAuth slot without native table | 818a8b49
  provider-credits | U7-T01 Tavily native budget shows 1000 of 1000 Credits | 4c87e8ef
  provider-credits | U7-T06 Free exhaustion stops at zero Credits without PAYGO | 107b91fa
  provider-credits | U7-T10 Native totals stay in Credits with extract labels | 26863a5a
  provider-credits | U7-T27 Keyboard opens details and Escape returns focus | 5cf6ed23
  provider-credits | U7-T30 Stale vendor read keeps reset line with unknown rate headroom | b2233f62
  provider-quota-display | Brave manual entry opens a USD balance dialog from the card | c08fd80a
  provider-quota-display | Parallel without a card keeps an action slot and no invented balance | 7312c7b0
  provider-quota-display | Tavily native Credits render with Credits labels | 2e257925
  routing | Tavily card tier slot shows compact labels beside buttons with no numeric rate text | d261b3c1
09_trace_and_usage_column_shape: 4
  activity-traces | Modal and summary-strip geometry hold at desktop width | 7ef73c6b
  activity-traces | Trace list failure shows an error and recovers on retry | 254a1257
  activity-traces | Trace list shows Actions with real buttons and no payloads | 6ef45410
  project-activity-usage | Usage shows this project's totals only and links to Activity | 662fe862
10_trace_stage_labels_or_raw_disclosure: 5
  activity-traces | Provider identities show logo followed by name | 1da49522
  activity-traces | Result and trajectory rows select with the keyboard | 06a8cfb6
  activity-traces | Trajectory fuses timing into rows with a side span inspector | c112fb31
  activity-traces | Trajectory hides transport, parse, and function-level spans | 88f05512
  activity-traces | Trajectory row selection replaces request and response payloads | a8a2f97d
11_trace_score_latency_and_format: 4
  activity-traces | Latency summary counts overlapping provider calls once | b558b1bf
  activity-traces | Single-provider inspector shows recorded metadata before the long summary | c8b36fc0
  activity-traces | Source-null Exa result keeps Exa attribution without a source warning | 2df2a812
  activity-traces | Trajectory ruler and bars share one time axis | d1681057
12_narrow_overflow_and_scroll_contract: 3
  activity-traces | Narrow viewport keeps keyboard selection and focus return | caf8407c
  activity-traces | Narrow viewport keeps the dialog in bounds without horizontal scroll | d865d59f
  activity-traces | Recorded metadata stays visible without scrolling the summary | 7a3b0f65
13_trace_notice_punctuation: 1
  project-activity-usage | Trace detail explains stored-metadata, missing results and unreadable traces | 998aea02
14_api_key_stale_menu_or_cell: 4
  project-api-keys | Issuing a key with no expiration reveals it once and lists it | ad3fff08
  project-api-keys | Revoking a key after confirmation lists it as revoked without actions | 7c8e9f8e
  project-api-keys | Rotating a key with the default 24 hour overlap reveals the new key once | bb653a9e
  project-api-keys | Two tabs on different projects keep separate API key drafts, keys and access | f316c8d6
15_vault_save_key_stale_name: 2
  parallel-oauth-pairing | An owner connects a Parallel key | bee145b9
  project-providers | Free-first Search order places a keyless provider first | c7dc6fc6
16_vault_pool_stale_action_or_row: 2
  account-keys-pools | An owner supplies a project from a vault key | 10361e93
  project-providers | Search order and pool operations stay independent from Fetch | 10201253
17_sidebar_email_policy: 5
  sidebar-account-menu | B3 Expanded account row opens the identity popup | 543eca12
  sidebar-account-menu | B4 Collapsed avatar opens the same popup | 9195dfcc
  sidebar-account-menu | Example #1 | f9cfc726
  sidebar-account-menu | Example #2 | 3da9d787
  sidebar-account-menu | Example #3 | 310c490d
18_sidebar_css_class_drift: 2
  sidebar-account-menu | R1 Avatars use larger centered circles | 471f2301
  sidebar-account-menu | R5 One inset divider sits above the outside account row | ae7260f0
19_project_empty_state_punctuation: 2
  project-discovery | A granted membership appears on focus without a reload | 568cb1f6
  projects-shell | An account without memberships sees the empty state | d666cf29
20_other_legacy_contract: 5
  app-shell-routing | Example #1 | 38414b2c
  project-settings | A stale copy asks for a new preview and writes nothing | ac5c9cc5
  provider-access-flags | Unsupported tools stay off and unavailable | 346f6bf0
  providers-settings-merge | Provider registry is one table with a per-row Health column | 8b43eb34
  settings | Provider operation state survives a page reload | 2a9566a7

```


## Second opinion (Devin Claude Opus 5.5, 2026-11-15)

It agrees with the inventory above and adds the following.

- Zero API traffic: the API logs of #125 and #126 contain only the readiness probe `GET /openapi.json`, so no `@stub` scenario reaches the real API. Its grouping by UI area is G1 Quotas page redesign (59), G2 Playground order from pools (8), G3 sidebar account row (7), G4 Activity/trace views from d8c6041 (17), G5 vault key UI (4), G6 project API keys table (4) and G7 single copy, label or redirect changes (7).
- Underlying cause: CI has gated only `@smoke` since 84a6128. Most step files date from 5660d26 (2026-11-09), and the UI changed after that in 2ac797c, the vault/pool commits of 2026-11-10, and d8c6041/038f59f (2026-11-14).
- Open question: is the duplicate `Credit details for <provider>` button (one in the card, one in its Key balances row, `ProviderLimitsCards.tsx:131-171`) intended UI or an app bug? Sol judged it an intentional two-surface rendering with a stale page-wide locator.
- Possible nondeterminism: "Tavily card tier with missing PATCH readback" failed on `toBeVisible` in #125 and on `toBeDisabled` in #126.
- Suggested repair hygiene: add a lowest-priority catch-all route on app API prefixes that records unstubbed calls, with an After-hook assertion; then `run-ui-bdd.sh` only needs the real API for `@live`.
