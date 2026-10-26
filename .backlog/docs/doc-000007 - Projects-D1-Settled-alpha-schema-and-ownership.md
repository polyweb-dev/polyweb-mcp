---
id: doc-000007
title: Projects D1 - Settled alpha schema and ownership
type: specification
created_date: '2026-10-26T10:42:00Z'
updated_date: '2026-10-26T13:15:00Z'
tags:
  - projects-first
  - specification
  - schema
---
# Projects D1 - settled alpha schema

This document is the schema of record for TASK-000040. One Alembic baseline revision, `0001_alpha_baseline`, creates every table below. Alembic owns table creation; the SQLAlchemy rows in `src/freesearch/persistence/` mirror it for typed access, and a test compares the two. `database_migrations.py` keeps the validation metadata (tables, columns, indexes, foreign keys) in step with it.

## Rules

- Identifiers are UUID text, `CHAR(36)`, except where a column says otherwise. Timestamps are UTC ISO-8601 text. Money and native amounts are exact decimal text. Rates are integers per explicit window. JSON is stored as text.
- `version` and `revision` columns start at 1 and are compare-and-set values.
- Foreign keys are enabled on every SQLite connection. After an upgrade, validation runs `PRAGMA foreign_key_check`.
- Composite foreign keys prevent cross-project references where SQLite can express the rule.
- Actor and creator attribution columns (`created_by` on API keys, bindings and allocations, `actor_id` on telemetry and audit rows) are snapshots without a foreign key, so removing a human account keeps history and never deletes project-owned API keys.
- Actor types are `human` and `project_api_key` on execution rows; audit rows add `system` and `anonymous`.

## Ownership categories

Every table has one category. A `shared pool` or `system` row never carries an owning project. Some shared-pool rows carry a nullable *consumer attribution* `project_id`: it names the project whose execution consumed the capacity, it is set only by the execution path, and it is never an owner.

| Category | Meaning |
| --- | --- |
| project | Owned by one project. `project_id` is required and every repository method takes it. |
| system | Installation scope. Owned by the installation account or the platform. |
| shared credential | A system-owned provider credential and the state attached to it. Projects reach it only through an explicit grant. |
| shared pool | An upstream quota boundary and its accounting. Shared by every credential and project that uses the pool. |

`provider_credentials` and `credential_oauth_grants` are row-level: `owner_scope = 'system'` rows are shared credential, `owner_scope = 'project'` rows are project.

## Tables

### System

| Table | Columns | Notes |
| --- | --- | --- |
| `accounts` | id, status | Seeded installation account `00000000-0000-4000-8000-000000000001`. |
| `user` | id, email, hashed_password, is_active, is_verified, auth_provider, auth_provider_id, username, first_name, last_name | One human identity type. `is_active` is the account status. No role, account-type or superuser column. `username`, `first_name`, `last_name` are nullable until TASK-000001 signup collects them; `username` is unique case-insensitively when present. Local/WorkOS provider checks are kept. |
| `login_throttle` | key, attempts, expires_at | Brute-force counters. |
| `auth_sessions` | id, user_id, created_at, expires_at, revoked_at | Human session families. |
| `refresh_tokens` | token_hash, family_id, issued_at, expires_at, consumed_at | Refresh digests only. |
| `system_role_assignments` | account_id, user_id, role_key, granted_by, version | `system_admin` is an assignment, not an account type. |
| `system_settings` | namespace, schema_version, document, revision | Typed system documents. The `traces` namespace holds the system trace policy (sampling, detail, payload capture, retention bounds) and exporter settings. |
| `runtime_settings` | key, value_json | Installation runtime values and encrypted secret slots. Credential secrets use `credential.<id>.g<generation>`; OAuth secrets use `credential.<id>.oauth.<kind>.t<token_generation>`. |
| `provider_limits` | provider, operation, auth_mode, supported, transport_available, rate_json, budget_json, native_unit, native_pool_id, conversion_profile_json, plan_name, usage_url, version | Provider catalog facts. |
| `provider_crd_grants` | provider, operation, auth_mode, period_start, period_end, granted_crd_text, consumed_crd_text, reserved_crd_text, version | Operator CRD grants. |
| `system_audit_events` | id, account_id, occurred_at, category, action, actor_type, actor_id, target_type, target_id, outcome, correlation_id, detail | `category` is `audit` or `security`. Authentication failures before project resolution are `security` events with no project. `detail` is sanitized JSON. |
| `execution_authority_leases` | authority_key, holder_id, fencing_token, state, acquired_at, renewed_at, expires_at, recovery_until, version | One row per execution authority. `fencing_token` increases on every acquisition; `state` is `vacant`, `active` or `recovering`. |

