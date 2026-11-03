---
id: TASK-000051
title: Add capacity fallback zones to GCP Spot workers
status: In Progress
assignee:
  - '@codex'
created_date: '2026-11-03T01:35:00Z'
labels: []
dependencies: []
ordinal: 35000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Mutation pipeline 11 is pending because c3d-highcpu-60 Spot allocation in us-central1-a returns stockout. Use another supported zone at the same regional price and preserve correct cleanup.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 Capacity failures try configured fallback zones in order; other errors stop without duplicate provisioning.
- [ ] #2 Destroy discovers the actual worker zone and handles an already removed Spot VM safely.
- [ ] #3 The live CLI and private configuration use a verified same-region fallback, with focused tests and repository instructions pushed.
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. Verify supported C3D zones and regional pricing. 2. Add capacity-only create fallback and zone-aware discovery for destroy with isolated tests. 3. Deploy the CLI and fallback configuration, observe pipeline 11 provisioning, and push evidence.
<!-- SECTION:PLAN:END -->
