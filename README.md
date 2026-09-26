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

- **Run migrations up to the latest revision:**
  ```bash
  uv run freesearch-db upgrade
  ```
  *(Note: `upgrade` automatically makes an integrity-verified pre-migration backup before applying schema changes, preserving existing data.)*

> **Tip:** You do not have to run `freesearch-db upgrade` manually every time. When the backend server starts, it will automatically verify the schema and run pending migrations up to Alembic head.

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

### Start the Frontend Dashboard

In a separate terminal, navigate to `freesearch-ui` and start the Vite dev server:

```bash
cd freesearch-ui
pnpm dev
```

- **Dashboard UI:** `http://localhost:5173`
- The Vite development server automatically proxies API requests (`/search`, `/fetch`, `/dashboard`, `/stats`, `/api`) to the backend at `http://127.0.0.1:8001`.

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
- Transports and flags can also be configured via `FREESEARCH_MCP_TRANSPORT` (`stdio` or `streamable-http`) and `FREESEARCH_MCP_STATELESS` (`true`/`false`).

---

## Quality & Testing

### Backend Checks

```bash
# Run unit and integration tests
uv run pytest

# Run BDD feature scenarios
uv run behave tests/bdd/features

# Linting and formatting checks
uv run ruff check .
uv run ruff format --check .

# Static type checking
uv run mypy src
```

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
