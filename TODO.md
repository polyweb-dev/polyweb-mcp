# Stage 2: Usage/Data

## Goal

Implement the provider-neutral, async SQLite persistence layer required by
stage 2 of `WORKPLAN.md`. It stores usage events, quota snapshots, provider
health observations, and cache metadata. It does not implement providers,
routing, MCP tools, retries, cached response bodies, or application wiring.

## Coordination Required First

The developer must request these changes from their owners before depending on
them. Do not edit the owned files in this worktree.

- Foundation/integration: add and lock `aiosqlite` and SQLAlchemy async ORM
  support in `pyproject.toml` and `uv.lock`.
- Contracts owner: add a provider-neutral `CacheMetadata` model. It needs an
  opaque cache key, provider, operation, creation/expiry/access timestamps,
  hit count, and optional size in bytes. It must never contain a response body
  or a secret.

`pyproject.toml`, `uv.lock`, shared models, and the application composition
root are owned by foundation/integration. The usage/data worktree must not
modify them. It must not import provider SDKs or vendor modules.

## Developer Agent

### Implementation

1. Add `src/freesearch/storage.py` with one concrete `SQLiteRepository` and
   typed SQLAlchemy ORM row models. Avoid protocols, factories, and separate
   repository classes until a second implementation or a real consumer requires
   them.
2. Give the repository an async open/close lifecycle around a SQLAlchemy async
   engine using `aiosqlite` as the SQLite driver. Schema initialization must be
   safe to call repeatedly and repair declared indexes.
3. Create four tables.
   - `usage_events`: append-only records for `UsageEvent`.
   - `quota_snapshots`: append-only records for `QuotaSnapshot`.
   - `provider_health`: append-only records for `ProviderHealth`.
   - `cache_metadata`: upserted records for `CacheMetadata` only.
4. Use text columns for `Decimal` values and ISO-8601 text for timestamps so
   contract values round-trip without precision loss. JSON-encode only the
   `UsageEvent.metadata` mapping. Do not log model data or SQL parameters.
5. Add indexes only for the required reads: provider/time for usage, quota,
   and health; expiry for cache metadata.
6. Provide the smallest async public API required by later stage-2 worktrees.
   - Append and list usage events, filterable by provider, operation, and time.
   - Append quota snapshots and read the latest one for a provider, optionally
     filtered by `QuotaSource`.
   - Append health observations and read the latest health state for a provider.
   - Upsert, read, touch, and remove expired cache metadata.
7. Preserve all model fields when reconstructing contract models. The quota
   repository must return the stored `QuotaSource` unchanged; routing decides
   how authoritative, observed, and estimated values are ranked.

### Scope Rules

- Accept an explicit database path or connection setup from the caller. Do not
  add a settings field or application factory wiring; configuration and
  integration own those seams.
- Keep usage and health histories. Do not add retention, aggregation,
  migration tooling, background jobs, payload caching, or cache eviction policy
  without a stated requirement.
- Do not persist credentials, response bodies, request queries, URLs, or other
  unnecessary data. Cache keys are opaque identifiers.
- Use parameterized SQL and transactions where a method changes more than one
  row. Ensure the connection is closed when repository use ends.
- Follow the existing strict typing and import style in `src/freesearch/`.

### Developer Quality Criteria

- The implementation uses typed SQLAlchemy async ORM models with `aiosqlite`,
  is fully async, and has no vendor imports or handwritten DDL/DML SQL.
- Schema initialization is idempotent and queries are parameterized.
- Decimals, timezone-aware timestamps, enums, nullable fields, and JSON
  metadata round-trip correctly.
- Usage, quota, and health writes are append-only; cache metadata upserts by
  its opaque key.
- Repository reads return existing contract models, including quota provenance.
- No secrets or response content can enter the schema or logs.
- The implementation adds only `src/freesearch/storage.py` and any essential
  package export; it does not alter another worktree's owned files.

## Tester Agent

### Test Work

1. Add `tests/test_storage.py`. Keep a local async fixture in that test file
   unless an existing shared fixture is genuinely reusable.
2. Use a `tmp_path` SQLite database and exercise the public repository API,
   never private tables as the primary assertion surface.
3. Cover these behaviors.
   - Initializing the same database twice succeeds.
   - A `UsageEvent` round-trips exactly, including `Decimal`, timestamp,
     `UsageOperation`, nullable `request_id`, and JSON metadata.
   - Usage listing respects provider, operation, and time filters.
   - Quota snapshots preserve `QuotaSource`, nullable remaining/limit/reset
     values, history, and latest-by-provider/source reads.
   - Health observations preserve status/message, history, and latest reads.
   - Cache metadata upserts by key, updates access/hit state, and expired rows
     are removed without affecting live rows.
   - Repository close is safe after normal use.
4. Use deterministic UTC datetimes and decimal strings with fractional values
   so precision regressions fail clearly.

### Tester Quality Criteria

- Tests are isolated: each test gets a temporary database and closes it.
- Tests are fully offline and never need a provider key, network connection,
  or vendor package.
- Assertions test contract-visible behavior and exact value preservation, not
  fragile SQL implementation details.
- Tests cover success paths, optional/null fields, ordering of latest records,
  and cache expiry boundaries.
- Tests stay small and direct; do not introduce new test frameworks, mocks, or
  shared abstractions without need.

## Shared Completion Gate

Both agents must leave the worktree passing these commands after the dependency
owner has integrated `aiosqlite`:

```powershell
uv lock --check
uv sync --locked
uv run ruff check .
uv run mypy src
uv run pytest
```

Update `PROGRESS.md` only after all checks pass and stage 2 usage/data is
actually complete. Record that routing policy, application wiring, provider
implementations, cache payload storage, and retention policy remain deferred.
