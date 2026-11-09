# Projects UI: Product and Engineering Review

## Review record

| Field | Value |
| --- | --- |
| Review date | 2026-11-02 |
| Branch | `chore/local-e2e-provider-seed` |
| Reviewed commit | `e90f52a` |
| Recommendation | Request changes. Retain the useful foundations. |
| Review environment | Existing worktree, API 8011, UI 5175, disposable `polyweb.dev.db` |
| Source changes during review | None |
| Document purpose | Review findings, evidence, decisions, and corrective work |

Use the checklist at the end to record decisions and progress. The findings describe the reviewed commit, not subsequent fixes.

Evidence links reference local files under `.runtime-tmp`. Git does not track these artifacts. Preserve or attach them before you share this document elsewhere.

## Instructions for the implementation agent

This document records review feedback, not implementation work. Dhruv retains authorship of the existing implementation.

**Required skill: `unslop`.** The repository includes the skill at [`.agents/skills/unslop/SKILL.md`](../.agents/skills/unslop/SKILL.md).

1. Invoke `unslop` before UI layout, style, or interaction changes.
2. If the agent cannot invoke skills, read the skill file and its referenced guidance first.
3. Follow its audit and direction-approval steps before visual changes.
4. Preserve the established Polyweb MCP identity and reusable components. Do not replace working UI merely to make it different.
5. Correct the functional findings as well as the visual defects. The skill does not replace permission, isolation, or workflow checks.
6. Retain the skill's original author credit and CC BY 4.0 license notice.

## Executive assessment

Do not accept this branch as a finished Projects experience. Do not discard the backend or replace the complete frontend.

The reported dissatisfaction has reproducible causes. This is not only an aesthetic disagreement.

The implementation contains useful authorization, isolation, execution, and API-key functionality. However, the product combines an incomplete project workspace with retained global screens.

Several important workflows stop between these two parts of the application. The corrective work needs complete user journeys, not only visual changes.

## Severity definitions

- **P1:** A release blocker. A core workflow cannot finish through the current product.
- **P2:** A significant behavior, usability, or consistency defect. Correct it before product approval.
- **Scope gap:** Functionality that the current product does not provide. Agree on its requirement before implementation.

## Findings

### F1. P1 — A new project does not lead to a usable project

#### Reproduction

1. Sign in as `admin1@example.com`.
2. Create a project.
3. Set `user1@example.com` as its first administrator.
4. Sign in as `user1@example.com`.
5. Open the new project.
6. Open Playground.
7. Submit a search.
8. Look for project provider configuration.

#### Observed result

- Search returns HTTP **503**.
- The UI displays `no provider is configured for this project`.
- Playground offers Auto and an enabled Search button.
- The project has no Providers or Settings section.
- The UI gives no setup instructions.
- This project administrator has no global Settings access.

The seeded projects work because the seed script grants credentials and creates provider bindings. The normal creation journey does not expose this setup.

Tests that use only configured fixture projects miss this defect.

This is not an authorization defect. A system administrator correctly receives no implicit membership after they assign another user as project administrator.

The product needs a usable handoff and setup workflow.

#### Root cause

The delivery boundary is incomplete. U1/U2 expose project creation and execution before U3 supplies project provider and settings management.

The overview shows status, roles, and usage. It does not guide a new administrator through first use.

#### Sources

- [`routes.ts`, lines 108–135](../polyweb-ui/src/app/routes.ts): available project sections.
- [`ProjectOverviewPage.tsx`, lines 22–70](../polyweb-ui/src/features/projects/ui/ProjectOverviewPage.tsx): project overview.
- [`ProjectCreateForm.tsx`](../polyweb-ui/src/features/projects/ui/ProjectCreateForm.tsx): creation and administrator handoff.
- [`seed_dev.py`](../scripts/seed_dev.py): fixture credential grants and provider bindings.

#### Evidence

![New project with no usable provider setup](../.runtime-tmp/review-new-project-503-stable.png)

### F2. P1 — The retained Parallel connection workflow calls an obsolete API

#### Reproduction

1. Sign in as an administrator.
2. Open **Provider usage**.
3. Click **Connect** on Parallel.

#### Observed result

The connection dialog displays **Not Found**.

```text
GET  /api/v1/providers/parallel/oauth/status       → 404
POST /api/v1/providers/parallel/oauth/device-code → 404
```

The live API exposes credential-scoped OAuth routes instead:

