# FreeSearch Progress

Updated: 2026-09-06 (Stage 6 — frontend live-API integration)

## Scope completed

Stages 0, 1, 2, 3, 4, and **Stage 4.5 (read-only monitoring API)** from
[`WORKPLAN.md`](WORKPLAN.md) are complete. All Stage 2 core-platform worktrees
(Resilience, Usage/data, Routing, MCP surface, and Configuration) are
implemented and tested. The Stage 3 Tavily, Brave Search, Exa, You.com,
Keenable, Firecrawl, and Parallel providers are implemented and tested, and
the Stage 4 integration root serves them over both MCP and the REST API.

### Stage 0 - Foundation

- Added a `uv`-managed `pyproject.toml` and generated `uv.lock`.
- Set the supported Python policy to `>=3.12,<3.14` and added `.python-version`.
- Added Ruff, mypy, pytest, and pytest-asyncio configuration.
- Created the `src/freesearch/` package with typed package metadata.
- Added Pydantic settings loading with `FREESEARCH_` environment variables and
  a safe `.env.example`.
- Added a shared async HTTPX client factory with common timeout, connection
  limit, redirect, and user-agent settings.
- Added standard-library logging setup and redaction for configured secrets and
  common credential-shaped fields.
- Added the provider credential map and a keyring-backed secret resolver. The
  resolver prefers environment injection for CI/deployment and falls back to
  the native OS credential manager for local use.

### Stage 1 - Contracts

- Added the abstract `ProviderAdapter` interface with search, fetch, cost
  estimation, health, quota, and capabilities hooks.
- Added strict provider-neutral Pydantic models for search, fetch, usage,
  quota, health, errors, capabilities, and routing preferences.
- Explicitly modeled quota provenance as `authoritative`, `observed`, or
  `estimated`.
- Added contract validation tests covering normalized responses, request
  validation, routing preferences, quota provenance, usage, and errors.

### Stage 2 - Resilience

- Added shared retry classification for retryable HTTP statuses (429, 500, 502,
  503, 504), HTTPX transport/timeout failures, and normalized retryable provider errors.
- Added capped jittered backoff, `Retry-After` header parsing (seconds and HTTP dates),
  shared per-provider cooldowns, and a concurrency-safe circuit breaker with half-open probing.
- Added defensive error sanitization and redaction for credential-shaped text, nested
  Pydantic models, aliases, mappings, tuples, bytes, auth schemes, and serialized error payloads.

### Stage 2 - Usage/data

- Added typed SQLAlchemy 2.x async ORM models and an async SQLite repository
  (`SQLiteRepository`, `sqlite+aiosqlite` driver) for usage
  events, quota snapshots, provider health observations, and cache metadata.
- Added strict cache metadata that accepts only opaque SHA-256 cache keys and
  never stores response payloads.
- Preserved decimal precision as text and normalized timezone-aware timestamps
  to UTC for correct SQLite ordering and expiry comparisons.
- Restricted persisted usage metadata to numeric JSON telemetry, rejecting
  sensitive fields and request-content values.
- Added isolated async SQLite tests for round trips, filters, history, quota
  provenance, health, cache replacement, expiry, and privacy validation.

### Stage 2 - Routing

- Added provider-neutral candidate selection and ranking (`select_route`) consuming
  `ProviderAdapter` contracts, health observations, and quota snapshots.
- Excluded adapters without requested capability (`search` / `fetch`), unavailable
  providers (`HealthStatus.UNAVAILABLE`), and depleted quota (`remaining == 0`).
- Implemented deterministic health ranking (`HEALTHY` > `DEGRADED` > `UNKNOWN`),
  user preference filtering/ordering (`PREFER`, `REQUIRE`), and fallback policy enforcement.
- Preserved quota provenance and configured adapter tie-breaker order without mutating inputs.
- Rejection of duplicate adapter registrations with dedicated `RoutingError`.

### Stage 2 - MCP surface

- Added provider-neutral `McpSurface` tool facade exposing only async `search` and `fetch`.
- Strict input payload validation against Pydantic `SearchRequest` and `FetchRequest`
  models before adapter delegation.
- Capability enforcement raising typed `UnsupportedOperationError` before execution.
- Normalized JSON-compatible dictionary response formatting matching contracts.

### Stage 2 - Configuration

- Added typed `ProviderConfig`, `ProviderConfigUpdate`, and `ProviderConfigSettings`
  for non-secret runtime configuration (enablement, priorities, free-tier estimates, reset schedules).
- Enforced strict non-negative `Decimal` parsing for estimates to avoid float precision loss.
- Configured registry overrides via JSON environment variable (`FREESEARCH_PROVIDER_CONFIG_OVERRIDES`).
- Provided isolated deep copies via `get_provider_configs()` with cache clearing support.
- Linked non-secret provider registry to shared `ProviderSecretResolver`.

### Stage 3 - Tavily provider

- Added `TavilyAdapter`, backed by the official async Tavily SDK, with normalized
  search and extract-backed fetch responses under the shared adapter contract.
- Routed every SDK operation through the shared resilience runner; normalized
  retryable SDK failures and malformed provider responses without leaking keys.
- Isolated Tavily authentication from caller-owned HTTP clients while preserving
  their transport policy, timeout phases, and lifecycle ownership.
- Added Tavily search country normalization, request-limit handling, observed
  credit usage events, deterministic fetch truncation, and network-free credit
  estimates (one search credit; 0.2 average extract credit per URL).
- Added an authoritative Tavily monthly-plan quota snapshot from `/usage`, with
  account-plan priority, bounded key fallback, rate-limit handling, and safe
  malformed-response normalization for future routing integration.
- Added mocked SDK, transport, concurrency, redaction, resolver, lifecycle, and
  timeout tests. Local `.env` provider keys now resolve through the shared secret
  resolver after process environment variables and before the OS keyring.
- Added tagged live Behave scenarios for Tavily search, fetch, and quota, with
  shared-client lifecycle coverage and zero-credit extract usage accepted.

### Stage 3 - Parallel provider

- Added `ParallelAdapter`, using direct HTTPX for Parallel v1 search and URL
  extraction while returning the shared provider-neutral response models.
- Scoped the resolver-provided API key to per-request `x-api-key` headers on an
  adapter-owned client, preserving caller transport policy without mutating or
  leaking caller authentication headers.
- Routed every operation through the shared resilience runner; normalized
  provider payloads, observed SKU usage, HTTP failures, malformed responses,
  and fetch truncation without exposing credentials.
- Added mocked wire fixtures and contract coverage for request mapping,
  response normalization, concurrent rate-limit routing, redaction, lifecycle,
  and boundaries. Parallel has no public balance endpoint, so quota capability
  remains disabled; local cost estimates are available for routing.