### Project

| Table | Columns | Notes |
| --- | --- | --- |
| `projects` | id, account_id, name, slug, status, created_by, created_at, version | `status` is `active` or `archived`. |
| `project_memberships` | project_id, user_id, status, version | |
| `project_role_assignments` | project_id, user_id, role_key, granted_by, version | Composite key to the membership. |
| `project_settings` | project_id, namespace, schema_version, overrides, revision | The `traces` namespace holds project trace overrides within system policy. |
| `credential_project_grants` | credential_id, owner_scope, project_id, permitted_operations, granted_by, created_at, version | Grants a project a system credential; `owner_scope` is fixed to `system`. |
| `project_api_keys` | id, project_id, label, prefix, verifier_digest, scopes, created_by, created_at, expires_at, revoked_at, last_used_at, rotated_from_id, version | `prefix` is the unique public lookup identifier. `verifier_digest` is a one-way digest; no recoverable secret is stored. `expires_at` null means no expiration. `rotated_from_id` must name a key of the same project. |
| `project_provider_bindings` | id, project_id, credential_id, credential_scope, private_project_id, granted_project_id, route_label, enabled_operations, priority, overrides, created_by, created_at, updated_at, version | Unique `(project_id, credential_id, route_label)`. A private binding must reference a credential the project owns; a system binding must reference an existing grant to the same project. `enabled_operations` defaults to `[]`, so a new binding starts disabled. |
| `project_pool_allocations` | project_id, pool_id, operation_scope, base_rate, rate_window_seconds, borrow_enabled, max_rate, weight, best_effort, max_concurrency, max_queued_requests, max_queued_bytes, max_queue_wait_ms, granted_by, created_at, updated_at, version | Strict caps by default: `borrow_enabled` defaults to false and then `max_rate` is null or equal to `base_rate`. With loans, `max_rate >= base_rate`. A zero `base_rate` needs `best_effort`. `weight >= 1`. Null queue and concurrency limits inherit system policy. |
| `project_audit_events` | id, project_id, occurred_at, action, actor_type, actor_id, target_type, target_id, outcome, correlation_id, detail | Membership, API key, grant, allocation, settings, copy and support-access events. |
| `retention_runs` | id, project_id, data_class, cutoff, status, started_at, finished_at, deleted_rows, error_code | Every retention run names one project. `data_class` is `traces`, `usage` or `audit`. |
| `usage_events` | id, provider, operation, units, observed_at, request_id, metadata, latency_ms, status, unit_kind, project_id, actor_type, actor_id, trace_id, credential_id, binding_id, pool_id | Project usage attribution. |
| `trace_spans` | span_id, trace_id, parent_span_id, user_id, project_id, actor_type, actor_id, name, kind, started_at, ended_at, duration_ms, status_code, status_message, outcome, error_type, operation, provider, input_text, output_json, result_count, attributes_json, events_json, resource_json | Project execution traces. |
| `execution_dispatches` | attempt_id, request_id, project_id, pool_id, credential_id, binding_id, operation, actor_type, actor_id, authority_key, fencing_token, state, dispatched_at, resolved_at | Recovery record of dispatched provider attempts. `state` is `dispatched`, `completed`, `failed` or `uncertain`. After an authority takeover, unresolved rows of an older fencing token become `uncertain` and keep holding pool concurrency until resolved. |

### Shared credential

