---
id: TASK-000050
title: Bake and adopt GCP Woodpecker worker golden image
status: Done
assignee:
  - '@codex'
created_date: '2026-11-03T01:07:00Z'
updated_date: '2026-11-03T01:19:00Z'
labels: []
dependencies: []
ordinal: 34000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Spot workers install dependencies at each boot, delaying CI. Bake Docker, Tailscale and the essential images once and preserve a repeatable workflow in freesearch. Live tooling is in /home/administrator/Programs/gcp-ci-worker on remote-homelab.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 A ready custom image in family woodpecker-ci-worker contains enabled Docker and Tailscale and both required cached images; temporary builder is removed.
- [x] #2 Worker defaults and live configuration use the custom family without boot-time package installation.
- [x] #3 Repeatable image creation workflow and instructions are committed and pushed to feature/project.
- [x] #4 A golden-image Spot worker connects, runs a pipeline, and is removed; autoscaler remains functional and measured timings are recorded.
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. Add repeatable builder and image preparation scripts with an opt-in CI workflow. 2. Bake and capture a clean image and delete the builder. 3. Update and preserve the worker CLI with focused bootstrap checks. 4. Exercise queue-driven pipeline execution and teardown, record timings and push the automation.
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Implemented and pushed fafed8c: opt-in image-builder deployment workflow, repeatable prepare/capture/cleanup scripts, repository copy of the fast worker CLI, configuration example, rebuild instructions, and five isolated tests. Builder preparation completed with both cached images and enabled services; custom image capture is in progress. Live .env activation waits for READY. Python/bootstrap checks, bash syntax, YAML parsing, git whitespace checks and STE structural checks passed.

Verification completed: image woodpecker-worker-v1 is READY in family woodpecker-ci-worker. Live worker.py and .env use the family/project. The autoscaler created c3d-highcpu-8 Spot gcp-spot-standard-1793668462 from v1 for pipeline 9 at fafed8c. Pipeline api-unit passed: 2073 tests, one warning, 26.05s; workflow 40s. Agent launch was 19.75s kernel uptime, about 53s after VM creation; the 12-15s estimate was not achieved. Bootstrap itself took 3.28s. Both cached digests, enabled services, healthy agent, Headscale connection, and 60m timer were verified live. Idle teardown began 01:18:00 UTC and finished 01:18:54 UTC. Final GCP instance/disk lists are empty, only the Headscale server bridge remains, autoscaler is active. Optional CI bake secret was not installed; CLI bake is complete and documented.
<!-- SECTION:NOTES:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
Baked and adopted the golden image, preserved repeatable CLI and opt-in Woodpecker deployment automation, and verified a real autoscaler-driven unit pipeline and automatic teardown. Five isolated checks passed. Measured agent boot was 19.75s rather than the estimated 12-15s. Detailed evidence and digests are in scripts/gcp-ci-worker/verification-2026-11-03.md. CI baking requires the documented optional repository secret.
<!-- SECTION:FINAL_SUMMARY:END -->
