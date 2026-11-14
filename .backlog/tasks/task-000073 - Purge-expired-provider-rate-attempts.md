---
id: TASK-000073
title: Purge expired provider rate attempts
status: To Do
assignee: []
created_date: '2026-11-14T11:37:00Z'
labels: []
dependencies: []
priority: high
type: bug
ordinal: 62000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
provider_rate_attempts is never purged: LimitRepository.purge_expired_attempts (src/polyweb/persistence/limit_repository.py) exists but no schedule calls it, so the table grows without bound. Its fixed 48h cutoff is also shorter than some configured rate windows, so wiring it as-is would undercount those windows.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 A scheduled job purges expired rate attempts
- [ ] #2 The purge cutoff is derived from the longest active rate window rather than a fixed 48h
- [ ] #3 Test proves attempts inside the longest window are retained and older ones are removed
<!-- AC:END -->
