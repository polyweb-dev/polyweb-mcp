# Polyweb provider mock

A development-only FastAPI app that impersonates every provider API Polyweb
calls: Exa, Tavily, Firecrawl, Parallel, You.com, Brave, Keenable, and
Tinyfish. Each provider answers on its real paths with its real status codes,
headers, JSON bodies, error envelopes, authentication, and usage or balance
endpoints. Polyweb does not know that it talks to a mock.

State lives in SQLite: accounts, keys, credits, pricing, keyless budgets, a
usage ledger, a request log, fault rules, and saved fixtures. The admin CLI
`polyweb-mock` (and the `/_mock` admin API) changes that state while the
server runs; the next request sees the change.

The mock is never part of the production stack. It has its own
`pyproject.toml` and `uv.lock`, it is not a workspace member of the root
project, and the production image does not contain it.

## Run it

```bash
cd polyweb-provider-mock
uv sync
uv run polyweb-provider-mock            # 127.0.0.1:8212, state in ./mock.db (seeded on first start)
uv run polyweb-mock seed                # default accounts, keys, and prices (idempotent)
uv run polyweb-mock export-keys         # POLYWEB_<PROVIDER>_API_KEY=... lines for Polyweb
```

Then start Polyweb with `POLYWEB_PROVIDER_MOCK_URL=http://127.0.0.1:8212`.
Seeded keys are fake but match each provider's real format (`tvly-dev-mock...`,
`fc-mock...`, `BSAmock...`, `keen_mock...`).

| Setting | Default | Meaning |
| --- | --- | --- |
| `POLYWEB_PROVIDER_MOCK_HOST` | `127.0.0.1` | bind host (also an admin host name) |
| `POLYWEB_PROVIDER_MOCK_PORT` | `8212` | bind port |
| `POLYWEB_PROVIDER_MOCK_DB` | `polyweb-provider-mock/mock.db` | state database (WAL) |
| `POLYWEB_PROVIDER_MOCK_ADMIN_TOKEN` | unset | protects `/_mock/*` (see below) |
| `POLYWEB_PROVIDER_MOCK_AUTO_SEED` | on | seed a database that was never seeded |
| `POLYWEB_PROVIDER_MOCK_RANDOM_SEED` | unset | repeatable fault probabilities and jitter |
| `POLYWEB_PROVIDER_MOCK_PUBLIC_URL` | unset | browser origin for links the mock hands out, such as the Parallel device page (the dev stack sets `http://127.0.0.1:<mock port>`); unset uses the listening address |

## How routing works

1. **Polyweb side.** With `POLYWEB_PROVIDER_MOCK_URL` set, Polyweb's startup
   calls `install_provider_mock` once (`src/polyweb/infrastructure/provider_mock.py`).
   It wraps the HTTPX transport classes, so a request to a known provider
   host (`api.exa.ai`, `admin-api.exa.ai`, `api.tavily.com`,
   `api.firecrawl.dev`, `api.parallel.ai`, `platform.parallel.ai`,
   `api.you.com`, `ydc-index.io`, `api.ydc-index.io`, `api.search.brave.com`,
   `api.keenable.ai`, `api.search.tinyfish.ai`, `api.fetch.tinyfish.ai`) goes
   to the mock origin with the same method, path, query, body, and headers,
   including the original `Host`. This one branch covers the shared client,
   borrowed transports, and the SDK-owned clients of Exa and Firecrawl. A blank
   value turns it off; `environment=production` refuses to start with it.
2. **Mock side.** The mock dispatches by the `Host` header (port stripped) to
   the provider plugin that claims the host; an operation can be scoped to
   one host (Tinyfish serves search and fetch on `/` of two hosts). The mock's
   own names (`localhost`, `127.0.0.1`, `::1`, `0.0.0.0`, `provider-mock`,
   `polyweb-provider-mock`, the bind host) reach the `/_mock` admin API and
   `/_mock/health`. Any other host gets `421 Misdirected Request`.
3. **Headers.** uvicorn sends no `Server` header; each plugin sends the
   provider's recorded one (`cloudflare`, `awselb/2.0`, `uvicorn`, ...) or none.

Proxy caveat: a client that uses a proxy transport (`HTTPS_PROXY`,
`HTTP_PROXY`, or an SDK proxy mount) sends the rerouted request through that
proxy. Unset the proxy variables, or add the mock host to `NO_PROXY`.

Try it by hand:

