# Backend support audit — reviewed synthesis

Date: 2026-10-26. Commit: `07d5e9b`. API/backend only; no implementation.

Antigravity Gemini 3.8 Flash Medium inspected noncritical backend support. The orchestrator checked its findings against current source and corrected unsupported claims: `UserRow.role`/`is_superuser` remain compatibility properties; CLI `developer` rejection is handled; Docker host ports differ from internal ports; D1 alone does not prove rollout metadata dead. The final findings below include those corrections.

Read the [main audit](2026-10-26-api-rewrite-simplification-audit.md) for acceptance precedence and implementation order. These support findings do not expand the A-series requirements.

## SUP-01 — P1: replace legacy CLI authority vocabulary

**Evidence:** `cli/users.py:91` describes account-role commands, the parser accepts `UserRole`, `:233–236` prints `Role: admin`, and `:251–255` calls `AuthService.change_role`. `services/users.py:673–689` rejects `developer` via `AuthUnsupportedRole`, formatted by `cli/users.py:195–197`. `persistence/users.py:132–160` derives legacy role/superuser properties from system assignments. D1 removed the columns, not these properties. An unhandled crash is not established.

**Action:** A1 should cut CLI DTOs, service mutations and output over to explicit scoped assignments. Retire `developer`/`agent` account classifications and the old `set-role` contract after callers/tests migrate. Trusted bootstrap remains an ordinary human plus installation `system_admin` assignment. Do not add a general role-administration language.

**Preserve/verify:** A1.1/.2/.3/.8 and P01/P02. Keep masked terminal password entry, refusal of password arguments, sanitized errors, appropriate session revocation and transactional `LAST_PROJECT_ADMIN` protection in `deactivate` (`:238–246`). Rewrite role-output expectations in `tests/integration/cli/test_users.py` and `tests/unit/cli/test_users.py`; retain non-echo, deactivation and revocation assertions. Use temporary databases.

## SUP-02 — P3: place database CLI with operator entrypoints when next touched

**Evidence:** `persistence/database_cli.py:27–46` owns argparse, `:49–90` owns operator output/status and `:93–96` exits. Other operator CLIs live in `cli/`. This is a cohesion opportunity, not a proven cycle or runtime defect.

**Action:** optionally move it to `cli/database.py`, updating the console entrypoint, test imports and docs together. Keep migration operations in persistence. Do not retain an alpha internal-import redirect or prioritize this move over runtime invariants.

**Preserve/verify:** executable name `freesearch-db`, read-only status, atomic creation/validation, byte-preserving rejection with actionable stderr/exit 1. Existing tests include `tests/integration/persistence/test_database_migrations.py:481::test_cli_reports_reset_required_without_traceback`; CLI reset tests are not wholly absent.

## SUP-03 — P3: share small CLI mechanics without a command framework

**Evidence:** `cli/secrets.py:31–38`, `persistence/database_cli.py:32–39` and user subparsers repeat database-argument/help text. Reset formatting repeats in `secrets.py:88–90`, `database_cli.py:72–74`, `users.py:176–178` and transport entrypoints. `secrets.py:64–82` repeats repository lifetime/reporting between status and rekey.

**Action:** a plain `add_database_argument(parser)` is sufficient if callers change together. Combine status/rekey resource lifetime without obscuring different exit semantics. Keep specialized errors local; two lines of error printing may remain if extraction adds indirection. Do not introduce decorator frameworks or a new KeyboardInterrupt policy to remove a few lines.

**Preserve/verify:** current environment precedence, sanitized stderr/exit codes, no-write dry run, no secret/key output and teardown. Reuse CLI integration tests with temporary paths. This is optional maintenance reduction, not separate acceptance work.

## SUP-04 — P2: move database-path policy below monitoring

**Evidence:** `services/monitoring.py:208–230::_environment_file_value` parses cwd `.env`; `:233–249::resolve_database_path` applies process environment → explicit path → local file → default. Imports include `persistence/database_cli.py:14`, `cli/secrets.py:23`, `cli/users.py:39` and `services/users.py:62`. Database path selection does not belong to telemetry.

**Action:** move resolver/constants below services without unrelated settings loading. A focused typed configuration/path-resolution object is appropriate when it encapsulates source/precedence policy; a helper can implement the mechanics. Choose the boundary consistently with the typed OOP design in the main report, rather than imposing either a class-only or function-only rule.

**Preserve/verify:** `.env.example` explicitly documents cwd behavior. Automatic repository-root discovery would change database selection; do not introduce it incidentally. Cover precedence, quoted values, missing files and distinct cwd using temporary files. This protects D1 startup/test isolation and worktree safety.

## SUP-05 — P2: retire record translation, preserve current enablement commands

**Evidence:** `configuration/provider_config.py:62::_legacy_enable_mask`, `:129::_decode_legacy_access` and `:369::_translate_legacy_entry` translate old Boolean records. This is reachable compatibility code, not proven unused code. Separately `ProviderConfigUpdate:217–220` accepts current global/search/fetch toggles, and `:318–323` updates individual mask bits. `.env.example` still shows a Boolean override.

**Action:** A2/A4 should define one canonical stored configuration/binding format and remove old record translation after environment examples, writers, readers and fixtures switch. Do not delete every `enabled` field: public toggle operations, system support masks and project choices have distinct meanings. Preserve global-off retaining per-operation choices.

