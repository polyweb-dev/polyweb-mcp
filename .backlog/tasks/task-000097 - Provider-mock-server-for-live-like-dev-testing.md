---
id: TASK-000097
title: Provider mock server for live-like dev testing
status: Testing
assignee: []
created_date: '2026-11-17T01:25:00Z'
updated_date: '2026-11-17T09:35:00Z'
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
- [x] #1 With `POLYWEB_PROVIDER_MOCK_URL` set, API and MCP route every outbound provider call to the mock through one startup branch, with no per-call checks and no adapter edits
- [x] #2 The app refuses to start with the mock flag in production
- [x] #3 Each provider operation the adapters use (search, fetch/extract, answers/context, usage/balance, key validation, Parallel OAuth) returns status codes, headers, and bodies that match recorded or documented real responses, and contract tests lock that down
- [x] #4 A mock SQLite DB tracks keys, credits/balances, pricing, keyless mode, and usage; a seed script and admin CLI can add credits, set pricing, create or revoke keys
- [x] #5 Fault scenarios (outage 5xx, connection error, timeout, added latency/jitter, 429 with headers, credit exhaustion, invalid key, malformed body, intermittent failure rate) can be switched on per provider and operation through CLI or admin API at runtime
- [x] #6 compose.dev.yaml and the dev seed scripts can start the app against the mock; the live production container is untouched
- [x] #7 The Polyweb @live Behave scenarios and unit tests pass against the mock, and mock unit tests pass in CI
<!-- AC:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Evidence (2026-11-17): Woodpecker on 0b37bd1 all green: provider-mock #179 (mock ruff/format/mypy/664 tests, then root Behave @live against the mock: 9 features, 22 scenarios passed, 0 failed), api-unit #180, api-integration #181, api-bdd #182. Full stack (mock + API + MCP) in an isolated polyweb-wt1-mock Compose project: search 200 for all 8 providers, fetch for the 7 with fetch, keyless Keenable/Tavily, MCP search+fetch, balances match the mock ledger, Parallel OAuth device flow connects. Faults through the app: outage -> auto/prefer fall back; +1500 ms latency visible; revoked/invalid key -> provider skipped next request; credits exhausted -> 402 and limits 0; 429 storm -> 8/8 via Retry-After and fallback; recovery after clearing. Known non-mock failures: routing_latency_live p95 gate fails on the busy host with or without the mock (CI owns it); UI @live features without a sign-in step fail on main too (TASK-000083).
Review round (the Devin reviewers died on quota, so the fix round was done in-session): production guard verified at Settings and install time, and the live stack runs with POLYWEB_ENVIRONMENT=production; every provider adapter, SDK client, OAuth flow and limits sync reaches the network through the patched httpx transports after create_async_client runs; CLIs never call providers; the prod image copies only src/ and the mock package stays out of it; the merged mock Compose config namespaces images, volumes and network under the -mock project and binds loopback only. Fixed: compose.mock.yaml ui (behind --profile ui) inherited the base host-wide 3000 publish; it now binds a random loopback port and the header points at pnpm dev. Open minor: the keyless budget counts ledger rows, so keyless requests that fail before charging do not count toward per-minute/day limits.

Environments (owner request, 2026-11-17): pd = root compose.yaml + Dockerfile (deployed, unchanged); npd = docker/npd (worktree source, real providers); dev = docker/dev on top of npd (provider mock). scripts/{linux,windows}/stack npd|dev replaces mock_stack; projects polyweb-wtN-npd / -dev. dev-live = stack.sh dev live (@live against the dev mock); live = api-live (real providers). Woodpecker stays flat (it ignores .woodpecker subfolders). Also fixed: npd host-wide ports and leaked .env mock origin; delete_worktree tore down the pd 'polyweb' project via bare compose down (now only the worktree's own projects). Verified locally: dev up, dev live 22/22 with all calls in the mock log, npd up, down -v for both.
<!-- SECTION:NOTES:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
Adds polyweb-provider-mock/, a dev-only FastAPI app that impersonates all 8 providers (Exa, Tavily, Firecrawl, Parallel incl. OAuth, You.com, Brave, Keenable, Tinyfish) from recorded formats, with SQLite state (accounts, keys, pricing, keyless, ledger, faults, fixtures, redacted request log), a god-mode polyweb-mock CLI and admin API, and fault/latency/rate-limit/credit scenarios. POLYWEB_PROVIDER_MOCK_URL is read once in create_async_client and wraps the httpx network transports to send provider hosts to the mock with the real Host header; production refuses it. scripts/linux|windows/mock_stack runs an isolated -mock Compose project, seed_dev --keys-from-mock seeds polyweb.mock-dev.db with fake keys only, tests ignore a .env mock origin unless POLYWEB_TEST_PROVIDER_MOCK=1, and a provider-mock Woodpecker workflow runs the @live Behave suite against the mock. All CI green; see notes for live evidence and the one open minor.
<!-- SECTION:FINAL_SUMMARY:END -->
