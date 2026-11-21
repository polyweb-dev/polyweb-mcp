---
id: TASK-000104
title: 'Provider mock: paid-plan switch'
status: To Do
assignee: []
created_date: '2026-11-19T14:00:00Z'
labels:
  - provider-mock
  - future
dependencies: []
references:
  - polyweb-provider-mock/README.md
  - polyweb-provider-mock/src/polyweb_provider_mock/models.py
priority: low
ordinal: 89000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
The mock seeds each provider's documented free tier. Add a mock setting (a seed profile or `polyweb-mock` command) that switches a provider, or all of them, to a documented paid plan, so Polyweb can be tested against paid accounts. Examples: Tavily PAYGO or Project at 1,000 RPM, Firecrawl Hobby (5,000 credits, 100 RPM), Exa or Keenable with purchased credit, Brave with a postpaid card, Keenable at 25 rps, Tinyfish with wallet spending on.

The store already supports what these plans need: a recurring grant, one-time prepaid credit, postpaid overage with a cap, and grant expiry. Two pieces are missing:
- A per-key spend cap that resets each billing period. The You.com cap currently never resets, and the docs don't give the period.
- A flat starting balance (for example $20 per account) for teams that want the same amount everywhere.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 One setting switches a provider between its seeded free tier and at least one documented paid plan, and back
- [ ] #2 Each paid profile lists its source (pricing or docs URL) and marks undocumented values as guesses
- [ ] #3 Per-key spend caps can reset with a billing period
<!-- AC:END -->
