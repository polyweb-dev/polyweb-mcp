---
id: TASK-000024
title: Projects P08 - Credential instances and explicit global grants
status: Done
assignee:
  - '@devin'
created_date: '2026-10-24T15:54:00Z'
updated_date: '2026-10-25T17:45:00Z'
labels:
  - projects-first
  - phase-p08
  - parallel-b
milestone: m-1
dependencies:
  - TASK-000020
references:
  - src/freesearch/infrastructure/encrypted_store.py
  - src/freesearch/infrastructure/cryptography.py
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
ordinal: 900
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
The singleton provider secret slots prevent multiple keys for one provider. Shared reuse must avoid duplicate secrets while keeping private credentials isolated.

Phase: P08. Execution lane: parallel-b. Milestone: Projects 2 - Project-first release.

Dependency gate: P03 (TASK-000020)
Do not implement or mark In Progress until every dependency is Done, merged into the integration branch, and its acceptance evidence is available. Priority and phase numbers never override this gate. Parallel work is permitted only where the dependency graph and shared-file ownership allow it.

Accepted scope from plan section 10 / P08:

Add credential metadata, per-instance encrypted slots, generation numbers, ownership, and global project grants.
Store newly entered provider secrets through the encrypted store. Preserve delete-wins tombstone behavior for the new per-instance slots.
No old provider-secret import is necessary.

Restructure note (2026-10-25): TASK-000035 (pool schema) now follows this card. P04, P07, P08 and TASK-000035 all add Alembic revisions: allocate them serially from the actual head and merge one schema head.

Cross-phase constraints:
User-approved constraints: one human account type; one common scoped RBAC service; system/project roles are assignments, not account types. Preserve internal UUIDs and local/WorkOS storage constraints without implementing WorkOS/cloud features. Use one internal installation account. Project tokens can expire or have no expiration. Support private and explicitly shared credential instances. Strict pool/project caps are the default; fair loans require their later phase. Use a fresh alpha database; do not migrate/import old history, humans, settings or secrets. Never use the live database or real provider credentials for tests. Desktop UI only; local environment controls ports.

Verification expectations:
Use encrypted-store and persistence tests with fake secrets. Exercise private ownership, explicit grants, generation rotation and delete-wins behavior. Do not read live keys.
Use the managed verification specification for required quality commands and test placement. Record objective evidence before completion.

Before code work, read AGENTS.md and applicable skills, use CodeGraph for indexed code, inspect current implementation and record the task implementation plan through Backlog. The referenced design is context; this future ticket intentionally has no speculative implementation-plan field.

Documentation: local .agents/communication/projects-feature-plan.md, sections 4-10 for design and scope, section 11 for ordering. The managed specification documents are durable copies for checkouts where the gitignored local plan is absent. Use the execution-index document for exact phase-to-ticket IDs and ready-work commands.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 Multiple separately labelled credential instances can exist for the same provider.
- [x] #2 One installation-shared credential can serve explicitly granted projects without duplicate secret storage.
- [x] #3 A project's private credential cannot be enumerated, read or bound by another project.
- [x] #4 Imported credentials expose only permitted metadata; project administrators cannot rotate, delete or reshare a system-owned secret.
- [x] #5 Per-instance encrypted storage preserves generation and delete-wins tombstone behavior without secret output.
- [x] #6 No legacy credential import or cloud credential-management feature is introduced.
- [x] #7 Encrypted secrets are bound to their slot: ciphertext moved to another slot or credential does not decrypt; granted projects read the one shared slot unchanged.
- [x] #8 The master key can be rotated: envelopes record a key id, retired keys still decrypt, an operator re-key command moves every envelope to the current key without printing secrets, and legacy v1 envelopes are readable only for singleton slots.
<!-- AC:END -->

