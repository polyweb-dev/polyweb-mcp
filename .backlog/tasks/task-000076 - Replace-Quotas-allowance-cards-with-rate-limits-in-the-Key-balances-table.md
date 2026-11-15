---
id: TASK-000076
title: Replace Quotas allowance cards with rate limits in the Key balances table
status: To Do
assignee: []
created_date: '2026-11-14T16:00:00Z'
labels:
  - frontend
  - ui
dependencies: []
priority: medium
type: task
ordinal: 65000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
The Quotas page has two sections that repeat each other:

- **Allowance left** (`polyweb-ui/src/features/quota/ui/ProviderLimitsCards.tsx` and `ProviderLimitsCard.tsx`) shows one card per provider. Each card holds:
  - the free-tier rate-limit meters, for example Keenable "Search, Fetch · 997 of 1,000 requests left this hour" and Tinyfish search per hour plus fetch URLs per day;
  - Tavily's balance meter, its Refresh button and its rate-tier selector.
- **Key balances** (`KeyBalances.tsx`) is a table with one row per provider key. Its columns are Provider, Key, Balance and Last refresh, plus Refresh and "…" actions.

Credit balances already appear in the Key balances table (Tavily "958 credits left", Firecrawl, You.com). The cards take most of the page and mostly restate those balances.

Remove the Allowance left cards. Make the Key balances section the single place for quota state, and show each provider's rate limits there clearly. For example:
- a "Limits" column holding one compact line per window, such as "Search 497/500 per hour" and "Fetch 1,000/1,000 per day", with a thin meter;
- or an expandable row detail.

Pick the layout during implementation, and confirm it with a screenshot review.

Everything the cards do today must keep working from the table:
- per-provider refresh;
- the Tavily rate-tier selector, for example in the row's "…" menu or in the limits cell;
- OAuth pairing actions (`renderOAuthActions`);
- the manual balance anchor and prefill flow;
- the provider info tooltips;
- the "Free" badge.

Keyless free providers such as Keenable have no key row today. They need a row (for example Key "No key needed") so their limits stay visible.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 The Quotas page no longer renders the "Allowance left" section or its per-provider cards
- [ ] #2 The Key balances table shows each provider's rate-limit windows: capability, remaining of limit and period. Each window has a compact meter, and the windows stay readable when a provider has several, such as Tinyfish search per hour and fetch per day.
- [ ] #3 Keyless or free providers (Keenable, Tinyfish) have a row that shows their limits
- [ ] #4 Every action from the removed cards is still reachable from the table: refresh, the Tavily rate tier, OAuth pairing, the manual balance anchor, info tooltips and the Free badge
- [ ] #5 Desktop and 390 px layouts, in dark and light themes, pass a screenshot-only aesthetic review with no overflow or misalignment. At 390 px the table may become stacked rows.
- [ ] #6 Unit tests (vitest) cover the limit rows and the moved actions. Tests for the removed cards are deleted or migrated, including ProviderLimitsCards, QuotaPage and quotaReviewSurfaces.
<!-- AC:END -->
