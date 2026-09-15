# Stage 1: Build React frontend SPA
FROM node:22-bookworm-slim AS frontend-builder

WORKDIR /app/ui

RUN corepack enable && corepack prepare pnpm@latest --activate

COPY freesearch-ui/package.json freesearch-ui/pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile

COPY freesearch-ui/ ./
RUN pnpm build

# Stage 2: Production Python runtime
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

WORKDIR /app

ENV UV_COMPILE_BYTECODE=1
ENV UV_LINK_MODE=copy

# Default container runtime settings
ENV FREESEARCH_HOST=0.0.0.0
ENV FREESEARCH_API_PORT=8001
ENV FREESEARCH_MCP_PORT=8000
ENV FREESEARCH_DATA_DIR=/data
ENV FREESEARCH_DB=/data/freesearch.db
ENV FREESEARCH_STATIC_DIR=/app/static
ENV FREESEARCH_SECRET_STORE=database
ENV PYTHON_KEYRING_BACKEND=keyring.backends.null.Keyring

# Copy dependency definitions for layer caching
COPY pyproject.toml uv.lock ./

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project --no-dev

# Copy backend source
COPY src/ ./src/
COPY README.md .env.example ./

# Install application
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

# Copy compiled frontend SPA from Stage 1
COPY --from=frontend-builder /app/ui/dist /app/static

# Persistent data directory
RUN mkdir -p /data
VOLUME ["/data"]

EXPOSE 8000 8001

CMD ["uv", "run", "freesearch-all"]
