---
id: TASK-000081
title: Remove or wire up the unused ProviderConfig.reset_schedule label
status: To Do
assignee: []
created_date: '2026-11-15T15:06:00Z'
labels: []
dependencies: []
priority: low
type: task
ordinal: 69000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
ProviderConfig.reset_schedule (src/polyweb/configuration/provider_config.py, added in b686c377) accepts any non-empty label such as monthly. No adapter or limits code reads it, and the UI shows it only as resetPeriod text. Users may expect it to control the reset. Found during TASK-000070 planning.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 reset_schedule either drives the provider period start and reset date, or is removed from the config, API and UI with a migration note
<!-- AC:END -->