- Added opt-in tagged live Behave scenarios for Parallel search and extraction;
  both passed against the configured API key on 2026-08-21 with normalized
  results, content, usage telemetry, and request identifiers.

### Stage 3 - Firecrawl provider

- Added `FirecrawlAdapter`, backed by the official `AsyncFirecrawl` SDK, with
  normalized web-search and scrape-backed markdown fetch responses under the
  shared adapter contract.
- Routed SDK requests through the shared resilience runner and normalized
  typed SDK, HTTP, malformed-response, and status errors without exposing
  credentials. Retryable vendor statuses are 429, 500, 502, 503, and 504.
- Resolved Firecrawl keys exclusively through the shared secret resolver,
  failing closed when absent; adapter-owned SDK transport lifecycle is closed
  without affecting the caller-owned shared HTTP client.
- Added deterministic fetch truncation, observed usage evidence when supplied,
  and network-free zero-unit estimates because Firecrawl has no documented
  per-request unit price.
- Added mocked acceptance, SDK-model, error/redaction, lifecycle, and mutation
  tests for the Firecrawl search and fetch paths.
- Added tagged opt-in live Behave search and scrape scenarios. They select the
  Firecrawl adapter from the bare Behave provider tag, verify normalized results
  and bounded markdown, and were run successfully with a resolver-provided key.

### Stage 3 - Keenable provider

- Added `KeenableAdapter`, using direct caller-owned HTTPX for native search and
  fetch endpoints with every outbound request routed through the shared
  resilience runner.
- Supports the free keyless public tier: absent credentials select `/public`
  endpoints with `X-Keenable-Title`; configured credentials select private
  endpoints with `X-API-Key` only.
- Normalizes search and fetch responses, free zero-unit usage/cost estimates,
  truncation, malformed payloads, and retryable HTTP errors to shared contracts.
- Isolates Keenable requests from caller default credential headers and HTTPX
  client authentication without mutating or closing the caller-owned client.
- Added 43 deterministic mocked provider tests covering public/keyed request
  mapping, credential isolation, response/error normalization, boundaries, and
  shared-runner routing; focused mutation score is 100%.
- Added an opt-in live Behave scenario for one keyless search (`limit=1`). It
  verifies the public endpoint/header, normalized result shape, and zero-unit
  usage; `FREESEARCH_RUN_LIVE=1` is required so ordinary BDD stays offline.
- Live verification completed successfully against Keenable's public API:
  one scenario and seven steps passed with no API key.

### Stage 3 - Brave Search provider

- Added `BraveAdapter` using direct HTTPX against Brave Search, with normalized
  web results, ISO publication dates, one-query usage events, and observed
  rate-limit-remaining telemetry.
- Resolved `FREESEARCH_BRAVE_SEARCH_API_KEY` only through the shared secret
  resolver and sent it per request as `X-Subscription-Token`; caller auth,
  API-key headers, and redirects cannot leak it to another origin.
- Routed each search through the shared resilience runner, normalized malformed,
  transport, and HTTP errors without exposing credentials, and declared
  `fetch=False` with a network-free one-query search estimate.
- Added mocked request, retry, concurrency, redaction, malformed-payload, and
  credential-isolation tests; targeted mutation testing killed all 31 mutants.
- Added opt-in `@live @brave` Behave scenarios that verify live normalized
  search results and the observed one-query usage event without logging keys.

### Stage 3 - Exa provider

- Added `ExaAdapter`, backed by the official `exa-py` async SDK, with normalized
  search and URL-content fetch responses under the shared adapter contract.
- Routed SDK requests through the shared resilience runner, resolved credentials
  only through the shared secret resolver, and normalized SDK failures without
  exposing response bodies or credential-shaped text.
- Added real per-response `costDollars.total` usage telemetry when supplied by
  Exa; estimates explicitly remain zero because Exa does not publish a stable
  per-request price. Exa exposes no public remaining-credit endpoint, so quota
  capability is deliberately disabled rather than inferred.
- Added mocked SDK, wire-level, lifecycle, error-redaction, missing-key,
  truncation, resilience, and mutation tests plus tagged live Behave search and
  fetch scenarios. Keyless live Exa scenarios skip before client construction.
- Live-verified both Exa Behave scenarios on 2026-08-21 with the configured
  shared-secret credential: search returned structured results and fetch
  returned non-empty content.

### Stage 3 - You.com provider

- Added `YoucomAdapter`, using direct HTTPX against the You.com YDC Index API
  for normalized web/news search and Contents API-backed Markdown fetches.
- Scoped the resolver-only `X-API-Key` to an adapter-owned client, preserving
  the shared transport and timeout policy while preventing caller credentials
  and cross-origin redirects from leaking the You.com key.
- Routed search and fetch through the shared resilience runner; normalized
  malformed payloads and HTTP errors without exposing response secrets.
- Added deterministic URL matching, Markdown truncation, publication-date and
  safe result/document metadata normalization, plus network-free USD estimates
  of $0.005/search and $0.001/fetched page.
- Added balance-backed quota polling through You.com's account-balance endpoint.
  The authoritative USD-credit balance is converted conservatively to
  **estimated Web Search call equivalents** at $0.005 per call; snapshots are
  explicitly marked `estimated`, with no claimed limit or reset schedule.
- Added mocked adapter, error/redaction, retry, redirect-security, lifecycle,
  quota, and BDD environment tests, plus tagged live Behave scenarios for
  search, fetch, and balance-backed quota. The adapter tests achieved 98%
  statement / 100% branch coverage and 100% mutation score.

### Stage 4 - MCP integration (composition root)

- Added `src/freesearch/server.py`: the application composition root building
  enabled, key-configured adapters in configured priority order and exposing
  the provider-neutral `search` and `fetch` tools over MCP (FastMCP,
  streamable HTTP on loopback:8000) with per-request routing through
  `select_route`.
- Registered all 7 canonical provider adapters (`BraveAdapter`, `ExaAdapter`,
  `FirecrawlAdapter`, `KeenableAdapter`, `ParallelAdapter`, `TavilyAdapter`,
  `YoucomAdapter`) in the composition root's `_ADAPTERS` registry.
- Supported Keenable's keyless public tier in `build_adapters()`: unconfigured
  credentials fall back to keyless public mode instead of failing closed.
- Added uniform asynchronous lifecycle cleanup (`aclose` on `ProviderAdapter`,
  `close_adapters()` in `server.py`) and wired async `lifespan` handlers to both
  FastMCP and FastAPI (`api.py`) to guarantee underlying HTTP clients and
  transports are disposed cleanly.
