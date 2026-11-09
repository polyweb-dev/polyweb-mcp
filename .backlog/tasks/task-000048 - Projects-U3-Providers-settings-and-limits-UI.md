---
id: TASK-000048
title: Projects U3 - Providers, settings and limits UI
status: In Progress
assignee:
  - '@devin'
created_date: '2026-10-26T09:47:00Z'
updated_date: '2026-11-03T15:42:00Z'
labels:
  - projects-first
  - step-3-ui
milestone: m-1
dependencies:
  - TASK-000045
  - TASK-000043
  - TASK-000044
documentation:
  - doc-000003
  - doc-000005
  - doc-000002
priority: high
type: feature
ordinal: 32000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Providers, settings, settings copy, trace policy and limits need desktop screens that follow effective permissions and never expose secrets. Design: local plan sections 4.7, 7 and 8 (doc-000001, doc-000002).

Step rules and the shared Definition of Done: doc-000003. Card map and worktree rules: doc-000005. Do not start before every dependency is Done and merged into feature/project. When you start, record your own implementation plan in Backlog after researching the current code.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 Credential, grant, binding, private-key and OAuth screens never show secret material.
- [x] #2 Settings show provenance, inherit/reset and read-only state from effective permissions; the copy dialog previews before applying.
- [x] #3 Trace policy controls show the effective policy within system limits.
- [x] #4 Allocation views explain strict caps and loans; system administrators edit allocations and loan settings; projects see a read-only explanation.
<!-- AC:END -->

