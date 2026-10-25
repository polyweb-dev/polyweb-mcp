---
id: TASK-000019
title: Projects P02 - Project lifecycle and authorization service
status: Done
assignee: []
created_date: '2026-10-24T15:54:00Z'
updated_date: '2026-10-25T10:14:00Z'
labels:
  - projects-first
  - phase-p02
  - serial-foundation
milestone: m-0
dependencies:
  - TASK-000018
references:
  - src/freesearch/services/users.py
  - src/freesearch/routers/auth.py
  - src/freesearch/cli/users.py
  - src/freesearch/persistence/users.py
documentation:
  - doc-000001
  - doc-000002
  - doc-000003
  - doc-000004
  - doc-000005
  - .agents/communication/projects-feature-plan.md
  - .backlog/docs/doc-000005 - Projects-execution-index-start-here.md
priority: high
type: feature
ordinal: 1000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Different project roles must apply to the same human identity without granting installation-wide privilege or leaving a project without an administrator.

Phase: P02. Execution lane: serial-foundation. Milestone: Projects 1 - Foundation.

Dependency gate: P01 (TASK-000018)
Do not implement or mark In Progress until every dependency is Done, merged into the integration branch, and its acceptance evidence is available. Priority and phase numbers never override this gate. Parallel work is permitted only where the dependency graph and shared-file ownership allow it.

Accepted scope from plan section 10 / P02:

Add project list/create/archive and membership read/change endpoints behind the rollout state.
Implement the common RBAC service, built-in scoped roles, extra role assignments, delegation limits, and live authorization checks.
Guard all administrator-affecting operations in write transactions.

Cross-phase constraints:
User-approved constraints: one human account type; one common scoped RBAC service; system/project roles are assignments, not account types. Preserve internal UUIDs and local/WorkOS storage constraints without implementing WorkOS/cloud features. Use one internal installation account. Project tokens can expire or have no expiration. Support private and explicitly shared credential instances. Strict pool/project caps are the default; fair loans require their later phase. Use a fresh alpha database; do not migrate/import old history, humans, settings or secrets. Never use the live database or real provider credentials for tests. Desktop UI only; local environment controls ports.

Verification expectations:
Use unit permission matrices and real SQLite concurrency tests with separate connections. Cover self-removal, demotion, bulk changes and account-wide deactivation.
Use the managed verification specification for required quality commands and test placement. Record objective evidence before completion.

Before code work, read AGENTS.md and applicable skills, use CodeGraph for indexed code, inspect current implementation and record the task implementation plan through Backlog. The referenced design is context; this future ticket intentionally has no speculative implementation-plan field.

Documentation: local .agents/communication/projects-feature-plan.md, sections 4-10 for design and scope, section 11 for ordering. The managed specification documents are durable copies for checkouts where the gitignored local plan is absent. Use the execution-index document for exact phase-to-ticket IDs and ready-work commands.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 One common authorization service governs system and project operations using the stable permission catalog and scoped role assignments.
- [x] #2 Project list/create/archive and membership/role operations enforce the documented scope and delegation boundaries.
- [x] #3 The same human can be project_member in one project and project_admin in another without an account conversion.
- [x] #4 Concurrent membership removal, demotion and account deactivation cannot remove a project's last active administrator through supported app or CLI paths.
- [x] #5 No project role or legacy superuser flag bypasses system or project permission checks.
- [x] #6 System administration remains a scoped assignment and does not imply project content membership.
<!-- AC:END -->

## Definition of Done
<!-- DOD:BEGIN -->
- [x] #1 All phase acceptance criteria have objective test or review evidence recorded in Backlog before Done.
<!-- DOD:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. Add a live ScopedAuthorizationService that resolves system/project role assignments from SQLite on every check, maps each catalog action to its documented scope, enforces active human/project-membership/account state and deny-by-default decisions, and exposes effective-permission and delegation checks.
2. Extend ProjectRepository with strict membership reads/updates/removals, extra-role assignment/removal, per-user project listing, and active project-admin counts. Add a BEGIN IMMEDIATE write helper with bounded SQLite lock retries.
3. Add services/projects.py for project list/create/archive, membership add/change/remove, role add/remove, atomic bulk changes, and account-wide deactivation. Enforce scope, delegation subsets, archived-project write refusal, initial-admin provisioning, and a rolled-back LAST_PROJECT_ADMIN guard.
4. Add thin REST endpoints for project/membership operations and a system-authorized deactivation path behind the rollout state; add an operator CLI deactivation command using the same guard.
5. Add focused unit permission-matrix/delegation tests, integration lifecycle/router/CLI tests, and separate-connection SQLite concurrency tests; run ruff, mypy and changed-area tests only.
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
### P02 Developer Handoff (production implementation)

