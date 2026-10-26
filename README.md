# FreeSearch

FreeSearch is a provider-neutral search, content extraction, and quota-orchestration platform. It aggregates multiple search and web-scraping providers behind a unified REST API, Model Context Protocol (MCP) server, and modern React dashboard.

---

## Supported Providers

- **Brave Search** (Search & Summarizer / Answers)
- **Exa** (Search & Content Fetch)
- **Firecrawl** (Web Scrape / Fetch)
- **Tavily** (Search & Extract)
- **Parallel** (Search & Fetch with OAuth balance tracking)
- **You.com** (Search & Fetch)
- **Keenable** (Search with rolling-hour keyless tier or API key)
- **Tinyfish** (Search & Markdown Fetch)

---

## Prerequisites

Ensure you have the following installed on your system:

- **Python**: `>= 3.12, < 3.14`
- [**uv**](https://docs.astral.sh/uv/): Fast Python package and virtual environment manager
- [**Node.js**](https://nodejs.org/): `>= 20.x`
- [**pnpm**](https://pnpm.io/): Frontend package manager (`corepack enable pnpm` or `npm i -g pnpm`)

---

## Getting Started

### 1. Clone the Repository

```bash
git clone <repository-url>
cd freesearch
```

### 2. Environment Configuration

Copy the example environment file:

```bash
# On Linux/macOS
cp .env.example .env

# On Windows PowerShell
Copy-Item .env.example .env
```

Keep `.env` for non-secret runtime settings. Store provider credentials in the encrypted vault through the settings dashboard (the same encrypted-vault API the dashboard itself uses). Keenable can remain keyless.

Local account authentication needs one more entry in that file: `FREESEARCH_AUTH_JWT_SECRET`. Supply at least 32 random bytes. A secret is required to log in, access protected routes, and validate an optional Bearer token on Search/Fetch; anonymous Search/Fetch does not need one. The gitignored `.env` file holds the real value, and `.env.example` holds an empty placeholder. The operator account CLI does not need that value.

Full account rules, limits, token lifetimes, and the rollback procedure: [docs/releases/local-users.md](docs/releases/local-users.md).

---

### 3. Backend Setup & Dependencies

Install all Python dependencies and set up the local virtual environment using `uv`:

```bash
uv sync
```

This installs both core runtime and development dependencies (FastAPI, Alembic, SQLAlchemy, Behave, Pytest, Ruff, Mypy, etc.).

---

### 4. Database Setup & Migrations

FreeSearch uses SQLite for telemetry, quota snapshots, runtime settings, and provider health. The default database path is `freesearch.db` (override with the `FREESEARCH_DB` environment variable).

FreeSearch includes a dedicated database management CLI tool (`freesearch-db`):

- **Check migration & schema status:**
  ```bash
  uv run freesearch-db status
  ```

- **Create or validate the database:**
  ```bash
  uv run freesearch-db upgrade
  ```
  *(Note: a missing or empty database is created at the alpha baseline revision `0001_alpha_baseline`; a database already at the baseline is validated. There are no incremental migrations and no automatic backup.)*

> **Alpha reset:** The alpha keeps no compatibility with databases from earlier revisions. The backend, MCP server, and CLIs refuse such a database without changing it and print reset steps: stop FreeSearch, move or delete the database file together with its `-wal`/`-shm` side files (or point `FREESEARCH_DB` at a new path), and start again. Accounts, provider credentials, and settings must then be entered again.

#### Local account bootstrap

Accounts have no role or account type. Public registration creates an ordinary human account with no system role and no project membership. System authority comes only from an explicit `system_admin` assignment, which the operator CLI creates and removes by explicit account UUID:

```bash
uv run freesearch-users create-admin --email admin@example.com
uv run freesearch-users grant-system-admin --user-id <account-uuid>
uv run freesearch-users revoke-system-admin --user-id <account-uuid>
uv run freesearch-users deactivate --user-id <account-uuid>
```

`create-admin` reads the password from a masked terminal prompt, refuses a password argument, and prints only the account UUID and the system role outcome. The commands require a database file that is present, so run `freesearch-db upgrade` first. A failed grant leaves an ordinary account, and the command reports that state. `revoke-system-admin` and `deactivate` refuse to remove the last active system administrator, and `deactivate` (CLI and `POST /api/v1/users/{id}/deactivate`, which answers `409 LAST_SYSTEM_ADMIN`) refuses to leave any project (archived ones included) without an active project administrator. Every system role change and deactivation writes a system audit event.

---

### 5. Frontend Setup

The dashboard UI is located in the `freesearch-ui` directory.

```bash
cd freesearch-ui
pnpm install
```

---

## Running with Docker (homelab / LAN)

There is no prebuilt image on Docker Hub yet, so you clone the repo and build locally:

```bash
git clone <repository-url>
cd freesearch
cp .env.example .env   # optional, non-secret settings only

# First build takes a few minutes (Python deps + UI bundle), later runs are cached.
docker compose up --build -d
docker compose ps
docker compose logs -f   # Ctrl+C to detach from logs; containers keep running
```

- **Dashboard:** `http://<host>:3000` (nginx serves the built UI and proxies `/api`, `/search`, `/fetch`, `/dashboard`, `/stats` to the API — nginx is Docker-only, local dev keeps using `pnpm dev`)
- **API + Swagger:** `http://<host>:8001/docs`
- **MCP for coding agents (streamable HTTP):** `http://<host>:8000/mcp`

  ```json
  { "type": "streamable-http", "url": "http://<host>:8000/mcp" }
  ```

  STDIO cannot be served over a network (the client must spawn the server), so remote agents must use the URL above. STDIO remains a local-only option on the Docker host itself: `docker exec -i freesearch-mcp uv run freesearch-mcp --transport stdio`.

To stop everything (state is kept): `docker compose down`.

### Development with Docker

This starts the dashboard, API, and MCP server together for local development.

Before you start:

- Start Docker Desktop.
- Make sure this worktree has a `.env` file. On Windows,
  `scripts/windows/create_worktree.bat` copies it from the main checkout.
- Add provider API keys through the dashboard, not `.env`.

Docker reads `.env` when it starts the containers. It does not copy the file into
an image or store it in the `freesearch-data` volume.

From the repository root, run:

```bash
docker compose -f compose.yaml -f compose.dev.yaml up --build -d
```

Open:

- Dashboard: `http://localhost:3000`
- API documentation: `http://localhost:8001/docs`
- MCP server: `http://localhost:8000/mcp`

Check that the containers are running:

```bash
docker compose -f compose.yaml -f compose.dev.yaml ps
```

To stop the app:

```bash
docker compose -f compose.yaml -f compose.dev.yaml down
```

The plain `down` command keeps your saved data and API keys, so you do not need
to enter them again. Using `down -v` wipes all local data, so your keys must be
re-entered.

To check the Compose files without printing their contents, run
`docker compose -f compose.yaml -f compose.dev.yaml config --quiet`. Never share
the output of plain `docker compose config`: it prints your real API keys.

After rotating an API key with its provider, enter the new key once in the
dashboard.

### Encryption key (random, automatic)

Provider keys are encrypted in SQLite with a master key. On first start the containers auto-generate a random 32-byte key and store it as `/data/.secret_key` on the shared volume (readable only by the container, mode `0600`). There is nothing to configure.

Back it up once, so a lost volume doesn't mean re-entering every provider key:

```bash
docker cp freesearch-api:/data/.secret_key ./freesearch-secret-key.bak
```

Keep that file somewhere safe (password manager / offline backup) — whoever holds it can decrypt your vault, and without it (or the volume) stored keys are unrecoverable and must be re-entered via the dashboard.

### Persistent data

`api` and `mcp` share one SQLite database and the key file on the `freesearch-data` **named volume** (`/data/freesearch.db`, `/data/.secret_key`). Single-node only — do not scale replicas without moving off SQLite.

- `docker compose down` / rebuilds / image updates all **keep** the volume: your keys, quotas, and telemetry survive.
- `docker compose down -v` **deletes** it. You will have to re-enter provider keys afterwards.
- Back up any time (Linux/macOS):
  ```bash
  docker run --rm -v freesearch_freesearch-data:/data -v "$(pwd):/backup" \
    alpine tar czf /backup/freesearch-data-backup.tar.gz -C /data .
  ```
  Windows PowerShell:
  ```powershell
  docker run --rm -v freesearch_freesearch-data:/data -v "${PWD}:/backup" `
    alpine tar czf /backup/freesearch-data-backup.tar.gz -C /data .
  ```
  Restore into a fresh volume with the reverse (`tar xzf`), then `docker compose up -d`.
  (The `freesearch_` volume prefix follows the project folder name — check yours with `docker volume ls` if you cloned into a different directory.)

Store provider keys in the encrypted vault via the dashboard — never in `.env` or the Compose file.

## Running the Services (local development)

### Start the REST API Backend

From the project root:

```bash
uv run freesearch-api
```

- **API URL:** `http://127.0.0.1:8001`
- **Interactive Swagger Docs:** `http://127.0.0.1:8001/docs`
- **Alternative ReDoc:** `http://127.0.0.1:8001/redoc`

### Local accounts and access control

`POST /search` and `POST /fetch` always require a credential; there is no anonymous execution. They accept either a human access JWT (the browser session; the request must name a `project_id` where the account is an active member) or a project API key (see [Project API keys](#project-api-keys)). All other REST routes, including projects, members, API key management, provider controls, account management, and trace reads, accept only a human access JWT; a project API key is rejected there with HTTP 401. The MCP transport exposes only the Search and Fetch tools and accepts only project API keys.

- **Register:** `POST /auth/register` with `{"email": ..., "password": ...}` creates an active ordinary account with no role and returns no token. A request that also sends a role, privilege, or status field is rejected with HTTP 422.
- **Log in:** `POST /auth/jwt/login` with the OAuth2 form (`username` holds the email) returns `access_token`, `refresh_token`, `token_type`, `expires_in`, and `refresh_expires_in`.
- **Refresh:** `POST /auth/jwt/refresh` takes the opaque refresh credential in the Bearer header and rotates it once. A second use of a consumed credential revokes that family.
- **Log out:** `POST /auth/jwt/logout` revokes the current family, so its access and refresh credentials stop at once.
- **Current account:** `GET /users/me` returns the account record (identity, provider, profile and status fields) without the password hash and without any role or privilege flag.
- **Authority:** every decision reloads scoped role assignments. A `system_admin` assignment governs installation-wide controls (provider controls, provider OAuth, account provisioning, project creation) and confers no project membership. Project authority comes only from an active project membership and its project roles (`project_admin`, `project_member`, and the extra `routing_editor`, `provider_editor` and `token_manager` roles). Every project keeps at least one active human `project_admin`; removals, demotions, suspensions and account deactivations that would break this fail with `409 LAST_PROJECT_ADMIN`. On project-scoped routes (project, members, roles, API keys) an unknown project and a caller who is not an active member get the same `404`; a member without the needed permission gets `403`.
- **Provider usage:** Search and Fetch still pass through provider quota and rate admission and use the server's configured provider credentials. These limits and provider budgets are shared across callers; there is no per-caller spend cap.
- **Public documentation:** `/docs`, `/redoc`, and `/openapi.json` are accessible anonymously without authentication.
- **Limits:** 5 pair attempts and 20 peer-address attempts per 900 seconds for login, 5 peer-address attempts and 100 deployment attempts per 900 seconds for registration, and a 4096-byte cap on a public auth body.
- **Token lifetime:** 900 seconds for an access JWT and 604800 seconds for the absolute refresh family. An ordinary API call and an ordinary MCP call never extend a token.

The API and the MCP transports read `FREESEARCH_API_PORT` and `FREESEARCH_MCP_PORT` from the gitignored `.env` file, so a launch command never hardcodes a port. The full account rules and the release procedure are in [docs/releases/local-users.md](docs/releases/local-users.md).

### Project API keys

REST machine clients and MCP clients authenticate with a project API key instead of a user account. A key belongs to one project, holds only the `search.execute` and/or `fetch.execute` scopes, and never inherits any role of the person who created it. Browser and playground calls use the human session and project membership and never need a key.

- **Format:** `fs_live_<prefix>_<secret>`. The 12-character `prefix` is public and identifies the key in lists and audit records; the secret has 256 bits. Only a SHA-256 verifier of the secret is stored. Send the key only in `Authorization: Bearer <key>`, never in a URL.
- **Issue:** `POST /api/v1/projects/{project_id}/api-keys` with `{"label": ..., "scopes": [...], "expires_at": ...}` returns `201` with the key metadata and the raw `key`. The raw key appears only in this response and in a rotation response. Omitted `scopes` grants both scopes; an empty or unknown scope is `422`. **Omitted `expires_at` means the default lifetime of 90 days from issue; an explicit `"expires_at": null` means no expiration;** a past timestamp is `422`.
- **List:** `GET /api/v1/projects/{project_id}/api-keys` returns `id`, `label`, `prefix`, `scopes`, `created_by`, `created_at`, `expires_at` (`null` = no expiration), `revoked_at`, `last_used_at`, `rotated_from_id` and `status` (`active`, `expired` or `revoked`).
- **Rotate:** `POST /api/v1/projects/{project_id}/api-keys/{key_id}/rotate` with optional `{"overlap_seconds": 0..604800, "expires_at": ...}` returns `201` with a new key of the same label and scopes. Omitted `expires_at` keeps the old key's lifetime (no expiration stays no expiration); `null` means no expiration. The old key stays valid for `overlap_seconds` (default 86400, never beyond its own expiry); `0` revokes it at once. Rotating a revoked, expired or already rotated key is `409 API_KEY_INACTIVE`.
- **Revoke:** `DELETE /api/v1/projects/{project_id}/api-keys/{key_id}` returns `204`, also when the key is already revoked.
- **Permissions:** managing keys needs `tokens.manage` in the project (`project_admin` or `token_manager`) and a human session; a non-member gets `404`, a member without `tokens.manage` `403`. A key cannot carry authority its issuer lacks: every requested scope must be among the issuer's own live project permissions, and rotation requires the rotating person to hold every scope of the key (`403` otherwise). `token_manager` grants no execution, so pair it with `project_member` (or hold `project_admin`) to issue keys. A key id of another project is `404`. An archived project cannot issue or rotate keys (`409 PROJECT_ARCHIVED`).
- **Execution:** with a key, `project_id` in a Search or Fetch request is optional; when given it must name the key's project, otherwise the call is `404`. An unknown, malformed, expired or revoked key is a generic `401`; a missing scope is `403`; an archived project is `409`. Every rejection happens before any provider access, and the key, its revocation, expiry and scope are checked again on every REST request and every MCP tool call.
- **Audit:** issue, rotation and revocation write project audit events, and a rejected use of an existing key writes a system security event identified by its prefix. Security events and `last_used_at` stamps are written off the request path by one background writer (at most one event per key and reason per 60 seconds per process; a full queue of 1024 drops the write with a prefix-only warning). No raw key or verifier is ever logged, traced or audited.

### Start the Frontend Dashboard

In a separate terminal, navigate to `freesearch-ui` and start the Vite dev server:

```bash
cd freesearch-ui
pnpm dev
```

- **Dashboard UI:** `http://localhost:5173`
- The Vite development server automatically proxies API requests (`/search`, `/fetch`, `/dashboard`, `/stats`, `/api`) to the backend at `http://127.0.0.1:8001`. Set `VITE_BACKEND_URL` (shell environment or `freesearch-ui/.env`) to point the proxy at a different backend origin for a session, e.g. `VITE_BACKEND_URL=http://127.0.0.1:8003 pnpm dev -- --port 5175`.

### OpenTelemetry traces (Search / Fetch)

Every `POST /search` and `POST /fetch` — the only provider-querying routes — produces one
OpenTelemetry trace with a stable `trace_id`:

```text
POST /search                SERVER root (selective ASGI middleware, X-Trace-Id header)
├─ freesearch.backend       INTERNAL, request handling
│  ├─ freesearch.route      INTERNAL, candidate planning
│  ├─ freesearch.provider   CLIENT, one per attempted/fanout provider (request/response events)
│  │  ├─ freesearch.provider.http   CLIENT, Keenable outbound request
│  │  └─ freesearch.provider.parse  INTERNAL, Keenable JSON + normalization
│  └─ freesearch.results    INTERNAL, result assembly (single projection or RRF fusion)
└─ freesearch.response      INTERNAL, encoded response send
```

Monitoring reads (`/stats`, `/dashboard`), the trace read API, health/control routes, and
static UI requests are never traced. Fanout is always one trace with concurrent provider
children; a handled provider failure marks that child `error` and the root `partial`.

- **Instrumentation facade:** `src/freesearch/infrastructure/observability.py` is the only
  instrumentation module importing `opentelemetry.*`; the persistence exporter
  (`persistence/otel_exporter.py`) is the second and last permitted OTel boundary (PLAN §2.1)
  because it maps SDK span objects onto the trace table. Routes, services, and adapters never
  import `opentelemetry.*` — they call `current_observability()`. The provider is app-scoped
  (never `trace.set_tracer_provider`), so repeated `create_app()` compositions and per-test
  databases stay isolated.
- **Persistence:** finished spans are exported by
  `src/freesearch/persistence/otel_exporter.py` into the SQLite `trace_spans` table
  (Alembic revision `0003_open_telemetry_spans`). Root rows double as the Activity summary.
  Exports are batched, so the middleware flushes once per traced request after the root span
  ends — that is what makes the row visible without a refresh.
- **Read API:** `GET /api/v1/traces` returns the account's own summary rows only (no query,
  no results); `GET /api/v1/traces/{trace_id}` returns the full input, tagged output, and
  ordered stage timeline. An absent, foreign-owned, or historical unowned trace gives the
  same `404`. Every root span carries the verified account UUID in `freesearch.user.id`.
- **Correlation:** every traced response carries `X-Trace-Id: <32-lowercase-hex>` (including
  handled error responses) matching the detail API's `trace_id`.
- **Activity UI:** the Activity page lists those traces and discloses query in, results out,
  per-stage latency, and errors behind an explicit **View details** control.

#### Configuration

| Variable | Default | Meaning |
| :--- | :--- | :--- |
| `FREESEARCH_OTEL_PROCESSOR` | `database` | `database` persists spans locally; `none` disables tracing (no-op runtime, no `X-Trace-Id`). |
| `FREESEARCH_OTEL_SERVICE_NAME` | `freesearch` | `service.name` resource attribute on every span. |

#### Future exporter seam (OTLP / Langfuse / LangSmith)

`build_span_processors(settings, database)` in
`src/freesearch/infrastructure/observability.py` is the single registration point for span
exporters. Adding an OTLP, Langfuse, or LangSmith exporter means appending a
`SpanProcessor` there (optionally driven by the standard `OTEL_EXPORTER_OTLP_*` variables);
no route, service, or adapter call site changes. Span attributes and events already use
OpenTelemetry HTTP semantic conventions plus provider-neutral `freesearch.*` keys with a
`freesearch.trace.schema_version` marker, so a vendor exporter can consume them unchanged.

#### Local content and retention

Trace content (query text, URLs, normalized result snippets/scores, fetched document text)
is stored **as-is and locally** so the Activity page can show what was actually sent and
received. It is not sent anywhere, and it persists with the SQLite database until the rows
are deleted; there is deliberately no automatic purge yet (the partial root-start index
keeps an age-based purge cheap to add). Credentials, API keys, `Authorization`/`Cookie`
headers, arbitrary request headers, and configured secrets are never captured — the single
redaction hook `trace_content_attributes(...)` drops any credential-, header-, cookie-, or
token-shaped key (including nested ones) before a span attribute, event, or row is written.

### Start the Model Context Protocol (MCP) Server (Optional)

If integrating with AI agents, IDE assistants, or tools supporting Model Context Protocol:

```bash
# Default: streamable HTTP transport on http://127.0.0.1:8000
uv run freesearch-mcp

# Stateless HTTP mode (ideal for stateless proxies and microservices):
uv run freesearch-mcp --transport streamable-http --stateless

# Stdio transport (ideal for desktop clients like Claude Desktop, Cursor, Gemini):
uv run freesearch-mcp --transport stdio
```

- Exposes provider-neutral `search` and `fetch` tools with automatic route selection and quota tracking.
- MCP accepts only [project API keys](#project-api-keys); human JWTs and anonymous calls are rejected. The tools' `project_id` is optional and, when given, must name the key's project.
- The HTTP transport requires `Authorization: Bearer fs_live_...` on every `/mcp` request (HTTP 401 otherwise), and every tool call uses the key principal verified on the HTTP request that carried it, then re-reads the key at the execution boundary, so revocation, expiry, archive and scope changes stop a persistent session at its next call. Unknown paths remain guarded.
- The stdio transport reads the project API key from `FREESEARCH_MCP_BEARER_TOKEN` (the process credential channel) and verifies it at each tool call; without it every tool call is rejected. The HTTP transport never reads this variable. Do not give the child a human or refresh credential.
- Transports and flags can also be configured via `FREESEARCH_MCP_TRANSPORT` (`stdio` or `streamable-http`) and `FREESEARCH_MCP_STATELESS` (`true`/`false`).

---

## Quality & Testing

### Backend Checks

```bash
# Run unit and integration tests
uv run pytest

# Run BDD feature scenarios (default run excludes @live; includes the offline @latency gate)
uv run behave tests/bdd/features

# Linting and formatting checks
uv run ruff check .
uv run ruff format --check .

# Static type checking
uv run mypy src
```

### Routing Latency Checks

FreeSearch must add under 80 ms at p95, per provider, for a warm search and a warm fetch
over both REST and MCP. FreeSearch latency is measured server-side: from the request
reaching the FreeSearch app until its response leaves it, minus provider time. The Behave
latency scenarios serve the real REST app and the MCP Streamable HTTP app with uvicorn on
`127.0.0.1` using OS-assigned ports, call them over TCP, and wrap each served app in a
timing middleware. Each request pins one provider; per request the report lists
`server_ms` (inside the app), `provider_ms` (the adapter call), the gated
`added_ms = server_ms - provider_ms`, and, reported only, the client `wall_ms`,
`client_overhead_ms = wall_ms - server_ms`, and database reads per request (never
pass/fail). Brave has no fetch, so Brave fetch rows are reported as N/A (skipped).

- **Offline gate (default suite):** `tests/bdd/features/routing_latency.feature` (`@latency`)
  uses instant fake adapters that mirror each provider's capability flags and limit rail,
  so provider time is near zero. It runs in every default `uv run behave` run
  (5 warmup + 30 measured requests per row) and writes
  `test_reports/routing_latency_offline.{csv,md}`.
- **Server-side profiles (opt-in):** set `FREESEARCH_LATENCY_PROFILE=1` to profile every
  measured request with pyinstrument; combined sessions per transport are written to
  `test_reports/routing_latency_<mode>_<rest|mcp>_profile.{html,txt,pyisession}`. Profiling
  adds overhead, so use the unprofiled run for the latency numbers.
- **Live performance checks (opt-in, real credits):** `@live` scenarios never run by
  default — `pyproject.toml` sets `[tool.behave] default_tags = ["not @live"]`, and an
  explicit `--tags` replaces that default. The one command for the live latency checks
  (and a later CI job) is:

  ```bash
  uv run behave --tags="@live and @latency"
  ```

  Each provider runs only when its key is set in the process environment:
  `FREESEARCH_BRAVE_SEARCH_API_KEY`, `FREESEARCH_EXA_API_KEY`,
  `FREESEARCH_FIRECRAWL_API_KEY`, `FREESEARCH_PARALLEL_API_KEY`,
  `FREESEARCH_TAVILY_API_KEY`, `TINYFISH_API_KEY`, `FREESEARCH_YOU_API_KEY`. Keenable is
  keyless and runs only with `FREESEARCH_RUN_LIVE=1` (an optional
  `FREESEARCH_KEENABLE_API_KEY` selects its keyed rail). A provider without its variable
  is skipped with a reason naming the variable, never its value. Sample counts default to
  1 warmup + 5 measured requests per row; override them with
  `FREESEARCH_LATENCY_LIVE_WARMUP` and `FREESEARCH_LATENCY_LIVE_SAMPLES`. Requests are
  spaced to each provider's documented per-second/per-minute rate windows. Results land in
  `test_reports/routing_latency_live.{csv,md}`.

### Frontend Checks

Inside `freesearch-ui`:

```bash
# Run unit tests (Vitest)
pnpm test

# Type checking
pnpm typecheck

# Linting
pnpm lint

# Production build validation
pnpm build
```

---

## Project Structure

```
freesearch/
├── src/freesearch/          # Core backend package
│   ├── adapters/            # Search & fetch provider adapters
│   ├── infrastructure/      # Foundation, resilience, secrets/keyring
│   ├── mcp/                 # Model Context Protocol server & tools
│   ├── models/              # Canonical contracts & Pydantic models
│   ├── persistence/         # SQLite storage, Alembic migrations & CLI
│   ├── routers/             # FastAPI search, fetch, & control routes
│   └── services/            # Routing policy, monitoring, quota tracking
├── freesearch-ui/           # React 19 + Vite + Tailwind CSS dashboard
├── tests/                   # Test suite (unit, integration, and BDD features)
├── pyproject.toml           # Python dependencies and CLI entrypoints
└── uv.lock                  # Pinned Python dependency graph
```
