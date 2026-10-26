---
id: TASK-000040
title: Projects D1 - Settled alpha schema and repositories
status: Done
assignee:
  - '@devin'
created_date: '2026-10-26T09:47:00Z'
updated_date: '2026-10-26T13:57:00Z'
labels:
  - projects-first
  - step-1-database
milestone: m-0
dependencies: []
documentation:
  - doc-000003
  - doc-000005
  - doc-000002
  - doc-000001
  - doc-000004
  - doc-000007
priority: high
type: feature
ordinal: 24000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
The alpha keeps no compatibility with old databases, contracts or account roles. Settling the whole schema once, including fair capacity, lets the API cards run in parallel against it instead of serializing migrations. Design: local plan sections 4.2-4.5, 5 and 12 (doc-000001, doc-000002, doc-000004).

Step rules and the shared Definition of Done: doc-000003. Card map and worktree rules: doc-000005. Do not start before every dependency is Done and merged into feature/project. When you start, record your own implementation plan in Backlog after researching the current code.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 One baseline Alembic revision replaces all existing revisions; a fresh database upgrades to it and passes schema validation and SQLite foreign-key integrity checks.
- [x] #2 A database at any other revision is rejected with an actionable reset message and is not modified.
- [x] #3 The schema contains every plan section 5 table plus the persisted state the plan needs for API keys, bindings, per-credential OAuth, pools and allocations (base rate, max rate, weight, concurrency, queue limits, loan switch), trace policy and retention, scoped audit events, the execution-authority lease and recovery; state the plan keeps in memory (queue contents, scheduler deficits) is documented as not persisted.
- [x] #4 A Backlog schema document lists every table and column with its ownership category (project, system, shared credential, shared pool); no system or shared-pool row is attached to an arbitrary project.
- [x] #5 Human accounts store identity, authentication provider, status and the TASK-000001 profile fields (username, first name, last name); no role, account-type or superuser column exists.
- [x] #6 Project API keys store a lookup prefix and a verifier digest, never a recoverable secret; a null expires_at means no expiration.
- [x] #7 Allocations default to strict caps with loans disabled; credentials link to upstream pools per operation; a pool balance is stored once per pool, never per credential or project.
- [x] #8 Repository methods for project-owned data require a project id; none silently reads across projects.
<!-- AC:END -->

## Definition of Done
<!-- DOD:BEGIN -->
- [x] #1 Tests of the changed layer pass, plus ruff/mypy (backend) or lint/typecheck/depcruise/knip/build (frontend) with no new findings.
- [x] #2 Tests use fake providers and temporary databases; security assertions are rewritten to the new model, never weakened or dropped without a replacement.
- [x] #3 No secret material (passwords, API keys, provider keys, OAuth grants) appears in responses, logs, traces or test output.
- [x] #4 If the card changes the request path, the routing-latency check passes: FreeSearch adds under 80 ms at p95 per provider, end to end, over REST and MCP. Database read counts are a diagnostic, not a limit.
<!-- DOD:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. Replace the 13 Alembic revisions with one baseline, 0001_alpha_baseline, that creates the full settled schema in doc-000007 and seeds the installation account.
2. Rewrite database_migrations.py: create a missing or empty database at the baseline, validate a database at the baseline, and reject any other revision or an unversioned database with tables with an actionable reset message, without modifying it. Remove the legacy adoption, preflight and backup paths. Keep validation metadata (tables, columns, indexes, foreign keys, PRAGMA foreign_key_check) in step with the baseline.
3. Add the new tables and columns: project_api_keys, project_provider_bindings, upstream_quota_pools, credential_pool_links, project_pool_allocations, credential_oauth_grants, system_audit_events, project_audit_events, retention_runs, execution_authority_leases, execution_dispatches; user profile columns; consumer attribution columns on admissions, rate attempts and usage; pool and credential links on quota snapshots and health; actor type project_api_key.
4. Add ORM rows and repositories for every new table. Project-owned repository methods take a required project_id; system and shared-pool reads use explicit scope names. Add project-scoped usage and trace reads; rename the installation-wide usage aggregates and make the provider usage read require a provider.
5. Tests: baseline and rejection integration tests (byte-identical rejection), ORM/migration metadata comparison, foreign-key integrity, constraint tests (strict caps default, null expiry, no secret column, cross-project binding rejection), repository isolation tests, and the rewritten database_migrations Behave feature.
6. Publish the schema and ownership document (doc-000007) and record in-memory state as not persisted.
7. Gates: ruff and mypy clean; persistence unit and integration tests pass; record any higher-layer test failures that wait for step 2 cards.
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Baseline before changes (2026-10-26, commit eacafc8): ruff clean, mypy clean (103 files); pytest tests/unit tests/integration: 2831 passed, 4 skipped, 18 failed, 6 errors (pre-existing higher-layer failures in routers/services: test_role_matrix, test_monitoring, test_limits_api, test_auth_api, test_users provision, test_api auto_route, test_encrypted_secrets_api keenable, test_manual_quota, test_observability_api). Full run takes about 20 minutes.

