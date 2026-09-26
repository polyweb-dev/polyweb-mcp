# Implementation Plan: Encrypted-DB Secrets Storage ("Auth migration for all keys")

## 1) Objective

Replace the OS-keyring (`KeyringSecretStore`) write path with an **encrypted-DB write path** so that all 7 provider API keys (exa, firecrawl, tavily, parallel, you, brave, keenable) and the 4 Parallel OAuth token slots (access / refresh / device / client_secret) submitted via `PUT /api/v1/providers/{id}/secret` (and produced by the OAuth device flow) are **AES-256 encrypted before touching SQLite**; only ciphertext envelopes touch the DB. Decryption happens in memory at adapter-construction time into `SecretStr`, never logged or persisted. Master key comes from `FREESEARCH_ENCRYPTION_KEY` (passphrase through a KDF) or an auto-generated 256-bit key saved to a local-dev key file with `0600` perms. `KeyringSecretStore` stays only as a **legacy read fallback** for migration. API behavior (fingerprint-only responses) is unchanged. **Docker/volumes/`/data` mounts are out of scope** — all paths are local-dev.

## 2) Target files + function/class signatures

### 2a) New module — master key + codec (new file, preferred location)

- **NEW** `src/freesearch/infrastructure/secret_crypto.py` (name negotiable; must live under `infrastructure/` per backend-code-structure boundaries):
  - `MASTER_KEY_ENV_VAR: str = "FREESEARCH_ENCRYPTION_KEY"`
  - `DEFAULT_KEY_FILE: Path` — local-dev default (e.g. alongside the resolved SQLite path or under the app data dir; **not** `/data/.secret_key`, which is the Docker-scoped path from `docs/bugs.md` — pick the existing `resolve_database_path()` sibling, e.g. `<db-dir>/.secret_key`).
  - `@dataclass(frozen=True) class MasterKey: key: bytes  # exactly 32 bytes; __repr__ redacted`
  - `def load_or_create_master_key(*, key_file: Path | None = None, passphrase_env: str | None = None) -> MasterKey`
    - If `FREESEARCH_ENCRYPTION_KEY` set → treat as **passphrase**, derive 32 bytes via KDF (see Contracts). Never use the raw string as AES bytes.
    - Else if key file exists → load 32-byte key (validate length; fail closed on corrupt).
    - Else → `secrets.token_bytes(32)`, atomic-write to key file (`0600`, parent `0700`, `fsync`), return it.
  - `def _derive_key_from_passphrase(passphrase: str, salt: bytes, *, iterations: int = ...) -> bytes` — PBKDF2-HMAC-SHA256 via `hashlib` (stdlib, no new dep) with stored per-installation salt (`secrets.token_bytes(16)`, persisted `0600` next to key file, e.g. `.secret_salt`). (Argon2/scrypt acceptable only if a dep already covers it — it does not; PBKDF2 is the simplest stdlib KDF. Document parameters as constants.)
  - `class SecretCodec:` (or plain `encrypt_value/decrypt_value` functions)
    - `def __init__(self, master: MasterKey) -> None`
    - `def encrypt(self, plaintext: str) -> str  # base64/json envelope, never the plaintext`
    - `def decrypt(self, envelope: str) -> SecretStr  # raises SecretDecryptError on wrong key/corrupt`
    - `class SecretDecryptError(Exception)` — message must not include key material or plaintext.
  - Crypto primitive: **AES-256-GCM** via `cryptography` (`AESGCM`, 12-byte random nonce from `secrets`). Envelope (JSON, versioned): `{"v":1,"alg":"AES-256-GCM","nonce":b64,"ct":b64}` (plus `kdf` metadata only if per-row salt is chosen — preferred design uses a single installation salt file, so envelope stays minimal).
  - `__repr__`/logging: no key material; `MasterKey.__repr__` returns `MasterKey(***)`.
- **Why a new module**: keeps crypto, file-permission, and atomic-write logic out of `secrets.py` (protocol/resolver) and out of the persistence layer; unit-testable without a DB.

