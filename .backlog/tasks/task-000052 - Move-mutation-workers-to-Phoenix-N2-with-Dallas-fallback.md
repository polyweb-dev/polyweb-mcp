---
id: TASK-000052
title: Move mutation workers to Phoenix N2 with Dallas fallback
status: Done
assignee:
  - '@codex'
created_date: '2026-11-03T01:47:00Z'
updated_date: '2026-11-03T01:52:00Z'
labels: []
dependencies: []
ordinal: 36000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
User requests mutation-only n2-standard-64 Spot workers, Phoenix first then Dallas, and one test attempt. Keep the standard worker profile and Iowa routing intact.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 Only mutation defaults select n2-standard-64 and Phoenix then Dallas; standard profile is unchanged.
- [x] #2 Region-scoped CPU quota failures can try another configured region without retrying the same quota region or bypassing global errors.
- [x] #3 A single mutation allocation and pipeline attempt is made where capacity and quotas permit; evidence, cleanup and automation are saved and pushed.
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. Verify N2 availability and regional quotas. 2. Add mutation-specific defaults and overrides, cross-region CPU quota fallback, and focused tests. 3. Deploy and provision once without queuing repeated autoscaler retries. If successful, run mutation once, observe and clean up. 4. Record result and push.
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Implemented and pushed 3aeaafa. Mutation defaults and live private config now use n2-standard-64 with GCP_MUTATION_REGIONS=us-west8,us-south1. Standard c3d-highcpu-8 and Iowa zone settings are preserved. Compute zones/regions list and describe reported Phoenix unavailable for this project, despite its pricing entry; runtime region discovery skipped it rather than inventing a zone. Dallas N2_CPUS=200 and regional CPUS=100, both unused before allocation. Exactly one create request was made in us-south1-a for gcp-n2-mutation-1793670621. Operation operation-1793670628898-65f557cadf8a4-b7d44b85-bfd2fada failed QUOTA_EXCEEDED: CPUS_ALL_REGIONS global limit 32. Project-info confirmed global limit=32, usage=0. Mutation suite was not started and no retries or pipeline restarts occurred. Destroy handled the absent VM and checked Headscale. Final instance/disk lists are empty; autoscaler active, tracked workers empty. Twenty isolated automation tests pass, including profile isolation, Phoenix-before-Dallas ordering, unavailable-region skip, explicit-zone pinning, regional CPU quota skip, and global quota stop. Documentation and whitespace checks pass. Further 64-vCPU attempts require sufficient global CPU quota; no quota request or unrelated profile change was made.
<!-- SECTION:NOTES:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
Switched and deployed mutation-only N2 64-vCPU Spot workers with Phoenix then Dallas preferences. Made one allocation attempt: Phoenix was unavailable through Compute API, Dallas rejected the request at the 32-CPU global quota. No workload ran or resources remained. Standard workers retain their Iowa profile. Twenty focused automation checks pass.
<!-- SECTION:FINAL_SUMMARY:END -->