```bash
key=$(uv run polyweb-mock export-keys --format json | python3 -c 'import json,sys; print(json.load(sys.stdin)["POLYWEB_TAVILY_API_KEY"])')
curl -s http://127.0.0.1:8212/search -H 'Host: api.tavily.com' \
  -H "Authorization: Bearer $key" -H 'Content-Type: application/json' -d '{"query": "polyweb"}'
```

## Admin API and token

`/_mock/docs` lists the admin API; every CLI command has a route. Without
`POLYWEB_PROVIDER_MOCK_ADMIN_TOKEN` the admin API is open (bind it to
loopback). With a token, every `/_mock` route needs `Authorization: Bearer
<token>`, except `/_mock/health` and plugin pages. The CLI writes the
database directly and needs no token.

Plugin pages render forms only. The Parallel device page
`/_mock/parallel/oauth/device?user_code=ABCD-EFGH` (the `verification_uri`
that Polyweb shows) stays usable behind the token: its form asks for the
token, or open it once with `&admin_token=<token>` to keep the token in an
HttpOnly, `SameSite=Strict` cookie for `/_mock`. The approve and deny routes it
posts to stay guarded. The token never appears in a provider response.

The Parallel OAuth flow matches two recordings of the real platform
(2026-11-17 up to approval, 2026-11-19 through approval, refresh and revoke):
status codes, `error_description` strings, headers, the 2 s poll interval, no
`slow_down` for fast polls (`polyweb-mock parallel oauth set
--enforce-interval on` turns it on), the token body and JWT claims, refresh
rotation (a reused old refresh token fails without ending the session), revoke
(200 with an empty body for any token; the access token keeps reading the
balance until it expires), and balance cents as numbers with a fraction. The
OAuth token reads the balance only: on `/v1/search` and `/v1/extract` it gets
401 `{"code": 16, "message": "Invalid JWT credential"}`. Only `access_denied`
and `slow_down` still follow the documentation.

<!-- DEV-STACK START -->
## Run Polyweb against the mock

Each worktree uses mock port `82N2` (main checkout `8202`, `polyweb_wt_1`
`8212`); see the port table in the root `AGENTS.md`. Run the commands below
from the repository root. Never use a production database or real keys.

### Docker stack

This is the dev stack. `docker/dev/compose.yaml` layers on `compose.yaml` and
`docker/npd/compose.yaml` and adds a `provider-mock` service. The api and mcp
send all provider traffic to it, use a disposable `polyweb.mock-dev.db` on the
project's own volume, and get blank provider key variables. Always use the
helper script. It sets a worktree-unique Compose project (`polyweb_wt_1` gives
`polyweb-wt1-dev`) and publishes the worktree ports on `127.0.0.1` only. A bare
`docker compose` with the overlay stops, because the overlay needs
`POLYWEB_STACK_PROJECT`.

```bash
scripts/linux/stack.sh dev up         # build, start the mock, seed once, start api + mcp
scripts/linux/stack.sh dev cli scenario apply tavily-down
scripts/linux/stack.sh dev logs api
scripts/linux/stack.sh dev live       # dev-live: the @live scenarios against this mock
scripts/linux/stack.sh dev down       # add -v to delete this project's volumes
```

Windows: `scripts\windows\stack.bat dev` takes the same commands. The first
`up` seeds the mock and the Polyweb database. After `cli reset` or
`cli seed --reset`, the mock keys change: run `down -v`, then `up`.

### Processes with uv

```bash
POLYWEB_PROVIDER_MOCK_PORT=8212 uv run --project polyweb-provider-mock polyweb-provider-mock &
uv run python scripts/seed_dev.py --keys-from-mock http://127.0.0.1:8212
export POLYWEB_DB=polyweb.mock-dev.db POLYWEB_PROVIDER_MOCK_URL=http://127.0.0.1:8212
uv run polyweb-api &
POLYWEB_EXECUTION_AUTHORITY_URL=http://127.0.0.1:8211 uv run polyweb-mcp &
cd polyweb-ui && pnpm dev               # VITE_PORT from .env, proxies to the API port
```

`seed_dev.py --keys-from-mock` seeds the running mock, reads its fake keys
through the admin API, and creates `polyweb.mock-dev.db`. It never reads
provider keys from `.env` or the process. The five dev accounts use the
password `PolywebDev123!`. Alpha has one keyed pool per provider. Beta
(admin2) has the keyless Keenable and Tavily pools. Brave Answers has no
Polyweb adapter, so its key is not imported. Polyweb has no keyless Firecrawl
mode.

