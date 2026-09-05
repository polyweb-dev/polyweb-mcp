# FreeSearch Progress

Updated: 2026-09-05

## Scope completed

Stages 0, 1, 2, 3, 4, and **Stage 4.5 (read-only monitoring dashboard)** from
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

## Stage 4.5 - Basic monitoring dashboard (read-only, no secrets)

Implemented per [`WORKPLAN.md`](WORKPLAN.md) §4.5; live-verified on
2026-09-05. All non-goals respected (no enablement/priority editing, no
secret management, no keyring/Vault wiring, no auth/session/CSRF/audit, no
rotation/revocation).

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
  (JSON `StatsResponse`) and `GET /dashboard` (stdlib-only HTML, no template
  engine): per-(provider, operation) usage totals, newest-first recent usage
  events (`?limit`, default 20, clamped 1–100), `latest_quota` snapshots and
  latest health per provider; empty/missing repository returns 200 with empty
  sections, never 503. Routes are `include_in_schema=False` (the existing
  OpenAPI pin on `/search` + `/fetch` is preserved).
- **Privacy**: `/stats` uses projection models (`RecentUsageEntry`,
  `LatestHealthEntry`) so `metadata`, `request_id`, and health `message`
  never leave the endpoint regardless of stored rows; write-side metadata is
  still gated by the numeric-telemetry-only `_metadata_json` rule; health
  `message` is always `None` from the new writers; Exa usage metadata was
  made numeric-only (`metadata={}` — the `CostEstimate` currency label is
  unchanged); the dashboard renders only projected fields, every dynamic
  value `html.escape`d, no forms/JS/external assets.
- **Provenance + labeling**: every quota row displays its `source`
  (`authoritative` / `observed` / `estimated`); the UI shows a persistent
  banner "local-observed only — vendor `/usage` endpoints lag 10–15 min".
  `latest_quota` is empty until the coordinator lands — nothing on the
  request path calls `adapter.quota()` by design (provenance rendering is
  unit-tested with seeded snapshots).
- **Storage additions** (no schema change): `usage_totals(since=None)`
  (Python `Decimal` sums grouped per provider+operation to avoid SQLite
  REAL coercion), `recent_usage(limit)` (newest-first), and a restored
  chronological `list_usage` contract (`observed_at, id`).
- **Offline BDD suite**: new `features/monitoring.feature` (4 scenarios, no
  keys/network; stub adapters + temp-file SQLite in the steps) guarded via a
  feature-level `@monitoring` tag and an `environment.py` check on
  `effective_tags` (feature tags are not visible through `scenario.tags`).
- **Testing**: 27 monitoring unit tests + 2 storage-aggregate tests + 3
  BDD-environment guard tests; full suite 859 passed; monitoring feature
  4 scenarios / 16 steps passed.
- **Live acceptance (2026-09-05)**: with a fresh telemetry DB, Brave search
  (`routing.mode=require`, 1 unit) and Tavily fetch (require mode, 0 units —
  a real zero-credit extract usage event) both returned 200; `/stats`
  attributed `brave/search` and `tavily/fetch` totals with `healthy`
  observations, newest-first recent events, and the local-observed banner in
  `/dashboard`; no `message`/`metadata`/`request_id`/`query`/`url`/`content`
  keys anywhere in the reads (evidence: `.runtime-tmp/live-stats.json`,
  `live-dashboard.html`).
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

## Next - Quota reconciliation coordinator

Planned per [`WORKPLAN.md`](WORKPLAN.md) §4; not yet implemented. Bridges the
local SQLite `UsageEvent` ledger (live decrements) with periodic vendor
`adapter.quota()` polling to eliminate provider telemetry lag (vendors lag
10–15 minutes). It must re-anchor the authoritative baseline
(`QuotaSnapshotRow`), detect external account drift, and clear or offset
processed local usage events without blocking active search and fetch
requests. The Stage 4.5 monitoring read surface (`latest_quota` with
provenance) is already in place and will display coordinator-produced
snapshots; routing consumption of local snapshots also lands with this
stage.


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
end-to-end tests, documentation/local setup guide, Docker packaging, and the
full settings/secrets dashboard (Stage 5), as specified by the work plan.

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

All checks pass locally:

```text
uv lock --check
uv sync --locked
uv run ruff check .
uv run ruff format --check .
uv run mypy src
uv run pytest  # 859 passed
uv run behave features/monitoring.feature  # 4 scenarios, 16 steps passed (offline, no keys)
FREESEARCH_RUN_LIVE=1 uv run behave --tags=@keenable --no-capture  # 1 live scenario, 7 steps passed
uv run behave --tags=@live,@parallel features/parallel.feature  # 2 passed
```
Live Stage 4.5 acceptance (2026-09-05): fresh `FREESEARCH_DB` + API server,
Brave search (1 unit) and Tavily fetch (0 units) via `routing.mode=require`,
attribution verified in `/stats` + `/dashboard` (evidence in
`.runtime-tmp/live-stats.json` / `live-dashboard.html`).
