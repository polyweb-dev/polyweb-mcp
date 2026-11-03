---
id: TASK-000054
title: Preserve CI reports on VPS with authenticated downloads and deletion
status: In Progress
assignee:
  - '@codex'
created_date: '2026-11-03T02:47:00Z'
labels: []
dependencies: []
ordinal: 38000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Disposable GCP worker cleanup removes mutation JSON and latency report files. User wants durable VPS storage and download/delete access associated with Woodpecker.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 Mutation HTML/JSON and latency report bundles upload to VPS after success or failure, without hiding test failures.
- [ ] #2 Report bundles remain available after worker deletion through a Woodpecker-authenticated download/delete interface.
- [ ] #3 Uploads are authenticated, paths and archive sizes are bounded, downloads are attachments, and deletion requires write permission plus CSRF protection.
- [ ] #4 Automation, service configuration and instructions are preserved in freesearch, with isolated service/upload checks and a real CI smoke verification.
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. Add a small artifact receiver and browser under /artifacts on the existing Woodpecker hostname, authenticated through Woodpecker. 2. Store ZIP bundles on VPS with run/commit metadata and authenticated upload credentials. 3. Add success/failure upload steps to mutation and latency, enable mutation HTML, and preserve full test output. 4. Deploy the service and proxy, verify downloads/deletion/auth and one CI smoke flow, then push documentation.
<!-- SECTION:PLAN:END -->