- Added the `freesearch-mcp` console script; the server runs against whatever
  `FREESEARCH_*_API_KEY`s are configured and skips providers without keys.
- Added network-free smoke tests driving the real FastMCP server with stub
  adapters (routing, capability filtering, no-provider guard).
- Live-verified over streamable HTTP with the MCP client SDK: initialize
  handshake, tool listing, and a routed live Brave search (HTTP 200).
- Added `src/freesearch/api.py`: the REST API (FastAPI) with OpenAPI docs at
  `/docs`, exposing `POST /search` and `POST /fetch` over the same
  composition root and routing as the MCP server, via the `freesearch-api`
  console script on loopback:8001.
- Status: composition root, registry, lifecycle, smoke tests, and live Brave
  check are done. Stage 4.5 (below) wires per-request usage/health
  persistence from both paths into the shared `SQLiteRepository` and adds the
  read-only monitoring reads (`GET /stats`, `GET /dashboard`) on the REST app
  without touching the MCP surface. `_route` still passes empty health/quota
  maps by design: consuming local snapshots for routing belongs to the quota
  reconciliation coordinator stage.
- Deferred (in planned order): the background quota reconciliation
  coordinator (next, per WORKPLAN §4), MCP end-to-end tests, docs/local setup
  guide, Docker packaging (per the work plan), and the Stage 5 full
  settings/secrets dashboard.

## Stage 4.5 - Basic monitoring API (read-only JSON, no secrets)

Implemented per [`WORKPLAN.md`](WORKPLAN.md) §4.5; live-verified on
2026-09-05. All non-goals respected (no enablement/priority editing, no
secret management, no keyring/Vault wiring, no auth/session/CSRF/audit, no
rotation/revocation).

**2026-09-05 change:** `GET /dashboard` switched from stdlib-only HTML to a
JSON `DashboardResponse` (the `StatsResponse` fields plus `generated_at`,
UTC timezone-aware) served with `application/json`. (Superseded 2026-09-06:
the React dashboard/UI consumer is now live — see **Stage 6** below.) For the
React consumer: Decimal-valued fields (`total_units`, `units`, quota
`remaining`/`limit`) serialize as JSON strings in both payloads.

#### Delivered Stage 4.5 Endpoints Specification

| Method | Path | Request Body | Response Model | Description |
| --- | --- | --- | --- | --- |
| `POST` | `/search` | `SearchRequest` | `SearchResponse` | Execute search across routed adapters; records usage & health telemetry. Powers Search Playground. |
| `POST` | `/fetch` | `FetchRequest` | `FetchResponse` | Execute document extraction across routed adapters; records telemetry. Powers Fetch Playground. |
| `GET` | `/stats` | Query: `limit=20` | `StatsResponse` | Operational telemetry reads: totals, newest-first recent events, health, quota snapshots. |
| `GET` | `/dashboard` | Query: `limit=20` | `DashboardResponse` | Full JSON snapshot (`StatsResponse` + `generated_at`) serving the future dashboard UI. |

- **Per-request telemetry on both paths**: `POST /search`/`POST /fetch`
  (`api.py`) and the `search`/`fetch` MCP tools (`server.py`) record
  `response.usage` verbatim and one `HEALTHY` observation (`message=None`)
  via the shared async `SQLiteRepository` (SQLAlchemy 2.x ORM,
  `sqlite+aiosqlite`; no new ORM/driver), through one shared helper module
  `src/freesearch/monitoring.py` (`record_response_telemetry` /
  `record_failure_telemetry` / `tracked_call`). Adapter failures record one
  `DEGRADED` observation (`message=None`) and re-raise unchanged (REST
  `RoutingError`→503 and MCP `ToolError` mappings preserved); routing
  failures record nothing. Usage and health writes are independent
  best-effort blocks; telemetry failures are swallowed with payload-free
  warnings and never fail the user request.
- **Repository lifecycle**: `create_app`/`create_server` accept an optional
  injected repository; owned repositories (`adapters is None and repository
  is None`) are opened in the lifespan at `resolve_database_path`
  (`FREESEARCH_DB` env → explicit `database=` argument → `freesearch.db`) and
  closed on exit; injected repositories are never closed. The MCP owned path
  additionally scopes resources per lifecycle **generation** (fresh HTTP
  client + adapters + repository per refcount 0→1 under a lock; detach on
  1→0, teardown outside the lock) because the streamable-HTTP manager runs
  one lifespan per MCP session, concurrently (sequential and
  delayed-teardown race both pinned by tests).
- **Read-only monitoring reads** on the FastAPI app (loopback): `GET /stats`
  (JSON `StatsResponse`) and `GET /dashboard` (JSON `DashboardResponse`: the
  `StatsResponse` fields plus `generated_at` UTC): per-(provider, operation)
  usage totals, newest-first recent usage
  events (`?limit`, default 20, clamped 1–100), `latest_quota` snapshots and
  latest health per provider; empty/missing repository returns 200 with empty
  sections, never 503. Both reads use `response_model` contracts and appear
  in OpenAPI by design; no routes are hidden with `include_in_schema=False`.
- **Privacy**: `/stats` uses projection models (`RecentUsageEntry`,
  `LatestHealthEntry`) so `metadata`, `request_id`, and health `message`
  never leave the endpoint regardless of stored rows; write-side metadata is
  still gated by the numeric-telemetry-only `_metadata_json` rule; health
  `message` is always `None` from the new writers; Exa usage metadata was
  made numeric-only (`metadata={}` — the `CostEstimate` currency label is
  unchanged); `/dashboard` reuses the same projection models, so
  `metadata`/`request_id`/`message` never leave the endpoint; no HTML output,
  no template engine.
- **Provenance + labeling**: every quota entry exposes its `source`
  (`authoritative` / `observed` / `estimated`); both payloads carry the
  persistent notice "local-observed only — vendor `/usage` endpoints lag
  10–15 min". `latest_quota` is empty until the coordinator lands — nothing
  on the request path calls `adapter.quota()` by design (provenance is
  unit-tested with seeded snapshots).
- **Storage additions** (no schema change): `usage_totals(since=None)`
  (Python `Decimal` sums grouped per provider+operation to avoid SQLite
  REAL coercion), `recent_usage(limit)` (newest-first), and a restored
  chronological `list_usage` contract (`observed_at, id`).
- **Offline BDD suite**: new `features/monitoring.feature` (4 scenarios, no
  keys/network; stub adapters + temp-file SQLite in the steps) guarded via a
  feature-level `@monitoring` tag and an `environment.py` check on
  `effective_tags` (feature tags are not visible through `scenario.tags`).
