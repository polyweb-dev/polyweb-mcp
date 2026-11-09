---
id: TASK-000046
title: Projects U1 - Project shell, members and API keys UI
status: Done
assignee:
  - '@devin'
created_date: '2026-10-26T09:47:00Z'
updated_date: '2026-11-09T12:32:00Z'
labels:
  - projects-first
  - step-3-ui
milestone: m-1
dependencies:
  - TASK-000041
documentation:
  - doc-000003
  - doc-000005
  - doc-000002
  - doc-000008
priority: high
type: feature
ordinal: 45000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
The desktop app needs project selection, membership and API-key management driven by effective permissions instead of account roles. The merged P06 shell is the starting point. Design: local plan section 8 (doc-000002).

Step rules and the shared Definition of Done: doc-000003. Card map and worktree rules: doc-000005. Do not start before every dependency is Done and merged into feature/project. When you start, record your own implementation plan in Backlog after researching the current code.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 Navigation, routes and controls follow effective permissions from the API, never role labels; signup and administration show no account-type choice.
- [x] #2 Permitted system users create projects and name the first administrator; project administrators manage members and roles; last-administrator refusals are explained.
- [x] #3 API-key screens issue keys with a No expiration option, show the raw key once, list creator, expiry and last use, and rotate and revoke keys.
- [x] #4 Two tabs in different projects never share drafts, results or access rights.
- [x] #5 Project screens retain the shared colors, typography and controls. The selected project and active screen remain visible at 1280x800 and 1440x900.
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
Research findings (2026-10-31): the UI still decodes a role-bearing account (UserRole admin/developer/agent, is_superuser) and gates routes and controls by role. The backend UserAccount has no role (id, email, auth_provider, auth_provider_id, username, first_name, last_name, is_active, is_verified), so /users/me fails the UI decoder. Registration and POST /api/v1/users accept only email and password (extra fields give 422). Global control routes require system.settings.read for reads and system.settings.write for mutations and account provisioning. /search, /fetch and /api/v1/traces are project-scoped now; U2 moves playground and activity. Project API key routes exist: POST and GET /api/v1/projects/{id}/api-keys, POST .../{key_id}/rotate, DELETE .../{key_id}.

