---
id: TASK-000020
title: Projects P03 - Project context and typed settings storage
status: Done
assignee: []
created_date: '2026-10-24T15:54:00Z'
updated_date: '2026-10-25T11:52:00Z'
labels:
  - projects-first
  - phase-p03
  - serial-foundation
milestone: m-0
dependencies:
  - TASK-000019
references:
  - src/freesearch/configuration/provider_config.py
  - src/freesearch/routers/control.py
  - src/freesearch/persistence/storage.py
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
Global singleton settings currently affect all requests. Project-specific behavior needs validated context and typed overrides with a visible and enforceable inheritance policy.

Phase: P03. Execution lane: serial-foundation. Milestone: Projects 1 - Foundation.

Dependency gate: P02 (TASK-000019)
Do not implement or mark In Progress until every dependency is Done, merged into the integration branch, and its acceptance evidence is available. Priority and phase numbers never override this gate. Parallel work is permitted only where the dependency graph and shared-file ownership allow it.

Accepted scope from plan section 10 / P03:

Add `ProjectContext`, project-aware repository facades, system settings, project overrides, and revisioned resolution.
Expose scoped settings reads and bounded writes. Keep execution in preview mode during this phase.
Extract configuration resolution out of transport handlers where necessary.

Cross-phase constraints:
User-approved constraints: one human account type; one common scoped RBAC service; system/project roles are assignments, not account types. Preserve internal UUIDs and local/WorkOS storage constraints without implementing WorkOS/cloud features. Use one internal installation account. Project tokens can expire or have no expiration. Support private and explicitly shared credential instances. Strict pool/project caps are the default; fair loans require their later phase. Use a fresh alpha database; do not migrate/import old history, humans, settings or secrets. Never use the live database or real provider credentials for tests. Desktop UI only; local environment controls ports.

Verification expectations:
Test inheritance and revision conflicts with temporary repositories. Run affected configuration, control-router and persistence suites plus backend checks.
Use the managed verification specification for required quality commands and test placement. Record objective evidence before completion.

Before code work, read AGENTS.md and applicable skills, use CodeGraph for indexed code, inspect current implementation and record the task implementation plan through Backlog. The referenced design is context; this future ticket intentionally has no speculative implementation-plan field.

Documentation: local .agents/communication/projects-feature-plan.md, sections 4-10 for design and scope, section 11 for ordering. The managed specification documents are durable copies for checkouts where the gitignored local plan is absent. Use the execution-index document for exact phase-to-ticket IDs and ready-work commands.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 Immutable validated account/project context reaches project repository and settings operations.
- [x] #2 System defaults and explicit project overrides resolve with per-field provenance and system safety constraints.
- [x] #3 Missing overrides, explicit false, null, empty collections, reset and replacement rules retain their documented distinct meanings.
- [x] #4 Stale revisions reject writes instead of silently overwriting another change.
- [x] #5 Settings reads/writes cannot cross project scope; cross-process cache invalidation respects system and project revisions.
- [x] #6 Project execution remains in preview mode until the release gate.
<!-- AC:END -->