- **Testing**: 31 monitoring tests in `tests/test_monitoring.py` (one
  parametrized → 32 cases) + 2 storage-aggregate tests + 3 BDD-environment
  guard tests; full suite 864 passed; monitoring feature 4 scenarios /
  16 steps passed.
- **Live acceptance (2026-09-05)**: with a fresh telemetry DB, Brave search
  (`routing.mode=require`, 1 unit) and Tavily fetch (require mode, 0 units —
  a real zero-credit extract usage event) both returned 200; `/stats`
  attributed `brave/search` and `tavily/fetch` totals with `healthy`
  observations, newest-first recent events, and the local-observed notice in
  `/dashboard` JSON; no `message`/`metadata`/`request_id`/`query`/`url`/`content`
  keys anywhere in the reads. The evidence files were removed with
  `.runtime-tmp/` and are not recreated; the 2026-09-05 Brave/Tavily
  attribution stays verified in `/stats` + `/dashboard` JSON.
- **Findings recorded for future stages**:
  - FastMCP registers `call_tool` dynamically as the protocol handler —
    subclassing it to normalize return shapes breaks real transports
    (e.g. `list(False)`); never override it.
  - Write-side gates do not make read endpoints safe: monitoring reads must
    project, not echo, stored models.
  - Behave feature-level tags require `effective_tags`; scenario-level-only
    checks silently miss them (masked locally by configured keys).
  - The REST "unhandled adapter-error 500 / language validation" candidate
    fix from the harness bridge notes remains open — deliberately out of
    this stage's scope.

## Stage 5 - Provider control plane, secrets, and routing policy (ahead of the coordinator)

Implemented on 2026-09-06 per the Stage 5 endpoint specification in
[`WORKPLAN.md`](WORKPLAN.md); ordering deviation (control surface before the
quota reconciliation coordinator) recorded there per operator decision. The
full authenticated dashboard UI, CSRF/session/audit machinery, hosted vault
adapters, and rotation/revocation workflows remain deferred non-goals — this
round delivers the backend control API only.

- **Contract models** (`src/freesearch/contracts.py`, all `extra="forbid"`):
  `UsageStatus` (`success`/`failure`), `UsageEvent.latency_ms` (`int | None`,
  `ge=0`) and `UsageEvent.status` (default `success` — keyword defaults keep
  every existing constructor green), `SecretPresence`, `BreakerState`,
  `CircuitBreakerState`, `CircuitBreakerStatusResponse`, `ProviderStatusResponse`,
  `ProviderTestResponse`, `SetSecretRequest` (`SecretStr(min_length=1)`),
  `SecretStatusResponse` (source literal `environment`/`dotenv`/`keyring`/`none`),
  `FallbackPolicy`, `CostPreset`, `RoutingConfigResponse`, and
  `RoutingConfigUpdate`. `ProviderConfigUpdate` is reused verbatim as the
  PATCH body. `GET /api/v1/providers` entries carry exactly
  `provider_id, enabled, priority, health, circuit_breaker, latency_p95_ms,
  secret_presence, free_tier_estimates, reset_schedule`.
- **Persistence** (`src/freesearch/storage.py`): `UsageEventRow` gained
  nullable `latency_ms`/`status` with full round-trip (`record_usage` writes
  them; legacy rows read back as `None`/`success`). `initialize()` now runs an
  idempotent, data-preserving additive migration (`PRAGMA table_info`
  + `ALTER TABLE ADD COLUMN latency_ms INTEGER` / `status TEXT`) so legacy
  databases self-upgrade on open. New `runtime_settings` key/value table
  (create_all self-heals it on old databases) stores: `provider.{name}` (merged
  config as strict JSON, estimates as exact decimal strings),
  `provider.{name}.breaker`, `secret.{name}` (masked fingerprint + timestamp
  only), and `routing`. Added `recent_latencies(provider, limit)` for p95
  sampling.
- **Telemetry** (`src/freesearch/monitoring.py`): `tracked_call` measures
  wall-clock milliseconds around the adapter call, attaches
  `{latency_ms, status=success}` to stored success usage via `model_copy` (only
  when usage is present), and on failure records a zero-unit
  `status=failure` usage row (new private `_record_failure_usage`) plus the
  unchanged degraded health row, then re-raises. `record_response_telemetry`
  gained keyword-only `latency_ms`/`status` (direct callers unchanged).
  `RecentUsageEntry` now projects `latency_ms` + `status`; the failure path
  still records health only (`record_failure_telemetry` unchanged).
  `latency_p95_ms(repository, provider, *, window=100)` computes the
  nearest-rank 95th percentile over the last ≤100 non-null samples (`None`
  when empty). Measured latency attaches only on the canonical provider
  surface (`ProviderName` members) through `tracked_call`; synthetic adapter
  names and direct `record_response_telemetry` callers keep the verbatim
  Stage 4.5 usage contract.
- **Control service + routes** (`src/freesearch/control.py`, new): the
  `/api/v1` endpoints are registered directly on the FastAPI app (so every
  `app.routes` entry keeps a `path` attribute). Effective provider config
  resolves defaults ← env JSON (`get_provider_configs`) ← persisted record
  (persisted wins; `ProviderConfigUpdate.apply_to` performs the merge), and a
  strict-invalid persisted payload self-heals to the defaults at every read
  seam (item GET, list GET, and the `/search` request path) instead of
  surfacing 500s. The fingerprint `AAA_••••••••xxxx` (SHA-256 last 4) is
  derived in memory and is the only secret-adjacent value ever persisted.
  Secret presence resolves **environment → `.env` → store** (parity with
  `ProviderSecretResolver`, so presence matches actual adapter construction);
  `.env` is read-only for the control plane, and `PUT .../secret` reports the
  **effective** source and fingerprint, so a higher-precedence key that
  shadows the stored write stays visible. Keenable with no key reports
  `keyless_public`; a `DELETE` that leaves nothing resolvable reports
  `source="none"` with no fingerprint. `POST /test` runs a timed
  `adapter.health()` probe: `ok = status != unavailable` with explanatory
  detail for `unknown`, an actionable 503 "restart" hint when the provider is
  absent and unconstructible, and on-demand adapter construction under
  `app.state._control_lock` (construct-once via the public
  `server.adapter_factory`, appended to the live routes, MCP refcount
  untouched). Circuit-breaker reset persists `closed` + timestamp for the
  control surface only — the live per-runner breakers self-recover through
  cooldown/half-open probing, and a runner-level reset API is a documented
  follow-up. Routing config GET/PUT persist
  `fallback_policy`/`cost_optimization_preset`/`max_attempts`;
  **`max_attempts` and breaker state remain staged out of `select_route`**
  (signature and semantics unchanged); `max_attempts` is
  stored-validated-deferred (validated `ge=1`, persisted, resilience runner
  construction untouched this round).