## Definition of Done
<!-- DOD:BEGIN -->
- [x] #1 All phase acceptance criteria have objective test or review evidence recorded in Backlog before Done.
<!-- DOD:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. Migration 0008_provider_credentials (down_revision 0007; rename if P04 merges first). provider_credentials(id, account_id FK accounts, provider_type, owner_scope system|project, owner_project_id FK projects CASCADE, label, auth_mode api_key|oauth, generation>=1, status active|deleted, created_by FK user, created_at, updated_at, version>=1) with owner-scope CHECK, unique (id, owner_scope), partial unique live label per (account, owner_scope, coalesce(owner_project_id,''), provider_type, label) WHERE status='active'. credential_project_grants(credential_id, owner_scope CHECK='system', project_id FK projects CASCADE, permitted_operations JSON, granted_by FK user, created_at, version) PK (credential_id, project_id) with composite FK (credential_id, owner_scope) -> provider_credentials(id, owner_scope) so a private credential can never be granted. Extend database_migrations.py head validation; update head literals in the three tests.
2. Per-instance encrypted slots: session-scoped write-once operations on EncryptedDbSecretStore (create slot fails if ciphertext or tombstone exists; tombstone removes ciphertext and writes secret.deleted marker; tombstone-wins read). Slot name credential.<id>.g<generation>; a new generation always gets a fresh slot, so a deleted or rotated-out generation can never be resurrected. Legacy singleton slots and their census are unchanged; no import.
3. models/credentials.py: CredentialOperation, CredentialAuthMode, CredentialStatus, CredentialCreate (SecretStr), CredentialRotate (expected_generation), CredentialGrantUpsert, ProjectCredentialRead (sanitized project projection: imported system credentials show no generation, can_manage false). Reuse P00 CredentialInstanceRead and CredentialProjectGrantRead.
4. persistence/credentials.py rows + CredentialRepository with mandatory owner/project parameters.
5. services/credentials.py CredentialService: live RBAC through ScopedAuthorizationService; system.credentials.manage for system create/list/rotate/delete and grants; project providers.read for list/get, credentials.manage_private for private create/rotate/delete; non-revealing 404 for unknown, other-project and ungranted credentials; 403 when a project admin tries to rotate/delete/reshare a system credential; archived projects reject new private credentials and grants. All writes in one BEGIN IMMEDIATE transaction (metadata + ciphertext), generation compare-and-set (409 CREDENTIAL_GENERATION_CONFLICT). Delete tombstones the current slot, marks the row deleted and drops its grants. Runtime seam resolve_for_project(context, credential_id, operation, expected_generation) rechecks ownership/grant/operation/status per call for P09.
6. routers/credentials.py thin routes: /api/v1/system/credentials (+/{id}/rotate, /{id}, /{id}/grants, /{id}/grants/{project_id}) and /api/v1/projects/{project_id}/credentials (+/{id}, /{id}/rotate); register in api.py; 503 if the encrypted store is not configured. Responses never include secrets.
7. Tests: unit models and encrypted-store slot cases; integration persistence schema constraints; integration service scenarios for AC1-AC6 (multiple labels, single shared ciphertext, private isolation, imported metadata limits, rotation/concurrent rotation/delete-wins, no secret in output or logs, legacy slot ignored); HTTP status mapping. Verify with ruff, mypy, focused suites, then full unit and integration suites against the baseline.

8. Scope addition (user-approved 2026-10-25), slot binding: v2 envelope {v:2, alg, kid, nonce, ct}. The AES-GCM associated data is the canonical JSON of [freesearch-secret, 2, kid, slot name], so ciphertext cannot be moved between slots or credentials. Grants are references to one slot, so granted projects are unaffected. All writes use v2. v1 envelopes (no AAD) are still read for legacy singleton slots via get() only; credential slots (get_in_session) accept only v2.
9. Master-key rotation: MasterKey.key_id = truncated HMAC-SHA256 fingerprint. SecretCodec takes a primary key plus retired keys and selects the key by kid. New settings encryption_retired_key_files (list of paths) and encryption_retired_keys (list of passphrases, using the same installation salt). A shared load_secret_codec(settings) replaces the duplicated wiring in routers/api.py and mcp/server.py. New freesearch-secrets CLI with status (value-free counts per version/kid) and rekey (one BEGIN IMMEDIATE transaction re-encrypts every non-current envelope with the primary key; undecryptable rows are counted, left unchanged and give a non-zero exit). Credential generations stay independent of master-key ids. Cloud KMS/Key Vault master-key storage stays a follow-up ticket, created from the main checkout.
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Implementation (uncommitted, branch projects/p08-credential-instances):
- Migration 0008_provider_credentials (down 0007_project_settings): provider_credentials + credential_project_grants. The composite FK (credential_id, owner_scope='system') -> provider_credentials(id, owner_scope) blocks grants of private credentials at the DB level. A partial unique index enforces unique live labels per owner and provider. Head validation (tables/columns/indexes/FKs) extended in database_migrations.py. Head literals updated in test_database_migrations.py, test_projects.py, alpha_fixtures.py. MERGE NOTE: if P04 merges its revision first, rename this to the next number and update the same three literals.
- Encrypted slots: EncryptedDbSecretStore gains session-scoped get_in_session / write-once create_slot_in_session / tombstone_in_session (physical ciphertext delete + secret.deleted marker). The slot is credential.<id>.g<generation>, so every generation is a fresh write-once slot and a tombstoned slot can never be rewritten (SecretSlotConflict). Legacy singleton get/set/delete and the census are unchanged; no import.
- models/credentials.py, persistence/credentials.py (CredentialRepository with mandatory scope params, CAS advance_generation), services/credentials.py (CredentialService; each write runs row and slot changes in one BEGIN IMMEDIATE transaction; resolve_for_project / usable_credential_in_session are the P09 seam and recheck grant, operation, project status and generation on every call), routers/credentials.py (/api/v1/system/credentials[/{id}[/rotate|/grants[/{project_id}]]], /api/v1/projects/{project_id}/credentials[/{id}[/rotate]]), registered in routers/api.py. Credential routes return 503 unless the encrypted store is configured.
- Decisions: secret_reference is derived from (id, generation) rather than stored. Deleted credentials stay as status='deleted' rows, so IDs and generations are never reused. The system credential list excludes project-private credentials. A project admin rotating or deleting a granted system credential gets 403; an unknown, other-project or ungranted credential gets a non-revealing 404. Archived projects reject private creates and grants (409 PROJECT_ARCHIVED) and do not resolve. Secrets are stripped of surrounding whitespace on input. auth_mode CHECK allows 'oauth' as a P10 seam; the service only accepts api_key.
- Residuals: hard project deletion (not a supported path; projects archive) would cascade credential rows but leave tombstone and ciphertext runtime_settings rows. Audit events for grants are deferred because no audit log infrastructure exists yet. There is no UI (P12) and no binding table (P09).

