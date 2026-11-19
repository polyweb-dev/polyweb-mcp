---
id: TASK-000099
title: 'Exa: read authoritative spend from the admin usage API'
status: To Do
assignee: []
created_date: '2026-11-19T00:17:00Z'
labels:
  - exa
  - billing
  - future
dependencies: []
references:
  - src/polyweb/adapters/exa.py
  - src/polyweb/configuration/provider_limits.py
  - polyweb-provider-mock/src/polyweb_provider_mock/providers/exa.py
  - https://exa.ai/docs/reference/team-management/get-api-key-usage
priority: low
ordinal: 84000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Possible future integration, not scheduled. Polyweb estimates Exa spend from costDollars on each search/contents response and the local usage ledger (adapters/exa.py usage_snapshot); it never calls Exa's admin API. Exa's GET admin-api.exa.ai/team-management/api-keys/{id}/usage returns authoritative per-key usage but needs a team admin (service) key, which a normal search key cannot use (recorded: 401 with a regular key). The provider mock already serves that endpoint from Exa's docs, without a live capture of a success. Decided 2026-11-19: no Exa admin key for now.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 Decide whether operators should supply an Exa admin key, and where it is stored (vault, separate from the search key)
- [ ] #2 If yes: Polyweb reads per-key usage from the admin API and prefers it over the costDollars estimate, falling back when the admin key is absent or rejected
- [ ] #3 A successful admin usage response is recorded live, and the provider mock's usage body is checked against it
<!-- AC:END -->
