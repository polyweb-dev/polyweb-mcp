---
id: TASK-000050
title: Bake and adopt GCP Woodpecker worker golden image
status: In Progress
assignee:
  - '@codex'
created_date: '2026-11-03T01:07:00Z'
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
- [ ] #1 A ready custom image in family woodpecker-ci-worker contains enabled Docker and Tailscale and both required cached images; temporary builder is removed.
- [ ] #2 Worker defaults and live configuration use the custom family without boot-time package installation.
- [ ] #3 Repeatable image creation workflow and instructions are committed and pushed to feature/project.
- [ ] #4 A golden-image Spot worker connects, runs a pipeline, and is removed; autoscaler remains functional and measured timings are recorded.
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. Add repeatable builder and image preparation scripts with an opt-in CI workflow. 2. Bake and capture a clean image and delete the builder. 3. Update and preserve the worker CLI with focused bootstrap checks. 4. Exercise queue-driven pipeline execution and teardown, record timings and push the automation.
<!-- SECTION:PLAN:END -->
