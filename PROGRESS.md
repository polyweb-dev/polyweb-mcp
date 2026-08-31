# FreeSearch Progress

Updated: 2026-08-21

## Scope completed

Stages 0, 1, and 2 from [`WORKPLAN.md`](WORKPLAN.md) are complete. All Stage 2
core-platform worktrees (Resilience, Usage/data, Routing, MCP surface, and
Configuration) are implemented and tested. The Stage 3 Tavily, Brave Search, and
Exa providers are implemented and tested.

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

- Added typed SQLAlchemy async ORM models and an async SQLite repository for usage
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

The remaining Stage 3 providers, application composition root / integration
tests (Stage 4), Docker packaging, and settings dashboard (Stage 5) remain for
later work as specified by the work plan.

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
uv run pytest  # 443 passed
```