```text
/api/v1/system/credentials/{credential_id}/oauth/device
/api/v1/system/credentials/{credential_id}/oauth/poll
/api/v1/system/credentials/{credential_id}/oauth

/api/v1/projects/{project_id}/credentials/{credential_id}/oauth/device
/api/v1/projects/{project_id}/credentials/{credential_id}/oauth/poll
/api/v1/projects/{project_id}/credentials/{credential_id}/oauth
```

The client converts a 404 from the old status endpoint into an ordinary **unpaired** state. This conceals the contract mismatch until connection starts.

#### Root cause

The backend API migration and retained frontend workflow do not use the same contract. This is a functional regression.

#### Sources

- [`polywebApi.ts`, lines 152–179](../polyweb-ui/src/services/api/polywebApi.ts): old OAuth paths and the 404 fallback.
- [`useOAuthPairing.ts`](../polyweb-ui/src/features/oauth/model/useOAuthPairing.ts): status consumption.
- [`credential_oauth.py`](../src/polyweb/routers/credential_oauth.py): credential-scoped backend routes.

#### Evidence

- [Connection dialog](../.runtime-tmp/review-parallel-connect-404.png).
- [Network requests](../.runtime-tmp/review-network-final.txt).

**Do not confuse this defect with manual-quota responses.** Manual-quota GET requests return 404 when no manual entry exists. Those routes still exist.

### F3. P2 — Membership changes do not refresh the project list

#### Reproduction: access addition

1. Leave a regular user's Projects page open with no memberships.
2. Use another administrator session to add that user to a project.
3. Return to the regular user's tab.
4. Focus the tab.
5. Use normal application navigation.

#### Observed result

The page continues to show:

> You are not a member of any project.

At the same time, the authenticated project-list API returns the new project. A full browser reload corrects the UI.

#### Reproduction: access removal

1. Leave a member on a project page.
2. Suspend that membership in another administrator session.
3. Return to the member's tab.
4. Follow **All projects** from the access-denied screen.

#### Observed result

The backend correctly denies access. However, the Projects page still lists the revoked project.

The user can select the same project and return to the unavailable-project screen.

#### Root cause

The UI uses two different freshness policies:

- Project access refreshes every 30 seconds and on window focus.
- The project list and system access load once per account.

The access boundary works. The navigation data remains stale.

#### Sources

- [`ProjectsProvider.tsx`, lines 19–43](../polyweb-ui/src/domains/projects/state/ProjectsProvider.tsx): account-level snapshot and explicit reload.
- [`ProjectScopeProvider.tsx`, lines 11–38](../polyweb-ui/src/domains/projects/state/ProjectScopeProvider.tsx): project access refresh policy.

#### Evidence

- [Empty state after the administrator grants access](../.runtime-tmp/review-stale-empty-after-add.png).
- [Revoked project remains in the list](../.runtime-tmp/review-stale-project-list.png).

### F4. P2 — Project identity and navigation do not form a consistent workspace

#### Reproduction

1. Open Alpha's Members or Activity page at 1280×800.
2. Repeat at 1440×900.
3. Identify the current project without a menu.
4. Select global **Routing**, **Settings**, or **Provider usage**.
5. Look for a direct return to the project's Playground or Activity page.

#### Observed result

- The project name appears as approximately `Alpha - Sh...`.
- At 1280×800, the label has 76 pixels for text that needs 126 pixels.
- The expanded project selector has no tooltip.
- Members and Activity show no full project identity in their main header.
- A global page changes the selector to **Select project**.
- The complete project navigation group disappears on global pages.

This is a loss of orientation and continuity. It is not evidence of cross-project data leakage.

#### Root cause

The current URL supplies project context. Prominent navigation still takes the user outside the project subtree.

The Preview badge also consumes much of the selector's fixed-width row.

#### Sources

- [`Sidebar.tsx`, lines 37–46](../polyweb-ui/src/app/layout/Sidebar.tsx): project selection from the URL.
- [`ProjectSelectorTrigger.tsx`, lines 34–49](../polyweb-ui/src/features/projects/ui/ProjectSelectorTrigger.tsx): label truncation, badge, and tooltip behavior.
- [`routes.ts`](../polyweb-ui/src/app/routes.ts): separate global and project routes.

#### Evidence

![Members page at a supported desktop size](../.runtime-tmp/review-members-1280.png)

