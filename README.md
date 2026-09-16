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

Keep `.env` for non-secret runtime settings. Store provider credentials in the encrypted vault:

```bash
curl -X PUT http://127.0.0.1:8001/api/v1/providers/exa/secret \
  -H 'content-type: application/json' \
  -d '{"key":"your-provider-key"}'
```

The settings dashboard uses the same encrypted-vault API. Keenable can remain keyless.

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

## Running the Services

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