## Definition of Done
<!-- DOD:BEGIN -->
- [x] #1 All phase acceptance criteria have objective test or review evidence recorded in Backlog before Done.
<!-- DOD:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. Extend the P00 typed settings contracts with the documented per-field catalog: routing fallback policy, cost preset, max attempts, ordered provider preference list; execution cache flag, default timeout, fanout concurrency, cache TTL. Classify each field as project-override or system-constrained, publish its default and static safety bounds, and define system defaults, system safety ceilings, revisioned update contracts, and per-field provenance/source/override-permission resolution records.
2. Add the documented `system_settings(namespace, schema_version, document, revision)` and `project_settings(project_id, namespace, schema_version, overrides, revision)` tables in Alembic 0007, plus head schema columns/foreign keys and project-aware scoped repository facades that take the project identity only from an immutable ProjectContext.
3. Add a live ProjectContext resolver to the common ScopedAuthorizationService and a settings service that requires settings.read/settings.write (project scope) or system.settings.read/write (system scope), resolves defaults then overrides then system safety limits, and exposes per-field provenance with system/project revisions.
4. Implement bounded writes with expected-revision compare-and-set under BEGIN IMMEDIATE: missing overrides inherit, explicit false/zero/empty list are real overrides, explicit null resets one field or section, lists replace wholesale, stale revisions return SETTINGS_REVISION_CONFLICT, archived projects refuse writes, and invalid overrides fail before mutation.
5. Add revision-keyed effective-settings caching (system revision + project revision + project id + database identity) so a cross-process system or project revision change always misses, and isolate project cache invalidation. Register thin `/api/v1/system/settings` and `/api/v1/projects/{project_id}/settings` routes behind the existing rollout gate; keep execution untouched in preview and return 404 for unknown/inaccessible project settings without leaking cross-project existence.
6. Verify with focused existing configuration/control/persistence/project tests plus ruff and mypy, and run ad-hoc fresh-database service/HTTP checks for inheritance, false/null/empty/replacement/reset, constraints, stale revisions, isolation and cache revision behavior. Do not edit tests; hand test authoring and independent adjudication to the tester.
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
P03 developer handoff in progress; detailed evidence follows.

Production files added:
- src/freesearch/models/settings.py: documented typed settings catalog. Fields: routing.fallback_policy, routing.cost_optimization_preset, routing.max_attempts, routing.preferred_providers (ordered list, max 8, explicit empty list clears), execution.cache_enabled (boolean), execution.default_timeout_seconds, execution.max_fanout_concurrency, execution.cache_ttl_seconds, plus system-only safety ceilings system.max_timeout_seconds and system.max_fanout_concurrency. Each field publishes policy (system_only/project_override/system_constrained), kind, initial default, static bounds, and safety-limit rule. Adds non-null system defaults, SystemSafetyLimits, revisioned SystemSettingsDocument/Update and bounded ProjectSettingsUpdate contracts.
- src/freesearch/persistence/settings.py: system_settings(namespace, schema_version, document, revision) and project_settings(project_id, namespace, schema_version, overrides, revision) rows with strict project repository methods and revision compare-and-set. No optional project scope exists.
- src/freesearch/persistence/scoped.py: ProjectScopedRepository/ScopedProjectSettings facade. Project identity comes only from the immutable ProjectContext and every operation is confined to that project; context account mismatch is rejected.
- src/freesearch/services/settings.py: live scoped authorization, immutable context resolution, defaults -> explicit override -> system ceiling resolution with per-field provenance/source/override permission/safety-limit metadata, bounded BEGIN IMMEDIATE writes, stale-revision rejection, archived-write rejection, and revision-keyed effective-settings cache.
- src/freesearch/routers/settings.py: thin GET/PUT /api/v1/system/settings and GET/PUT /api/v1/projects/{project_id}/settings routes. Safe 403/404/409/400/503/500 mapping; no policy in handlers.
- src/freesearch/persistence/migrations/versions/0007_project_settings.py: head 0007_project_settings, creates both tables with FK project_settings.project_id -> projects.id ON DELETE CASCADE and revision/schema-version checks.

Ownership: no test, fixture, snapshot, or test-configuration file was created, edited, deleted, reformatted, or regenerated in this turn. Only this Backlog task was changed through the CLI. Production code only; task remains In Progress with all AC/DoD unchecked pending independent tests and review.