### 2b) Encrypted store (new file or inside `secrets.py` — prefer new file)

- **NEW** `src/freesearch/infrastructure/encrypted_store.py` (or extend `src/freesearch/infrastructure/secrets.py` L1–147 if the team prefers one secrets module):
  - `ENCRYPTED_SECRET_PREFIX: str = "secret.enc:"` — storage keys in `runtime_settings`, e.g. `secret.enc:exa`, `secret.enc:parallel:oauth:access`. Reuses the existing `runtime_settings` table → **no Alembic migration needed**.
  - `class EncryptedDbSecretStore:` — async (see the sync/async decision in §5 Risks):
    - `def __init__(self, repository: SQLiteRepository, codec: SecretCodec) -> None`
    - `async def get(self, name: str) -> str | None  # decrypt in memory; None on missing/undecryptable (log redacted warning, fail to None — never raise key material)`
    - `async def set(self, name: str, value: str) -> None  # encrypt then set_runtime_setting; reject empty`
    - `async def delete(self, name: str) -> None  # idempotent`
  - Keep `SecretStore` Protocol (`src/freesearch/infrastructure/secrets.py` L44–54), `KeyringSecretStore` (L57–71), `MemorySecretStore` (L74–92) untouched; `KeyringSecretStore` becomes legacy-read-only in practice (code need not enforce read-only; call sites just stop calling its `set`).

### 2c) Modify — resolver precedence

- `src/freesearch/infrastructure/secrets.py`:
  - `ProviderSecretResolver.__init__` (L104–111): accept optional encrypted store alongside the legacy store, e.g. `def __init__(self, store: SecretStore | None = None, environ: dict | None = None, *, encrypted_store: <async store> | None = None, ...)`. Exact shape depends on the sync/async decision — plan must resolve this before coding (see §5). Minimal alternative: resolver keeps sync `SecretStore` for keyring fallback and gains an async `aget()` that checks the encrypted DB first.
  - `ProviderSecretResolver.get` (L113–135): new precedence **env → `.env` → encrypted-DB → keyring(legacy fallback) → None**. `.env`-only-when-bound-to-process-env rule (L98–111) is preserved.
  - `ProviderSecretResolver.set/delete` (L137–147): write path goes to the **encrypted store**; `delete` clears encrypted row **and** legacy keyring entry (best-effort `suppress(Exception)`).
  - `PROVIDER_ENV_VARS` (L33–41): unchanged — still the 7 canonical `FREESEARCH_*` names.

### 2d) Modify — control plane

- `src/freesearch/routers/control.py`:
  - `SecretSource` (L66): extend literal with the new source, e.g. `Literal["environment","dotenv","encrypted_db","keyring","none"]`. `"keyring"` remains only as a legacy-read label; new writes report `"encrypted_db"`.
  - `put_secret` (L166–192): `store.set` → encrypted-store write; keep write-only semantics, then re-resolve and return fingerprint-only `SecretStatusResponse`. Never echo the key.
  - `delete_secret` (L194–216): delete from encrypted store (+ legacy keyring best-effort).
  - `_resolve_secret` (L419–440): mirror the resolver's new precedence; add an async variant or make it async (it currently does sync `store.get` via `_store_get` L411–416). Callers `_provider_entry` (L739–758) and `_ensure_provider_adapter` (L792–824) become async-aware accordingly (they are already `async`, so awaiting is natural).
  - `secret_fingerprint` (L403–408), `persist_secret_record` (L623–635), `_secret_presence` (L443–450): **unchanged** — fingerprint-only persistence (`secret.{provider}` keys) stays; no raw keys in `runtime_settings` beyond ciphertext envelopes under the new `secret.enc:*` keys.
  - `_provider_entry` secret-presence reporting and `test_provider` error path (`redact_secrets`, L131–140): unchanged behavior; verify no ciphertext/plaintext leaks into `detail`.

### 2e) Modify — OAuth token storage