**Exact tests:** `tests/unit/configuration/test_provider_config.py:652::test_legacy_enabled_decodes_into_all_bits`, `:661::test_legacy_env_entry_migrates_to_enable_mask` and `:674::test_legacy_env_mixed_with_mask_is_rejected` become replacement candidates when that old input contract is retired. Replace with obsolete-record rejection and canonical round trips. Keep global/search/fetch toggle tests, strict mask validation, mixed-input safety and env precedence. D1's database-reset rule does not prove no config caller remains.

**Acceptance:** A2.3/.7, A4.4 and historical access semantics. No decoder test should disappear before the new contract has coverage.

## SUP-06 — P2 candidate: audit rollout callers before removing branches

**Evidence:** `configuration/config.py:204` defaults preview; `models/projects.py:45–50` defines preview/strict/fair. Project/settings/credential services expose rollout metadata, and `cli/users.py:245` passes it to `ProjectService`. All D1 tables existing does not establish these surfaces unused.

**Action:** separate release/availability metadata from execution policy. Delete alternate pre-project dispatch/authority paths after mandatory scoped execution takes over. Do not retain preview as an anonymous bypass or silently remove still-consumed API fields. Loans are controlled by persisted per-allocation policy, not global permission to borrow.

**Preserve/verify:** A1.6, A2.7, A3.3 and delivery gates in doc-000003/doc-000005. Prove fail-closed execution independently of the rollout label. This is conditional cleanup, not a claim the entire enum is dead.

## SUP-07 — P1: migrate shared auth fixtures instead of deleting failing suites

**Evidence:** `tests/fixtures/auth.py:57–74::create_temp_user` and `:173–183::promote_account` call `UserDatabase.set_role`; `:77–87::temp_principal` constructs legacy `UserPrincipal` with role/superuser properties. Monitoring/control/limits integration callers still request `UserRole.DEVELOPER`; persistence rejects it. PF/D1 record these fixture failures.

**Action:** A1 owns canonical ordinary-human, scoped-assignment, session, membership and API-key fixtures. Reuse `tests/fixtures/execution.py` and fresh-alpha safety helpers. Keep explicit fake-principal unit seams when isolating authentication. Avoid a fixture-builder DSL and assigning every former developer system-admin privilege.

**Preserve/verify:** A1.1/.2/.5/.6/.7; per-test signing secrets/restoration, temporary databases, no live keys and negative scope/security assertions. Rewrite the global-role matrix into scoped role/principal matrices. A fixture repair preserves intent; it does not establish redundancy. Run the affected integration/BDD paths, then the complete backend gate at API-step completion.

## SUP-08 — P2 support issue: align backend containers with ports and authority topology

**Evidence:** `compose.yaml:33` publishes `${API_PORT:-8001}:8001`, `:72` publishes `${MCP_PORT:-8000}:8000`; `.env.example:60–62` documents `FREESEARCH_API_PORT`/`FREESEARCH_MCP_PORT`. Docker CMD and Compose MCP commands bind fixed internal ports. Base/dev healthchecks call `/stats?limit=1` without credentials; `/stats` is protected data rather than a dedicated readiness contract.

**Action:** distinguish host publication from internal listening. Define one convention and verify custom worktree host ports, actual listening targets and healthchecks together. Simply removing `--port` without supplying process ports/updating mappings can break the stack. Avoid another chain of legacy aliases. Fixed internal ports alone do not prove host collision.

For A3, configure MCP forwarding to the API-hosted authority. Independent API/MCP runtimes sharing SQLite do not provide fair queue order. Use a lightweight readiness contract exposing no project content; do not embed a privileged bearer in a healthcheck command.

**Preserve/verify:** A3.1/.6, PF deployment measurement and worktree safety. Retain data/master-key volume semantics, development bind mounts and frozen dependency installation. Do not merge Dockerfiles solely for similar setup lines. Validate with a temporary canary environment or no env-resolution; never print a Compose rendering of live `.env`. No container execution/build check was performed in this audit.

## SUP-09 — P2: remove contradictory current operator guidance

**Evidence:** `README.md:97` recommends obsolete `set-role --role developer`; `:253` says ports come from local environment while container commands override them. `PROVIDER_API.md:49–56` describes anonymous downstream execution and excludes project API keys, superseded by A1/A2. `docs/releases/local-users.md` records the former roles/migrations. `.env.example` omits primary/retired encryption-key settings exposed by `configuration/config.py:94–97`.

**Action:** update current onboarding/auth/CLI examples with the owning card. Label historical release notes and link the new baseline rather than erasing history. Preserve provider-native option/response documentation despite its stale auth paragraph. Document safe key-file/rekey configuration without sample secrets. Use Backlog CLI for managed-doc changes.

**Preserve/verify:** baseline reset instructions, no import/migration promise, process-only stdio credential input and explicit live-test selection. Check examples against command help and temporary-database tests; update historical doc assertions to the supported contract rather than delete them.

## Coverage and evidence limits

Inspected: backend CLIs/configuration, relevant composition roots, fixture seams, Windows worktree scripts, Docker/Compose backend setup, `.env.example` and historical/current project specs. No additional script simplification was established beyond existing port/data isolation; no Windows-script rewrite is recommended. UI, cloud workflows and POSIX tooling are outside scope; their absence is not an A-series defect.

Gemini ran no support runtime suite. The orchestrator checked references/handlers/properties/configuration and corrected the initial findings. The main audit separately records static checks and fake-only adapter tests. Follow-up validations above are recommendations, not passing results. Locations refer to the audited commit.
