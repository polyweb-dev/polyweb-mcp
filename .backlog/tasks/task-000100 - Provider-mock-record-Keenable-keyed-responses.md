---
id: TASK-000100
title: 'Provider mock: record Keenable keyed responses'
status: To Do
assignee: []
created_date: '2026-11-19T00:17:00Z'
labels:
  - provider-mock
  - keenable
dependencies: []
references:
  - polyweb-provider-mock/src/polyweb_provider_mock/providers/keenable.py
  - polyweb-provider-mock/README.md
priority: low
ordinal: 85000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
The provider mock's Keenable plugin is recorded only for keyless search and fetch (tests/contract/recordings/keenable). Keyed paths follow Keenable's docs: the usage block in responses, keyed X-RateLimit-* headers, 401/402/403 bodies, monthly allowance and purchased-credit resets. Record them once a Keenable API key is available, and align the mock.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 Keyed search and fetch successes are recorded (scrubbed) under tests/contract/recordings/keenable with their usage block and rate-limit headers
- [ ] #2 Keyed 401 (bad key) is recorded; 402/403 recorded if they can be triggered safely
- [ ] #3 The mock's keyed bodies and headers match the recordings, contract tests replay them, and the README fidelity row is updated
<!-- AC:END -->
