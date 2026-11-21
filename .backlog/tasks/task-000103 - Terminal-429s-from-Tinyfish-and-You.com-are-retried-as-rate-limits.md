---
id: TASK-000103
title: 'Terminal 429s from Tinyfish and You.com are retried as rate limits'
status: To Do
assignee: []
created_date: '2026-11-19T14:00:00Z'
labels:
  - adapter
  - tinyfish
  - youcom
  - routing
dependencies: []
references:
  - src/polyweb/adapters/tinyfish.py
  - src/polyweb/adapters/youcom.py
  - polyweb-provider-mock/tests/e2e/test_tinyfish_polyweb.py
  - polyweb-provider-mock/tests/e2e/test_you_polyweb.py
  - https://docs.tinyfish.ai/error-codes.md
  - https://you.com/docs/using-the-api/error-code-reference.md
priority: high
ordinal: 88000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Two providers answer an exhausted budget with a 429 that retrying cannot clear. Polyweb's adapters map every 429 to a retryable `rate_limited` error. So Polyweb retries a request that cannot succeed, sends the provider more refused calls, and keeps treating the provider as briefly busy rather than out of budget, so routing fails over late or not at all.

- **Tinyfish** (documented in docs.tinyfish.ai/error-codes.md): when the daily free allowance (12,000 searches / 1,000 fetch URLs) is used up and wallet spending is off, Search and Fetch return 429 `RATE_LIMIT_EXCEEDED` with `details.reason = "free_allowance_exhausted"`, which lasts until 00:00 UTC. `TinyfishAdapter._http_error` and `_remap_error` turn it into retryable `rate_limited`. The provider mock now returns this response; `test_free_allowance_429_is_terminal_quota_exhausted` (two cases) is a strict xfail until this is fixed.
- **You.com** (documented in you.com/docs/using-the-api/error-code-reference.md): a key over its dollar spend cap gets 429 `spend_cap_exceeded`, and "retrying does not help". `YoucomAdapter._remap_error` turns every 429 into retryable `rate_limited`. The mock e2e test currently asserts that retryable mapping.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 A Tinyfish 429 with `details.reason = "free_allowance_exhausted"` becomes a non-retryable quota-exhausted error, with the reset at the next 00:00 UTC
- [ ] #2 A You.com 429 `spend_cap_exceeded` becomes a non-retryable quota-exhausted error for that key
- [ ] #3 Ordinary 429 rate limits from both providers stay retryable
- [ ] #4 The Tinyfish xfail tests pass without the xfail marker, and the You.com e2e test asserts the terminal mapping
<!-- AC:END -->