Ownership note: Two test files were created before the explicit no-test-edits instruction and are left byte-for-byte intact for the tester: tests/integration/services/test_projects_authorization.py and tests/unit/services/test_authorization.py. No test, fixture, snapshot, or test configuration was edited after that instruction.

Production files added/changed:
- src/freesearch/services/authorization.py: ScopedAuthorizationService resolves account/user active state, active project membership, system/project role assignments, and token execution scopes live on every decision. It uses the P00 evaluator, documented action-scope mapping, deny-by-default behavior, and delegation subset checks. System assignments never enter project permission sets.
- src/freesearch/services/projects.py: ProjectService with project list/create/archive, member read/add/status/remove, extra-role assign/remove, atomic bulk membership updates, and account-wide deactivation. Every admin-affecting write runs one SQLite BEGIN IMMEDIATE transaction with bounded lock retries, then verifies active project_admin count after mutation and rolls back with LAST_PROJECT_ADMIN. Archived projects permit access-reducing changes only; expansion returns PROJECT_ARCHIVED. Project creation is system-scoped; system administrators gain no implicit membership.
- src/freesearch/persistence/projects.py: strict membership/role read-update-delete queries, per-user project access, and active-admin counts joining role+membership+active user rows.
- src/freesearch/models/projects.py: documented action_scope mapping (project.create is system scope), PROJECT_CREATE in system_admin, and ProjectMemberChange/ProjectMembersBulkUpdate contracts.
- src/freesearch/routers/projects.py: thin routes for GET/POST /api/v1/projects, POST archive, GET/POST members, PATCH/DELETE member, PUT/DELETE role, PATCH members/bulk, and POST /api/v1/users/{id}/deactivate. Failures map to 403/404/409(code)/400/503 without leaking policy internals.
- src/freesearch/routers/auth.py + control.py: require_admin/require_control_reader now use the common live service (system.settings.write/read) instead of account-role comparison; no is_superuser shortcut remains on these paths.
- src/freesearch/cli/users.py: freesearch-users deactivate --user-id ... (repeatable) uses the same trusted deactivation guard and reports LAST_PROJECT_ADMIN without changing the account.
- src/freesearch/routers/api.py registers the project routes.

Focused verification commands and outcomes:
- uv run ruff check <9 touched source files>: All checks passed.
- uv run ruff format --check <9 touched source files>: all formatted.
- uv run mypy <9 touched source files>: Success, no issues in 9 source files.
- uv run pytest tests/unit/services/test_authorization.py tests/unit/models/test_projects.py tests/unit/persistence/test_projects.py tests/integration/persistence/test_projects.py tests/integration/persistence/test_projects_adversarial.py -q: 58 passed.
- uv run pytest tests/integration/cli/test_users.py tests/integration/routers/test_admin_users_api.py -q: 17 passed.
- uv run pytest tests/integration/routers/test_control_api.py::test_provider_patch_merges_estimates_and_returns_updated_status tests/integration/routers/test_control_api.py::test_rest_lifespan_clears_config_cache -q: 2 passed.
- uv run pytest tests/integration/services/test_projects_authorization.py -q: 6 passed, 1 failed. Failure: test_account_deactivation_guard_bulk_and_live_revocation. The test deactivates admin, then tries to add the same deactivated user back to the project and expects the subsequent bulk-deactivation check. Production correctly rejects adding an inactive account; this is a stale/buggy test setup, not a production defect. Tester should use a third active user for the bulk-deactivation assertion.
- Ad-hoc non-pytest HTTP flow (TestClient, fresh temp DB): anonymous 401; non-system project create 403; system create 201 with system admin list empty; project admin list/member-read 200; system admin member-read 403; last-admin DELETE 409 LAST_PROJECT_ADMIN; project member archive 403; role assignment/bulk suspend 200; suspended member next request 403 with same JWT; project-admin deactivation 403; system deactivation 200 and old JWT 401; archive 200; archived expansion 409 PROJECT_ARCHIVED; archived last-admin removal 409 LAST_PROJECT_ADMIN.
- Ad-hoc CLI flow (fresh temp DB): sole-admin deactivate exit 1 with last-admin message and account stays active; with a peer admin deactivate exit 0 and account inactive; bulk deactivation that would leave zero admins exit 1 with no state change.

Pre-existing unrelated failure observed while running a broader unit batch:
- uv run pytest tests/unit/services/test_users.py::test_provision_account_uses_safe_manager_and_returns_projection fails because it still requests the obsolete developer role that P01 intentionally rejects. Not caused by P02 and not edited.

