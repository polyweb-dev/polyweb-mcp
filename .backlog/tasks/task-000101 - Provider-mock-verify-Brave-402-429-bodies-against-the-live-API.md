---
id: TASK-000101
title: 'Provider mock: verify Brave 402/429 bodies against the live API'
status: To Do
assignee: []
created_date: '2026-11-19T00:17:00Z'
labels:
  - provider-mock
  - brave
dependencies: []
references:
  - polyweb-provider-mock/src/polyweb_provider_mock/providers/brave.py
  - https://api-dashboard.search.brave.com/documentation/guides/rate-limiting
  - https://api-dashboard.search.brave.com/api-reference/web/search/get
priority: low
ordinal: 86000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Brave's 429 RATE_LIMITED / QUOTA_LIMITED / USAGE_LIMIT_EXCEEDED and 402 CREDIT_EXHAUSTED responses in the provider mock follow Brave's docs only. Documented: the ErrorResponse envelope (type, error.id/status/code/detail/meta, time), 429 on a rate-limit breach, and X-RateLimit-Limit/Policy/Remaining/Reset. Not documented, so guessed: the detail and meta text, and the HTTP status for exhausted prepaid credits (the mock uses 402). Not verified against the live API: triggering them needs an exhausted or rate-limited key.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 A live per-second 429 (two calls within 1 s on a 1 rps key) is recorded with its headers and body
- [ ] #2 The monthly-quota and credit/spend-cap responses are recorded if they can be reached without extra cost; otherwise their status stays marked as guessed
- [ ] #3 The mock's Brave error bodies and statuses match the recordings and contract tests replay them
<!-- AC:END -->