Verification:
- uv run ruff check src tests: clean. uv run mypy: Success, 100 source files. ruff format --check on all changed files: clean. Repo-wide format --check still lists 15 files that were already unformatted at HEAD; none were touched.
- Focused P08 suites: tests/unit/models/test_credentials.py, tests/unit/infrastructure/test_encrypted_store.py, tests/integration/persistence/test_credentials.py, tests/integration/services/test_credentials.py, tests/integration/routers/test_credentials_api.py: 65 passed.
- Full gate uv run pytest tests/unit tests/integration: 28 failed, 2770 passed, 6 errors, against a baseline before changes of 28 failed, 2723 passed, 6 errors. The failing test ids are identical to the baseline (pre-existing, e.g. test_keenable_reports_keyless_public and the test_role_matrix errors). The +47 passing tests are the new P08 tests (the 3 rework tests ran in the focused pass).
AC evidence (tests/integration/services/test_credentials.py unless noted):
#1 test_ac1_multiple_instances_distinct_secrets_and_label_conflicts
#2 test_ac2_shared_system_credential_grants_and_revocation (exactly one secret.enc:credential.<id>.g1 row serves both projects)
#3 test_ac3_private_credentials_are_invisible_across_projects; persistence composite-FK/CHECK tests in tests/integration/persistence/test_credentials.py
#4 test_ac4_project_projection_hides_system_internals_and_scope_boundaries; HTTP 403/404 in tests/integration/routers/test_credentials_api.py
#5 test_ac5_rotation_advances_generation_and_slots, test_ac5_concurrent_rotations_have_exactly_one_winner, test_ac5_private_rotation_never_touches_other_credentials, test_ac5_delete_tombstones_slots_grants_and_label_reuse, test_ac5_no_secret_output_in_logs_or_dtos, test_ac5_archived_project_blocks_writes_and_resolution, test_slot_conflict_rolls_back_row_and_maps_conflict; slot tests in tests/unit/infrastructure/test_encrypted_store.py
#6 test_ac6_legacy_singleton_secrets_are_invisible_to_credentials; review: no import code, no cloud features, legacy endpoints and census untouched.