Known gaps / design concerns for tester and reviewer:
- Rollout gate currently treats preview/strict/fair as management-enabled (execution remains out of scope); there is no disabled enum value in P00, so the gate is structural rather than a kill switch.
- Account deactivation uses system.roles.assign as the closest existing system-scope authority; the P00 catalog has no dedicated system.users.manage action.
- Project creation by a system administrator intentionally bypasses the delegation-subset rule when naming the first project_admin; this is the documented provisioning exception.
- Archived projects accept only access-reducing membership/role changes; reviewer should confirm this interpretation against plan section 4.4.
- Two pre-authored concurrency tests can observe AuthorizationDenied instead of LAST_PROJECT_ADMIN depending on which concurrent operation commits first; the invariant (one active admin remains) is asserted, but the tester may want to make the allowed failure set explicit.
- CodeGraph did not return the new untracked production/test symbols; its query produced unrelated results, so blast radius was verified by direct file reads, ruff, mypy, and focused tests. Existing CodeGraph-backed blast-radius callers were UserPrincipal/UserAccount consumers and the auth ASGI guard.

Final developer addendum after requesting no-test-edits:
- Production implementation is complete for TASK-000019; task remains In Progress with all ACs unchecked.
- Final focused evidence: 58 passed (new authorization unit matrix, P01/P02 project model+persistence, adversarial persistence); 17 passed (existing CLI account tests + admin provisioning API); 2 passed (representative Admin control routes after common-system-gate integration); project-service integration suite 6 passed, 1 failed only on the pre-authored test that re-adds a deactivated user (production correctly rejects inactive accounts).
- Final ruff check passed on all 9 touched source files; mypy passed on all 9. ruff format --check passed on 8 files whose formatting was touched. control.py retains one unrelated pre-existing formatting difference at line 1205; it was not reformatted to avoid an unrelated diff.
- The only test-file work in this turn was authored before the no-test-edits instruction. No test file has been edited since that instruction; both pre-authored files remain at their prior contents for tester ownership.

Additional live-revocation evidence (ad-hoc TestClient, fresh temp DB): system admin created a project (201); after deleting the durable system_admin assignment, the same access JWT received 403 on project creation and 403 on a control read. This proves the new project service and the converted control guards use live scoped assignments rather than JWT claims, account type, or a stored superuser flag.

### Adversarial test pass (tests-only)

Scope: TASK-000019 P02. No production/source or configuration files were edited in this pass; only test files and Backlog notes changed. Task remains In Progress.

Tests changed/added:
- tests/integration/services/test_projects_authorization.py: replaced the stale account-deactivation setup that re-added a deactivated user (production correctly rejects inactive accounts) with an explicit inactive-add rejection plus a third active admin for the atomic bulk guard. Added legacy-role/superuser-claim service coverage. Hardened concurrency tests with an explicit Barrier, separate-engine/connection assertion, atomic rollback checks, and named allowed outcomes (LAST_PROJECT_ADMIN or live AuthorizationDenied only where the other writer removed the losing actor).
- tests/integration/routers/test_projects_api.py (new): saved HTTP coverage for system-admin no implicit project membership, project-admin scope separation, same-JWT live revocation after deleting the system assignment, HTTP deactivation last-admin 409, and immediate 401 after account deactivation.
- tests/integration/cli/test_users.py: added saved CLI coverage for last-admin refusal, successful deactivation with peer admin, unchanged state after failed bulk deactivation, and no secret output.

Focused evidence:
- uv run pytest tests/unit/services/test_authorization.py tests/integration/services/test_projects_authorization.py tests/integration/routers/test_projects_api.py plus the new CLI test: 22 passed.
- uv run pytest tests/integration/cli/test_users.py: 9 passed.
- Concurrency quartet repeated 5 times: 3 passed each run (15 passed).
- ruff check and ruff format --check on all touched test files: clean.
- Focused mypy on the new service/router tests: no findings in those files; only pre-existing tests/fixtures/auth.py httpx typing errors.

Stale-test adjudication: the developer's inactive-admin re-add claim is correct; the old assertion created an impossible supported state. The production validation is retained and now locked explicitly.

Quality/limitation: CodeGraph did not surface the new untracked P02 production/test symbols; the query returned unrelated UI/auth symbols. Blast radius was therefore confirmed by direct source reads, call-path searches, live HTTP/CLI tests, and the focused suites above.

Production defects: none confirmed against AC1-AC6. All six criteria have objective test evidence; no acceptance criteria were checked and no commit/merge/PR was made.

