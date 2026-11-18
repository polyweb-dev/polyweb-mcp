---
id: TASK-000069
title: Wire Parallel OAuth access-token refresh
status: Done
assignee:
  - Abhishek
created_date: '2026-11-14T11:37:00Z'
updated_date: '2026-11-18T10:40:00Z'
labels: []
dependencies: []
priority: high
type: bug
ordinal: 1000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Parallel OAuth credentials stop resolving once the access token expires. ParallelOAuthClient.refresh_access_token (src/polyweb/services/parallel_oauth.py) and CredentialOAuthService.refresh (src/polyweb/services/credential_oauth.py) exist, but nothing calls them on the runtime path: CredentialService._load_material (src/polyweb/services/credentials.py) returns None for an expired token, so the provider goes dark until someone re-pairs. Found during the feature/cleanup dead-code review; refresh was kept on purpose because it is an unwired feature, not dead code.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 Runtime material resolution refreshes an OAuth access token within REFRESH_SKEW_SECONDS of expiry and persists the new token
- [x] #2 A failed refresh marks the credential with a visible status rather than silently returning no material
- [x] #3 Integration test covers expired-token resolution end to end
<!-- AC:END -->
