---
id: TASK-000085
title: >-
  Tavily 402 recovery: use the highest same-allowance report of the month as the
  baseline
status: To Do
assignee: []
created_date: '2026-11-15T18:38:00Z'
labels: []
dependencies: []
priority: low
type: bug
ordinal: 72000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Found in the TASK-000070 round 3 re-review (#2). The Tavily 402 baseline is the newest vendor report of the month (persistence/limit_repository.py _last_vendor_report; adapters/tavily.py). If /usage ever returns an older, higher balance after a newer report was accepted (lagging replica), that value counts as proof of new funds and unblocks the key.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 A same-month report unblocks a 402 only when its remaining exceeds the highest remaining among this month's vendor reports with the same allowance, or its allowance exceeds the last reported allowance
- [ ] #2 Repository and adapter tests cover an out-of-order higher report that stays rejected
<!-- AC:END -->