Final combined focused run: 30 passed (unit authorization + project service + project HTTP + full CLI). Concurrency trio repeated 5 times: 15 passed. Task remains In Progress; no source/config changes by the adversarial tester.

### Board finalization (2026-10-25)

Dependency, plan and evidence verification:
- Direct dependency TASK-000018 (P01) is Done; transitive TASK-000017 (P00) is Done. Dependency gate satisfied.
- Recorded plan items 1-5 match the final implementation: live ScopedAuthorizationService; ProjectRepository read/role/admin-count helpers with BEGIN IMMEDIATE and bounded retries; ProjectService lifecycle, membership, bulk and deactivation paths with rolled-back LAST_PROJECT_ADMIN guard; REST and CLI surfaces behind the rollout gate using the common live gates; focused unit, integration, HTTP/CLI and separate-connection concurrency tests.
- Objective evidence for each AC is recorded in the developer and tester notes above and was independently rechecked by the final Gemini review: AC1 common live service/permission matrix and live revocation; AC2 lifecycle scope and delegation tests; AC3 same-human multi-project role test; AC4 app/CLI removal, demotion, bulk and account-deactivation guards plus concurrency tests; AC5 forged legacy-role/superuser claims fail and scope separation holds; AC6 system-admin project list is empty and direct member reads are denied.

Ownership and source snapshots:
- Production files (9): src/freesearch/services/authorization.py, src/freesearch/services/projects.py, src/freesearch/persistence/projects.py, src/freesearch/models/projects.py, src/freesearch/routers/projects.py, src/freesearch/routers/auth.py, src/freesearch/routers/control.py, src/freesearch/routers/api.py, src/freesearch/cli/users.py.
- Test files (4): tests/unit/services/test_authorization.py and tests/integration/services/test_projects_authorization.py (authored by developer before the restriction and handed to the tester), tests/integration/routers/test_projects_api.py (new) and tests/integration/cli/test_users.py (tester).
- Final Gemini review round 2 verdict APPROVE. Source snapshots prove the tester never edited src and the developer made no test edits after the restriction. This board finalization changed no source, test, fixture, config or other repository file; only this Backlog task was updated through the CLI.

Reviewer and quality evidence:
- Focused suite: 30 passed (unit authorization, project service, project HTTP, full CLI). Concurrency trio repeated five times: 15 passed total. Gemini final rerun: 30 passed, 3 concurrency passed.
- ruff check and mypy clean on the 9 production files; touched test files lint and format clean.
- Baseline-only typing issues remain in tests/fixtures/auth.py and legacy untyped access in tests/integration/cli/test_users.py. The old developer-role provisioning test tests/unit/services/test_users.py::test_provision_account_uses_safe_manager_and_returns_projection is a pre-existing P01 failure, outside P02.

Residual findings, limitations and accepted decisions:
- RESIDUAL: a direct member lookup for an existing but inaccessible project returns 403 while an unknown project returns 404, creating an existence distinction. The independent reviewer ruled this non-blocking for P02 because the collection endpoint filters by membership and the consistent cross-project inaccessible-resource response belongs to Section 8 context/token phases. It is not fixed here and no follow-up task was created.
- CodeGraph did not index the stale/untracked P02 files; paths and blast radius were confirmed by direct source inspection and focused tests.
- Accepted decisions: project management is enabled in preview/strict/fair rollout states (the gate is structural, not a kill switch); account deactivation uses the existing system.roles.assign authority because the P00 catalog has no dedicated user-management action; archived projects are reductions-only under the same last-admin guard; control guards use system.settings.read/write; first project-admin provisioning is a documented delegation exception.
- No commits, PRs, merges or follow-up tasks were created.
<!-- SECTION:NOTES:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
P02 delivered the project lifecycle control plane and one common scoped authorization service. System and project decisions resolve live SQLite role assignments on every check; project create/list/archive, membership and role changes enforce scope, delegation and archived-state rules; app and CLI deactivation share a transactional LAST_PROJECT_ADMIN guard. All six acceptance criteria and the Definition of Done have recorded objective evidence accepted by the independent reviewer (round 2 APPROVE).

Verification: focused suite 30 passed; five repeated concurrency runs 15 passed; Gemini rerun 30 passed plus 3 concurrency passed; ruff check and mypy clean on the 9 production files; touched tests lint/format clean. Known risks: non-blocking 403/404 existence distinction for direct inaccessible-project lookups, deferred to the later Section 8 context/token phases and not fixed here; CodeGraph could not index the new P02 files; baseline test typing issues and the pre-existing P01 developer-role provisioning test failure remain unrelated. No commits, PRs or merges.
<!-- SECTION:FINAL_SUMMARY:END -->