- `src/freesearch/services/parallel_oauth.py`:
  - Secret slot constants (L125–129) unchanged: `ACCESS_SECRET_KEY="parallel:oauth:access"`, `REFRESH_SECRET_KEY`, `DEVICE_SECRET_KEY`, `CLIENT_SECRET_KEY`; metadata key `METADATA_RUNTIME_KEY="oauth.parallel"` stays plaintext metadata-only (T2: assert no token material in it).
  - `_resolve_secret_store` (L511–517): resolve to the **encrypted store** in production; `_test_secret_store` seam and `MemorySecretStore` test doubles stay.
  - `_store_get_secret` / `_store_set_secret` (L534–544), `_clear_vault`, `_persist_token_grant`, `_refresh_grant`, `_valid_access_token`, `start_device_flow`, `query_oauth_status`, `disconnect_oauth`, `_poll_device_once`, `_fetch_and_record_oauth_balance`: all flow through the store interface — if the store becomes async, these `async` functions `await` it (they are already `async` except the two tiny sync helpers, which become async or move behind an async wrapper). `revoke_token`/`refresh_access_token`/`get_balance` (`SecretStr` in-memory use, `.get_secret_value()` only at the HTTP boundary) are unchanged.
  - Threat-model doc line "Bearer tokens live ONLY in SecretStore (OS keyring)" (`docs/THREAT_MODEL.md` L15) must be updated to "(encrypted-DB SecretStore)" — docs edit, include in slice.

### 2f) Modify — configuration & composition root

- `src/freesearch/configuration/config.py` (`Settings`, L10–32):
  - Add `encryption_key: SecretStr | None = None` (auto-reads `FREESEARCH_ENCRYPTION_KEY` via the `FREESEARCH_` prefix; `hide_input_in_errors=True`, never in repr/logs) and `encryption_key_file: Path` (local-dev default; explicit field so tests can point at `tmp_path`).
  - Note: passphrase-vs-raw decision lives in `secret_crypto.py`, **not** in Settings — Settings only carries the env string.
- `src/freesearch/configuration/provider_config.py` `get_provider_secret_resolver` (L238–247): bind the resolver to the encrypted store (codec built from `load_or_create_master_key`) with keyring as fallback; keep `lru_cache` + `cache_clear` test seam.
- `src/freesearch/routers/api.py` `create_app` (L60–114, secret-store wiring L112): default `app.state.secret_store` becomes the encrypted store (built from repository + codec); injected `secret_store` remains the offline test seam. Startup (`lifespan`, L86–106) runs the one-shot legacy migration after the repository is available.
- `src/freesearch/persistence/storage.py`: **no schema change** (reuse `RuntimeSettingRow`, L150–157, via `get_runtime_setting`/`set_runtime_setting`, L493–511). Only constraint to respect: values must be JSON-serializable (envelope is a string — fine) and the `_FORBIDDEN_METADATA_KEYS` guard (L41–81) applies to usage/quota metadata, not `runtime_settings` — confirm no secret-bearing payload ever flows into `_metadata_json`.

### 2g) Dependencies, docs, tests layout

- `pyproject.toml` (L7–21): add direct dependency `cryptography` (already present transitively in `uv.lock` via `secretstorage`; pin a compatible range, e.g. `cryptography>=44,<51`, and re-lock). No other new deps (KDF = stdlib `hashlib.pbkdf2_hmac`; randomness = stdlib `secrets`). If the team instead chooses AES-256-GCM-by-hand over `cryptography`, justify; do not add `pycryptodome`/`passlib`/`argon2-cffi`.
- `docs/THREAT_MODEL.md` (T1/T2 table, L17–22 + L15 bearer sentence): update store reference; add rows for master-key-file perms and wrong-key-fails-closed if the Tester wants them.
- Tests (Tester-owned, Planner only lists seams):
  - `tests/unit/infrastructure/test_secrets.py` (extend: resolver precedence incl. legacy fallback), **NEW** `tests/unit/infrastructure/test_secret_crypto.py` (KDF, codec round-trip, wrong-key, envelope versioning, perms/atomicity with `tmp_path`).
  - `tests/integration/routers/test_control_api.py` (extend: PUT/DELETE round-trip, ciphertext-only rows, fingerprint-only responses), **NEW** migration integration test (legacy keyring/env/`.env` → encrypted rows).
  - OAuth leakage/lifecycle suites (`tests/integration/services/oauth/`, `adv_oauth_security.feature`): extend T1/T2 scans to the encrypted store (ciphertext scans must not false-positive on envelopes — assert decryptability + absence of plaintext substring).