Delivery used three adversarial roles: a developer, a tester writing against a fixed contract, and a reviewer auditing both. There were two review rounds.
- Round 1 fixed:
  - a false reset when two processes create the same fresh database; creation now uses a staging file moved into place under the lock
  - a NULL bypass of the binding ownership CHECK, and the scopes JSON check
  - row modules not loaded in server processes; SQLiteRepository now loads all of them
  - narrow audit sanitization; audit detail now uses a strict mode
  - reset messages hidden by the CLIs and servers
  - a locked database reported as needing a reset
  - credential generation and delete changes not limited to their owner
  - login_throttle checks restored
  - execution_dispatches.project_id changed to RESTRICT
- Round 2 fixed a stale -wal next to a deleted database being replayed into the new baseline, which brought old rows back. Old side files are now deleted before the move. Also fixed: a clear message when the target is held open, fewer false positives in strict audit, and no traceback at startup for a locked database.
- Final gate:
  - ruff clean; mypy clean (102 files)
  - persistence unit + integration and the CLI suites: 386 passed
  - database_migrations Behave feature: 3 of 3 scenarios passed
  - compare_metadata reports no differences; foreign_key_check is empty
- Full unit + integration run: 3047 passed, 23 failed, 6 errors. 24 of these are the pre-existing baseline failures.
- 5 higher-layer main() tests fail by design and are left for the API cards: tests/unit/routers/test_api.py::test_main_* (3), tests/integration/mcp/test_server.py::test_main_cli_dispatch, tests/integration/mcp/test_auth.py::test_main_stdio_dispatch_reads_process_token. They call main() without an isolated database, so the new startup check reads the checkout's live freesearch.db (old revision) read-only and refuses to start. The file is unchanged.
- Full Behave: 9 failed, 27 errored, compared with 10 failed, 26 errored at HEAD. Spot checks show obsolete-role errors. Higher layers are left to the API cards.
<!-- SECTION:NOTES:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
One baseline revision, 0001_alpha_baseline, replaces the 13 Alembic revisions. It creates the full settled schema of 36 tables and seeds the installation account. doc-000007 is the schema and ownership document: every table has an ownership category, and it adds delete behaviour, settled details, and the state kept only in memory.

Database lifecycle:
- A missing or empty file is created atomically: the baseline is built in a staging file and moved into place under the lock, after any stale -wal/-shm/-journal files are deleted.
- A database at the baseline is validated (tables, columns, indexes, foreign keys, PRAGMA foreign_key_check).
- Any other revision, or an unversioned file with tables, is refused through a read-only check, with an actionable reset message. The file is not modified.
- All five entry points (api, mcp, db, users, secrets) print the reset message to stderr and exit 1.

New tables:
- API keys (prefix plus verifier digest only; a null expires_at means no expiration).
- Bindings (composite keys enforce private ownership or an existing grant).
- Upstream pools, credential-pool links per operation (provider types must match), and allocations (strict caps by default, loans off).
- Per-credential OAuth grants (a monotonic token_generation, so a disconnected grant is never restored).
- System and project audit events (strict detail sanitization), retention runs, execution authority leases with fencing, and dispatch recovery records.
- Changes to existing tables: user profile columns, and consumer attribution on admissions, rate attempts and usage.

Repositories: seven new ones. Project-owned methods require project_id; a structural test checks every public method. Storage gains project-scoped usage and trace reads, and the installation-wide and provider reads now have explicit names. Credential generation and delete changes are limited to their owner. The actor type is now project_api_key.

Verification: ruff and mypy clean; persistence and CLI suites 386 passed; database_migrations Behave 3 of 3 scenarios passed; ORM and migration metadata match; no foreign-key violations. DoD 4 does not apply: this card does not change the request path.

Follow-ups for the API cards: obsolete-role tests from before this change; 5 main() tests that need an isolated FREESEARCH_DB; UserRow role/is_superuser shims for TASK-000041; trace reads by user_id for TASK-000044. Nothing is committed yet.
<!-- SECTION:FINAL_SUMMARY:END -->