Production files changed:
- src/freesearch/models/projects.py: extended RoutingSettings with preferred_providers, ExecutionSettings with cache_enabled, and SettingsFieldResolution/SettingsResolution with section, source_scope, override_allowed, system_safety_limit, constraint_applied, project_id, schema_version, overrides. Existing P00 constructors remain compatible.
- src/freesearch/services/authorization.py: added resolve_project_context/resolve_project_context_in_session. Returns None for unknown/foreign-account/inaccessible projects (unknown or missing/suspended membership, inactive account/user), returns a deeply immutable ProjectContext for an accessible project, and computes policy_revision from live membership/role versions. Settings operations still call the live permission check separately; context is never the sole authorization.
- src/freesearch/persistence/database_migrations.py: head schema validation now includes both settings tables and the project_settings foreign key.
- src/freesearch/routers/api.py: registers the settings routes after project routes.
- src/freesearch/persistence/users.py: import SQLAlchemyUserDatabase directly from fastapi_users_db_sqlalchemy. This fixes an existing import-order partial-initialization bug (importing persistence.auth_sessions before persistence.users made fastapi_users.db drop the symbol) exposed when the new transport-neutral settings service is imported first by tests or scripts. Behavior is unchanged; focused user/auth tests pass.

Documented write semantics:
- Revision 0 means no durable document: catalog/system defaults are in force. GET does not write. First PUT with expected_revision=0 creates revision 1.
- Missing field/section in a project update keeps the existing override. Explicit null removes that one override (reset); explicit null section resets the whole section. Explicit false, 0, and an empty list are stored values, not inheritance. A non-empty preferred_providers list replaces the previous list wholesale, never merges. An omitted field is distinct from explicit null in the request (model_fields_set).
- System defaults resolve first, project overrides second, system safety ceilings last (SYSTEM_CONSTRAINED provenance when a ceiling clamps). Invalid static bounds/unknown fields fail 422; unknown provider names fail 400 before mutation.
- Stale expected_revision returns 409 SETTINGS_REVISION_CONFLICT and leaves state unchanged. Archived project reads remain available; writes return 409 PROJECT_ARCHIVED.
- Project settings for unknown and inaccessible projects both return 404. A project member with live membership but no settings.read/write gets 403. This is the Section 8 consistent inaccessible-resource behavior for the new P03 paths only; the prior P02 member-route 403/404 residual is not expanded.
- Cache key is (database identity, namespace, project id, system revision, project revision). Supported writes increment a revision, so a second process cannot reuse an older effective document; no process-local mode bypasses the revisions. Cache is bounded LRU (256).

Execution gate: no execution, adapter, provider dispatch, token, credential, or trace-policy path was changed. Settings are storage/resolution only; execution remains the existing preview path. Default rollout state read back as PROJECTS_PREVIEW. P05 remains the consumer of these values.