## 3) Contracts

1. **Master-key loading** (`load_or_create_master_key`):
   - `FREESEARCH_ENCRYPTION_KEY` set (any non-empty string) → **passphrase mode**: `key = PBKDF2-HMAC-SHA256(passphrase_utf8, salt, iterations≈200k–600k, dklen=32)`; `salt` = 16 random bytes persisted once in a `0600` salt file beside the key file (created atomically if absent). Raw env string is never an AES key, never logged, never persisted.
   - Env unset → **auto-generate mode**: `key = secrets.token_bytes(32)`; if key file exists, load and validate (exactly 32 bytes after base64/raw decode — one encoding, documented); else atomic-write new key (`0600` file, `0700` parent, tmp-file + `os.replace` + `fsync`), return it.
   - Corrupt key/salt file → fail closed with redacted error (no material in message); never silently regenerate over an existing file (that would orphan all ciphertext — require explicit rotation instead).
2. **Encrypt/decrypt** (`SecretCodec`): `encrypt(plaintext) -> envelope_str` with fresh 96-bit nonce per call (AES-256-GCM, 32-byte key); `decrypt(envelope) -> SecretStr`; unknown `v`/truncated/corrupt input → `SecretDecryptError` (redacted); wrong master key → `SecretDecryptError`, never plaintext, never partial plaintext. Ciphertext is non-deterministic (same input → different envelope).
3. **Resolver precedence (after migration)**: process env → `.env` (only when bound to real process env, existing rule) → **encrypted-DB** → **keyring legacy fallback (read-only)** → `None`. `SecretSource` gains `"encrypted_db"`; `"keyring"` may still appear when the legacy fallback served the read (transitional).
4. **API behavior unchanged**: `PUT/DELETE /api/v1/providers/{id}/secret` request/response shapes identical (`SecretStatusResponse` with `presence`, masked `fingerprint`, `updated_at`, `source`); `GET` surfaces never include key material or ciphertext; `persist_secret_record` still stores only `{fingerprint, updated_at}` under `secret.{provider}`; adapter construction decrypts to `SecretStr` in memory and passes `.get_secret_value()` only to the vendor SDK/HTTP boundary; `redact_secrets` coverage on all error paths preserved.
5. **OAuth parity**: the 4 `parallel:oauth:*` slots use the same codec/store as provider keys; `OAuthMetadata` in `runtime_settings` under `oauth.parallel` remains non-secret; T3–T17 behaviors (revoke-before-delete, idempotent disconnect, single-flight refresh, terminal denied/expired, Decimal-exact balance) are untouched.

## 4) Migration strategy

1. **No schema migration**: ciphertext envelopes are strings stored via existing `set_runtime_setting` under new keys `secret.enc:<store-name>` (provider slots: `secret.enc:exa|firecrawl|tavily|parallel|you|brave|keenable`; OAuth slots: `secret.enc:parallel:oauth:access|refresh|device|client_secret`). No Alembic revision; no table changes; backups contain only ciphertext for these keys (verify: backup/restore tests must scan for plaintext sentinels, not just live rows).
2. **One-shot, idempotent import** — NEW `async def migrate_legacy_secrets_to_encrypted_db(*, repository, encrypted_store, legacy_store, environ_snapshot) -> MigrationReport` (place beside the store or in `secret_crypto.py`; called once from `create_app.lifespan` after the repo opens, and safe to re-run):
   - For each of the 7 provider slots: read legacy value in old precedence order (process env → `.env` single-var lookup → keyring `provider.value`); for each of the 4 OAuth slots: read keyring only (they were never env/`.env` keys).
   - If the encrypted row already exists → **skip** (never overwrite operator data); else if a legacy value exists → `encrypted.set(slot, value)`, count as migrated.
   - Do **not** delete keyring entries or `.env` lines in this slice (fallback reads keep old installs working; destructive cleanup is a documented follow-up). Report counts `{migrated, skipped_existing, absent}` for logs (slot names only, never values).
   - Concurrent-startup safe: `set_runtime_setting` is upsert-based; double-migration converges (second run sees existing rows and skips).
