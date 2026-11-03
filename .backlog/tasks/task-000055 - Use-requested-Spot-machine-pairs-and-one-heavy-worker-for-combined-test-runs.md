---
id: TASK-000055
title: Use requested Spot machine pairs and one heavy worker for combined test runs
status: In Progress
assignee:
  - '@codex'
created_date: '2026-11-03T16:53:00Z'
updated_date: '2026-11-03T17:03:00Z'
labels: []
dependencies: []
ordinal: 39000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
The user selected new Spot machine and region preferences from screenshots. Ordinary test runs need the ordered 16-vCPU machine/region pairs, mutation runs need the ordered N2 highcpu64 regions, and runs that include all test workflows need 64-vCPU capacity. The installed background autoscaler must follow the same policy without starting a verification VM.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 Standard preference order is n2-highcpu-16/northamerica-northeast2, e2-highcpu-16/us-west4, n2-highcpu-16/asia-south2
- [x] #2 Mutation and combined preference order is n2-highcpu-64 in northamerica-northeast2, asia-south2, europe-west8
- [x] #3 Combined queues use 64-vCPU capacity for standard and mutation workflows without an additional standard VM by default
- [x] #4 Fallback preserves machine/region pairing and stops on permission and global quota failures
- [ ] #5 Repository configuration, deployed worker/autoscaler, private nonsecret settings and daemon agree; narrow checks pass and changes are pushed without starting a CI job
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
Inspect scheduler label semantics and queue identity, implement paired allocation preferences and combined-run demand selection, verify with isolated worker/autoscaler checks and read-only GCP metadata, deploy and restart the idle daemon, update runbook and push feature/project.
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Implemented ordered paired allocation candidates: standard n2-highcpu16/Toronto, e2-highcpu16/us-west4, n2-highcpu16/Delhi; mutation and combined n2-highcpu64/Toronto, Delhi, Milan. All UP zones in each preferred region precede the next pair. Regional CPU quota skips that region; permission/global quota failures stop. Added repository autoscaler source and combined pipeline detection scoped by repo_id/pipeline_id, including dependencies and persisted assignment after mutation completes. Combined agent advertises size=* and processes one workflow at a time. Idle incompatible workers are released before a new allocation, active workers remain protected, failed deletion retains ownership. Updated private live candidate settings without changing credentials, preserved state, installed CLI and daemon and restarted idle user service. Unit definition and golden image unchanged. Read-only Compute API confirmed all6 requested pairs, 16/64GiB memory, adequate regional CPU limits and global CPU limit64, with zero usage. Thirty-one isolated checks passed, Ruff and strict MyPy for worker/autoscaler passed. No VM or CI job started. Private rollback directory ~/.local/state/freesearch/worker-profiles-20261103T170058Z. Remote publication pending.
<!-- SECTION:NOTES:END -->
