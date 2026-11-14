---
id: TASK-000074
title: >-
  Reconcile failure settlement between _finalize_failure and
  _finalize_native_failure
status: To Do
assignee: []
created_date: '2026-11-14T11:37:00Z'
labels: []
dependencies: []
type: bug
ordinal: 63000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
src/polyweb/services/monitoring.py: _finalize_failure and _finalize_native_failure settle an exception whose .error payload is not a ProviderError differently, so the same failure can be recorded differently depending on the execution path. Found during the feature/cleanup review (consolidation was rejected as a behaviour change).
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 Both paths settle non-ProviderError .error payloads the same way, or the difference is documented as intentional
- [ ] #2 Test covers a non-ProviderError .error payload on both paths
<!-- AC:END -->