3. **Env/`.env` stay read-priority overrides** post-migration (they shadow the DB by design, surfaced via `source`). Operators consolidate by removing env/`.env` keys after verifying the encrypted rows — document, don't automate.
4. **Rotation story**: master-key change (new passphrase or deleted key file) makes existing envelopes undecryptable → reads degrade to legacy/env/None (fail-closed, redacted warning). Full re-encrypt-on-rotation (`old codec decrypt-all → new codec encrypt-all`) is the designed follow-up; this slice must at minimum (a) never auto-regenerate over an existing key file, (b) document the rotation procedure, and (c) expose decrypt-failure observably (log + `source`/`presence` reflects missing). If cheap, ship `freesearch-db reencrypt --old-key-file ...` as part of the slice — Planner leaves the call to the orchestrator, but tests must pin whichever is chosen.

## 5) Security notes (must-haves, not nice-to-haves)

- **KDF mandatory**: raw `FREESEARCH_ENCRYPTION_KEY` string → UTF-8 → PBKDF2-HMAC-SHA256 with stored 16-byte salt, ≥200k iterations, `dklen=32`. Never `key.encode().ljust(32)` or raw-bytes-as-key.
- **Randomness**: auto-generated keys, salts, and GCM nonces from stdlib `secrets` only (`token_bytes`); never `random`/`uuid4`/`time`-seeded.
- **Filesystem**: key file `0o600`, parent dir `0o700` (create with `mkdir(mode=0o700, exist_ok=True)` + `os.chmod` hardening against pre-existing lax perms and umask); atomic write (tmp file in same dir + `flush`/`os.fsync` + `os.replace` + dir `fsync`); salt file same treatment. Key file path configurable via Settings for tests (`tmp_path` isolation); production local-dev default = sibling of the SQLite file.
- **No-leak invariants** (extend T1/T2 to the new surface): no key material, passphrase, plaintext provider keys, OAuth tokens, nonces-as-secrets, or full envelopes in logs / exceptions / `repr`s / Pydantic model dumps / API responses / fixtures / backups / config dumps; `SecretStr` hygiene everywhere (`get_secret_value()` only at SDK/HTTP call boundary); `hide_input_in_errors=True` on any model carrying secrets; `redact_secrets` on all new error paths.
- **Key-file backup coupling**: document that DB backups are useless without the key file and the key file is useless without… nothing — it is the crown jewel: back it up separately, `0600`, never commit, never print. `.gitignore` check for `*.secret_key`/`.secret_salt` patterns.
- **BIGGEST DESIGN RISK — sync/async mismatch**: `SecretStore` is a **sync** Protocol (`get/set/delete` returning `str`), but the encrypted store's backend (`SQLiteRepository`) is **async**. The Developer must pick one before coding: (a) introduce an `AsyncSecretStore` protocol + async encrypted store and `await` it at the (already-async) call sites (`control.py`, `parallel_oauth.py`, resolver `aget`), keeping a sync `MemorySecretStore` for unit seams; or (b) give the encrypted store its own short-lived sync SQLite connection (separate from the async engine — WAL/concurrent-access hazards, **not recommended**). Planner recommends (a). Whichever is chosen, `parallel_oauth._test_secret_store` / `MemorySecretStore` doubles must still satisfy the seams the adversarial suites rely on.
- **mypy strict + ruff 100-col**: all new crypto/store code fully typed (`bytes` vs `str` vs `SecretStr` boundaries explicit; envelope base64 helpers typed); no `Any` leaks; complexity ≤15.
- **Non-goals restated**: no KMS/vault/OS-keyring new work, no Docker/compose/volume code, no new network calls, no response-shape changes.

