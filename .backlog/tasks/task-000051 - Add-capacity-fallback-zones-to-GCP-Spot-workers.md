---
id: TASK-000051
title: Add capacity fallback zones to GCP Spot workers
status: Done
assignee:
  - '@codex'
created_date: '2026-11-03T01:35:00Z'
updated_date: '2026-11-03T01:40:00Z'
labels: []
dependencies: []
ordinal: 36000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Mutation pipeline 11 is pending because c3d-highcpu-60 Spot allocation in us-central1-a returns stockout. Use another supported zone at the same regional price and preserve correct cleanup.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 Capacity failures try configured fallback zones in order; other errors stop without duplicate provisioning.
- [x] #2 Destroy discovers the actual worker zone and handles an already removed Spot VM safely.
- [x] #3 The live CLI and private configuration use a verified same-region fallback, with focused tests and repository instructions pushed.
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. Verify supported C3D zones and regional pricing. 2. Add capacity-only create fallback and zone-aware discovery for destroy with isolated tests. 3. Deploy CLI and configuration. Preserve the user-canceled pipeline 11; use a temporary mutation-profile allocation check instead. 4. Record live stockout and quota results, cleanup, and push.
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Deployed and pushed bc4b250. GCP machine-types API confirms c3d-highcpu-60 support in us-central1-a/b/c/f. Fallback order is a, b, c, f, within the Iowa regional price schedule. All 13 isolated tests pass, including capacity-only retry, canonical wrapped error messages, explicit zone pinning, fallback-zone deletion, absent Spot VM cleanup, and ambiguous-name refusal. Live check gcp-fallback-check-1793669889 retried from a to b after real stockouts, then stopped correctly at c on CPUS_PER_VM_FAMILY quota exceeded (regional C3D limit 24; mutation requests 60). Did not attempt f after quota failure. No VM or disk remained, and destroy safely handled the absent VM. Pipeline 11 was canceled by sharathnirmala16 and was not restarted. Autoscaler remains active. Documentation structural and whitespace checks pass. A sufficient C3D regional quota is still required to run the 60-core mutation profile; no quota or machine-size change was made.
<!-- SECTION:NOTES:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
Added and deployed same-region capacity fallback a -> b -> c -> f with safe zone discovery for teardown. Verified 13 focused tests and a live sequence of capacity retries followed by a quota stop. Allocation remains blocked by the 24-CPU regional C3D family quota for the requested 60-core profile. User-canceled pipeline remains canceled.
<!-- SECTION:FINAL_SUMMARY:END -->