| Table | Columns | Notes |
| --- | --- | --- |
| `provider_credentials` | id, account_id, provider_type, owner_scope, owner_project_id, label, auth_mode, generation, status, created_by, created_at, updated_at, version | System rows are shared credentials; project rows are private. The secret is the derived slot `credential.<id>.g<generation>`. |
| `credential_oauth_grants` | credential_id, auth_mode, credential_generation, token_generation, status, client_id, scopes, access_expires_at, connected_at, refreshed_at, disconnected_at, last_error_code, updated_at, version | One OAuth connection per OAuth credential. `token_generation` only increases, and secret slot names include it, so a refresh race or a reconnect cannot restore old or disconnected tokens. `status` is `pending`, `connected`, `refresh_failed` or `disconnected`. |
| `provider_health` | id, provider, status, checked_at, message, credential_id | Null `credential_id` is a provider-wide fact. |

### Shared pool

| Table | Columns | Notes |
| --- | --- | --- |
| `upstream_quota_pools` | id, account_id, provider_type, upstream_scope, pool_key, label, constraints, max_concurrency, max_queued_requests, native_pool_id, status, created_at, updated_at, version | The real upstream quota boundary. `pool_key` is the provider-documented identity, unique per account and provider. `upstream_scope` is `account`, `credential`, `ip` or `installation`. `constraints` is the JSON list of rate constraints with explicit algorithm and window. `native_pool_id` links the single balance row. |
| `credential_pool_links` | credential_id, operation_scope, pool_id, provider_type, created_at, version | One pool per credential and operation. Provider type must match on both sides. |
| `provider_native_pools` | pool_id, provider, auth_mode, native_unit, remaining_text, allowance_text, actual_spend_usd_text, source, confidence, reset_at, observed_at, version, credential_generation, next_sync_at, lease_owner, lease_until, sync_error_code, stale, manual_anchor, tier_json, tier_split_known, last_tier_observed_at | The only stored balance. One row per pool; no credential or project table stores a balance. |
| `provider_limit_events` | event_id, provider, operation, auth_mode, pool_id, observed_at, source, reason, old_native_text, new_native_text, old_crd_json, new_crd_json, crd_debit_text, native_debit_text, actual_usd_text, confidence, local_attempt_id, detail_json | Pool balance audit. |
| `provider_limit_admissions` | attempt_id, provider, operation, auth_mode, pool_id, reserved_crd_text, reserved_native_text, state, created_at, expires_at, rate_reservations_json, local_only, project_id, credential_id, binding_id, upstream_pool_id, request_id | Reservations. `project_id` is consumer attribution. |
| `provider_rate_observations` | bucket_id, provider, auth_mode, window, unit, operation, limit_text, remaining_text, reset_at, observed_at, source, confidence, stale | Observed upstream windows. |
| `provider_rate_attempts` | attempt_id, bucket_id, provider, auth_mode, operation, window, unit, units_text, attempted_at, expires_at, project_id, credential_id, binding_id, upstream_pool_id, request_id | Rate debits. `project_id` is consumer attribution. |
| `quota_snapshots` | id, provider, source, remaining, limit_units, reset_at, observed_at, unit_kind, display_unit, metadata, pool_id, credential_id | Quota observations of a pool or credential. |

## State the plan keeps in memory

These are not persisted. A restart loses them by design; persisted attempts, admissions, dispatch records and the lease keep rate consumption and uncertain concurrency.

- Per-project queue contents, queued payloads and queue order.
- Weighted Deficit Round Robin deficits, quantum counters and the round-robin cursor.
- Monotonic queue deadlines and wait timers.
- Adapter instances cached by credential identity and generation.
- Effective settings caches, invalidated by system and project revisions.

## Database lifecycle

- A missing or empty file is created at the baseline.
- A database at the baseline is validated and opened.
- A database at any other revision, or an unversioned database with tables, is rejected with an actionable reset message and is not modified.

## Delete behaviour

Projects are archived, not deleted. The delete rules below still decide what survives a deletion.

