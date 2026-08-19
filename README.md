# FreeSearch

FreeSearch is a provider-neutral async search and document-fetching application.
The foundation, shared adapter contracts, and all Stage 2 core-platform worktrees
(Resilience, Usage/Data persistence, Routing, MCP surface, and Provider configuration)
are complete. Concrete provider implementations from [`WORKPLAN.md`](WORKPLAN.md)
are the next stage.

## Local development

The project uses [`uv`](https://docs.astral.sh/uv/).

```powershell
uv sync
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run mypy src
```

Copy `.env.example` to `.env` to customize local settings. Real provider keys
should preferably be entered through the planned settings dashboard, which will
use the operating-system keyring locally. For deployment, inject secrets via
the environment or a dedicated secret manager. Never commit `.env`, keys, or
dashboard exports.