- **Routing policy on the request path** (`src/freesearch/api.py`):
  `create_app(..., secret_store=None)` defaults to the OS keyring bound to
  `Settings.secret_service_name` (`KeyringSecretStore(get_settings().secret_service_name)`),
  keeping control-plane secret writes and the adapters' own credential
  resolution on the same service; an injected `secret_store` is a test-only
  seam. Per request, in-memory routes are enabled-filtered, stably sorted by
  persisted priority (injected/startup order is the tie-break, preserving the
  pinned single-candidate contracts), pinned for `free_first` (Keenable
  first — visible in both the provider list and `/search`), and truncated to
  one candidate under `first_only`. Adapter failures propagate unchanged
  (REST 500 / MCP `ToolError`, no cross-adapter retry, pinned by the offline
  BDD failure scenario); on-demand construction failures degrade to 503. MCP
  (`server.py`) gains telemetry parity (`operation=` through `tracked_call`)
  and the public `adapter_factory` construction seam; no new tools,
  `select_route` signature unchanged.
- **Secrets** (`src/freesearch/secrets.py`): added `MemorySecretStore`, the
  dict-backed `SecretStore` implementation mirroring the tests' double.
  `python-dotenv` is now a declared dependency (was imported undeclared).
- **Offline BDD**: `features/control.feature` (6 scenarios) + 
  `features/steps/control_steps.py` run fully offline (temp-file SQLite +
  stub adapters), guarded by the feature-level `@control` tag check in
  `features/environment.py`.
- **Deviations (all test-driven, recorded deliberately)**:
  - Control-plane secret presence keeps full `ProviderSecretResolver`
    precedence (environment > `.env` > store) so presence matches actual
    adapter construction; the `.env` leg is read-only, `PUT .../secret`
    reports the effective source/fingerprint rather than assuming the stored
    write won, and a delete that leaves nothing resolvable reports
    `source="none"` (with no fingerprint) rather than naming the store it
    emptied.
  - The `PATCH` body is optional so `PATCH`/`GET` on an unknown provider id
    always yields 404 even with no JSON body.
  - `GET /api/v1/providers` entries serialize `health` only (no
    `health_checked_at` key), matching the pinned response key set.
- **Verification (2026-09-06, finalize)**: full suite green — see the
  Verification section for the exact per-item commands, counts, and the
  sandbox accommodations.

## Stage 6 - Frontend live-API integration (`freesearch-ui`)

Delivered 2026-09-06 by the frontend team: the React app's fully **mocked** API
layer (generated results, simulated latency, invented provider telemetry) was
replaced with live calls to the FastAPI backend (`freesearch-api` on
loopback:8001) through a **same-origin Vite dev+preview proxy** (the backend
sends no CORS headers — mitigation is frontend-only; see backend feedback).
All edits confined to `freesearch-ui/`; backend sources read-only reference.

### Delivered (frontend-only)

- **Service layer**: new `services/api/backendTypes.ts` (snake_case wire DTOs),
  `httpErrors.ts` (`ApiError{status,detail,raw}`, `parseDetail`, friendly
  `statusMessage` incl. abort/timeout branch — `DOMException` is not
  `instanceof Error`), `providerCatalog.ts` (static UI metadata for the 7
  canonical providers; `youcom`↔`you` id seam), `mappers.ts` (pure wire→UI
  mappers, deterministic ids, decimal-string parsing), and a rewritten
  `freesearchApi.ts` — plain `fetch`, relative URLs
  (`import.meta.env.VITE_API_URL ?? ""`), all 9 routes
  (`/search`, `/fetch`, `/dashboard`, `/api/v1/providers*`,
  `.../test`, `.../circuit-breaker/reset`, `.../secret`, `/api/v1/routing/config`).
  Mock generators, latency `setTimeout` simulation, and `defaultProviders.ts`
  telemetry are gone (`maskKey.ts` deleted; `ui/switch.tsx` deleted).
- **Context** (`FreeSearchContext.tsx` + `context.ts`): parallel fail-soft
  mount loads (`providers` + `routing/config` + `dashboard?limit=50`);
  pessimistic persisted mutations (PATCH `{enabled}`/`{priority}` strict
  bodies, sequential priority swaps with compensating PATCH + authoritative
  refresh on failure, breaker reset POSTs / trip is local-only and labeled,
  write-only keys via PUT/DELETE `secret` with server fingerprint + env-shadow
  note, fallback config full-body PUT with authoritative re-GET on failure,
  `costOptimizationPreset` ↔ `free_first` wired); `runSearch`/`runFetch` map
  the UI request exactly (`limit` clamp 1–100, `mode`→`prefer/require/auto`
  with explicit provider ids, `allow_fallback`, `AbortSignal.timeout`
  client-side), report the backend winner **verbatim** (no fabricated
  provider/waterfall — single-entry waterfall + honest "trace unavailable"
  notice), keep last-good results on error, and fire-and-forget dashboard
  refresh; `latest_quota` records mapped + rendered when present;
  `dashboardNotice` surfaced; `providersError`/`routingError`/`usageError`
  rendered persistently in their views.
