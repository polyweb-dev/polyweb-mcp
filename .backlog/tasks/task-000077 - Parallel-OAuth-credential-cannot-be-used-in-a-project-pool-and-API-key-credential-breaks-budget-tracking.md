---
id: TASK-000077
title: >-
  Parallel: OAuth credential cannot be used in a project pool, and API-key
  credential breaks budget tracking
status: To Do
assignee: []
created_date: '2026-11-15T01:51:00Z'
updated_date: '2026-11-15T01:58:00Z'
labels: []
dependencies: []
references:
  - src/polyweb/services/parallel_oauth.py
  - src/polyweb/services/credential_oauth.py
  - src/polyweb/services/credentials.py
priority: high
type: bug
ordinal: 66000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Parallel OAuth setup moved into the Provider keys and pools section, but OAuth and API-key credentials for Parallel were never standardized into one model, so neither works fully in a project.

Reported on the homelab deployment (2026-11-15):
- Creating a Parallel OAuth credential succeeds, but it cannot be added to a project pool the way an API key can. The project pool only accepts one kind of Parallel credential.
- If the OAuth credential is the one attached (as if it were an API key), Parallel search and fetch do not work for the project.
- If a plain Parallel API key is attached to the pool instead, search and fetch work, but budget tracking for Parallel does not.

Follow-up observations (same day, single-project test setup):
- The OAuth credential can be removed from the project pool and the API key added in its place. The UI still shows a single pool covering both credentials, and that pool is labelled "unassigned" even though the only project uses it.
- Deleting the pool entirely and then adding the API key to a pool again does not fix cost tracking.
- With the API key in the pool, Parallel calls are tracked and each call shows only the default per-call cost value. Cost totals are never shown: per-call costs are not summed into usage or budget totals.
- The remaining budget/balance that Parallel reports through its API is not shown anywhere in the dashboard, so the user cannot see how much Parallel budget is left.

So a project today has to choose between a working Parallel provider (API key, no cost tracking) and an OAuth credential that cannot be used. We believe this is a standardization mistake in how Parallel auth modes map onto credentials, pools, and per-auth-mode budgets (budgets are keyed by auth mode: /api/v1/providers/{provider_id}/budgets/{auth_mode}). Related: TASK-000069 (OAuth access-token refresh), TASK-000070 (Parallel free-seed at startup).
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 A Parallel OAuth credential created in Provider keys and pools can be added to a project pool through the dashboard and API
- [ ] #2 A project whose Parallel pool holds only an OAuth credential runs search and fetch through Parallel successfully
- [ ] #3 A project whose Parallel pool holds only an API-key credential runs search and fetch successfully and records Parallel budget/usage
- [ ] #4 Budget tracking works for both Parallel auth modes, and a project can hold both credential kinds without one disabling the other
- [ ] #5 Parallel credential, pool, and budget handling follows the same model as other providers (no Parallel-only special case for attaching credentials)
- [ ] #6 Regression tests cover OAuth-only, API-key-only, and mixed Parallel pools for execution and budget recording
- [ ] #7 The pools view shows each Parallel credential in its own correct pool, and a pool assigned to a project is not labelled "unassigned"
- [ ] #8 Removing, deleting, and re-adding Parallel credentials and pools leaves no stale pool and keeps cost tracking working
- [ ] #9 Parallel API-key calls record their actual cost, and those costs are summed into the totals shown in usage and budget views (not only a default per-call value)
- [ ] #10 The remaining budget/balance reported by the Parallel API is fetched and shown in the dashboard (key balances/budget views) for the credential in use
<!-- AC:END -->