1. Auth domain without roles. UserAccount mirrors the backend shape. Remove UserRole, USER_ROLES, ROLE_LABELS, isUserRole, is_superuser and RoleField. Register and admin provisioning send only email and password. Register, register success, account page, sidebar account menu and admin users page show no role or account-type choice; they show the email, plus name or username when present.
2. Permission-driven shell. app/permissions.ts and routes.ts derive every gate from effective permissions: system permissions from GET /api/v1/system/access (ProjectsProvider), project permissions from GET /api/v1/projects/{id}/access (ProjectScopeProvider). Global routes: routing, usage and settings need system.settings.read; edits need system.settings.write, and FreeSearchProvider canReadControls/canEditControls come from these two. Admin users needs system.settings.write. Projects and account are always open. Playground and activity stay global and untouched until U2. While system access loads, gated routes show a loading state, never a redirect. When the projects or system access load fails, show an error with Retry instead of hiding the UI. An unauthorized direct URL redirects to "/".
3. Project-first landing. "/" and unknown paths go to the validated last project (resolveLastProject), else /projects. The login fallback destination is "/".
4. Project section registry in routes.ts: overview (segment "", needs project.read), members (segment "members", needs members.read), apiKeys (segment "api-keys", needs tokens.manage). U2 and U3 add entries to the same table. projectPath(projectId, section) and isInternalPath accept every registered section. ProjectScopeProvider moves up to DashboardShell, keyed by accountId:projectId from the URL, so the sidebar and the page share one project access state. The sidebar shows a Project nav group (sections filtered by project permissions) above the global group (Projects, permitted system items, Account). A section gate redirects to the project overview when its permission is absent. The project selector keeps the current section on a switch.
5. Members and project creation (AC 2). Audit the existing P06 pages against the backend contracts. The create form shows only with system.projects.create and needs an initial admin email (defaults to self). Add, suspend and remove need members.manage. Role assign and remove need roles.assign. The LAST_PROJECT_ADMIN 409 shows an explanation and the next step: "Make another active member a project admin first." Fix every gap.
6. API keys (AC 3). Domain: domains/projects/api/apiKeysApi.ts, wire decoders and a ProjectApiKey type. Feature in features/projects: useProjectApiKeysController, ProjectApiKeysPage, IssueApiKeyForm, ApiKeyRevealDialog, RotateApiKeyDialog, ApiKeyRowActions. Issue form: Label; Scopes (Search, Fetch; a scope the caller lacks in project access is disabled); Expiration (90 days default sends no expires_at; No expiration sends explicit null; Custom date sends a future ISO timestamp). The raw key shows once in a dialog with Copy and a "shown only once" warning. It lives only in local component state: never in Redux, storage, drafts, URLs or logs. It is cleared on close, unmount and project switch. This form has no persisted draft. List, newest first: label, prefix, scopes, created by (member email when members are readable, else a short id), created, expires ("No expiration" for null), last used ("Never" when null), status. Rotate (active keys only): overlap (Revoke old key now = 0, 1 hour, 24 hours default, 7 days) and expiration (Keep current lifetime sends no expires_at; No expiration sends null; Custom date); the new key shows once. Revoke has an inline confirm. Errors: 409 API_KEY_INACTIVE, 409 PROJECT_ARCHIVED, 403 (permission lost, then refresh access), 422 detail. An archived project hides issue and rotate and shows a note.
7. Isolation (AC 4). All project state is keyed by the URL project id. No cross-tab sync of drafts or access. The last project is written only on an explicit selection.
8. Visual (AC 5). Reuse the shared tokens and shared/ui controls. The selected project name and the active section stay visible without scrolling at 1280x800 and 1440x900.
9. Tests. Colocated Vitest unit tests for every new or changed module. Rewrite (never weaken) the role-based BDD stub scenarios (sidebar-account-menu, auth-display, projects-shell) to the permission model. Add a project-api-keys stub feature (issue with No expiration, reveal once, list, rotate, revoke) and a viewport scenario at 1280x800 and 1440x900. Gate: pnpm test, lint, typecheck, typecheck:e2e, depcruise, knip, build, Playwright stub suite.
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
2026-10-31 verification (branch chore/local-e2e-provider-seed):
- Vitest: 155 files, 2128 tests, 0 failed (--maxWorkers 6). Vitest at the default 16 workers times out on this machine before and after U1; 6 workers is stable.
- lint 0 errors (21 pre-existing warnings), typecheck, typecheck:e2e, depcruise 0 errors (3 pre-existing orphan warnings), build pass. knip reports only pre-existing findings (4 unused files, QuotaRow export).
- U1 BDD (@stub): sidebar-account-menu 32/32, auth-display 5/5, projects-shell 9/9 (incl. 1280x800 and 1440x900 viewport outline), project-api-keys 5/5 (issue with No expiration, reveal once, storage/URL/history absence, rotate 24h default, revoke, no-permission redirect, two-tab isolation), app-shell-routing 14/15 (C4-6 fails before and after U1: missing Ranks tab).
- Regression proof against e7fa123 in a temporary worktree: 0 scenarios fail now that passed before U1. 89 stub/visual scenarios fail both before and after U1 (activity-traces 22, provider-credits 20, routing 16, keenable-card 9, parallel-oauth-pairing 5, visual V2/V3/K2/K3, and 13 others); most were masked before because the stub had no session. 98 pass now that failed before.
- Decisions: project creation is gated on project.create (what the backend enforces). The admin page heading is "Accounts". Rotate is hidden for a key that already has a successor. The stub signs in as a role-less system administrator by default. Visual baselines V1/R1 were not regenerated because they already failed before U1 for non-U1 Routing changes.
- DoD 1 stays open: the 89 pre-existing e2e failures in other features are outside U1 scope and need a decision.
<!-- SECTION:NOTES:END -->
