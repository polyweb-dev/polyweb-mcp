---
id: TASK-000087
title: Back off adapter preparation retries after repeated failures
status: To Do
assignee: []
created_date: '2026-11-15T23:46:00Z'
labels: []
dependencies: []
priority: low
type: bug
ordinal: 73000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Found in the PR #78 review (A8) for TASK-000070. CredentialAdapterCache retires an entry whose preparation failed so the next lease retries (services/execution.py). A persistently failing preparation (for example a broken repository read) is retried on every request with no backoff: each request rebuilds the adapter and logs a warning.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 After repeated preparation failures for one credential, retries are spaced by a bounded backoff while requests still proceed
- [ ] #2 A unit test with a failing prepare shows retries limited by the backoff and one warning per attempt
<!-- AC:END -->