Parallel OAuth: as admin1, create a Parallel vault key with `auth_mode`
`oauth` (UI vault page or `POST /api/v1/account/vault/keys`), start the
device flow, then approve the shown code:

```bash
uv run --project polyweb-provider-mock polyweb-mock parallel oauth approve ABCD-EFGH
```

The next poll connects the key, and Polyweb reads the Parallel balance with
it. Search and extract need a Parallel API key: the mock refuses the OAuth
token there with 401 `Invalid JWT credential`, as the real API does
(TASK-000077).

### Behave live suite against the mock

The root test suites ignore `POLYWEB_PROVIDER_MOCK_URL` unless
`POLYWEB_TEST_PROVIDER_MOCK=1` is in the process environment.

```bash
set -a; eval "$(uv run --project polyweb-provider-mock polyweb-mock export-keys)"; set +a
export POLYWEB_PROVIDER_MOCK_URL=http://127.0.0.1:8212 POLYWEB_TEST_PROVIDER_MOCK=1 POLYWEB_RUN_LIVE=1
uv run --no-sync behave --tags="@live and not @latency"
```

CI: the manual Woodpecker workflow `provider-mock` runs the mock checks, then
this Behave run against a mock in the same step. Reports go to the Gitea
package `polyweb-provider-mock`.
<!-- DEV-STACK END -->

## CLI reference (`polyweb-mock`)

Every command prints JSON and takes `--db PATH` (default
`POLYWEB_PROVIDER_MOCK_DB`). `PROVIDER` is a plugin name (`polyweb-mock
scenario list` shows them all); fault and latency commands also accept `*`.

```bash
polyweb-mock seed [--reset]                         # default accounts, keys, keyless settings, prices
polyweb-mock reset                                  # delete all state (then seed again)
polyweb-mock keys list [--provider tavily]
polyweb-mock keys create tavily --label ci [--scope search] [--limit 50] [--env-var NAME] [--key VALUE] [--account ID]
polyweb-mock keys revoke tavily ci                  # by label or key value; `keys restore` undoes it
polyweb-mock credits show [tavily]
polyweb-mock credits add tavily 500                 # raise the recurring grant
polyweb-mock credits add exa 10 --prepaid           # one-time credit: never resets, spent after the grant
polyweb-mock credits funding tavily postpaid --overage-limit 500   # bill after use (PAYGO); `prepaid` refuses at zero
polyweb-mock credits set tavily 0                   # remaining balance; `unlimited` removes the cap; --used N
polyweb-mock account show [keenable]
polyweb-mock account set keenable reset_day=17      # JSON attribute values; NAME= removes one
polyweb-mock account set tinyfish search_per_minute=5 wallet_balance='"10.00"'
polyweb-mock pricing show [exa]
polyweb-mock pricing set tavily search.basic --credits 2 --usd 0.016 [--unit request] [--rule per_unit|accumulate]
polyweb-mock keyless show [firecrawl]
polyweb-mock keyless set tavily --enable --per-day 500 --per-minute none   # or --disable
polyweb-mock fault list
polyweb-mock fault add tavily --op search --kind rate_limit --probability 0.5 --count 10 --duration 10m --retry-after 30
polyweb-mock fault add exa --kind timeout --seconds 45                      # hold, then close
polyweb-mock fault add '*' --kind malformed --variant truncated
polyweb-mock fault disable 3 && polyweb-mock fault enable 3
polyweb-mock fault clear [--id 3] [--provider tavily] [--scenario NAME] [--kind latency]
polyweb-mock latency set brave --ms 800 --jitter 200 [--op web_search]
polyweb-mock latency clear brave
polyweb-mock scenario list
polyweb-mock scenario apply tavily-down
polyweb-mock scenario clear [tavily-down]           # all presets without a name
polyweb-mock fixtures list [--provider tavily]
polyweb-mock fixtures save tavily search "polyweb test" --file body.json [--status 200]
polyweb-mock fixtures save --from-log 42            # the logged response, under its match key
polyweb-mock fixtures delete 7
polyweb-mock log tail [--provider tavily] [--limit 50] [--bodies]
polyweb-mock export-keys [--format dotenv|json]
polyweb-mock parallel oauth show                    # settings, device codes, sessions (no secrets)
polyweb-mock parallel oauth approve ABCD-EFGH [--account parallel-org]
polyweb-mock parallel oauth deny ABCD-EFGH          # or: expire ABCD-EFGH
polyweb-mock parallel oauth revoke-sessions
polyweb-mock parallel oauth set --auto-approve on --access-ttl 60
polyweb-mock parallel balance show [--account ID]
polyweb-mock parallel balance set --pending-cents 250 --will-invoice off
```