Encryption hardening (scope addition, user-approved 2026-10-25):
- cryptography.py: v2 envelopes {v:2, alg, kid, nonce, ct}. The AES-GCM associated data is json [freesearch-secret, 2, kid, slot], so moved ciphertext fails closed. MasterKey.key_id is a 16-hex HMAC-SHA256 fingerprint. SecretCodec(primary, retired=...) selects the key by kid and always writes with the primary; it has needs_rekey(). load_retired_master_keys never creates files; passphrases reuse the installation salt. v1 (no AAD) is read only with allow_legacy.
- encrypted_store.py: every path passes context=slot name. The legacy get() allows v1 for existing singleton slots; get_in_session() (credential slots) accepts only v2. load_secret_codec(settings) replaces the duplicated wiring in routers/api.py and mcp/server.py. rekey_secrets(repository, codec, dry_run) makes one BEGIN IMMEDIATE pass that skips tombstoned, null and non-string rows, counts undecryptable rows and leaves them unchanged, and is idempotent.
- config.py: encryption_retired_key_files (list of paths), encryption_retired_keys (list of SecretStr).
- New freesearch-secrets CLI (pyproject script): status (exit 1 while a rekey is pending or a row is undecryptable) and rekey [--dry-run] (exit 1 on undecryptable rows). Output is value-free.
- Rotation runbook: (1) point FREESEARCH_ENCRYPTION_KEY_FILE (or FREESEARCH_ENCRYPTION_KEY) at the new key and list the old key in FREESEARCH_ENCRYPTION_RETIRED_KEY_FILES / FREESEARCH_ENCRYPTION_RETIRED_KEYS (JSON list); (2) restart the API and MCP processes; (3) run freesearch-secrets rekey; (4) confirm freesearch-secrets status exits 0; (5) remove the retired key config and restart. A process still configured with only the old key fails closed after the rekey.
- Grants are unaffected: granted projects read the same slot, so the AAD matches. Credential generation stays independent of the master-key id.
- Residual: until the rekey runs, v1 singleton envelopes stay readable without slot binding. An option to refuse v1 entirely after the rekey could follow. Also fixed a pre-existing test leak: test_settings_encryption_key_file_overrides_default left a poisoned get_settings cache.
Evidence:
- AC7: test_ac7_ciphertext_is_bound_to_its_slot (services); context-mismatch and copy-binding tests in tests/unit/infrastructure/test_cryptography.py and test_encrypted_store.py.
- AC8: test_ac8_master_key_rotation_keeps_credentials_usable; retired, v1, needs_rekey and load_retired_master_keys tests; rekey mixed-row counts, idempotency and dry-run tests; tests/integration/cli/test_secrets.py (exit codes, no secret or key bytes in output).
Verification: ruff check clean; ruff format clean on changed files; mypy Success (101 files). Focused run: 147 passed plus 1 baseline failure (test_keenable_reports_keyless_public). behave encrypted_secrets.feature: 8/8. Full unit+integration: 28 failed, 2788 passed, 6 errors, with failure ids identical to the pre-change baseline (+18 new tests).
<!-- SECTION:NOTES:END -->

## Comments

<!-- COMMENTS:BEGIN -->
author: @devin
created: 2026-10-25T15:06:00Z

---

Migration merge rule (2026-10-25): this card adds an Alembic revision while another lane also changes schema. Land the migration and its database_migrations.py schema-validation change as a small first pull request. P04 lands first when P04 and P08 are both ready; otherwise the first merged migration keeps the next number. The other branch rebases, renames its revision to the following number, sets down_revision to the new head, and updates the head literal in tests/integration/persistence/test_database_migrations.py, tests/integration/persistence/test_projects.py and tests/fixtures/alpha_fixtures.py. Keep one migration head. See doc-000005, Worktrees and merging.

---
<!-- COMMENTS:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
P08 adds provider credential instances and explicit system-to-project grants. Changes: migration 0008_provider_credentials; per-generation write-once encrypted slots with delete-wins tombstones; CredentialService with live scoped RBAC and atomic row+slot writes; system and project REST routes; a grant-aware resolve_for_project seam for P09. One shared system credential serves granted projects from a single ciphertext row. Private credentials are invisible to other projects and cannot be granted (service 404 plus a DB composite FK). Project admins cannot rotate, delete or reshare system credentials. Rotation is a compare-and-set on the generation and invalidates only the old generation. Verification: ruff and mypy clean; 65 focused P08 tests pass; full unit+integration has the same failures as the pre-change baseline, with no new failures. Follow-ups: rename the revision if P04 merges first; audit events for grants once audit infrastructure exists; P09 bindings; P12 UI.

Scope addition: encrypted secrets are now bound to their slot through AES-GCM associated data (v2 envelopes carrying a key id). The master key can be rotated: retired keys are configurable, and the freesearch-secrets status/rekey CLI migrates every envelope, including legacy v1 singleton slots, to the current key. Follow-up (to be created from the main checkout): hosted master-key storage in Azure Key Vault or AWS KMS (envelope encryption), and an option to refuse v1 envelopes after a rekey.
<!-- SECTION:FINAL_SUMMARY:END -->