- [Members at 1440×900](../.runtime-tmp/review-members-1440.png).
- [Global Routing page](../.runtime-tmp/review-global-routing.png).

### F5. P2 — A provider read failure looks like an empty configuration

#### Reproduction

Use a browser-only network fault. Do not change application code.

1. Make the project providers GET return HTTP 503.
2. Reload Playground.
3. Open the provider picker.

#### Observed result

- Named providers disappear.
- Only Auto and All providers remain.
- The UI gives no error explanation.
- The UI gives no Retry control.

The user cannot distinguish an empty configuration from a failed read.

#### Root cause

`ProjectPlaygroundPage` converts every non-ready provider state into an empty provider array.

The page exposes a loading flag, but no provider error state or recovery action.

#### Source

- [`ProjectPlaygroundPage.tsx`, lines 21–42](../polyweb-ui/src/features/playground/ui/ProjectPlaygroundPage.tsx).

#### Evidence

- [Provider read failure with no visible error](../.runtime-tmp/review-provider-read-error-hidden.png).

The project-list failure surface behaved better. Its Retry control recovered after the corresponding controlled fault.

### F6. P2 — Shared tokens do not produce consistent screen and interaction patterns

The statement that the implementation reuses nothing is incorrect.

Project creation and member addition use shared `TextField` and `Button` components. Colors and fonts largely retain the existing system.

The problem concerns reuse at the workflow and screen level:

- Members uses small native selects and custom text-button classes for administrative actions.
- Role removal appears as an inline `− Project admin` or `− Project member` action.
- Member removal changes to **Confirm removal**, without a corresponding Cancel action.
- Pending operations disable controls. Focus returned to `BODY` after submission during the review.
- Validation appears above the complete form, without an association with the affected field.
- Members uses a small heading and a bare table.
- API keys uses a larger heading and a large stacked form.

#### Reproduction

1. Open Members.
2. Submit an invalid or nonexistent account.
3. Inspect keyboard focus and error placement.
4. Start member removal.
5. Look for a clear Cancel action.
6. Compare Members with API keys and the existing Playground.

#### Root cause

Local JSX and CSS classes implement individual controls. The project screens lack consistently applied page, form, row-action, and feedback patterns.

#### Sources

- [`AddMemberForm.tsx`, lines 20–58](../polyweb-ui/src/features/projects/ui/AddMemberForm.tsx).
- [`MemberRowActions.tsx`, lines 39–84](../polyweb-ui/src/features/projects/ui/MemberRowActions.tsx).
- [`ProjectCreateForm.tsx`](../polyweb-ui/src/features/projects/ui/ProjectCreateForm.tsx): existing shared field and button reuse.

#### Evidence

- [Validation and interaction feedback](../.runtime-tmp/review-validation-feedback.png).
- [API-key form](../.runtime-tmp/review-api-keys-stable-1440.png).

### G1. Scope gap — Project editing is absent

The UI permits project creation and viewing. It does not provide a project rename or edit workflow.

The live API schema has no general project-update route. The backend exposes archive separately, but the overview provides no lifecycle-management action.

This is a scope gap, not a failed edit button.

Agree on the project-management contract and acceptance criteria before implementation.

## Verified functionality worth retaining

No authorization bypass occurred in the exercised paths. This review is not a complete security certification.

| Area | Verified result |
| --- | --- |
| Accounts | Sign-in worked for both administrators and all three regular users. |
| Original fixtures | Alpha, Beta, and Gamma matched the intended membership matrix. |
| Project creation | Self-admin and another-user-admin creation worked. No implicit system-admin membership appeared. |
| Membership administration | Add, remove, suspend, reactivate, promote, and demote operations worked. |
| Project administrator | A user without system-admin privileges managed their own project. |
| Last administrator | Sole-admin demotion, suspension, and removal received refusals with explanations. |
| Single-admin cases | The review covered an owner-only project and Beta's single-admin case. |
| Regular members | Management controls were absent. Direct member-management and key-issue requests received denials. |
| Isolation | Foreign-project reads and foreign trace lookups received denials. |
| Separate tabs | Different projects retained separate drafts for the same account. |
| Search and fetch | Brave search and Exa fetch succeeded through human sessions. |
| Request cancellation | A delayed request did not place late state into the newly selected project. |
| Activity | Filters, metadata-only explanations, timeline inspection, and detail close worked. |
| Cursor pagination | Real backend cursors worked with a browser-only one-item page-size override against the sparse live history. |
| List retention | Activity retained the loaded rows after detail close. |
| API keys | No-expiration issue, one-time reveal, immediate-overlap rotation, and revocation worked. |
| Secret persistence | The checks found no raw API key in local or session storage. |

