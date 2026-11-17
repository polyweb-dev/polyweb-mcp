# Polyweb provider mock

A development-only FastAPI app that impersonates the provider APIs Polyweb
calls. It keeps accounts, keys, credits, pricing, keyless budgets, a usage
ledger, a request log, fault rules, and saved fixtures in SQLite. The admin
CLI `polyweb-mock` changes that state while the server runs.

> Status: phase 1. Tavily is complete; the other providers follow the same
> plugin interface. The integration phase finishes this document.

## Run it

```bash
cd polyweb-provider-mock
uv sync
uv run polyweb-provider-mock            # 127.0.0.1:8212, state in ./mock.db
uv run polyweb-mock seed                # default accounts, keys, and prices
uv run polyweb-mock export-keys         # POLYWEB_<PROVIDER>_API_KEY=... lines
```

Then start Polyweb with `POLYWEB_PROVIDER_MOCK_URL=http://127.0.0.1:8212`
(never in production; startup refuses it). Polyweb's shared HTTP client
factory reroutes every known provider host to the mock and keeps the real
`Host` header, which the mock routes by.

Settings: `POLYWEB_PROVIDER_MOCK_HOST`, `POLYWEB_PROVIDER_MOCK_PORT` (8212),
`POLYWEB_PROVIDER_MOCK_DB`, `POLYWEB_PROVIDER_MOCK_ADMIN_TOKEN` (protects
`/_mock/*`), `POLYWEB_PROVIDER_MOCK_AUTO_SEED` (default on),
`POLYWEB_PROVIDER_MOCK_RANDOM_SEED`.

## Faults

```bash
uv run polyweb-mock fault add tavily --op search --kind rate_limit \
    --probability 0.5 --count 10 --duration 10m
uv run polyweb-mock latency set tavily --ms 800 --jitter 200
uv run polyweb-mock scenario list
uv run polyweb-mock scenario apply tavily-down
uv run polyweb-mock scenario clear
```

Kinds: `latency`, `timeout`, `http_error`, `outage`, `rate_limit`,
`quota_exhausted`, `auth_invalid`, `malformed`, `connection_drop`.

## Add a provider

Create `src/polyweb_provider_mock/providers/<name>.py` that exports
`PLUGIN`, an instance of a `ProviderPlugin` subclass. See the interface in
`providers/base.py` and the reference implementation in `providers/tavily.py`.
Put sanitized recordings in `tests/contract/recordings/<name>/` and add a
contract test like `tests/contract/test_tavily_contract.py`.

## Checks

```bash
uv run pytest -q
uv run ruff check . && uv run ruff format --check .
uv run mypy src
```
