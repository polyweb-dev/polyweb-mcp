---
title: Contributing
description: Set up a development environment and run the checks before you open a pull request.
---

Polyweb is a Python backend (`src/polyweb`), a React dashboard (`polyweb-ui`), and this docs site (`polyweb-docs`). Use a development machine and a disposable database. Never run these steps against a database that holds real keys.

## Repository layout

| Folder | What it holds |
| --- | --- |
| `src/polyweb/` | API server, MCP server, provider adapters, vault |
| `polyweb-ui/` | The dashboard (React) |
| `polyweb-docs/` | This documentation site (Astro Starlight) |
| `polyweb-landing/` | The marketing site |
| `tests/` | Unit, integration, and BDD tests |

## Run a development stack

Docker with the development override bind-mounts `./src` and needs a `.env` file with `POLYWEB_AUTH_JWT_SECRET` set:

```bash
docker compose -f compose.yaml -f compose.dev.yaml up --build -d
```

Stop it with:

```bash
docker compose -f compose.yaml -f compose.dev.yaml down
```

For a stack without Docker, follow [Manual setup](/setup/manual/).

## Use the development database

`scripts/seed_dev.py` creates `polyweb.dev.db` with five known accounts and three projects, so you can test member and admin flows without setting anything up. It makes no network calls and refuses to overwrite an existing file.

```bash
uv run python scripts/seed_dev.py
```

Then set this in `.env` and restart the API server and MCP server:

```dotenv
POLYWEB_DB=polyweb.dev.db
```

All five accounts use the public password `PolywebDev123!`. Set `POLYWEB_DEV_PASSWORD` before seeding to use another one. Never use this fixture for real data. The accounts are `admin1@example.com` and `admin2@example.com` (system admins) and `user1@example.com`, `user2@example.com`, and `user3@example.com` (regular users).

If `.env` contains provider keys such as `POLYWEB_EXA_API_KEY`, the script imports them into the vault and binds them to every project.

To start over, stop the servers and delete the files:

```bash
rm -f polyweb.dev.db polyweb.dev.db-wal polyweb.dev.db-shm polyweb.dev.db-journal
uv run python scripts/seed_dev.py
```

## Run the checks

Run the narrow check for what you changed while you iterate, then the wider ones before review.

Backend, from the repository root:

```bash
uv run pytest tests/unit -q
uv run ruff check src tests
uv run ruff format --check src tests
uv run mypy src
```

Dashboard, from `polyweb-ui`:

```bash
pnpm lint
pnpm typecheck
pnpm test
pnpm build
```

Docs, from `polyweb-docs`:

```bash
pnpm build
pnpm typecheck
```

Behave scenarios tagged `@live` call real providers and spend credits. Keep both exclusions when you filter tags:

```bash
uv run --no-sync behave --tags="not @live and not @latency"
```

## Work on the docs

```bash
cd polyweb-docs
pnpm install
pnpm dev
```

The docs server reads `POLYWEB_DOCS_PORT` and defaults to port 5284. The landing site (`polyweb-landing`) uses `POLYWEB_LANDING_PORT` and defaults to 5274, started with `pnpm dev` from that folder.

Write in plain second person, put the commands first, and keep one fact in one place. Do not paste real keys or `Authorization` values into any page.

## Troubleshooting

| Symptom | Cause | Fix |
| --- | --- | --- |
| API or MCP server will not start, asks for a port | Manual setup has no default ports | Set `POLYWEB_API_PORT` and `POLYWEB_MCP_PORT` in `.env` |
| `POLYWEB_AUTH_JWT_SECRET is required` | The secret is missing or short | Set 32 or more random bytes in `.env` |
| `seed_dev.py` refuses to run | The target file already exists or the environment is not development | Delete the old dev database or fix `POLYWEB_ENVIRONMENT` |