The review did not exercise every expiration permutation or complete external OAuth approval.

## Why the tests missed these problems

### The tests contain more than happy paths

Existing tests cover permissions, last-admin conflicts, archive refusals, cancellation, separate tabs, and secret handling.

The backend authorization suite also contains concurrency and last-administrator cases.

Retain these tests. The gaps concern integrated user journeys and visual acceptance.

### T1. The visual acceptance test checks the wrong property

The test checks the selector button's bounding box and accessible name. Its fixture uses the short name `Alpha`.

The test can pass when visible project text is clipped. It does not establish readable project identity or visual consistency.

Source: [`project-api-keys.steps.ts`, lines 264–296](../polyweb-ui/tests/steps/project-api-keys.steps.ts).

### T2. Membership discovery uses an initial-snapshot test model

Provider tests cover initial load, failure, and explicit reload.

They do not establish that another administrator's membership change becomes visible through normal navigation.

Source: [`ProjectsProvider.test.tsx`](../polyweb-ui/src/domains/projects/state/ProjectsProvider.test.tsx).

### T3. Playground tests omit the provider-read failure state

Cases cover provider choices, permission restrictions, session execution, section changes, and cancellation.

They do not cover the conversion of a failed provider read into an empty picker.

Source: [`ProjectPlaygroundPage.test.tsx`](../polyweb-ui/src/features/playground/ui/ProjectPlaygroundPage.test.tsx).

### T4. Frontend stubs can preserve obsolete API contracts

Stubbed expectations can pass without compatibility with the live backend.

The Parallel OAuth failure demonstrates the need for a real frontend/backend compatibility check.

### T5. The regression baseline does not establish product readiness

U1/U2 notes disclose substantial existing E2E failures. Their verification Definition of Done remains open.

No new regression against a post-API-rewrite baseline does not establish preservation of the earlier acceptable application.

The combined branch needs an integrated acceptance decision.

Related tasks:

- [TASK-000046: U1](../.backlog/tasks/task-000046%20-%20Projects-U1-Project-shell-members-and-API-keys-UI.md).
- [TASK-000047: U2](../.backlog/tasks/task-000047%20-%20Projects-U2-Activity-usage-and-playground-UI.md).

## Verification completed during this review

| Check | Result |
| --- | --- |
| Targeted frontend tests | 39 files, 312 tests passed |
| Targeted backend tests | Three files, 33 tests passed |
| Complete BDD release gate | Not rerun |
| Complete lint, typecheck, and build gate | Not rerun |

Frontend selections covered projects, project domains, the app shell, project Playground, Activity, and Usage.

Backend selections:

```text
tests/integration/routers/test_projects_api.py
tests/integration/routers/test_api_keys_api.py
tests/integration/services/test_projects_authorization.py
```

Evidence:

- [Frontend test output](../.runtime-tmp/review-vitest.log).
- [Backend test output](../.runtime-tmp/review-backend-tests-final.log).
- [Network requests](../.runtime-tmp/review-network-final.txt).
- [Console errors](../.runtime-tmp/review-console-errors.txt).
- [Live cursor pagination and retained list](../.runtime-tmp/review-live-cursor-retention.png).
- [Last-admin refusal](../.runtime-tmp/review-last-admin.png).

Interpret diagnostics by request. Intentional permission denials, absent manual-quota entries, and injected faults are not independent product defects.

The fresh-project 503 and obsolete OAuth endpoint 404 responses are real product failures.

## Cause assessment

### Product planning and delivery

The accepted architecture is defensible.

The delivery sequence exposes a broad intermediate product before its complete journey exists:

```text
Create → Configure → Execute → Inspect
```

U1/U2 and the retained global screens do not form a consistent release boundary.

### Implementation choices

Concrete implementation defects include:

- Stale project discovery state.
- Obsolete OAuth calls.
- Hidden provider read errors.
- Loss of project context on global routes.
- Inconsistent action and feedback patterns.

### Test strategy

Many important invariants have useful tests.

Integrated user journeys and visual acceptance need stronger checks. Shared tokens and an in-viewport button do not establish a good product experience.

