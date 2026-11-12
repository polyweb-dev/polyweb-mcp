---
title: Manual setup
description: Run the API server, the MCP server, and the dashboard directly with uv and pnpm instead of Docker.
---

Docker is the recommended way to run Polyweb, and it is what [Quick start](/quick-start/) covers. Use this page if you want to run each process yourself, for example to develop on Polyweb.

You need Python `>=3.12,<3.14`, [uv](https://docs.astral.sh/uv/), Node.js `>=20`, and [pnpm](https://pnpm.io/).

## Set up the environment

Without Docker, nothing sets ports for you. The API server and the MCP server read their ports from `.env` and refuse to start without them.

1. Clone the repository and create your `.env` file.

   ```bash
   git clone https://github.com/sharathnirmala16/freesearch.git
   cd freesearch
   cp .env.example .env
   ```

2. Set the signing secret, the two ports, and the dashboard origin.

   ```bash
   sed -i "s|^POLYWEB_AUTH_JWT_SECRET=.*|POLYWEB_AUTH_JWT_SECRET=$(openssl rand -hex 32)|" .env
   printf '\nPOLYWEB_API_PORT=8001\nPOLYWEB_MCP_PORT=8000\n' >> .env
   sed -i 's|^# POLYWEB_AUTH_BROWSER_ORIGINS=.*|POLYWEB_AUTH_BROWSER_ORIGINS=["http://localhost:5174"]|' .env
   ```

   On macOS, use `sed -i ''` instead of `sed -i`. The origin is a JSON list and is required for dashboard sign-in. It must match the address you open the dashboard at. The dashboard dev server listens on port `5174` unless you set `VITE_PORT`.

3. Install the Python dependencies and create the database.

   ```bash
   uv sync
   uv run polyweb-db upgrade
   ```

   The database path comes from `POLYWEB_DB`. The example file sets it to `POLYWEB.db` in the current directory. Keep one spelling, because `polyweb.db` and `POLYWEB.db` are different files on Linux.

4. Create the first admin. The command asks for a password once at a masked prompt, so use an interactive terminal. See [Admin accounts](/setup/admin-accounts/).

   ```bash
   uv run polyweb-users create-admin --email admin@example.com
   ```

## Start the servers

Run each command in its own terminal, from the repository root except for the last one.

```bash
uv run polyweb-api
```

```bash
uv run polyweb-mcp
```

```bash
cd polyweb-ui && pnpm install && pnpm dev
```

| Process | Address | Port setting |
| --- | --- | --- |
| API server and Swagger docs | `http://127.0.0.1:8001/docs` | `POLYWEB_API_PORT` |
| MCP server | `http://127.0.0.1:8000/mcp` | `POLYWEB_MCP_PORT` |
| Dashboard dev server | `http://localhost:5174` | `VITE_PORT` (default `5174`) |

The dashboard dev server proxies to the API server on `http://127.0.0.1:$POLYWEB_API_PORT`, or `http://127.0.0.1:8001` if that is unset. To point it elsewhere, set `VITE_BACKEND_URL` in the shell that starts `pnpm dev`.

The servers bind to `127.0.0.1`. Set `POLYWEB_API_HOST` or `POLYWEB_MCP_HOST` to listen on other interfaces.

Open `http://localhost:5174`, sign in, and continue with [Your first search](/guides/first-search/).

## Troubleshooting

| Symptom | Fix |
| --- | --- |
| `POLYWEB_API_PORT is required to start the api transport` | Set `POLYWEB_API_PORT` in `.env`, or pass `--port`. The MCP server needs `POLYWEB_MCP_PORT` the same way. |
| `POLYWEB_AUTH_JWT_SECRET is required for account authentication` | Set a secret of at least 32 bytes in `.env`. |
| Sign-in fails in the dashboard | `POLYWEB_AUTH_BROWSER_ORIGINS` must contain the exact address in your browser, for example `http://localhost:5174`. |
| A database reset message at startup | The file was created by an older build. See [Back up and upgrade](/setup/backup-and-upgrade/#reset-an-old-database). |
