# FreeSearch

FreeSearch is a provider-neutral async search and document-fetching application.
The foundation and shared adapter contracts are complete. The Stage 2 shared
resilience layer is also implemented; the other platform worktrees and provider
implementations in [`WORKPLAN.md`](WORKPLAN.md) remain deferred.

## Local development

The project uses [`uv`](https://docs.astral.sh/uv/).

```powershell
uv sync
uv run pytest
uv run ruff check .
uv run mypy src
```

Copy `.env.example` to `.env` to customize local settings. Real provider keys
should preferably be entered through the planned settings dashboard, which will
use the operating-system keyring locally. For deployment, inject secrets via
the environment or a dedicated secret manager. Never commit `.env`, keys, or
dashboard exports.
