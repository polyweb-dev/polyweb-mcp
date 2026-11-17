---
id: TASK-000097
title: Provider mock server for live-like dev testing
status: In Progress
assignee: []
created_date: '2026-11-17T01:25:00Z'
labels:
  - dev-tooling
  - testing
dependencies: []
priority: medium
ordinal: 82000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Debugging complex bugs needs the full app running as if live, but real provider calls cost credits, are not reproducible, and cannot be forced into outages, latency spikes, rate limits, or credit exhaustion on demand. A separate FastAPI app impersonates every provider (Exa, Tavily, Firecrawl, Parallel incl. OAuth, You.com, Brave, Keenable, Tinyfish) with recorded-accurate formats, a SQLite state DB, and an admin CLI. One env flag at startup routes all provider traffic to it; adapters stay unaware.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 With `POLYWEB_PROVIDER_MOCK_URL` set, API and MCP route every outbound provider call to the mock through one startup branch, with no per-call checks and no adapter edits
- [ ] #2 The app refuses to start with the mock flag in production
- [ ] #3 Each provider operation the adapters use (search, fetch/extract, answers/context, usage/balance, key validation, Parallel OAuth) returns status codes, headers, and bodies that match recorded or documented real responses, and contract tests lock that down
- [ ] #4 A mock SQLite DB tracks keys, credits/balances, pricing, keyless mode, and usage; a seed script and admin CLI can add credits, set pricing, create or revoke keys
- [ ] #5 Fault scenarios (outage 5xx, connection error, timeout, added latency/jitter, 429 with headers, credit exhaustion, invalid key, malformed body, intermittent failure rate) can be switched on per provider and operation through CLI or admin API at runtime
- [ ] #6 compose.dev.yaml and the dev seed scripts can start the app against the mock; the live production container is untouched
- [ ] #7 The Polyweb @live Behave scenarios and unit tests pass against the mock, and mock unit tests pass in CI
<!-- AC:END -->