## 6) Acceptance criteria

- **AC-1 (passphrase mode)**: with `FREESEARCH_ENCRYPTION_KEY=<passphrase>` set and no key file, `PUT /api/v1/providers/exa/secret` then adapter construction succeeds; raw env string is not usable as the AES key (code inspection + unit test asserting KDF is applied, e.g. derived key ≠ `sha256(passphrase)`/padded raw bytes); no key file containing key material is required in this mode (only the non-secret salt file may exist).
- **AC-2 (auto-generate mode)**: with the env var unset and no key file, first startup creates the key file as 32 random bytes with mode `0600` (parent `0700`), via atomic write + `fsync`; second startup reuses it (file mtime/content unchanged); permissions hold regardless of umask.
- **AC-3 (ciphertext-only at rest)**: after storing all 7 provider keys + completing an OAuth pairing (stubbed vendor), every `secret.enc:*` row in `runtime_settings` decrypts to the original under the correct master key, and a DB-wide scan finds **zero** plaintext key/token substrings (sentinel-based test); `secret.{provider}` rows hold only `{fingerprint, updated_at}`; `oauth.parallel` metadata holds no token material.
- **AC-4 (wrong key cannot decrypt)**: re-loading the codec with a different passphrase (or swapped key file) makes `decrypt` raise redacted `SecretDecryptError` for existing rows; API reads degrade to legacy/env/None (no crash, no leak, 503-with-hint adapter path preserved).
- **AC-5 (no-plaintext-leak)**: sentinel-key sweep across logs (`caplog`), all API response bodies for the secret/OAuth routes, raised error messages, and `runtime_settings`/quota/usage rows finds no sentinel substring (extends T1/T2 to the encrypted path); envelopes themselves are opaque (same plaintext stored twice → different ciphertext).
- **AC-6 (migration)**: given pre-existing keyring entries and/or env/`.env` provider keys and keyring OAuth tokens with an empty encrypted store, one startup migrates all present values into `secret.enc:*` rows (idempotent re-runs migrate nothing new and overwrite nothing); post-migration reads resolve identically; keyring entries are left intact (fallback) in this slice.
- **AC-7 (OAuth covered)**: device-flow → poll → refresh → disconnect lifecycle (stubbed transport) stores bearer/refresh/device/client_secret only as ciphertext, serves status fingerprint-only, revokes before deleting on disconnect, and stays idempotent — existing T3/T4 suites green against the encrypted store.
- **AC-8 (API compatibility)**: `PUT/GET/DELETE` secret routes keep exact response contracts (`presence` incl. `KEYLESS_PUBLIC` for keenable, masked `fingerprint` format `XXX_••••••••hash4`, `source` with new `encrypted_db` value); unknown providers still 404; full existing control + adv-oauth BDD suites green.
- **AC-9 (rotation documented or implemented)**: either a working re-encrypt procedure (command + test) or an explicit follow-up doc section describing manual rotation (export via old key → set new key → re-PUT secrets), plus a test pinning fail-closed behavior on key change. No silent key regeneration, ever.

## 7) Suggested build/test order

Batch work; run the suites only after significant chunks, not per-edit.