Focused verification commands and results:
- uv run ruff check src tests: All checks passed.
- uv run mypy: Success, no issues found in 95 source files.
- uv run ruff format --check on all touched source files: all formatted.
- uv run pytest tests/unit/models/test_projects.py tests/unit/services/test_authorization.py tests/integration/routers/test_projects_api.py tests/integration/persistence/test_projects.py -q: 48 passed, 1 failed. Failure: tests/integration/persistence/test_projects.py::test_fresh_database_schema_validation_and_head_revision asserts result.current_revision.startswith('0006'); fresh install now correctly reports new head 0007_project_settings. Stale literal expectation, not a schema defect.
- uv run pytest tests/integration/persistence/test_database_migrations.py -q: 1 stale failure: test_fresh_database_at_head_has_no_cache_metadata asserts equality with 0006_projects_and_memberships but head is 0007_project_settings. Other migration tests passed in the same run.
- uv run pytest tests/integration/routers/test_control_api.py -q: 72 passed, 2 failed. Failures test_get_providers_enumerates_canonical_status_contract and test_tavily_env_patch_denied_for_developer_reader both die in the test fixture promoting UserRole.DEVELOPER: Unsupported obsolete role developer. This is the P01 removal of developer account types, pre-existing and unrelated to P03 code paths.
- uv run pytest tests/integration/routers/test_runtime_settings.py tests/unit/routers/test_control.py tests/unit/routers/test_api.py -q: 20 passed, 9 failed. All 9 failures are the same obsolete UserRole.DEVELOPER fixture setup in test_runtime_settings (fresh defaults, partial legacy, stale support mask, locked/released reconcile, corrupt config, p95, empty latency, legacy projection). test_control.py and test_api.py passed.
- uv run pytest tests/integration/persistence/test_sqlite_repository.py tests/integration/persistence/test_runtime_setting_updates.py -q: 28 passed.
- uv run pytest tests/unit/models/test_users.py tests/unit/routers/test_auth.py tests/integration/persistence/test_users.py -q: 34 passed (validates the fastapi_users import-path change).
- Ad-hoc fresh temporary DB (not a committed test file): verified system defaults before any row (revision 0), system revisioned PUT, project inheritance, explicit false, explicit 0, empty-list override, non-empty list replacement, explicit null reset, whole-section reset, static-bound 422, unknown-provider 400, stale 409 with unchanged state, archived write 409 while read 200, cross-project read/write 404 with the other project unchanged, membership-without-permission 403, anonymous 401, and live system revision invalidation.
- Ad-hoc fresh temporary DB, actual separate OS process: parent cached a project resolution at revision 0, a child process opened the same SQLite file and wrote revision 1, parent then read revision 1 and the new value. Real cross-process revision-keyed invalidation passed.
- Ad-hoc two-repository concurrent race using asyncio.gather with expected_revision=0: exactly one 'written' and one 'conflict', final revision 1, final value one of the submitted values.
- Ad-hoc migration rehearsal: fresh upgrade to 0007, downgrade to 0006 (schema validation fails as expected), upgrade back to 0007, schema validation passes.
- Ad-hoc OpenAPI build: 38 paths, both settings routes present. create_app imports cleanly from api and mcp; services.settings imports cleanly first (after the users import fix).

CodeGraph: .codegraph exists. Current queries for ScopedAuthorizationService/ProjectService/resolve_project_context/settings still returned unrelated UI SettingsView, browser-auth Scope, and auth ASGI symbols; the new/untracked P03 files were not indexed and P02 service modules were not resolved either. Blast radius was therefore verified by direct source reads, import/call-path inspection, and the focused tests above. Real P03 call paths: routers/api.create_app -> routers/settings.register_settings_routes -> SettingsService -> ScopedAuthorizationService.resolve_project_context_in_session + ProjectScopedRepository -> persistence/settings rows; mutation path SettingsService._write -> BEGIN IMMEDIATE -> compare_and_set -> revision bump -> cache invalidation. The users.py import change affects persistence.users consumers (auth service, project service, tests/fixtures) and those focused tests passed.

Specific tester requirements (production invariants to lock down):
1. Immutability/validation: ProjectContext rejects mutation and token-project mismatch; resolve_project_context returns None for unknown/inaccessible/suspended membership/inactive account; scoped facade rejects a foreign-account context and cannot accept another project id.
2. Inheritance states: no system row (revision 0/catalog defaults), system row + no project row, project override per field, explicit false, explicit 0, explicit empty list, non-empty list replacement, explicit null one-field reset, explicit null section reset, omitted section/field keeps current overrides, system default change propagates while a project override remains.
3. Constraints/provenance: project value above a system safety ceiling resolves to the ceiling with SYSTEM_CONSTRAINED and constraint_applied; below/equal keeps PROJECT_OVERRIDE or SYSTEM_DEFAULT; system-only safety fields have override_allowed False; invalid static values 422; unknown provider 400; no partial mutation.
4. Revision races: stale expected_revision 409 SETTINGS_REVISION_CONFLICT with unchanged document; concurrent writers from separate repositories/connections yield exactly one success; first write expected 0 -> revision 1.
5. Isolation: A cannot GET/PUT B settings (404) and B is unchanged; system admin without membership gets 404; membership without settings.read/write gets 403; path/body project mismatch cannot select a different project (body extra=forbid).
6. Cross-process/cache: two SettingsService instances with separate SQLiteRepository objects; ideally an OS subprocess write, then the first process must observe the new system/project revision and value; system revision bump must invalidate all projects, project revision only that project; old cached key must not be returned.
7. Preview gate: default settings.projects_rollout_state is PROJECTS_PREVIEW; settings routes remain management-only and do not dispatch providers; no execution/token/credential/trace-policy path is introduced.
8. Archived project: reads 200, writes 409 PROJECT_ARCHIVED.
9. HTTP: anonymous 401; authorization 403; unknown/inaccessible 404; conflict 409 with code; invalid schema 422; invalid provider 400.

