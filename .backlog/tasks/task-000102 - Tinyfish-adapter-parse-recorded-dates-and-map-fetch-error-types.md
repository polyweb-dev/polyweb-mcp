---
id: TASK-000102
title: 'Tinyfish adapter: parse recorded dates and map fetch error types'
status: To Do
assignee: []
created_date: '2026-11-19T10:30:00Z'
labels:
  - tinyfish
  - adapter
dependencies: []
references:
  - src/polyweb/adapters/tinyfish.py
  - src/polyweb/infrastructure/dates.py
  - polyweb-provider-mock/tests/contract/recordings/tinyfish
priority: low
ordinal: 87000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
On 2026-11-19, TinyfishAdapter was run against the live API with a real key. Search (web, news, research papers, domain/location/language filters, paging), fetch (markdown, html, json, max_chars), and the 401 bogus-key path all worked. The live run found four gaps, all reproducible on the provider mock, whose recordings were taken in the same run:

1. Search `date` values come in mixed formats. Web results use ISO 8601 (`2023-09-25T15:00:15Z`), `Oct 18, 2020`, and `4 days ago`; news results use RFC 2822 (`Wed, 11 Nov 2026 23:13:16 GMT`). `parse_iso_datetime` accepts only ISO, so `published_at` is empty on every news result and on the non-ISO web results. The raw string is still kept in `metadata["date"]`.
2. Fetch `errors[].error = "selector_not_matched"`, returned when no include selector matches, maps to `not_found` 404 "target page not found". The page exists. The entry also carries `unmatched_selectors` and `candidate_selectors`, which the adapter drops.
3. Fetch `invalid_url` (unresolvable host, private or loopback address) maps to `not_found` 404. A non-retryable invalid-request code would be accurate.
4. HTTP 403 `FORBIDDEN` "highlights is not enabled for this account" maps to a generic `http_error` "HTTP 403". The provider message is lost, so the caller can't tell that the account lacks the feature. The 422 `INVALID_INPUT` for an unparseable CSS selector is likewise generic.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 Tinyfish search results with RFC 2822, `Mon D, YYYY` and `N days ago` dates get a `published_at` (relative dates resolved against the response time)
- [ ] #2 `selector_not_matched` maps to a non-retryable error that names the unmatched selectors, not `not_found`
- [ ] #3 `invalid_url` maps to a non-retryable invalid-request error
- [ ] #4 The 403 (highlights not enabled) and 422 (bad selector) errors keep the provider's message
- [ ] #5 Tests run the cases against the provider mock, which reproduces each recorded response
<!-- AC:END -->
