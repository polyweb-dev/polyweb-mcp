# FreeSearch Work Plan

Dockerization is deliberately deferred until the application works locally. The
first goal is a stable, mergeable MCP application core.

## Governing rule

No provider implementation begins until the shared adapter contract and
provider-neutral response models are fixed. This prevents provider branches
from creating incompatible definitions of search results, fetched documents,
quota data, and errors.

## Work sequence

### 0. Foundation worktree - complete first

Create the project and virtual environment with `uv`.

- Create `pyproject.toml`, `uv.lock`, Python version policy, linting, typing,
  and test tooling.
- Create the `src/freesearch/` package layout.
- Add Pydantic settings and configuration loading.
- Add an async HTTPX client factory.
- Add basic logging with secret redaction.
- Add initial test fixtures and CI checks.
- Do not add provider-specific implementation in this phase.

This team owns dependency management. Provider branches may declare an SDK they
need, but the foundation/integration team resolves `pyproject.toml` and
`uv.lock` conflicts.

### 1. Contracts worktree - complete before provider branches

Define the stable shared abstractions:

```text
ProviderAdapter (abstract base)
 |- search(request) -> SearchResponse
 |- fetch(request) -> FetchResponse
 |- estimate_cost(request) -> CostEstimate
 |- capabilities
 `- health/quota hooks
```

Own the provider-neutral Pydantic models:

- `SearchRequest`, `SearchResult`, `SearchResponse`
- `FetchRequest`, `FetchedDocument`, `FetchResponse`
- `ProviderCapabilities`
- `UsageEvent`, `QuotaSnapshot`, `ProviderError`
- `RoutingPreference`

Every provider returns these models regardless of its native API response.
This worktree also publishes a small adapter contract-test suite that every
provider implementation must pass.

### 2. Core-platform worktrees - parallel after contracts

These worktrees do not implement individual providers.

| Worktree | High-level responsibility |
| --- | --- |
| Routing | Select providers from user preference, operation capability, local quota, health, and fallback policy. |
| Usage/data | Provide async SQLite repositories for usage events, quota snapshots, cache metadata, and provider health. |
| MCP surface | Expose only `search` and `fetch`; validate inputs and present normalized responses. |
| Resilience | Provide shared HTTPX timeout, retryable-error, backoff, rate-limit, and circuit-breaker behavior. |
| Configuration | Configure provider enablement, priorities, free-tier estimates, reset schedules, and secret references; resolve actual credentials through the shared secret layer, not ordinary settings. |

The routing worktree must label quota information as `authoritative`,
`observed`, or `estimated`; it must not present a local estimate as a
vendor-confirmed balance.

### 3. Provider worktrees - parallel after contracts

Each provider branch owns only its adapter and tests:

```text
providers/<provider_name>.py
tests/providers/test_<provider_name>.py
tests/fixtures/<provider_name>/
```

Provider teams may add strict, provider-specific Pydantic models internally,
but they must convert responses to the shared contract models at the boundary.

| Branch | Implementation rule |
| --- | --- |
| `provider-exa` | Use the official async Exa SDK and adapt it to `ProviderAdapter`. |
| `provider-firecrawl` | Use `AsyncFirecrawl`; implement search and scrape-backed fetch. |
| `provider-tavily` | Use `AsyncTavilyClient`; implement search and extract-backed fetch. |
| `provider-parallel` | Use direct HTTPX against the official API; implement search and URL extraction where available. |
| `provider-youcom` | Use direct HTTPX; implement web search and content/live-crawl-backed fetch where supported. |
| `provider-brave` | Use direct HTTPX; implement Brave Search API (`FREESEARCH_BRAVE_SEARCH_API_KEY`, header `X-Subscription-Token`) and declare `fetch=False` in capabilities. (Brave Answers API is deferred to a later stage). |
| `provider-keenable` | Use direct HTTPX; implement native search and fetch endpoints (not its MCP server). Support keyless public tier (free, 30 req/IP/15min) when no `FREESEARCH_KEENABLE_API_KEY` is provided, attaching `X-API-Key` only when configured. |

Every provider worktree must:

- use the shared async contract;
- receive credentials only through the shared settings/secret layer;
- not build its own retry, cache, or SQLite logic;
- normalize errors without exposing secrets;
- supply mocked contract tests; and
- document request-cost or usage evidence it can observe.

#### Deferred provider-integration resilience hardening

When each provider adapter is implemented, add provider-specific tests for its
actual error payloads and retry behavior. The shared resilience layer cannot
know every vendor's aliases or error shapes before those adapters exist.

- Verify the provider's real error payloads, field aliases, and credential
  formats against the shared redaction layer.
- Use `SecretStr`/`SecretBytes` for provider-internal credential models.
- Exercise concurrent 429 responses through the provider adapter to confirm it
  invokes the shared resilience wrapper for every request attempt.

### 4. Integration worktree - after provider branches are ready

This team merges providers one at a time and owns the final dependency lockfile.

- Run shared adapter contract tests against every provider.
- Register adapters in the application factory.
- Implement the background quota reconciliation coordinator (bridging local
  SQLite `UsageEvent` decrementing with periodic vendor `adapter.quota()` polling
  to eliminate provider telemetry lag).
- Verify routing behavior with fake quota and health states.
- Confirm `search` and `fetch` expose identical shapes regardless of provider.
- Run opt-in smoke tests for any available provider keys.
- Resolve SDK and package-version conflicts.

Suggested merge order:

1. Foundation and core contracts.
2. Core-platform worktrees.
3. Tavily, Firecrawl, and Exa.
4. Brave and Keenable.
5. Parallel and You.com.
6. MCP end-to-end tests.
7. Documentation and local setup guide.

## Ownership boundaries

- Only the foundation/integration team edits `pyproject.toml`, `uv.lock`, the
  application composition root, and shared models.
- Provider teams edit only their provider module, tests, and fixtures.
- Core worktrees use contracts and do not import vendors.
- A provider that needs a shared-model change proposes it to the contracts
  owner instead of independently changing shared types.

## Final phase: Docker

After the MCP server works locally with `uv`, passes mocked provider tests, and
can use configured real keys in opt-in smoke tests, create the Docker image and
installation instructions.

### 5. Settings and secrets dashboard - after local and deployment flows are stable

Add a lightweight authenticated settings dashboard for the operator. It should
allow changing non-secret runtime settings such as provider enablement and
priority, routing defaults, free-tier estimates, reset schedules, and safe HTTP
tuning without editing source files.

The dashboard must accept provider API keys without writing them to `.env` or
the application database. For local desktop use, store them through the native
OS credential manager via the shared secret-store interface (Windows Credential
Manager, macOS Keychain, or Linux Secret Service). For hosted deployments,
provide an adapter for a managed secret service such as Azure Key Vault, AWS
Secrets Manager, Google Secret Manager, or HashiCorp Vault; deployment
environment injection remains supported for CI and simple single-host setups.

The dashboard work must include:

- loopback-only default binding for local use and strong authentication before
  any secret-management endpoint is exposed remotely;
- CSRF protection, secure session cookies, authorization, rate limiting, and
  audit events for secret create/replace/delete operations;
- never displaying or logging full secret values, and only showing presence,
  provider, last-updated metadata, and a masked fingerprint if needed;
- least-privilege secret access, rotation/revocation workflows, and clear
  separation of development and production credentials; and
- tests that verify secrets do not appear in responses, logs, model dumps,
  backups, or generated configuration files.