Unresolved design choices/objections and anticipated rebuttals:
- The catalog defines a small preview-phase subset of plan section 4.7 categories: routing preferences and execution timeout/fanout/cache. Queue depth, spend, rate ceilings, trace sampling/detail/retention, and sensitive payload capture belong to later phases (P11/P14/P17) and are intentionally absent. preferred_providers and cache_enabled were added because the P03 gate explicitly requires explicit-false and array-replacement semantics; they are storage contracts only until P05 consumes them.
- System defaults are stored in the new system_settings document, not imported from legacy runtime_settings. This follows the fresh-alpha/no-migration constraint and the accepted schema document; the legacy global provider/routing control surfaces remain untouched. Existing provider/routing resolution stays in routers/control.py because it is a separate pre-existing system catalog with cache-identity tests; the new typed resolution is transport-neutral in services/settings.py.
- Explicit null means reset/inherit for every current catalog field; false, 0, and empty arrays are real values. If review expects a field where null is itself a distinct effective value (not reset), that field must be named and documented before storage; the current catalog has none because downstream execution semantics for such a value are not defined in P03.
- Archived projects allow settings reads but refuse writes. Plan section 9 says archive blocks new execution; refusing config edits is a conservative derived rule, not an explicit line in P03. Reviewer should confirm or ask to allow archived writes.
- Settings GET/PUT paths deliberately return 404 for both unknown and inaccessible projects, fixing the Section 8 behavior for new P03 surfaces without changing the P02 member-route 403 residual.
- The effective cache still reads revision-bearing rows before a cache hit so it can prove the key; this favors cross-process correctness over minimum I/O. A future optimization may read revisions only, but must preserve the same invariant.
- The persistence/users.py import-path change is outside the literal P03 feature list but is required to let transport-neutral services and focused tests import cleanly. It is a one-line dependency correction, covered by 34 passing user/auth tests.

No commit, merge, PR, archive, or next-task work was performed. Shared checkout remains reviewable.

Clarification for AC1 review: the immutable context/facade is the new P03 seam for project reads and settings operations. Existing P02 lifecycle/membership service methods keep their actor + explicit project_id signatures and live authorization; P03 did not rewrite that validated P02 surface. ProjectScopedRepository.require_project and ScopedProjectSettings are the context-bound repository operations exercised by settings.

## P03 independent tester verification (2026-10-25)

Scope: test/fixture files only. No production source, development configuration, task status, acceptance criterion, or DoD was changed. TASK-000020 remains In Progress with AC/DoD unchecked.

Saved P03 coverage added:
- tests/unit/models/test_settings.py: catalog/default consistency, omission vs explicit null vs false vs zero vs empty list, required section and unknown fields, system default/safety payload checks, and static timeout minimum (new red test).
- tests/unit/services/test_settings.py: transport-neutral resolve_settings provenance, system default/override/ceiling order, false/zero/empty-list overrides, system-only override_allowed.
- tests/integration/persistence/test_settings.py: system/project compare-and-set, stale no-overwrite, separate project rows, project_settings FK rejection.
- tests/integration/services/test_settings.py: inheritance and system-default changes with surviving overrides, field/section reset, list replacement, stale/invalid atomicity, archived read/write, unknown/suspended/inactive/foreign context states, foreign-account facade rejection and context immutability, concurrent separate SQLite repositories, and real OS-subprocess cache invalidation for system and project revisions across two projects.
- tests/integration/routers/test_settings_api.py: 401/403/404 matrix, project-admin write, member read-only, token_manager denial, system-admin no-membership 404, cross-project 404, body/path mismatch 422, stale 409, static invalid 422, unknown provider 400, archived 409, system/project revision propagation, preview default and no project execution routes.

