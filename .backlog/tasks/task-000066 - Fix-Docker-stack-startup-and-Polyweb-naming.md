---
id: TASK-000066
title: Fix Docker stack startup and Polyweb naming
status: Done
assignee:
  - codex
created_date: '2026-11-12T21:11:00Z'
updated_date: '2026-11-12T21:17:00Z'
labels: []
dependencies: []
ordinal: 55000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Docker startup fails because the API health check calls a protected route. Compose also inherits the legacy checkout folder name.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 Compose defaults to polyweb resource names
- [x] #2 API health check succeeds without credentials and UI starts
- [x] #3 The old test volume is deleted and a fresh polyweb volume replaces it
- [x] #4 Docker proxies browser authentication and account requests to the API
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
Reproduce the failure; add a public health endpoint; fix Compose naming and probes; reset the test volume as requested; verify startup and run lint.
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Confirmed the original stats probe returns HTTP 401. Added public GET /health with a status-only response and updated both Compose probes. Disabled runtime uv sync to avoid installation of dev dependencies. User requested no test changes or test runs, only lint. Removed freesearch_polyweb-data on explicit request and started all three services with polyweb_polyweb-data. Build, Compose validation, Ruff lint and format checks passed.

Fixed the nginx 405 error reported when opening the dashboard: added proxy routes for /auth/, /users/me, and /health. Added localhost and loopback Docker dashboard origins to the local gitignored .env. Recreated the UI container after rebuilding; verified refresh and account return JSON 401 anonymously and health returns JSON 200 through nginx. nginx -t passed.
<!-- SECTION:NOTES:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
Fixed Docker startup with a public status-only health endpoint, explicit Polyweb project naming, and no runtime dependency sync. Reset the test volume as requested. Fixed nginx authentication and account proxy routes and configured local Docker browser origins. All services run, API health is healthy, and the dashboard responds. Ruff lint and format checks, Compose validation, nginx syntax, and manual HTTP checks passed. No tests changed or run per user instruction.
<!-- SECTION:FINAL_SUMMARY:END -->
