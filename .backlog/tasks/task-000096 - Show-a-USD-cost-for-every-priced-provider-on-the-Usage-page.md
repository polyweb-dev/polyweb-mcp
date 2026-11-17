---
id: TASK-000096
title: Show a USD cost for every priced provider on the Usage page
status: In Progress
assignee:
  - '@devin'
created_date: '2026-11-17T01:21:00Z'
updated_date: '2026-11-17T02:25:00Z'
labels:
  - backend
  - frontend
  - usage
dependencies: []
type: bug
ordinal: 82000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
The project Usage page (Totals by provider) shows a Cost only for providers that record usage in USD (Exa, and You.com through its estimated usage gap). Brave records `1 REQUEST`, Parallel records SKU counts as `REQUEST`, and Tavily records `CREDIT`, so their Cost cell is "—" and the Cost total undercounts (one fan-out search showed $0.012 against a real ~$0.030). The price is known: the provider limit catalog (`conversion_profile.native_usd_per_unit`) prices every call and the limits ledger (`provider_limit_events.crd_debit_text`) already stores it, but that ledger is installation-wide and the project usage read only reads `usage_events`. The fan-out search also writes a synthetic `aggregated` usage event (units 0, no unit kind) that counts as an extra call and makes an "Other units: 0" column appear.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 Each recorded usage event stores a USD cost and whether the cost is reported by the provider or estimated from the catalog price, priced at the time of the call
- [ ] #2 A provider that reports USD keeps its reported cost; a provider that reports requests or credits gets the native units multiplied by the catalog USD price per unit for its provider, operation and auth mode
- [ ] #3 Parallel usage is priced with its mode and bundle rules, not a flat per-call price
- [ ] #4 Events with no known price keep an unknown cost; an unknown price never becomes zero
- [ ] #5 The project usage totals expose the summed USD cost and an estimated flag per provider and operation
- [ ] #6 The Usage page Cost column shows the cost for Brave, Parallel and Tavily rows, marks estimated costs, and the Cost total includes them
- [ ] #7 The synthetic fan-out aggregated event does not add an extra call or an Other units column to the Usage totals
- [ ] #8 Unit, integration and UI tests cover the pricing fallback and the UI rendering; verified in the dev environment with seeded data
- [ ] #9 A successful call whose provider reports no usage at all (for example Firecrawl search, where the SDK drops creditsUsed) still records one estimated usage event from the catalog standard cost for that request, so it counts as a call and has a cost
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. Backend pricing helper (new services/usage_cost.py): price each successful usage event at record time. USD kind -> reported (estimated when metadata.estimated). FREE -> 0. Adapter metadata cost_usd -> estimated. Otherwise native units x catalog unit price for (provider, operation, auth mode): unit kind equal to the catalog native unit -> native_usd_per_unit; REQUEST event on a USD-native record (Brave) -> standard USD call cost; Keenable keyed CREDIT on REQUEST record -> native_usd_per_unit; price 0 -> 0; else unknown (None).
2. Parallel: expose its mode/bundle pricing as a public function and use it for Parallel REQUEST/SKU events.
3. Persistence: migration 0009_usage_event_cost adds usage_events.cost_usd and cost_source (nullable text), backfills USD rows (reported/estimated) and FREE rows (0). record_usage takes an optional cost. _sum_usage_rows sums cost_usd, flags estimated, counts unpriced events, and skips the fan-out "aggregated" bookkeeping row (constant in models/contracts.py).
4. Contract: ProviderUsageTotal gets cost_usd (decimal or null), cost_estimated (bool), unpriced_event_count (int). Exact-shape tests updated on purpose.
5. UI: decode the three fields; Cost column sums cost_usd, marks estimates with "~" and a hint, keeps Free and unknown rules.
6. Verify: targeted unit/integration tests, ruff/mypy, UI depcruise/knip/lint/typecheck/test/build; dev run with seed_dev.py on a new dev DB and local API/UI (no change to the live Docker stack).
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Dev E2E round 1: Brave/Exa/Parallel/Tavily/You.com costs correct, aggregated row excluded. Found: Firecrawl search succeeds with usage=None (firecrawl-py 4.41 SearchData drops creditsUsed) so no usage row; overview card showed ~$0.030000000000000002 (float sum). Added AC for a catalog fallback event; float fixed by rounding running sums in usageTotalsView (regression test in usageFigures.test.ts failed before: received 0.030000000000000002).
<!-- SECTION:NOTES:END -->