1. **Chunk 1 — crypto core**: add `cryptography` to `pyproject.toml` + re-lock; create `secret_crypto.py` (KDF, codec, key-file load/create with perms + atomic write); Settings fields (`encryption_key`, `encryption_key_file`). Tests after: NEW `test_secret_crypto.py` unit suite (round-trip, non-determinism, wrong-key, corrupt envelope, KDF-vs-raw assertion, perms/umask, existing-file-never-overwritten). Run: `pytest tests/unit/infrastructure/test_secret_crypto.py` + `ruff` + `mypy`.
2. **Chunk 2 — encrypted store + migration**: create `EncryptedDbSecretStore` on `runtime_settings` (`secret.enc:*` keys) + `migrate_legacy_secrets_to_encrypted_db`; wire composition root (`create_app` default store + `lifespan` migration hook) and `get_provider_secret_resolver`. Resolve the sync/async protocol decision first — it touches every call site. Tests after: store unit/integration tests (ciphertext-only rows, idempotent migration from keyring/env/`.env` doubles, skip-existing) + resolver precedence tests. Run: `pytest tests/unit/infrastructure tests/integration/routers/test_control_api.py tests/integration/routers/test_runtime_settings.py`.
3. **Chunk 3 — control plane + adapters + OAuth cutover**: migrate `control.py` (`put/delete/_resolve_secret` + `SecretSource`), `parallel_oauth.py` store resolution, adapter path (no adapter code changes expected — they consume the resolver/`SecretStr`). Update the `THREAT_MODEL.md` bearer sentence. Tests after: FULL target suites — `pytest tests/unit tests/integration` + `behave tests/bdd/features/control.feature adv_oauth_* parallel_oauth` + sentinel no-leak sweeps (AC-3/AC-5/AC-7) + AC-4 wrong-key + AC-9 rotation pin. Finish with `ruff check`, `ruff format --check` (if configured), `mypy` strict clean.

## 8) Next Phase: Granular Observability & Tracing Integration (OpenTelemetry / Phoenix / Langfuse / LangSmith)

### 8a) Objective & Rationale

- **Outsource granular monitoring to dedicated observability platforms**: Instead of spending engineering cycles building a complex internal query inspector, payload debugger, trace waterfall viewer, and retrieval evaluation dashboard, FreeSearch will integrate with external LLM observability tools (**Arize Phoenix**, **Langfuse**, **LangSmith**, **Helicone**).
- **Universal OpenTelemetry (OTel) / OpenInference foundation**: FreeSearch will emit standard OTel spans using OpenInference semantic conventions (`RETRIEVER` and `TOOL` span kinds) over standard OTLP (OpenTelemetry Protocol). This single integration enables zero-code-change support across Arize Phoenix (local or cloud), Langfuse OTLP ingest, LangSmith OTLP ingest, and standard APMs (Datadog, New Relic) without vendor-specific SDK lock-in.
- **Architectural separation of concerns**:
  - *Internal control loop (FreeSearch core)*: Lightweight SQLite/in-memory ledger remains responsible for synchronous routing decisions, real-time quota/rate-limit cutoffs, circuit breaking (429 backoff), and local health status.
  - *External observability (Phoenix / Langfuse)*: Receives detailed traces, latency waterfalls (DNS/routing/provider HTTP/fusion), error bodies, and retrieval outputs for developer inspection and search quality evals.
- **Privacy & payload controls**: In keeping with FreeSearch's privacy commitments, query text, URLs, and scraped Markdown content will only be captured when explicitly enabled via configuration (`FREESEARCH_TRACE_RECORD_PAYLOADS=true`). When disabled (the default), traces capture only operational metadata (provider, latency, status, counts, costs).

### 8b) Target Files & Signatures

- **NEW `src/freesearch/infrastructure/observability.py`**:
  - `init_tracer(settings: Settings) -> Tracer`: Configures OpenTelemetry `TracerProvider`, resource attributes (`service.name="freesearch"`), batch/simple span processor, and `OTLPSpanExporter` if endpoint is configured.
  - `class TracingContext`: Helper context manager / decorator to create `RETRIEVER` and `TOOL` spans adhering to OpenInference semantic conventions.
  - `def extract_parent_context(headers: Mapping[str, str]) -> Context`: Extracts incoming W3C `traceparent` or custom trace headers for distributed tracing.
- **Modify `src/freesearch/configuration/config.py`**:
  - Add fields to `Settings`:
    - `otel_enabled: bool = False` (or auto-enabled when `OTEL_EXPORTER_OTLP_ENDPOINT` is present)
    - `otel_exporter_otlp_endpoint: str | None = None` (e.g., `http://localhost:6006/v1/traces` for local Phoenix)
    - `otel_exporter_otlp_headers: str | None = None` (for Langfuse / LangSmith API authentication)
    - `trace_record_payloads: bool = False` (privacy toggle: record query text & fetched markdown vs metadata-only)
