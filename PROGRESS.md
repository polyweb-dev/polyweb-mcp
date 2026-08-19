# FreeSearch Progress

Updated: 2026-08-19

## Scope completed

Stages 0 and 1 from [`WORKPLAN.md`](WORKPLAN.md) are complete. The usage/data
portion of stage 2 is complete.

### Stage 0 - Foundation

- Added a `uv`-managed `pyproject.toml` and generated `uv.lock`.
- Set the supported Python policy to `>=3.11,<3.14` and added `.python-version`.
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
- Added initial tests, a fake adapter fixture, README setup instructions, and a
  GitHub Actions CI workflow.

### Stage 1 - Contracts

- Added the abstract `ProviderAdapter` interface with search, fetch, cost
  estimation, health, quota, and capabilities hooks.
- Added strict provider-neutral Pydantic models for search, fetch, usage,
  quota, health, errors, capabilities, and routing preferences.
- Explicitly modeled quota provenance as `authoritative`, `observed`, or
  `estimated`.
- Added contract validation tests covering normalized responses, request
  validation, routing preferences, quota provenance, usage, and errors.

### Stage 2 - Usage/data

- Added an async SQLite repository for usage events, quota snapshots, provider
  health observations, and cache metadata.
- Added strict cache metadata that accepts only opaque SHA-256 cache keys and
  never stores response payloads.
- Preserved decimal precision as text and normalized timezone-aware timestamps
  to UTC for correct SQLite ordering and expiry comparisons.
- Restricted persisted usage metadata to numeric JSON telemetry, rejecting
  sensitive fields and request-content values.
- Added isolated async SQLite tests for round trips, filters, history, quota
  provenance, health, cache replacement, expiry, and privacy validation.

## Credential and dashboard findings

The seven planned providers currently use API-key authentication, with
provider-specific header conventions documented in `.env.example`. Keenable
also supports a keyless tier, so its key remains optional.

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

## Deliberately deferred

No provider SDKs or provider modules were added, and no dashboard UI was added
yet. Routing, the MCP surface, shared resilience behavior, provider
configuration, Docker, and the dashboard remain for later work as specified by
the work plan.

## Verification

All checks pass locally:

```text
uv lock --check
uv sync --locked
uv run ruff check .
uv run mypy src
uv run pytest  # 28 passed
```
