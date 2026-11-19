---
id: TASK-000105
title: 'Provider limit catalog corrections from the docs review'
status: To Do
assignee: []
created_date: '2026-11-19T14:00:00Z'
labels:
  - provider-limits
  - adapter
dependencies: []
references:
  - src/polyweb/configuration/provider_limits.py
  - src/polyweb/adapters/tavily.py
  - src/polyweb/adapters/exa.py
  - src/polyweb/adapters/keenable.py
  - src/polyweb/adapters/youcom.py
  - src/polyweb/adapters/brave.py
  - polyweb-provider-mock/README.md
priority: medium
ordinal: 90000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
On 2026-11-19 each provider's free tier was checked against its official pricing and docs pages; the provider mock now follows them (polyweb-provider-mock/README.md, "Accounts and funding"). Polyweb's catalog and local ledgers disagree in ways that misstate remaining budget or funding:

1. **Tavily:** a free account is marked as PAYGO. `_UsageFacts.paygo_observed` is true whenever `paygo_usage` is not null, and a free account reports `paygo_usage: 0, paygo_limit: null` (recorded). So `overage_confirmed` and `paygo_confirmed` get set, and Polyweb believes overage billing is on. It should require a non-null `paygo_limit` or non-zero usage.
2. **Exa:** the one-time $10 onboarding bonus (documented, never expires) is missing from the allowance, so Polyweb reports $10 less remaining than there is and can stop routing to Exa early. The local ledger should spend the grant first, then the bonus, and refill only the $10 grant on the 1st.
3. **Keenable:** the keyed ledger resets on the calendar 1st. The free allowance resets on the day the organization was created, so after the 1st Polyweb shows a refill that hasn't happened. The keyless limits (1,000/hour, 10/second) are per endpoint and per IP, not one shared bucket. Purchased credit is documented as never expiring, not "expiry unknown".
4. **Tinyfish:** limits apply per person or organization, but the catalog counts them per key. The 12,000/day search window is missing, and the fetch daily window should count successful URLs only. The 60/min limit on invalid requests and usage reads is missing.
5. **You.com:**
   - The "100 calls/day" tier belongs to the keyless MCP endpoint (`api.you.com/mcp/free`), not API keys, and covers extract and discover too.
   - The signup credit is $10 + $90 after verification and expires after 60 days (catalog: $100, never).
   - The plan name is garbled ("100 Polyweb MCPes/day").
6. **Parallel:** the `parallel:keyed:free` tier says the reset is unknown, but the docs give $5 a month with a card on file, no rollover. Past $5, usage is billed to the card and never blocked (spend limits only notify), so an estimated $0 isn't exhaustion for a card-on-file org.
7. **Brave:** `brave:keyed:free` claims the $5 credit is observed from the `X-RateLimit-*` monthly element, but a real free-credit account reports `0` (unlimited) there, so the credit is never observed. The reset anchor is undocumented (the mock uses the 1st).
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 Each numbered item is fixed or explicitly declined with a reason in this task's notes
- [ ] #2 Each fix has a test against the provider mock, which models the documented behaviour
<!-- AC:END -->