Stale test adjudication:
- Migration head 0006 -> 0007_project_settings in test_projects.py and test_database_migrations.py; added system_settings/project_settings to the exact table inventory and 0002-downgrade absence check.
- Obsolete UserRole.DEVELOPER fixtures in test_control_api.py and test_runtime_settings.py replaced with system_admin (system.settings.read/write) because no system read-only role exists in P02/P03. The tavily denial case now uses a system-admin read plus a real project-scoped administrator denial, so it still proves system control authority is not granted by project settings.write; assertions were not weakened. Runtime control/provider reads now use the live system.settings.read assignment.
- Baseline stale-role debt found but not modified: tests/integration/routers/test_role_matrix.py (6 setup errors) and tests/integration/routers/test_limits_api.py (4 failures, 5 passes) still call UserDatabase.set_role(UserRole.DEVELOPER). Other developer-role fixtures remain in observability/monitoring/encrypted-secrets/manual-quota/BDD suites. These are P01/P02 contract cleanup outside P03.

Commands and results:
- uv run ruff check src tests: pass.
- uv run mypy: pass, 95 source files.
- uv run ruff format --check on all touched test files: 10 files already formatted.
- uv run pytest tests/integration/routers/test_control_api.py -q: 74 passed.
- uv run pytest tests/integration/routers/test_runtime_settings.py (combined focused run): 12 passed.
- uv run pytest tests/integration/persistence/test_database_migrations.py -q: 22 passed.
- uv run pytest tests/integration/persistence/test_projects.py -q: 7 passed.
- uv run pytest <new P03 five files> -q: 17 passed, 1 failed (confirmed production defect below).

Production defect (no source change made):
- P03-T1, Medium severity. The published catalog has minimum 1.0 second for execution.default_timeout_seconds and system.max_timeout_seconds, but the Pydantic models accept 0.5 (gt=0). A 0.5 safety ceiling can also clamp an otherwise valid 1.0 project timeout below the catalog minimum. This violates AC2's documented static bounds and system safety constraints.
- Minimal red test: tests/unit/models/test_settings.py::test_timeout_static_minimum_is_enforced_everywhere (currently fails with DID NOT RAISE ValidationError).
- Exact expected requirement: enforce ge=1.0 for ExecutionSettings.default_timeout_seconds, SystemExecutionDefaults.default_timeout_seconds, and SystemSafetyLimits.max_timeout_seconds, or change the catalog minimum consistently if sub-second values are intended. Source symbols: freesearch.models.projects.ExecutionSettings.default_timeout_seconds; freesearch.models.settings.SystemExecutionDefaults.default_timeout_seconds; freesearch.models.settings.SystemSafetyLimits.max_timeout_seconds; SETTINGS_FIELD_CATALOG entries execution.default_timeout_seconds and system.max_timeout_seconds.

AC evidence status (not checked):
- AC1: green for immutable context, resolver invalid/suspended/inactive/foreign states, foreign-account facade, and scoped route 404/403 behavior.
- AC2: green for defaults, overrides, per-field provenance and ceiling clamps, except the timeout static-minimum defect above.
- AC3: green for omission, explicit null field/section reset, false, zero, empty list, list replacement, and reset/replacement distinctions.
- AC4: green for stale 409 with unchanged document, first write 0->1, and concurrent separate-repository one-winner.
- AC5: green for cross-project 404/unchanged target, system-admin 404, member 403, body/path mismatch 422, and OS-subprocess invalidation of both system and project revisions across two projects.
- AC6: green for default PROJECTS_PREVIEW and absence of new project execution routes; no provider dispatch was introduced.