## Definition of Done
<!-- DOD:BEGIN -->
- [ ] #1 Tests of the changed layer pass, plus ruff/mypy (backend) or lint/typecheck/depcruise/knip/build (frontend) with no new findings.
- [x] #2 Tests use fake providers and temporary databases; security assertions are rewritten to the new model, never weakened or dropped without a replacement.
- [x] #3 No secret material (passwords, API keys, provider keys, OAuth grants) appears in responses, logs, traces or test output.
- [x] #4 If the card changes the request path, the routing-latency check passes: FreeSearch adds under 80 ms at p95 per provider, end to end, over REST and MCP. Database read counts are a diagnostic, not a limit.
<!-- DOD:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
Research findings (2026-11-02): every U3 contract exists on this branch from A4/A5. Project: GET /api/v1/projects/{id}/providers (provider types with capability, kill_switch, system_enabled_operations, available credentials incl. pools, bindings with enabled and effective operations, plus this project's allocations), bindings POST/PATCH/DELETE (providers.configure; a new binding starts disabled), project credentials list/get (providers.read) and create/rotate/delete (credentials.manage_private; rotate needs expected_generation; Parallel only may use auth_mode oauth), credential OAuth device/poll/status/disconnect (device response is only user_code, verification_uri, interval, expires_in), settings GET/PUT (settings.read / settings.write; per-field provenance system_default|project_override|system_constrained, override_allowed, system_default, system_safety_limit, constraint_applied; expected_revision, explicit null resets one override, 409 on stale revision), copy preview/apply (settings.read on source, settings.copy and settings.write on target; overrides_only default or effective_snapshot; revision-bound). System: credentials CRUD + grants + OAuth (system.credentials.manage), pools + credential links (system.pools.manage), per-project allocations (system.allocations.manage; strict by default, borrow_enabled with max_rate >= base_rate, weight >= 1, base 0 needs best_effort, infeasible -> 409). The UI still calls removed routes: PUT/DELETE /api/v1/providers/{id}/secret (Settings Keys tab) and /api/v1/providers/{id}/oauth/* (Parallel pairing on Provider usage). A3 (scheduler) is not merged, but U3 only reads and writes the A4 allocation contract; user confirmed the API is stable.

1. Permissions and routes. Add project permissions settingsRead/Write/Copy, providersConfigure, credentialsManagePrivate and system credentialsManage, poolsManage, allocationsManage. Project sections after Usage: Providers ("providers", providers.read) and Settings ("settings", settings.read). Global routes: System credentials (/system/credentials, system.credentials.manage) and Capacity (/system/capacity, any of system.pools.manage, system.allocations.manage). Rename the global "Settings" link to "Provider settings" so it never shares a name with the project Settings link.
2. Remove dead secret paths. Delete the Keys tab, the key vault, putSecret/deleteSecret, the provider-scoped OAuth client and the Parallel pairing actions on Provider usage. The OAuth pairing dialog is rewired to credential-scoped endpoints and mounted from credential rows only.
3. Secret handling (AC1). One write-only secret input: password type, autocomplete off, held in component state only, cleared on success, failure, cancel, unmount and project switch; never in Redux, persisted state, URL, storage, toasts, errors or logs. Decoders keep only documented safe fields. OAuth shows only the user code, verification link and status; polling follows interval and stops on close, unmount and project switch.
4. Project Providers page. Per provider type: capability, system state (kill switch, system-enabled operations), available credentials (owner Project or System granted, auth mode, status, health, granted operations), bindings (route label, credential, priority, per-operation enable toggles, effective operations) with add/edit/remove under providers.configure. Private credentials: add (API key, or OAuth for Parallel), rotate, delete, connect/disconnect OAuth under credentials.manage_private and can_manage. Read-only for others with an explanation.
5. Capacity explanation (AC4). One shared explanation per allocation: strict cap (base is the ceiling, unused capacity is not lent), loans (guaranteed base under contention with weight, borrow up to effective max when the pool is idle, pool limit always applies), best effort for zero base. The project Providers page shows its allocations read-only with "Set by a system administrator."
6. Project Settings page (AC2, AC3). Sections Routing, Execution and Trace policy; each field shows the effective value, a provenance badge (System default, Project override, Limited by system), the system default and the system limit. With settings.write and override_allowed a field is editable, an override has Inherit (sends null), Save sends only changed fields at expected_revision, 409 shows a reload prompt. Without settings.write everything is read-only with an explanation. Trace policy shows a one-line effective policy summary; options looser than the system allows are disabled with the reason and retention is capped by the system limit.
7. Copy settings dialog (AC2). Source project, mode (Overrides only default, Effective snapshot), Preview lists fields, rejections and eligible bindings; Apply is enabled only for the current preview, echoes its three revisions and selected binding versions; any change invalidates the preview; 409 asks for a new preview. Needs settings.copy and settings.write.
8. System credentials page (AC1). Create (provider, label, API key or Parallel OAuth), rotate, delete, OAuth connect, and per-credential grants (project picker from visible projects, permitted operations limited to supported ones, edit, remove).
9. Capacity page (AC4). Pools (provider, label, upstream scope and key, rate constraints, concurrency, queue, status) with create/edit and credential links under system.pools.manage; per-project allocations editor under system.allocations.manage: base rate, window, Strict or Loans, max rate (loans only), weight, best effort, queue bounds, infeasible 409 explained; everyone else sees the read-only explanation.
10. Tests. Colocated Vitest tests for every new or changed module, including secret clearing and absence from storage/URL/DOM. Stub backend routes for all endpoints above. New BDD features for project providers, project settings plus copy, system credentials, capacity; rewrite settings Keys and parallel-oauth-pairing scenarios to the credential model without weakening their security assertions. Gate: pnpm test (maxWorkers 6), lint, typecheck, typecheck:e2e, depcruise, knip, build, Playwright stub suite against the post-U2 baseline.
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
2026-11-03 verification (branch chore/local-e2e-provider-seed, on top of U2 e90f52a):
- Vitest full suite 192 files / 2267 tests pass (--maxWorkers 6). lint 0 errors (19 pre-existing warnings, down from 21), typecheck, typecheck:e2e, depcruise (3 pre-existing orphans), knip (pre-existing findings only), build pass.
- Playwright stub: project-providers 5/5, project-settings 8/8, system-credentials 5/5, system-capacity 7/7, parallel-oauth-pairing 5/5 (rewritten to credential-scoped OAuth); with sidebar, app-shell, projects-shell, api-keys, playground and activity-usage features 88/88 on the final code. Remaining failures are pre-existing: routing C4-6 and tab-unification ("Ranks" tab), provider-quota-display Tavily card layout, providers-settings-merge header, untagged settings @smoke needing a live API.
- Security: the secret travels in exactly one create/rotate request body; BDD asserts it is absent from DOM, input values, localStorage, sessionStorage, URL, history state and console; failure text never echoes server detail for secret-bearing calls. Dropped Keys-tab and old pairing assertions are mapped to equivalent checks on the new screens.
- Review: one P2 fixed (copy preview pending flag not reset when inputs change mid-preview). P3 notes kept: ApiError keeps the raw response body in memory (never rendered or logged); OAuth dialog title is "Connect Parallel" because only Parallel supports OAuth; OAuth rows show both Connect and Disconnect.
- Decisions: A3 not merged; U3 uses the A4 allocation contract only (user confirmed the API is stable). Removed dead UI for PUT/DELETE /api/v1/providers/{id}/secret and /api/v1/providers/{id}/oauth/*. Global "Settings" nav renamed "Provider settings". Capacity with only system.pools.manage shows allocations read-only, or a notice when the backend returns 403.
- DoD 1 stays open for the same pre-existing e2e failures as U1/U2. DoD 4: the request path is unchanged (UI only).
<!-- SECTION:NOTES:END -->