## Salvage assessment

### Retain

- Project-scoped backend contracts and authorization.
- Effective-permission gates instead of account-role assumptions.
- Last-administrator protections.
- Project-scoped execution and cancellation boundaries.
- API-key lifecycle and one-time reveal behavior.
- Separate project drafts and stores.
- Existing Playground and trace-inspector components.
- Useful negative-path and concurrency tests.

### Rework

- The project workspace shell and project identity.
- The first-use setup and administrator handoff.
- Project discovery refresh and access-change recovery.
- OAuth integration with credential-scoped APIs.
- Provider loading, error, and empty states.
- Page headers, form layouts, action menus, confirmations, and focus behavior.
- Acceptance tests that substitute element presence for usable workflows.

Do not replace working isolation or authorization with an older global model to simplify the UI.

## Corrective plan

### 1. Establish a complete release boundary

Complete project provider setup and first-use guidance. Alternatively, keep Projects outside the default released experience until the journey works.

Do not leave users with projects that they cannot make useful through the product.

### 2. Correct integration defects before visual changes

- Migrate OAuth calls to credential-scoped APIs.
- Refresh project discovery on appropriate focus and navigation events.
- Reconcile discovery after access changes.
- Distinguish provider loading, read failure, and empty configuration.
- Give the user a clear recovery action for each failure.

### 3. Rework the workspace shell, not the complete application

- Keep full project identity visible.
- Keep project navigation consistent.
- Separate project operations from installation administration.
- Preserve a direct return to the project workspace.

### 4. Standardize new screens with existing patterns

Use consistent page headers, forms, row-action menus, confirmation controls, and field errors.

Preserve keyboard focus. Retain the useful Playground and trace inspector.

### 5. Add a small live acceptance gate

Cover these workflows against a fresh database:

- Fresh project creation through first successful execution.
- Another user gains and loses membership.
- Project switches and late responses.
- API-key lifecycle.
- Retained provider integration.

Add visual checks with realistic long project names at 1280×800 and 1440×900.

## Editable follow-up checklist

These entries are proposed review actions. They do not replace Backlog tasks or change task status.

| ID | Action | Acceptance evidence | Status / owner / notes |
| --- | --- | --- | --- |
| F1 | Complete project setup and administrator handoff | A newly created project reaches successful execution without scripts | Open |
| F2 | Migrate retained Parallel OAuth | Connect starts through credential-scoped routes without obsolete-route 404 responses | Open |
| F3 | Refresh project discovery after membership changes | Add and revoke access in another session without a full page reload | Open |
| F4 | Preserve readable project identity and navigation | Long names remain readable at both supported desktop sizes | Open |
| F5 | Expose provider read errors and recovery | A failed provider read shows an explanation and a working Retry action | Open |
| F6 | Standardize forms, row actions, confirmation, and focus | Consistent controls, explicit cancellation, field errors, and stable keyboard focus | Open |
| G1 | Decide the project edit and lifecycle contract | Agreed rename/edit/archive requirements and acceptance criteria | Decision needed |
| T1 | Correct visual acceptance assertions | Checks detect clipped project names and inconsistent project context | Open |
| T2 | Add a live membership-discovery journey | Two sessions cover an access grant and revocation | Open |
| T3 | Cover provider-read failures | Component tests distinguish loading, empty, and error states | Open |
| T4 | Check frontend/backend contract compatibility | Retained workflows use routes that the actual backend exposes | Open |
| T5 | Complete the integrated release gate | Record remaining regressions and obtain explicit product acceptance | Open |

### Decisions and updates

| Date | Decision or update | Owner | Evidence / related task |
| --- | --- | --- | --- |
| 2026-11-02 | Initial review: request changes and retain the useful foundations | Review | Reviewed commit `e90f52a` |

## Environment handback

- The original seeded memberships match the initial Alpha/Beta/Gamma matrix after the review.
- Review-issued API keys are revoked.
- Two review projects remain in the disposable development database: `Review - User owned` and `Review - Owner only`.
- The review did not change normal databases, provider credentials, or `.env`.
- Existing source changes remain intact.
- Application source changes were not necessary.

## Final recommendation

Reject the current product experience, not the complete engineering investment.

Preserve the scoped backend, permission model, cancellation boundaries, API-key lifecycle, and reusable execution and trace components.

Rework the integration and project shell around complete user journeys.