Tester addendum: added no-system-row project-override unit test; focused P03 total is 18 passed, 1 failed (P03-T1 red test). Other evidence unchanged.

Round 2 production correction (2026-10-25), P03-T1 timeout minimum:
- Fixed ExecutionSettings.default_timeout_seconds (src/freesearch/models/projects.py), SystemExecutionDefaults.default_timeout_seconds, and SystemSafetyLimits.max_timeout_seconds (src/freesearch/models/settings.py) from gt=0 to ge=1.0, matching the published catalog minimum of 1.0 seconds for execution.default_timeout_seconds and system.max_timeout_seconds. The catalog bound was not weakened.
- All P03 write and resolve paths inherit these model bounds: SystemSettingsUpdate -> SystemSettingsPayload, ProjectSettingsUpdate -> ExecutionSettings (including merge), ProjectSettingsDocument/SystemSettingsDocument stored-document revalidation, and resolve_settings ceiling application. No other timeout write or resolve path accepts a sub-1.0 value, so a 0.5 system ceiling can no longer clamp a valid 1.0 project timeout below the documented minimum.
- Red test tests/unit/models/test_settings.py::test_timeout_static_minimum_is_enforced_everywhere now passes. Focused P03 suites: 19 passed. tests/unit/models/test_projects.py: 29 passed. Ad-hoc boundary check: 0.999 rejected by all three models, 1.0 accepted.
- uv run ruff check and ruff format --check on the two changed files pass; uv run mypy passes (95 source files). No test, fixture, snapshot, or test-configuration file was modified. TASK-000020 remains In Progress with all AC/DoD unchecked. No commit, PR, merge, or archive.

Round 2 independent tester closure (2026-10-25): P03-T1 re-verified, no source changes made. Existing red regression tests/unit/models/test_settings.py::test_timeout_static_minimum_is_enforced_everywhere now passes. Added two tests-only boundary regressions: tests/unit/models/test_settings.py::test_timeout_minimum_boundary_is_exact_and_matches_catalog and tests/integration/services/test_settings.py::test_timeout_minimum_boundary_survives_write_and_read_resolution. They lock 0.999 rejection and 1.0 acceptance for ExecutionSettings, SystemExecutionDefaults, SystemSafetyLimits, SystemSettingsPayload, project write/read, and a 1.0 system ceiling clamping a 2.0 project override. Focused five P03 files: 21 passed (19 prior + 2 added). tests/unit/models/test_projects.py: 29 passed. Combined focused run: 50 passed. ruff check and ruff format --check on the two touched test files: pass. No broad suite rerun. AC/DoD remain unchecked; TASK-000020 remains In Progress. P03-T1 closed; all six AC retain objective evidence from the prior round plus this boundary closure.

P03 board finalization: detailed evidence below.

## P03 board finalization (2026-10-25)

Dependency and plan verification:

- Direct dependency TASK-000019 (P02) is Done with 6/6 acceptance criteria and DoD 1/1 plus final summary. P02 is committed at HEAD 6534d6b (feat(projects): add lifecycle services and scoped authorization, 2026-10-25 11:25), before P03 started (11:48). Transitive TASK-000018 (P01) and TASK-000017 (P00) are Done with 5/5 acceptance criteria each. Dependency gate satisfied.

- Recorded plan items 1-6 match the final implementation: typed settings catalog and models; Alembic 0007 system_settings/project_settings tables; ProjectContext-bound scoped repository/settings facades; SettingsService live common RBAC with defaults -> override -> system ceiling provenance; BEGIN IMMEDIATE compare-and-set writes, stale 409, archived-write 409, and revision-keyed cache; thin settings routes behind the preview gate; focused verification. The P03-T1 ge=1.0 correction enforces the documented static bounds without weakening the catalog.

Evidence and review:

