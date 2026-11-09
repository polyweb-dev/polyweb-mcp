---
id: TASK-000017
title: Projects P00 - Contract and alpha baseline
status: Done
assignee:
  - '@antigravity-developer'
created_date: '2026-10-24T15:53:00Z'
updated_date: '2026-10-24T17:14:00Z'
labels:
  - projects-first
  - phase-p00
  - serial-foundation
milestone: m-0
dependencies: []
references:
  - AGENTS.md
  - pyproject.toml
  - freesearch-ui/package.json
documentation:
  - doc-000001
  - doc-000002
  - doc-000003
  - doc-000004
  - doc-000005
  - .agents/communication/projects-feature-plan.md
  - .backlog/docs/doc-000005 - Projects-execution-index-start-here.md
  - doc-000006
priority: high
type: spike
ordinal: 1000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
The project-first redesign changes identity, ownership and execution contracts across the application. A shared contract and baseline must exist before coding agents change those boundaries.

Phase: P00. Execution lane: serial-foundation. Milestone: Projects 1 - Foundation.

Dependency gate: None. This is the first implementation assignment.
Do not implement or mark In Progress until every dependency is Done, merged into the integration branch, and its acceptance evidence is available. Priority and phase numbers never override this gate. Parallel work is permitted only where the dependency graph and shared-file ownership allow it.

Accepted scope from plan section 10 / P00:

Define the permission catalog, ownership inventory, API contracts, configuration fields, and feature rollout states.
Specify one human account contract and the shared system/project RBAC decision interface before implementation.
Confirm open decisions and capture current auth, routing, rate, and frontend case counts.
Prepare fresh-database fixtures and an explicit alpha reset/bootstrap procedure.

Cross-phase constraints:
User-approved constraints: one human account type; one common scoped RBAC service; system/project roles are assignments, not account types. Preserve internal UUIDs and local/WorkOS storage constraints without implementing WorkOS/cloud features. Use one internal installation account. Project tokens can expire or have no expiration. Support private and explicitly shared credential instances. Strict pool/project caps are the default; fair loans require their later phase. Use a fresh alpha database; do not migrate/import old history, humans, settings or secrets. Never use the live database or real provider credentials for tests. Desktop UI only; local environment controls ports.

Verification expectations:
Record relevant backend and desktop UI baseline results and case counts. Validate the ownership inventory and the full dependency graph before downstream implementation.
Use the managed verification specification for required quality commands and test placement. Record objective evidence before completion.

Before code work, read AGENTS.md and applicable skills, use CodeGraph for indexed code, inspect current implementation and record the task implementation plan through Backlog. The referenced design is context; this future ticket intentionally has no speculative implementation-plan field.

Documentation: local .agents/communication/projects-feature-plan.md, sections 4-10 for design and scope, section 11 for ordering. The managed specification documents are durable copies for checkouts where the gitignored local plan is absent. Use the execution-index document for exact phase-to-ticket IDs and ready-work commands.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 An ownership inventory assigns each persistent table, API, cache and job to an explicit scope.
- [x] #2 The accepted contracts define one human account type, common scoped RBAC, account/project context, optional-expiry project tokens and shared credential/pool identity.
- [x] #3 An explicit fresh-alpha bootstrap procedure replaces preservation or migration of old accounts, settings, credentials and history.
- [x] #4 The source/test baseline, phase gates, API/DTO contracts and parallel file-ownership boundaries are documented for coding agents.
- [x] #5 Cloud-specific features remain excluded; existing local/WorkOS identity constraints and extension seams are preserved.
<!-- AC:END -->

## Definition of Done
<!-- DOD:BEGIN -->
- [x] #1 All phase acceptance criteria have objective test or review evidence recorded in Backlog before Done.
<!-- DOD:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. Contract definition in src/freesearch/models/projects.py:
   - ProjectRolloutState (PROJECTS_PREVIEW, PROJECTS_STRICT, PROJECTS_FAIR).
   - ScopeType (SYSTEM, PROJECT), ResourceScope, PermissionAction catalog, BuiltinRole definitions.
   - Principals: HumanPrincipal (user_id, session_id), ProjectTokenPrincipal (token_id, project_id, scopes), deeply immutable ProjectContext (account_id, project_id, principal, effective_permissions, policy_revision).
   - Authorization protocol & evaluator: AuthorizationQuery, AuthorizationDecision, AuthorizationService protocol, evaluate_authorization() deny-by-default evaluator.
   - Project & Membership DTOs: ProjectCreate (requiring atomic initial_admin_user_id), ProjectUpdate, ProjectRead, ProjectArchive, ProjectStatus, ProjectMemberAdd, ProjectMemberUpdate, ProjectMemberRead, RoleAssignmentRead (enforcing scope matching).
   - Project Token DTOs: ProjectTokenCreate (supporting omitted=90d default vs explicit null perpetual token), ProjectTokenRead, ProjectTokenIssueResponse (masked repr, unmasked wire serialization), ProjectTokenRotate.
   - Credential & Upstream Pool DTOs: CredentialOwnerScope, CredentialInstanceRead (enforcing owner_scope matching), CredentialProjectGrantRead, ProjectBindingRead, UpstreamQuotaPoolRead, ProjectPoolAllocationRead.
   - Settings contracts: SettingsScope, SettingsProvenance, SettingsResolution, RoutingSettings, ExecutionSettings, ProjectSettingsDocument.
2. Configuration rollout wiring in src/freesearch/configuration/config.py:
   - Added projects_rollout_state: ProjectRolloutState = ProjectRolloutState.PROJECTS_PREVIEW.