Fixtures replace synthetic content for `(provider, operation, match key)`:
the normalized query for searches, the normalized URL for fetches. The
request log never holds a presented key, an auth or cookie header, a token,
secret, or key field, or a JWT; operations that carry tokens or minted keys
(Parallel OAuth and key minting) log no bodies at all.

## Faults

A rule targets a provider (or `*`) and an operation (or `*`), fires with
`--probability`, at most `--count` times, until `--duration` ends. Every
firing `latency` rule adds its delay; the first firing rule of another kind
decides the outcome. Rules apply live, in creation order.

| Kind | Parameters | Effect |
| --- | --- | --- |
| `latency` | `--ms`, `--jitter` | adds delay; stacks with every other rule |
| `timeout` | `--seconds` (30), `--status` | holds the request, then closes the connection without a response; with `--status` (for example 504) answers that status after the hold |
| `http_error` | `--status` (500), `--message` | the provider's error for that status |
| `outage` | `--status` (503) | the provider's 503 (or 502) |
| `rate_limit` | `--retry-after` (60), `--no-retry-after-header` | the provider's 429 with its rate headers |
| `quota_exhausted` | `--status`, `--scope` | the provider's credit exhaustion; billed operations only |
| `auth_invalid` | `--status` | the provider's wrong-key answer |
| `malformed` | `--variant` `invalid_json`, `truncated`, `wrong_content_type`, `missing_field` | damages a success response |
| `connection_drop` | none | aborts the TCP connection before any byte |

Per provider, the faults render as the real provider does:

| Provider | `auth_invalid` | `rate_limit` | `quota_exhausted` | `outage` / 5xx |
| --- | --- | --- | --- | --- |
| Tavily | 401 `{"detail": {"error"}}` | 429 + `Retry-After`; keyless 429 `daily_cap_reached` | 432; `--scope paygo` 433; `--status 402` | `{"detail": {"error"}}` |
| Exa | 401 `INVALID_API_KEY` (no key: 402 x402 challenge); admin API 401 | 429 `RATE_LIMIT_EXCEEDED` | 402 `NO_MORE_CREDITS`; `--scope key`/`team` budgets | 503 `SERVICE_OVERLOADED`, tagged 5xx |
| Firecrawl | 401 `Unauthorized: Invalid token` | 429 + `Retry-After` | 402 | `{"success": false}`; `http_error --status 408 --scope processing_continues` = scrape resume |
| Parallel | 401 `{"code": 16}` (C.0/C.1); Account API gateway 401; OAuth `invalid_client` | v1 envelope 429 + `Retry-After` | 402 v1 envelope (OAuth: 500) | v1 envelope; OAuth errors on `platform.parallel.ai` |
| You.com | gateway 403 `Forbidden` (no key: 402 `payment_required`); `api.you.com` 401 | gateway 429 + `X-RateLimit-*` | 402 `{"detail": "Insufficient credits"}`; `--scope key` 429 `spend_cap_exceeded` | AWS gateway or FastAPI bodies |
| Brave | edge 422 `SUBSCRIPTION_TOKEN_INVALID` | 429 `RATE_LIMITED` + ledger `X-RateLimit-*` | spent credit 402 `CREDIT_EXHAUSTED`; monthly header limit 429 `QUOTA_LIMITED`; `--scope spend_cap` 429 | 502/503/504 AWS ELB HTML page |
| Keenable | 401 `invalid_api_key` (`Malformed API key` without `keen_`) | 429 `rate_limit_per_second`; keyless `public_rate_limit_*` | 402 `insufficient_credits` | 500, 503 `auth_unavailable`, 529 `search_overloaded`, fetch 502/504 |
| Tinyfish | 401 `INVALID_API_KEY` / `MISSING_API_KEY` | 429 `RATE_LIMIT_EXCEEDED` + `X-RateLimit-*` | daily allowance 429 `RATE_LIMIT_EXCEEDED` (`free_allowance_exhausted`); wallet spending on: 402 `INSUFFICIENT_CREDITS` | 503 `BACKEND_UNAVAILABLE`, 500 `INTERNAL_ERROR` |