- P03-T1 (medium): the independent tester found the published 1.0-second catalog minimum was not enforced (gt=0) and a sub-1.0 system ceiling could clamp a valid project timeout. The developer changed only src/freesearch/models/projects.py and src/freesearch/models/settings.py to ge=1.0 on all three timeout fields; the catalog remained 1.0. The tester re-verified and added two exact-boundary/write-read tests without changing src. Gemini round 2 recorded APPROVE and explicit P03-T1 closure; round 1 had missed the defect.

- Final P03 counts: five P03 files 21 passed (19 prior + 2 boundary); tests/unit/models/test_projects.py 29 passed; combined focused run 50 passed. Earlier affected suites after stale fixture/head updates: control API 74 passed, runtime settings 12, migrations 22, project persistence 7. Quality: ruff check src tests passed; mypy 95 files passed; changed source/test formatting and the latest boundary tests are lint/format clean. These are focused runs, not an exhaustive all-repo pass; duplicate runs are not summed as unique tests.

- AC evidence: AC1 immutable validated context/facade and 401/403/404 boundaries; AC2 defaults/overrides/per-field provenance/system-only fields/ceiling clamping after P03-T1; AC3 omission vs explicit null vs false/zero/empty/replacement; AC4 stale 409 with no mutation, first write 0 -> 1, one-winner concurrency; AC5 cross-project 404 with unchanged target, member 403, and real OS-subprocess system+project revision invalidation across projects; AC6 default PROJECTS_PREVIEW and no project execution route. All six have recorded test and independent review evidence.

Ownership and limits:

- This finalization changed no source, test, fixture, configuration, audit or other repository content; only TASK-000020 was updated through the Backlog CLI. No commit, PR, merge, archive, or follow-up task was created.

- No exhaustive all-repo/BDD run was performed. External P01-era obsolete UserRole.DEVELOPER fixtures still fail unrelated role-matrix/limits/observability suites; recorded as baseline outside P03, with no new follow-up. CodeGraph was consulted first but new/untracked P03 symbols were not indexed; direct call-path checks and focused tests supplement it. The catalog is scoped to routing/execution/cache/timeouts/fanout; queue/spend/rate/trace fields remain later phases. Legacy runtime settings remain until later execution/provider phases, and P02 actor+project_id signatures are preserved. New settings routes use uniform 404 for unknown/inaccessible projects and 403 for a member without permission; archived reads 200/writes 409. Preview execution is untouched.
<!-- SECTION:NOTES:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
P03 delivered the typed system/project settings foundation on top of P02 so project-specific behavior no longer depends on global singleton settings: a published per-field catalog and validated contracts, Alembic 0007 system_settings/project_settings storage, ProjectContext-bound scoped repository/settings facades, and a SettingsService with live common RBAC, defaults -> override -> system-ceiling resolution with per-field provenance, BEGIN IMMEDIATE compare-and-set writes, stale-revision 409, archived-write 409, and revision-keyed cross-process cache invalidation. Thin system/project settings routes sit behind the existing preview gate; execution remains PROJECTS_PREVIEW and untouched. Adversarial review found P03-T1, a medium timeout-minimum mismatch; the developer changed only the three model validators to ge=1.0 with the catalog unchanged, and the tester closed it with two exact-boundary/write-read tests. Gemini round 2 verdict APPROVE. Verification: five P03 files 21 passed (19 + 2 boundary), project-model regression 29, combined focused run 50; earlier affected control API 74, runtime settings 12, migrations 22, project persistence 7; ruff check src tests and mypy (95 files) passed, touched files format-clean. Limits: no exhaustive all-repo/BDD run; unrelated P01-era UserRole.DEVELOPER suites remain baseline debt; CodeGraph did not index the new P03 files; the catalog covers routing/execution/cache/timeouts/fanout only; legacy runtime settings and P02 actor+project_id signatures remain until later phases. No commit, PR, merge, or archive.
<!-- SECTION:FINAL_SUMMARY:END -->