3. Isolated fresh-alpha test fixtures in tests/fixtures/alpha_fixtures.py:
   - create_alpha_test_db(db_path) refusing existing files and applying Alembic migrations to head 0005_tinyfish_plan_label.
   - bootstrap_fresh_alpha(...) provisioning installation account, admin UserRow, and in-memory target contracts with safe repository close preventing Windows SQLite handle locks.
4. Comprehensive unit test suite in tests/unit/models/test_projects.py:
   - 21 unit tests covering all P00 models, immutability, token boundaries, token expiry semantics, RBAC evaluation, and safe DB bootstrap.
5. Backlog-managed specification doc-000006:
   - Full inventory of 17 physical tables (16 application + alembic_version) and 12 target tables with explicit System/Project/Shared-Pool/Shared-Credential scopes.
   - Explicit concern classification for all REST and MCP endpoints (aggregates, provider health, OAuth, secrets, limits, observability).
   - In-memory cache structures (_CONFIG_CACHE, _POLICY_CACHE, _quota_poll_cache, _quota_failure_cache, _quota_poll_locks) with target partition keys and invalidation lifecycles.
   - Background tasks (LimitSyncService in limits_sync.py, quota refresh, trace flush, downstream P10 OAuth refresh and P14 trace retention).
   - Canonical phase dependency graph labeled as transitive simplification with authoritative Table 3.1 and doc-000005.
   - Verified baseline execution matrix with exact commands and factual metrics.
   - Simplified Technical English (ASD-STE100) compliant with 0 errors via ste_check.py.
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Objective Evidence & Verification Record:
1. Subsystem Verification & Tester Approval:
   - Domain Model & Fixture Unit Tests: uv run pytest tests/unit/models/test_projects.py -> 21 passed (100% pass rate in 2.98s).
   - Static Code Quality:
     - uv run ruff check src/freesearch/models/projects.py src/freesearch/configuration/config.py tests/fixtures/alpha_fixtures.py tests/unit/models/test_projects.py -> All checks passed (0 errors).
     - uv run mypy src/freesearch/models/projects.py src/freesearch/configuration/config.py tests/fixtures/alpha_fixtures.py tests/unit/models/test_projects.py -> Success: no issues found in 4 source files.
   - STE Compliance: uv run python scripts/ste_check.py --no-vocab ".backlog/docs/doc-000006 - Projects-P00-Ownership-inventory-bootstrap-runbook-and-baseline-matrix.md" -> 0 errors, 12 warnings (structural rules fully satisfied).
   - Repository Graph Health: bunx backlog.md doctor -> 20 phases analyzed, 0 duplicate IDs, 0 cycles.
2. Verified Pre-P00 Repository Baseline (Collection-Only & Focused Blast Radius):
   - Unit collection: uv run pytest --collect-only tests/unit -> 1,836 tests collected.
   - Integration collection: uv run pytest --collect-only tests/integration -> 834 tests collected.
   - Acceptance dry-run: uv run behave --dry-run tests/bdd/features -> 27 features, 281 scenarios, 1,306 steps.
   - Frontend collection: in freesearch-ui: npx vitest list -> 1,797 test cases across 116 files.
   - Focused auth/session: uv run pytest tests/unit/models/test_users.py tests/unit/routers/test_auth.py tests/unit/services/test_users.py -> 49 passed.
   - Focused routing/limits: uv run pytest tests/unit/services/test_routing.py tests/unit/services/test_rate_limits.py tests/unit/models/test_provider_limits.py -> 62 passed.
   - Focused auth/role integration: uv run pytest tests/integration/persistence/test_users.py tests/integration/persistence/test_auth_sessions.py tests/integration/routers/test_role_matrix.py -> 31 passed.
   - Focused UI components: in freesearch-ui: npx vitest run --configLoader native src/features/users/model/useAdminUsersController.test.ts src/app/layout/SidebarNavList.test.tsx src/app/layout/SidebarBrand.test.tsx src/features/users/ui/AdminUsersPage.test.tsx src/app/layout/SidebarAccountMenu.test.tsx src/components/layout/Sidebar.test.tsx src/components/layout/AppSidebarShell.test.tsx -> 152 passed across 7 files.
   - Core BDD acceptance: uv run behave tests/bdd/features/users.feature:7 -> 1 scenario passed.
3. Tester Approval:
   - Implementation reviewed and approved: P00 contract boundaries, immutability, safe fresh alpha bootstrap fixture, and doc-000006 baseline specification strictly verified against project specifications doc-000001 through doc-000005.
<!-- SECTION:NOTES:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
Phase P00 (TASK-000017) is complete and verified.

P00 Scope Completed:
- Core domain contracts, principal abstractions, and deny-by-default authorization protocol established in src/freesearch/models/projects.py.
- Rollout configuration wired in src/freesearch/configuration/config.py defaulting to preview mode.
- Safe alpha database test fixtures and Windows-safe bootstrap runbook implemented in tests/fixtures/alpha_fixtures.py.
- Comprehensive unit tests (21 passed) and clean static quality (Ruff & MyPy) in tests/unit/models/test_projects.py.
- Authoritative specification doc-000006 published and validated with 0 STE structural errors.
- Pre-P00 test collection and focused blast radius baselines verified and documented.

Downstream Gating:
All downstream phases (P01 through P19, TASK-000018 through TASK-000033) remain gated and are NOT started.
P00 establishes shared domain contracts and alpha baselines without persisting project tables, modifying production schemas, or migrating old history/accounts.
<!-- SECTION:FINAL_SUMMARY:END -->