**Timeouts and SDK-owned clients.** The default hold (30 s) is longer than
Polyweb's default `POLYWEB_HTTP_TIMEOUT_SECONDS` (20 s), so adapters on the
shared client time out first (`timeout_error` or `transport_error`, both
retryable). The Exa SDK (`AsyncExa`) owns an HTTPX client with a 600 s
timeout, and the Firecrawl SDK sets no timeout at all: they wait for the
whole hold and then see the connection close, which Polyweb reports as a
retryable `transport_error`. A timeout never becomes a 504 by itself; add
`--status 504` to model an upstream gateway timeout. The end-to-end tests
`tests/e2e/test_{tavily,exa,firecrawl}_polyweb.py` cover each case.

## Scenario presets

`polyweb-mock scenario apply NAME` adds the preset's rules tagged with its
name; `scenario clear NAME` removes exactly those rules.

| Preset | Rules |
| --- | --- |
| `all-providers-down` | every operation answers 503 in its provider's format |
| `<provider>-down` | the same for one provider (one preset per plugin) |
| `slow-network` | +1.5 s latency plus up to 1 s jitter on every call |
| `flaky-10pct` | 5% HTTP 500, 3% HTTP 502, 2% dropped connections |
| `credits-exhausted` | every billed operation answers its credit exhaustion error |
| `rate-limit-storm` | half of all calls answer 429 with `Retry-After: 5` |

Add a preset as `src/polyweb_provider_mock/scenarios/<name>.json`:
`{"description": "...", "faults": [FaultSpec, ...]}`.

## Add a provider

1. Create `src/polyweb_provider_mock/providers/<name>.py` that exports
   `PLUGIN`, an instance of a `ProviderPlugin` subclass (discovery needs no
   central edit; modules whose name starts with `_` are helpers). Implement
   `operations()` (real method and path, operation name, `billable`,
   `keyless`, `scopes`, `hosts`, `log_body`), `credentials(request, store)`,
   `default_seed()`, `default_pricing()`, and `error(kind, context)` for every
   `ErrorKind` in the provider's real format. Optional hooks:
   `response_headers()` (include the real `Server` header), `not_found()`,
   `drop_required_field()`, `admin_routes()`, `admin_pages()`, `cli_commands()`.
2. In handlers, validate the request, bill with `context.charge()` (or
   `context.charge_all()` for a request billed in parts, all or nothing),
   spend provider rate windows with `context.admit()`, honour saved fixtures
   with `context.fixture()`, and set `context.match_key`. Keep extra state
   in `store.state(namespace)` and account facts in
   `store.set_account_attributes()`; never write SQL in a plugin.
3. Add the host to `PROVIDER_API_HOSTS` in Polyweb's
   `src/polyweb/infrastructure/provider_mock.py`.
4. Put sanitized recordings in `tests/contract/recordings/<name>/`, scrub the
   success bodies with `uv run python -m tests._support.scrub
   tests/contract/recordings/<name>/*.json`, and add a contract test like
   `tests/contract/test_tavily_contract.py` (shape helper:
   `tests._support.shape.assert_same_shape`). Add unit tests and an
   end-to-end test that drives the real Polyweb adapter through the shared
   `mock_server` fixture (`tests/conftest.py`).

`providers/base.py` documents the interface; `providers/tavily.py` is the
reference implementation.

## Accounts and funding

Each seeded account follows the provider's documented free tier (checked
against the official pricing and docs pages on 2026-11-19). An account spends,
in order: its **grant** (`credit_limit`, refilled by its reset rule and
forfeited at an expiry date when it has one), then its **prepaid** balance
(one-time credit that never resets: signup bonuses, purchased credit), then,
on a **postpaid** account, **overage** billed after use, cleared each period
and capped by `--overage-limit` when set. A prepaid account with nothing
left is refused with the provider's exhaustion error. Units are the
provider's own.

