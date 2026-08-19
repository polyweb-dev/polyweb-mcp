# FreeSearch

FreeSearch is a provider-neutral async search and document-fetching application.
The project is prepared through stages 0 and 1 of [`WORKPLAN.md`](WORKPLAN.md),
plus the stage 2 usage/data repository. The foundation, shared contracts, and
async SQLite persistence layer are in place; provider implementations and the
remaining stage 2 platform work remain intentionally deferred.

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
