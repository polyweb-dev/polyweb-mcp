---
id: TASK-000003
title: Add Provider Tier settings for rate limits and budgets
status: To Do
assignee: []
created_date: 2026-10-15 22:19
updated_date: '2026-10-26T09:48:00Z'
labels: []
dependencies:
  - TASK-000049
documentation:
  - doc-000005
type: feature
ordinal: 12000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Provider Tier settings should drive rate-limit calculations, with budget calculation from the tier evaluated as part of the feature.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 A Provider Tier can be configured for each provider.
- [ ] #2 Rate limits are calculated from the selected Provider Tier.
- [ ] #3 The settings define whether and how budgets are calculated from the selected tier.
<!-- AC:END -->

## Comments

<!-- COMMENTS:BEGIN -->
author: @codex
created: 2026-10-24T15:55:00Z

---

This ticket remains the provider-tier/preset follow-up. Projects P11 establishes authoritative strict admission and P12 establishes scoped settings. Start tier-driven calculations only after the project-first cutover; do not duplicate or bypass those phases. Existing acceptance criteria remain unchanged.

---

created: 2026-10-26T09:48:00Z

---

2026-10-25: The Projects phase cards were replaced by the layered rebuild board (doc-000005). This card now waits for TASK-000049 instead of the deleted TASK-000038, so Provider Tier settings build on the new scoped settings and strict caps.

---
<!-- COMMENTS:END -->