| Provider | Seeded account | Resets | Other seeded accounts and keys |
| --- | --- | --- | --- |
| Tavily | 1,000 credits | 1st of the month | 100 requests/min per account; `/usage` 10 per 10 min; PAYGO via `credits funding tavily postpaid` (433 at the cap) |
| Exa | $10 grant + $10 one-time bonus (grant spent first: undocumented) | grant on the 1st; bonus never | key `budgeted` ($0.05 budget, `API_KEY_BUDGET_EXCEEDED`); 10/5/100 QPS search/deep/contents |
| Firecrawl | 1,000 credits (Free) | monthly (calendar; real cycle anchor undocumented) | 10 RPM search and scrape; prepaid = coupon/purchased credit (in `remainingCredits`, not `planCredits`) |
| Parallel | $5 grant, card on file: postpaid, never blocked (spend limits only notify) | calendar month | account `parallel-no-card` (key `no-card`): prepaid, 402 at $0; 600/min search and extract |
| You.com | $100 (verified signup: $10 + $90), forfeited after 60 days | never | account `you-unverified` ($10, key `unverified`); key `capped` ($1 spend cap, 429); 10 rps per endpoint |
| Brave | $5 a month per plan: Search 1,000 requests, Answers 1,250 | 1st of the month (anchor undocumented) | the `X-RateLimit-*` monthly element stays `0` as recorded (`account set brave monthly_request_limit=N` to show one) |
| Keenable | 100,000 requests (free) | the organization's creation day (seeded: the 17th) | purchased credit is prepaid; keyless 1,000/hour and 10/second per endpoint per IP |
| Tinyfish | free: 12,000 searches and 1,000 successful fetch URLs a day | 00:00 UTC | wallet spending off: exhaustion is 429 `free_allowance_exhausted` (`wallet_spending=true` with no balance: 402) |

The dev stack keeps mock state on a volume, so expiry and resets happen as
they would live: after 60 days the You.com signup credit is gone. Run
`polyweb-mock seed --reset` (or `credits set you 10000`) to start over.
Paid plans are not seeded yet (TASK-000104).

## Fidelity

**Recorded**: live exchanges of 2026-11-17 and 2026-11-19 in `tests/contract/recordings`;
the contract tests replay each one and check the status, the important
headers, and the JSON shape. Success bodies are scrubbed (Brave's terms forbid
storing results): values are synthetic, the structure is real.
**Documented**: from the provider's public reference, without a capture.
**Inferred**: neither; chosen to be plausible and documented in the plugin.

| Provider | Recorded | Documented only | Inferred, known gaps |
| --- | --- | --- | --- |
| Tavily | search, extract, usage, keyless, 401/422/400 errors (15) | 432/433 exhaustion, 429, 100 RPM per account, PAYGO | keyed 429 body; extract credit carry as observed; keyless 500/day cap invented (its window is the UTC day; the recorded `Retry-After` was not) |
| Exa | search, contents, usage 401, x402 402 challenge, 401/400 (14) | admin usage success (TASK-000099), budgets, 503, 429 tags | 429/5xx/budget/revoked-key messages; synthetic company `entities` |
| Firecrawl | search, scrape, credit usage, 401/400 (12) | 402, 429, scrape resume (408) | 402/429/5xx/keyless-cap/DNS messages; keyless cap 50/day; `branding`/`product`/`menu`/`attributes` formats return no content |
| Parallel | search, extract, 401/422, balance 401 (10); OAuth device flow, token, refresh, revoke, balance, OAuth token refused on search (2026-11-19 capture, pinned in `tests/unit/test_parallel.py`) | apps, key minting, `access_denied`, `slow_down`, 402/403/429/5xx | expired-token gateway wording; JWTs signed HS256 (real: RS256) |
| You.com | search, contents, balance, 401/402/403/422 (14) | live-page pricing, spend cap, 60-day signup credit, 10 rps | revoked keys, 429 and spend-cap bodies, 5xx bodies; a key's spend cap never resets (billing period undocumented); keyless MCP endpoint out of scope |
| Brave | web search, LLM context, 400/422 (10) | rate-limit headers, plans, 429/402 envelope and codes (TASK-000101) | 429/402 `detail`/`meta` text, prepaid exhaustion status, revoked key, outage pages; Answers key on Web Search |
| Keenable | keyless search and fetch, 400s (8) | keyed paths, 401/402/403, retryable 5xx (TASK-000100) | keyed rate headers; keyless window per IP is the mock client's address (one shared limit behind a proxy); auto top-up, the 25 rps tier and the 1,000/month disposable-email tier not modelled |
| Tinyfish | 401 missing and bogus key on both hosts; search (web, news, research, filters), fetch (3 formats, options, per-URL errors), 400/403/405/422 (41); `/usage` fields and minute-slot accounting (2026-11-19, history not stored) | 402/429, 5xx, highlights success, `iframe_links`, conditional fetch, daily allowance, wallet spending, 60/min invalid-and-usage limit | 402/429/5xx bodies and the exhaustion `Retry-After`; JSON `format` heading/list nodes; 405 lacks `X-TF-User-ID`; overage price unpublished (0) |

## Checks

```bash
uv sync
uv run pytest -q -n auto            # unit, contract, and end-to-end tests
uv run ruff check . && uv run ruff format --check .
uv run mypy src
```
