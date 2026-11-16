---
id: TASK-000079
title: >-
  Keenable keyed allowance resets on the organization creation day, not the
  calendar month
status: To Do
assignee: []
created_date: '2026-11-15T15:06:00Z'
labels: []
dependencies: []
priority: low
type: bug
ordinal: 67000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Keenable resets the free monthly allowance on the organization creation day (https://keenable.ai/pricing). The adapter (src/polyweb/adapters/keenable.py) and the shared month_start helper (src/polyweb/infrastructure/dates.py) reset on the 1st of the month at 00:00 UTC. TASK-000070 stores usage.credits_remaining from each billed response as a vendor fact, which hides most of the gap, but the local fallback estimate and the 402 reset date still use the calendar month. Found during TASK-000070 planning.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 The Keenable keyed period start and reset date follow the organization reset day when it is known (for example from a manual record billing period), and fall back to the calendar month otherwise
- [ ] #2 A 402 block on a keyed Keenable key lifts at the organization reset, not at the calendar month start
<!-- AC:END -->