- **Modify `src/freesearch/routers/api.py` & `src/freesearch/mcp/server.py`**:
  - Extract incoming trace context (`traceparent`) in FastAPI middleware / request handlers so search spans nest directly inside caller agent traces (LangChain, LlamaIndex, Claude Desktop, Cursor).
  - Wrap `_dispatch` and `_dispatch_fanout_search`:
    - Root span: `freesearch.search` / `freesearch.fetch`
    - Child spans: `freesearch.adapter.<provider>` per candidate call (capturing provider-specific latency, HTTP status, and raw error messages upon failure).
    - Fusion span: `freesearch.reciprocal_rank_fusion` (capturing scoring and participating provider count).

### 8c) Contracts & OpenInference Mapping

- **Span Kind**: `RETRIEVER` for `search` operations, `TOOL` for `fetch` operations.
- **Span Attributes**:
  - `openinference.span.kind`: `"RETRIEVER"` | `"TOOL"`
  - `input.value`: `request.query` or `request.url` (if `trace_record_payloads=True`, else redacted string `[REDACTED]`)
  - `output.value`: Top search result URLs/snippets or document markdown (if `trace_record_payloads=True`, else result count)
  - `provider.name`: Adapter name (`exa`, `brave`, `firecrawl`, etc.)
  - `routing.mode`: `single` | `fanout` | `chained`
  - `search.result_count`: `len(response.results)`
  - `usage.units`: `response.usage.units` (if present)
  - `usage.unit_kind`: `response.usage.unit_kind`
- **Error Spans**: When a provider returns 429/500 or times out, the child span records exception details, error status, and HTTP payload (with secrets redacted via `redact_secrets`), while the root span marks fallback progression.

### 8d) Acceptance Criteria for Observability Phase

- **AC-O1 (OTel Exporter)**: When `OTEL_EXPORTER_OTLP_ENDPOINT` is configured, executing a search or fetch request emits an OTLP trace batch containing the operation span and adapter child spans without failing the user request if the exporter is unreachable.
- **AC-O2 (OpenInference Compliance)**: Emitted spans parse successfully into Arize Phoenix and Langfuse as `RETRIEVER` and `TOOL` entities with correct latency waterfalls and result counts.
- **AC-O3 (Payload Privacy Guard)**: With `FREESEARCH_TRACE_RECORD_PAYLOADS=false` (default), emitted spans contain zero query text or document content; with `true`, query text and snippets are captured. Secrets (API keys, OAuth tokens) are never emitted in span attributes or event logs under any configuration.
- **AC-O4 (Distributed Trace Propagation)**: Supplying a valid W3C `traceparent` header links the FreeSearch span as a child of the external caller's trace ID.

## 9) Risks & open questions for the orchestrator

- **R1 (blocking design choice)**: sync `SecretStore` Protocol vs async `SQLiteRepository` backend — Developer must adopt the async-store option (§5) or propose an equivalent; estimate hinges on it.
- **R2**: `cryptography` is currently only a transitive dep (via `secretstorage`); adding it direct is low-risk but requires a lockfile refresh and a floor version supporting `AESGCM` (any modern release does).
- **R3**: local-dev key-file default path is undecided (recommending sibling-of-DB via `resolve_database_path()`); confirm it doesn't collide with backup globs or the BDD scenario working dirs (`freesearch-control-cwd-*`, ruff-excluded).
- **Q1**: rotation scope for this slice — ship a `reencrypt` CLI (recommend only if cheap) or document-as-follow-up (AC-9 allows either; needs a ruling before Chunk 3).
- **Q2**: may the migration clean up (delete) legacy keyring entries after verified import, or must they persist indefinitely as fallback? Plan assumes persist (safe default).
- **Q3**: per-installation salt file vs per-row envelope salt — plan assumes one salt file (simpler rotation story); confirm acceptable.
- **Q4**: PBKDF2 iteration count vs startup latency on low-end hosts — plan assumes 200k–600k HMAC-SHA256 (≈100–300 ms once, cached in memory); confirm no caching objection (key lives in process memory by necessity).