| Rule | Foreign keys |
| --- | --- |
| Cascade with the owner | Project-owned rows cascade with their project: memberships, role assignments, settings, grants, API keys, bindings, allocations, project audit events, retention runs, private credentials. Credential state cascades with its credential: OAuth grants, pool links, grants, bindings, `provider_health` and `quota_snapshots` rows for that credential. Allocations and `quota_snapshots` rows cascade with their pool. Session families and refresh digests cascade with the human account. |
| Restrict | `projects.account_id`, `projects.created_by`, `provider_credentials.account_id` and `created_by`, `upstream_quota_pools.account_id` and `native_pool_id`, `credential_pool_links.pool_id`, `system_audit_events.account_id`, `granted_by` on role assignments and grants, and every foreign key of `execution_dispatches` except credential and binding. A project or pool with dispatch records cannot be deleted, so uncertain upstream concurrency is never dropped. |
| Set null | Consumer attribution on `provider_limit_admissions`, `provider_rate_attempts` and `usage_events` (`project_id` on admissions and attempts; `credential_id`, `binding_id`, pool on all three), and `credential_id` and `binding_id` on `execution_dispatches`. The consumption row survives and only the attribution is cleared. |
| No action | `usage_events.project_id`, `trace_spans.project_id`, and `project_api_keys.rotated_from_id` (same-project composite key). |

## Settled details

- `accounts.status` is `active` or `suspended`. `projects.status` is `active` or `archived`. Membership status is `active` or `suspended`.
- `login_throttle.key` is a 64-character SHA-256 hex digest, so no raw email or address is stored.
- `project_api_keys.scopes` must be a non-empty JSON array. `record_use` never moves `last_used_at` backwards.
- `credential_oauth_grants.token_generation` is 1 after the first `begin_connect`, and every connect, token write and disconnect increases it.
- If the same holder acquires the execution authority again, a new incarnation starts: the token increases, the holder's earlier open dispatches become `uncertain`, and the lease is `recovering` until the recovery time ends.
- Audit `detail` uses the strict sanitizer. A key that contains `token`, `secret`, `password`, `passwd`, `apikey`, `privatekey`, `credential`, `authorization`, `cookie`, `digest`, `verifier`, `bearer` or `session` is refused, unless it ends in `id`, `ids`, `count`, `label`, `generation`, `scope` or `status`. A value that starts with `fs_live_` or `Bearer ` is refused. Identifiers and API key prefixes go in `target_type` and `target_id`, not in `detail`.
- Composite foreign keys on bindings, OAuth grants and pool links need unique parent indexes on `provider_credentials (id, owner_scope)`, `(id, owner_project_id)`, `(id, auth_mode)`, `(id, provider_type)`, and on `upstream_quota_pools (id, provider_type)`.
- `user_username_lower_key` is a partial unique index on `lower(username)`.
- Query indexes, in addition to the keys:
  - Telemetry: `project_api_keys_project_created`, `trace_spans_project_root_started_at`, `usage_events_project_observed_at`.
  - Pool accounting: `provider_limit_admissions_upstream_pool_state`, `provider_rate_attempts_upstream_pool_attempted`, `quota_snapshots_pool_observed_at`, `provider_health_credential_checked_at`.
  - Audit and retention: `system_audit_events_account_occurred`, `project_audit_events_project_occurred`, `retention_runs_project_class_started`.
  - Execution: `execution_dispatches_pool_state`, `execution_dispatches_project_dispatched`, `execution_dispatches_authority_state`.
  - Lookups: `ix_login_throttle_expires_at`, `ix_project_provider_bindings_credential_id`, `ix_credential_pool_links_pool_id`, `ix_project_pool_allocations_pool_id`.
- Child spans of a trace are read only when they carry the root's `project_id`.

## Creation and rejection details

- The baseline is built in a staging file `<name>.creating-<8 hex>` in the same directory. It is validated and then moved into place under the migration lock. Before the move, any old `-wal`, `-shm` and `-journal` files at the target are deleted, so a leftover log can never bring old rows into the new database. WAL mode is turned on after the move.
- An interrupted creation never leaves a partial file at the target. The next creation removes its leftover staging files.
- Before the lock, only a database with a different revision, or a file that is not SQLite, is rejected. An unversioned database that has tables is rejected only under the lock, so a process cannot reject a database that another process is still creating.
- Rejection opens the file read-only and changes no byte of it. For a WAL database, SQLite can create empty `-wal` and `-shm` files during the read-only check. The reset message tells the operator to move or delete them together with the database.
- A locked database is reported as locked, never as a reset.
- `freesearch-api`, `freesearch-mcp`, `freesearch-db`, `freesearch-users` and `freesearch-secrets` print the reset message to stderr and exit with status 1, without a traceback.
