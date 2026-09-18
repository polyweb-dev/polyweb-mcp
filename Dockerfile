# FreeSearch production image (multi-target).
#
# Targets:
#   backend — Python API + MCP server (default).
#   ui      — nginx serving the built React dashboard (Docker-only; local dev
#             keeps using `pnpm dev` with the Vite proxy, no nginx involved).
#
# The same file builds both Compose services, so `docker compose up --build`
# just works:
#   docker build --target backend -t freesearch:latest .
#   docker build --target ui -t freesearch-ui:latest .

# --------------------------------------------------------------------------
# Stage 1: build the React dashboard to static files.
# --------------------------------------------------------------------------
FROM node:24-slim AS ui-build

# Docker is non-interactive: never prompt, and match the local toolchain.
ENV CI=true

WORKDIR /ui

# Install pnpm, then dependencies first for optimal layer caching.
RUN npm install -g pnpm@11
COPY freesearch-ui/package.json freesearch-ui/pnpm-lock.yaml freesearch-ui/pnpm-workspace.yaml ./
RUN --mount=type=cache,id=pnpm-store,target=/pnpm/store \
    pnpm install --frozen-lockfile --store-dir /pnpm/store

# Build the static bundle (VITE_API_URL stays empty → same-origin calls,
# so nginx can reverse-proxy /api/* to the backend with no rebuild per env).
COPY freesearch-ui/ ./
RUN pnpm build

# --------------------------------------------------------------------------
# Stage 2: Python runtime with the FreeSearch package installed.
# --------------------------------------------------------------------------
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS backend

WORKDIR /app

ENV PYTHONUNBUFFERED=1
ENV UV_COMPILE_BYTECODE=1
ENV UV_LINK_MODE=copy
# Headless container: no D-Bus/desktop keyring service available.
ENV PYTHON_KEYRING_BACKEND=keyring.backends.null.Keyring

# Dependency layer first for optimal Docker layer caching.
# --no-dev: production image skips pytest/behave/mypy/ruff (dev group).
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,id=uv-cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project

# Runtime source: package, migrations (alembic.ini points at
# src/freesearch/persistence/migrations), and README (hatchling wheel metadata).
COPY src/ ./src/
COPY alembic.ini README.md ./

RUN --mount=type=cache,id=uv-cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

# Persistent state (SQLite DB + master-key file) lives here in Compose via a
# named volume; override with FREESEARCH_DB / FREESEARCH_ENCRYPTION_KEY_FILE.
RUN mkdir -p /data
ENV FREESEARCH_DB=/data/freesearch.db
ENV FREESEARCH_ENCRYPTION_KEY_FILE=/data/.secret_key

EXPOSE 8001 8000

# Default: REST API. Compose overrides the mcp service command with
# `freesearch-mcp --transport streamable-http --host 0.0.0.0 --port 8000`.
CMD ["uv", "run", "freesearch-api", "--host", "0.0.0.0", "--port", "8001"]

# --------------------------------------------------------------------------
# Stage 3: nginx serving the built dashboard + proxying the API.
# Docker-only: local development uses `pnpm dev`, never this.
# --------------------------------------------------------------------------
FROM nginx:alpine AS ui

COPY --from=ui-build /ui/dist /usr/share/nginx/html
COPY docker/nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80
