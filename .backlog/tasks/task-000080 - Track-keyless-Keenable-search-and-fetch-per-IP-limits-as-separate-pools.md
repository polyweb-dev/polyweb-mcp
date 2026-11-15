---
id: TASK-000080
title: Track keyless Keenable search and fetch per-IP limits as separate pools
status: To Do
assignee: []
created_date: '2026-11-15T15:06:00Z'
labels: []
dependencies: []
priority: low
type: bug
ordinal: 68000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Keenable docs (https://docs.keenable.ai/rate-limits) give keyless calls separate per-IP pools for search and fetch (1,000 per hour and 10 per second each). The keyless catalog record (src/polyweb/configuration/provider_limits.py) and the adapter's rolling-hour log (src/polyweb/adapters/keenable.py) share one bucket, so fetch traffic consumes search headroom and the other way round. Found during TASK-000070 planning.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 Keyless Keenable search and fetch each have their own per-IP hourly and per-second windows
- [ ] #2 The Quotas page shows the two windows separately
<!-- AC:END -->
