---
title: Configuration
description: Every Polyweb environment variable, its default, and what it does.
---

Polyweb reads settings from environment variables. Values in the shell win over values in the `.env` file at the repository root. Create that file once with `cp .env.example .env`.

In Docker, Compose passes `.env` to the API server and the MCP server. After you edit it, run `docker compose up -d` to apply the change.

## What you must set

| Variable | Needed for | Notes |
| --- | --- | --- |
| `POLYWEB_AUTH_JWT_SECRET` | Accounts and sign-in | At least 32 bytes. Generate one with `openssl rand -hex 32`. |
| `POLYWEB_AUTH_BROWSER_ORIGINS` | Dashboard sign-in | Required. The exact address of the dashboard as a JSON list, such as `["http://localhost:3000"]`. |
| `POLYWEB_API_PORT`, `POLYWEB_MCP_PORT` | Manual setup only | No default. Docker sets its own ports. |

Provider keys never go in `.env`. Add them in the dashboard, where they are stored encrypted in the vault.

## Sign-in from a browser

The dashboard keeps its refresh credential in a strict cookie. The API server only sends that cookie to origins you list in `POLYWEB_AUTH_BROWSER_ORIGINS`. With an empty list, sign-in fails with "The server returned a refresh credential to the browser." If you change `UI_PORT`, change the origin to match.

List exact origins as a JSON array.

```dotenv
POLYWEB_AUTH_BROWSER_ORIGINS=["http://localhost:3000","https://search.example.com"]
```

Each entry is a scheme, host, and optional port. Wildcards, paths, and trailing slashes are rejected. Outside loopback addresses such as `localhost`, the origin must use `https`. If you open the dashboard at `http://127.0.0.1:3000`, list that origin instead of `localhost`, since they are different origins.

To serve Polyweb on a network, put an HTTPS reverse proxy in front of it. Then set the origin to your public address, and set `POLYWEB_AUTH_ISSUER_URL` and `POLYWEB_MCP_RESOURCE_URL` to your public `https` URLs.

## Ports and addresses

| Variable | Default | Meaning |
| --- | --- | --- |
| `UI_PORT` | `3000` | Docker host port for the dashboard. |
| `API_PORT` | `8001` | Docker host port for the API server. |
| `MCP_PORT` | `8000` | Docker host port for the MCP server. |
| `POLYWEB_API_HOST` | `127.0.0.1` | Address the API server binds to (manual setup). |
| `POLYWEB_API_PORT` | none | API server port (manual setup). |
| `POLYWEB_MCP_HOST` | `127.0.0.1` | Address the MCP server binds to (manual setup). |
| `POLYWEB_MCP_PORT` | none | MCP server port (manual setup). |
| `VITE_PORT` | `5174` | Dashboard dev server port (manual setup). |
| `VITE_BACKEND_URL` | `http://127.0.0.1:$POLYWEB_API_PORT` | API server the dashboard dev server proxies to. |

The Docker settings above change only the host side. Inside the containers the ports stay `80` (dashboard), `8001`, and `8000`.

## Storage

| Variable | Default | Meaning |
| --- | --- | --- |
| `POLYWEB_DB` | `polyweb.db` | Path of the SQLite database. Docker sets it to `/data/polyweb.db`, and `.env.example` sets `POLYWEB.db`. |
| `POLYWEB_ENCRYPTION_KEY_FILE` | `~/.local/share/polyweb/.secret_key` | File holding the master key for the vault. Docker sets it to `/data/.secret_key`. |

Docker forces both values, so changing them in `.env` has no effect there. The master key file is created on first start.

## Sign-in tokens

| Variable | Default | Meaning |
| --- | --- | --- |
| `POLYWEB_AUTH_JWT_LIFETIME_SECONDS` | `900` | Lifetime of an access token. |
| `POLYWEB_AUTH_REFRESH_LIFETIME_SECONDS` | `604800` | Lifetime of a sign-in session (seven days). It must be longer than the access token lifetime. |
| `POLYWEB_AUTH_ISSUER_URL` | none | Public `https` URL of the API server, for use behind a proxy. |
| `POLYWEB_MCP_RESOURCE_URL` | none | Public `https` URL of the MCP server, for use behind a proxy. |

## Providers, tracing, and logging

| Variable | Default | Meaning |
| --- | --- | --- |
| `POLYWEB_OTEL_PROCESSOR` | `database` | `database` stores traces in SQLite. `none` turns tracing off. |
| `POLYWEB_LOG_LEVEL` | `INFO` | Log level. |
| `POLYWEB_ENVIRONMENT` | `development` | `development`, `test`, or `production`. |
| `POLYWEB_HTTP_TIMEOUT_SECONDS` | `20` | Timeout for provider requests. |
| `POLYWEB_HTTP_CONNECT_TIMEOUT_SECONDS` | `5` | Connect timeout for provider requests. |
| `POLYWEB_HTTP_MAX_CONNECTIONS` | `20` | Size of the provider connection pool. |
| `POLYWEB_HTTP_MAX_KEEPALIVE_CONNECTIONS` | `10` | Idle connections kept open. |
| `POLYWEB_USER_AGENT` | `Polyweb/0.1` | User agent sent to providers. |
| `POLYWEB_PROVIDER_CONFIG_OVERRIDES` | none | One-line JSON that overrides a provider's `enabled`, `priority`, `free_tier_estimates`, or `reset_schedule`. |

Traces contain query text and fetched content, and they stay in the database until you delete them.

An override looks like this. Valid provider names are `exa`, `firecrawl`, `tavily`, `parallel`, `you`, `brave`, `keenable`, and `tinyfish`. A lower `priority` is preferred.

```dotenv
POLYWEB_PROVIDER_CONFIG_OVERRIDES={"exa": {"priority": 10, "reset_schedule": "monthly"}, "tavily": {"enabled": false}}
```

## Troubleshooting

| Symptom | Fix |
| --- | --- |
| The server refuses to start with a lifetime error | Make `POLYWEB_AUTH_REFRESH_LIFETIME_SECONDS` larger than `POLYWEB_AUTH_JWT_LIFETIME_SECONDS`. |
| The server refuses to start with an origins error | Use exact origins only, and `https` outside loopback. |
| A provider key in `.env` has no effect | Polyweb never reads provider keys from `.env`. Add them in the dashboard, where they are stored in the encrypted vault. |
