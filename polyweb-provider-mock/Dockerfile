# Polyweb provider mock: development only, never part of the production stack.
#
# Build context is this folder:
#   docker build -t polyweb-provider-mock:dev polyweb-provider-mock
#   docker run --rm -p 127.0.0.1:8212:8212 -v polyweb-provider-mock:/data polyweb-provider-mock:dev
# The image installs only the runtime dependencies; the editable `polyweb`
# path dependency belongs to the dev group and is not needed here.
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

LABEL org.opencontainers.image.licenses="Apache-2.0"

WORKDIR /app

ENV PYTHONUNBUFFERED=1
ENV UV_COMPILE_BYTECODE=1
ENV UV_LINK_MODE=copy

COPY pyproject.toml uv.lock README.md ./
RUN --mount=type=cache,id=uv-cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project

COPY src/ ./src/
RUN --mount=type=cache,id=uv-cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

# The state database lives on a volume, owned by the unprivileged runtime user.
RUN useradd --system --uid 10001 --no-create-home --home-dir /app mock \
    && mkdir -p /data && chown mock:mock /data
ENV POLYWEB_PROVIDER_MOCK_HOST=0.0.0.0
ENV POLYWEB_PROVIDER_MOCK_PORT=8212
ENV POLYWEB_PROVIDER_MOCK_DB=/data/mock.db
USER mock

EXPOSE 8212
HEALTHCHECK --interval=10s --timeout=3s --retries=3 \
    CMD ["/app/.venv/bin/python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8212/_mock/health')"]
CMD ["/app/.venv/bin/polyweb-provider-mock"]