- **Components**: SearchPlayground (live results, Units label, real UTF-8 byte
  length, `statusCode` honestly "—" — not exposed by backend), ProviderMatrix
  (trip/reset split, healthy count uses `healthStatus`, null-safe latency
  "—"), QuotaAnalytics (usage_totals + latest_quota verbatim + "quota
  unavailable" degrade; invented savings/cache numbers removed), ActivityStream
  (dashboard-fed; `queryOrUrl` never rendered; loading/error/empty states),
  Routing (strategy cards: only Cost-optimized persists `free_first`, others
  "simulation view only"; failover copy discloses single-attempt dispatch;
  sync simulator; auto-bypass row deleted), Settings (async persisted
  switches, opaque-bullet key drafts, "Delete key", failover honesty).
- **Tests**: 155 unit/component tests (fetch-mocked, exact wire-body
  assertions, zero-fetch counters, timeout/abort path, privacy + no-fabrication
  negative guards); unit-test typecheck restored (`tsconfig.vitest.json` +
  `pnpm typecheck`); Playwright-BDD **22/22** — `@visual`/`@stub` scenarios run
  against a deterministic `page.route` backend stub (`tests/steps/backendStub.ts`)
  so the suite is **state-neutral and non-destructive** to the live backend,
  while playground live-search and activity-privacy remain real integration
  scenarios.

### Verification battery (frontend, 2026-09-06, final)

```text
cd freesearch-ui
node_modules\.bin\vitest run --configLoader native   # 12 files, 155 passed
node_modules\.bin\eslint .                           # 0 errors
node_modules\.bin\tsc -b                             # clean
node_modules\.bin\tsc -p tsconfig.vitest.json --noEmit  # clean (unit typecheck)
node_modules\.bin\tsc -p tests/tsconfig.json --noEmit   # clean (E2E typecheck)
node_modules\.bin\bddgen                             # features-gen regenerated
node_modules\.bin\playwright test --reporter=line    # 22/22 passed (stub + live)
```

Grep guards empty in `src/`: `generateMock|simulatedLatency|setTimeout.*latency|
Math.random.*latency|INITIAL_CACHE_STATS|INITIAL_USAGE_EVENTS|BSA_live|tvly-prod|
formatMaskedKey`. Working tree confined to `freesearch-ui/`. Backend state
hygiene after the pre-stub suite runs: routing config restored to the contract
default (`chained/balanced/3`), one test-written You.com keyring entry deleted
(presence `configured` via `.env`, `source=dotenv`).

### Backend feedback (gaps hit by the frontend; partial integrations marked)

1. **No CORS headers** — browser cross-origin to :8001 blocked; frontend
   mitigates with the Vite proxy + relative URLs. Ask: add CORS for hosted UIs
   or document the proxy as the permanent contract.
2. **Winner-only `/search`/`/fetch` (no waterfall/fallback trace)** — partial:
   single-entry waterfall + "trace unavailable" notice; per-attempt latency/
   errors would need a new response field.
3. **No provider display metadata** (names/descriptions/capabilities) — partial:
   frontend-owned static catalog; backend `ProviderCapabilities` exists but is
   not exposed on `ProviderStatusResponse`.
4. **No per-operation enablement** (only global `enabled`) — per-op switches
   are session-only display filters; ask: per-op flags or confirm global-only
   is permanent.
5. **No breaker "trip" endpoint** (reset only) — frontend trip is local-only and
   labeled; ask: trip/half-open endpoints or confirm reset-only.
6. **No provider delete** — `removeProvider` removed from UI; fleet is fixed at
   the 7 canonical ids.
7. **`latest_quota` chronically empty** (vendors lag 10–15 min) — Usage view
   renders `usage_totals` + a "quota unavailable" notice until the coordinator
   lands; real snapshots render verbatim when present.
8. **No cache telemetry surfaced** — cache card replaced with "unavailable".
9. **`recent_usage` intentionally carries no query/URL** — Activity never
   renders it (privacy invariant kept). Ask: confirm omission is permanent.
10. **Routing vocab mismatch** — `fallback_policy`/`max_attempts` persist but
    dispatch is single-attempt (stored-validated-deferred); `fallbackOnRateLimit/
    Timeout/ServerError` UI flags are session-only; UI preset vocabulary
    (`priority|cost_optimized|latency_optimized|quality_first`) has no backend
    counterpart except `cost_optimization_preset` (`balanced|free_first`, wired
    to the Cost-optimized card); the other preset cards are labeled
    "simulation view only".
11. **No `mode`/`timeoutMs`/`format`/`includeRawHtml` wire fields** — partial:
    `fast→prefer`, `balanced|deep→require`, no ids→`auto`; timeout is
    client-side `AbortSignal`; fetch always returns markdown.
12. **Secret fingerprint only on write; no GET secret (405)** — key card shows
    a placeholder until first save; presence is live. Ask: optionally include
    `fingerprint` in `ProviderStatusResponse`.
13. **PUT secret shadowing** (environment/.env wins) — surfaced as a subtle
    "env key shadows vault" note.
14. **Decimal-as-string + strict PATCH** — frontend parses with
    `parseFloat(...)||0` and sends minimal exact-typed bodies.
15. **Health vocab** (`healthy|degraded|unavailable|unknown`) vs UI —
    `unavailable|unknown→degraded`, `null→offline` (breaker-open overrides).

### Documented residuals (non-blocking)

- E2E real-backend PUT paths (routing toggle, secret save) are exercised by
  unit tests; E2E proves UI behavior against the stub (state-neutrality trade).
- `statusMessage`'s 404/422/503/500 branches are unit-tested but the live HTTP
  path flows raw `parseDetail` through (honest, but the per-status framing is
  dead code in the live path).
- RoutingStrategy dual-highlight when the backend preset is `free_first` while
  a non-cost card is selected (labeled "simulation view only").
- Minor `act(...)` warnings in unit-test stderr.

## Next - Quota reconciliation coordinator

Planned per [`WORKPLAN.md`](WORKPLAN.md) §4; not yet implemented — it remains
next after the Stage 5 control plane, which landed early per operator decision.
It bridges the local SQLite `UsageEvent` ledger (live decrements, now carrying
measured latency and status) with periodic vendor `adapter.quota()` polling to
eliminate provider telemetry lag (vendors lag 10–15 minutes). It must
re-anchor the authoritative baseline (`QuotaSnapshotRow`), detect external
account drift, and clear or offset processed local usage events without
blocking active search and fetch requests. The Stage 4.5 monitoring read
surface (`/stats` + `/dashboard` JSON, `latest_quota` with provenance) and the
Stage 5 control surface (`/api/v1` provider/secret/routing endpoints) are in
place; routing consumption of local snapshots also lands with this stage.


## DeepSeek Harness `web_search` integration (Path B bridge)

Integrated the freesearch REST API as the search backend of the DeepSeek
Harness agent shell's built-in `web_search` tool; verified live end to end.

- **Why a bridge was needed**: the harness's `web_search` executes through a
  `ctx.web` seam with a `WebSearchProvider` registry (`{id, available(),
  search({query, maxResults}, signal)}`). The shipped provider
  (`deepseek-official`, id `deepseek-official`) calls DeepSeek's native search
  over HTTP, and the seam is not an MCP client — freesearch's MCP `search`/
  `fetch` tools cannot feed it directly. The shipped `dsh-mcp-client` bridge
  *can* surface them as ordinary `mcp__freesearch__search`/`fetch` tools
  (Path A), but not through `web_search`.
- **Delivered**: a durable host-plane Cordis plugin, `freesearch-web-search`
  at `~/.dsh/profiles/web/plugins/freesearch-web-search/`, implementing the
  `WebSearchProvider` contract under provider id `freesearch`. It POSTs each
  seam query to `http://127.0.0.1:8001/search` (map: `maxResults` →
  `limit`), forwards `AbortSignal`, and maps `SearchResponse` results
  (`title`/`url`/`snippet`/`published_at`) onto the seam's normalized
  `sources[]` shape. The bridge holds no credentials; the API server resolves
  the `FREESEARCH_*_API_KEY`s.
- **Composition**: `~/.dsh/profiles/web/cordis.patch.yml` overrides the host
  `web` row (`searchProvider: freesearch`) and inserts the plugin row. A
  composition change requires a harness restart — `watchUserPatches` hot
  reload is not wired in this deployment.
- **Loader pitfall found**: a patch entry cannot create a row. A bare
  `{id, name, config}` entry is skipped with `patch: entry <id> not found`
  (id-targeted entries only override/disable *existing* rows); new rows must
  come from an `insert` list. The first attempt used the wrong form: the
  provider never registered and `web_search` failed with
  `WEB_PROVIDER_CONFIGURED_MISSING`. Fixed with `- insert:`.
- **Verified**: loader-parser validation of the patch; module smoke tests
  against the live API (sources shape, `WEB_ABORTED` on pre-aborted signals);
  and in-session `web_search` calls routed through freesearch (Brave) after
  restart. The freesearch API must be running (`python -m freesearch.api` or
  the `freesearch-api` console script) or `web_search` fails with a
  descriptive `WEB_PROVIDER_ERROR`.
- **REST API findings from live testing**:
  - `routing.providers` are lowercase `ProviderName` strings and must be
    JSON-quoted (`["you"]`); `[Youcoom]` is a 422 JSON decode error. Unknown
    names pass validation silently — they never rank in `prefer`, and
    `require` with one yields 503 `no_eligible_provider`.
  - `mode: auto` ignores `providers` entirely; ranking consults them only in
    `prefer`. `allow_fallback: false` restricts candidates to the single best.
  - `language` must be a BCP-47 code: `"English"` is forwarded to Brave's
    `search_lang`, which rejects it, and the escape produced an unhandled
    HTTP 500 — `api.py` maps only `RoutingError` to 503, so adapter
    exceptions surface as generic 500s. Candidate fix (not applied): catch
    adapter errors and return 502/503 with `detail`, and validate language
    codes in `SearchRequest`.
- **Steering you.com from `web_search`**: not possible per query — the seam's
  `WebSearchRequest` carries only `query`/`maxResults`. Options recorded: the
  MCP path (Path A) exposes the full `SearchRequest` including `routing` per
  call, and a dashboard (Stage 5) can enforce provider routing server-side
  for every client. A bridge-level `routingMode`/`routingProviders` config
  extension (prefer `you`) was drafted but deliberately not applied this
  session.

## Credential and dashboard findings

The seven planned providers currently use API-key authentication, with
provider-specific header conventions documented in `.env.example`. 

**Keenable Free/Public Tier:**
- Keenable provides a keyless public tier allowing search/fetch testing without an API key or upfront registration.
- **Cost**: Free (0 credits).
- **Public Rate Limits**: 30 requests per IP per 15 minutes.
- When `FREESEARCH_KEENABLE_API_KEY` is not present, the Keenable adapter must operate in keyless mode without failing authentication, attaching the `X-API-Key` header only when a configured key is present.

Real keys should not be written by a dashboard to `.env` or SQLite. The local
implementation uses `keyring`, which delegates to Windows Credential Manager,
macOS Keychain, or a Linux Secret Service backend. Environment variables remain
available for CI and deployment injection. Hosted deployments should use a
managed secrets service rather than a hand-rolled encrypted file.

Added a new final stage 5 to `WORKPLAN.md` for a lightweight authenticated
settings dashboard. It will manage non-secret routing/provider settings and
write credentials only through the secret-store abstraction, with loopback
defaults, CSRF/session protection, least privilege, audit events, masking, and
rotation/revocation requirements.

## Quota telemetry lag and reconciliation findings

Live verification with provider endpoints (e.g. Tavily `/usage`) confirmed that
public developer usage endpoints reflect asynchronous batch aggregation (10–15
minute ingestion lag) rather than immediate transactional session state.

To prevent misrouting or quota exhaustion stalls under heavy burst traffic:
- Real-time routing decisions must rely on the instant local SQLite ledger
  (`UsageEventRow` decrements) anchored against the last authoritative vendor
  baseline (`QuotaSnapshotRow`).
- A background reconciliation coordinator must be integrated to periodically
  poll vendor `adapter.quota()`, re-anchor the baseline, detect external account
  drift, and clear or offset processed local usage events without blocking active
  search and fetch requests.

## Deliberately deferred

Remaining, in planned order: quota reconciliation coordinator (next), MCP
end-to-end tests, documentation/local setup guide, and Docker packaging, as
specified by the work plan. The Stage 5 backend control API (provider
controls, secrets, routing policy) landed early on 2026-09-06 (see the Stage 5
section); still deferred are the authenticated dashboard UI itself,
CSRF/session/audit machinery beyond loopback binding, hosted vault adapters,
and rotation/revocation workflows.

- **Brave Answers API**: Brave provides separate API keys and subscriptions for
  Search (`FREESEARCH_BRAVE_SEARCH_API_KEY`) and AI Answers (`FREESEARCH_BRAVE_ANSWERS_API_KEY`).
  Stage 3 focuses on integrating Brave Search (declaring `fetch=False`), while
  the generative/rich Answers endpoint is deferred to a future milestone.

### Deferred provider-integration resilience hardening

The shared resilience work identified checks that require concrete provider
adapters and their real error shapes. They are recorded in
[`WORKPLAN.md`](WORKPLAN.md) and must be completed with each provider:

- test real provider error payloads and credential formats against shared
  redaction;
- use `SecretStr`/`SecretBytes` in provider-internal credential models; and
- confirm each adapter invokes the shared resilience wrapper under concurrent
  rate limiting.

## Verification

All checks pass locally (2026-09-06, finalize battery — 100% green):

```text
uv lock --check   # via `uv lock --check --no-cache` in this sandbox: lock is consistent
uv run ruff check .  # all checks passed (via `uv run --no-sync --no-cache`)
uv run ruff format --check . --exclude .runtime-tmp --exclude tests/.pytest-tmp  # 93 files already formatted
uv run mypy src  # Success: no issues found in 26 source files
uv run pytest -p pytest_tmp_mode_fix --basetemp .runtime-tmp/pt-dev-finalize -q  # 907 passed, 0 failed
uv run behave features/control.feature --no-capture    # 6 scenarios, 23 steps passed (offline, no keys)
uv run behave features/monitoring.feature --no-capture # 4 scenarios, 16 steps passed (offline, no keys)
uv run behave --dry-run 2>$null                        # 0 undefined steps (9 features / 25 scenarios / 109 steps untested as expected)
```

- The finalize round flipped the last items green: corrupt persisted provider
  config self-heals to defaults at every read seam (B1), control-plane secret
  presence gained the `.env` leg with effective-source reporting on PUT/DELETE
  (B2-B4), and the app default store is bound to
  `Settings.secret_service_name` (B5). The earlier round-1 schema contradiction
  was resolved by the Tester's `_SCHEMA` update in `tests/test_storage.py`;
  one whitespace-only reformat (`ruff format`) was applied to
  `tests/test_control_api.py` to satisfy the format gate.
- **Sandbox accommodations (this constrained harness session)**: `uv`'s cache
  directory and directory-listing of `mode=0o700` temp dirs are denied by the
  file sandbox, and the project's console-script exe is held by the running
  API server, so the battery ran with `uv run --no-sync --no-cache`; pytest
  tmp handling uses the Tester's refreshed `.runtime-tmp/pytest_tmp_mode_fix.py`
  (readable-mode `os.mkdir` patch) with an explicit `--basetemp`, and scenario
  debris directories (`freesearch-control-cwd-*`, never source) are excluded
  from ruff via `pyproject.toml` because the harness cannot list or delete
  them. `uv lock --check` runs directly with `--no-cache` (the `uv run` form
  re-reads the denied cache path). No test or source semantics were changed by
  these; without the sandbox the verbatim battery commands apply.
- **Prior Stage 4.5 record (unchanged)**: 864 passed suite; live 2026-09-05
  Brave/Tavily attribution stays verified in `/stats` + `/dashboard` JSON.

## Backend modularization (2026-09-11, per `docs/backend-modularization-plan.md`)

Structural move only: whole files relocated into responsibility-based
packages, plus import/reference/path updates and empty `__init__.py` markers.
No function/class bodies, signatures, SQL, scenarios, or assertions changed.
Historical entries above keep their original paths by intent.

- `src/freesearch/api.py`, `control.py` → `src/freesearch/routers/`
- `src/freesearch/server.py` → `src/freesearch/mcp/server.py` (lazy
  `routers.control` import kept inside `_apply_parallel_seed`)
- `src/freesearch/config.py`, `provider_config.py` →
  `src/freesearch/configuration/`; `contracts.py` →
  `src/freesearch/models/contracts.py` (root reexports preserved)
- `src/freesearch/routing.py`, `monitoring.py`, `parallel_oauth.py` →
  `src/freesearch/services/`
- `src/freesearch/http.py`, `logging.py`, `resilience.py`, `secrets.py` →
  `src/freesearch/infrastructure/`
- `src/freesearch/storage.py`, `database_cli.py`,
  `database_migrations.py`, `migrations/` → `src/freesearch/persistence/`
- `tests/providers/*` → `tests/unit/adapters/`; other pytest modules split
  into `tests/unit/<package>/` and `tests/integration/<package>/`
  (OAuth security tests → `tests/integration/services/oauth/`;
  `THREAT_MODEL.md` → `docs/THREAT_MODEL.md` — follow-up 2026-09-11
  dissolved the `adversarial/` label; fixture scope unchanged)
- `features/` → `tests/bdd/features/` (`[tool.behave] paths` set;
  `Dockerfile.test` no longer copies `features/`)
- Entry points unchanged in name, retargeted in `pyproject.toml`:
  `freesearch-api = freesearch.routers.api:main`,
  `freesearch-db = freesearch.persistence.database_cli:main`,
  `freesearch-mcp = freesearch.mcp.server:main`; `alembic.ini`
  `script_location` → `src/freesearch/persistence/migrations`.

Current-use verification (all green): `uv run pytest` (1170 passed),
`uv run ruff format --check src tests`, `uv run ruff check src tests`,
`uv run mypy` (42 source files), `uv run python -m behave --dry-run`
(17 features / 115 scenarios / 510 steps, 0 undefined), offline Behave
(control, monitoring, database_migrations: 12 scenarios / 48 steps passed),
wheel build with both Alembic revisions (`migration_head()` =
`0002_canonical_quota_units`). Baseline for comparison: 1124 collected
with 1 pre-existing `tests.adversarial` collection error (missing `tests`
package marker; resolved by the new markers). `freesearch-ui/` untouched.

## TO BE DONE (loop ended 2026-09-14 — vault-only slice + live verification)

 Secrets storage upgrade is implemented (encrypted-DB vault, AES-256-GCM,
 PBKDF2 master key, vault-only runtime reads, simplified
 "Key stored in the encrypted vault." toast). Targeted suites green.
 Remaining items, in order:

1. **Tester update (in flight when loop ended):** 3 new proofs — genuine
   MCP vault-key routing proof, DELETE→re-migrate tombstone proof
   (provider + OAuth slot), unbound-store `start_device_flow` preflight
   proof — plus stale-test rewrites T-A…T-D (unit adapters,
   `test_quota_units.py`, unit-bdd ×6, `quota_steps.py`,
   `keenable_steps.py`, hygiene). Full suite currently red on stale
   legacy tests (209 failed + 145 errors, all adjudicated stale
   Categories A–C) plus 2 pre-existing oauth backoff failures.
2. **Developer CODE-A (P1, AC-V1):** MCP vault-keyed construction — open
   repo → build encrypted store → resolve keys async → construct via
   `control._build_with_resolved_secret` in `_build_generation`; keep
   `build_adapters(client)` signature; genuine MCP proof must pass.
3. **Developer CODE-B (P1, AC-V2/V6/V8):** delete-wins tombstones in
   `EncryptedDbSecretStore` (`delete()` writes tombstone, `set()` clears
   it, migration consults it) so DELETE survives restart; land before/with
   CODE-A. Tombstone namespace must avoid `secret.enc:*` / `secret.*`
   collision.
4. **Developer CODE-C (P2, AC-7):** OAuth unbound preflight — writability
   guard at top of `start_device_flow` (fail before vendor egress).
5. **Developer CODE-D (P2):** delete `get_provider_secret_resolver`
   (`provider_config.py`) + ~12-line test-import cleanup + rewrite
   `test_provider_config.py` L222–249. CODE-E comments reword (P3,
   non-blocking).
6. **Approval gate:** CODE-A…D + proofs landed; full pytest green except
   2 known pre-existing oauth failures; full behave green except 1
   pre-existing invoice failure + keyless live-gating skips; ruff +
   slice mypy clean.
7. **Operator step:** restart backend (migration auto-imports legacy keys
   once), then paste the you.com key via dashboard Key vault.
8. **Live verification:** opt-in live you.com BDD (search + fetch, `@live`
   tag, never in CI) + `docs/THREAT_MODEL.md` live-test section
   (opt-in egress, call budget, redaction, no real-key fixtures).
9. **Separate follow-ups (not this slice):** 2 oauth backoff-count
   failures + invoice BDD @1.3 (pre-existing on HEAD); MCP/REST
   pre-existing items per reviewer notes.
