---
title: Troubleshooting
description: Common errors and symptoms in Polyweb, with the cause and fix for each.
---

Find your symptom in the table for your area. Commands assume Docker, run from the repository folder. For a manual setup, replace `docker compose exec api` with the same command run directly, such as `uv run polyweb-users ...`.

## Start and sign in

| Symptom | Cause | Fix |
| --- | --- | --- |
| Sign in fails with "The server returned a refresh credential to the browser." | `POLYWEB_AUTH_BROWSER_ORIGINS` is empty or does not match the dashboard address | Set it to the exact origin as a JSON list, such as `["http://localhost:3000"]`, then run `docker compose up -d` |
| Sign in or register fails, or the API logs `POLYWEB_AUTH_JWT_SECRET is required for account authentication` | The signing secret is missing or shorter than 32 bytes | Set `POLYWEB_AUTH_JWT_SECRET` to 32 or more random bytes in `.env` (`openssl rand -hex 32`), then run `docker compose up -d` |
| Registration works but you cannot create a project | Registered accounts are ordinary users. Only system admins create projects | Create an admin with the command below, then sign in with it |
| `429` while signing in or registering | Rate limit on attempts (15-minute window) | Wait for the `Retry-After` time |
| `400` on sign in | Wrong email or password, or a deactivated account | Check the credentials. A system admin can tell you whether the account was deactivated |
| `422` on registration | Password outside 12 to 128 characters, or extra fields in the body | Send only `email` and `password` |
| Port already in use when running `docker compose up` | Another program uses 3000, 8001, or 8000 | Set `UI_PORT`, `API_PORT`, or `MCP_PORT` in `.env`, update `POLYWEB_AUTH_BROWSER_ORIGINS` if you changed `UI_PORT`, then run `docker compose up -d` |
| The dashboard returns `502` after you recreate the `api` container | The dashboard proxy lost the API server | Run `docker compose restart ui` |
| A container is unhealthy | The API server is still starting, or crashed | Run `docker compose logs api` and read the last error |

Create the first system admin once the API is up. The password is a masked prompt, so run it in an interactive terminal (piping a password fails, and the first run can take a few seconds):

```bash
docker compose exec api uv run polyweb-users create-admin --email admin@example.com
```

## Database

| Symptom | Cause | Fix |
| --- | --- | --- |
| `Polyweb cannot open the database ... reset required` | The file is from an older alpha, is unversioned, or is from a newer Polyweb version | For a newer version, use a compatible Polyweb. For an old file, stop Polyweb, move the database and its `-wal` and `-shm` files, or point `POLYWEB_DB` at a new path. Accounts, provider keys, and settings must then be entered again |
| `polyweb-users` fails because the database is missing | The API has not created the database yet | Wait for the API to start. In a manual setup, run `uv run polyweb-db upgrade` first |
| Provider keys no longer work after a restore | The database was restored without its matching master key | Restore `.secret_key` from the same backup, or enter the provider keys again |
| Everything is gone after `docker compose down -v` | `-v` deletes the `polyweb-data` volume, including the database and master key | Use `docker compose down` to keep data. Restore from a backup (see [Back up and upgrade](/setup/backup-and-upgrade/)) |

## Project API keys and agents

| Symptom | Cause | Fix |
| --- | --- | --- |
| `401` or `authentication is required` | Unknown, expired, or revoked key, or a dashboard token was used | Create a new project API key on the project's **API keys** page. Keys default to 90 days |
| `403` or `execution is not permitted` | The key lacks `search.execute` or `fetch.execute` | Create a key with the missing scope |
| `404` or `project is unavailable` | `project_id` names a different project than the key's | Drop `project_id` or use the key's own project |
| `409` or `project is archived` | The project is archived | Ask a project admin to unarchive it |
| MCP client cannot connect | Wrong URL or header | Use `http://localhost:8000/mcp` with `Authorization: Bearer fs_live_...`. Replace `localhost` for a remote server |
| MCP works but REST fails (or the reverse) | Different host or port | The API server is on 8001, the MCP server on 8000, and the dashboard on 3000 |
| Lost the key value | Keys are shown once | Rotate the key and use the new value |

See [Authentication and keys](/concepts/authentication/) for the full table of auth errors.

## Search and fetch results

| Symptom | Cause | Fix |
| --- | --- | --- |
| Provider error: no usable provider or key | The project has no enabled binding with a key for that operation | In the dashboard, add a provider key, put it in a key pool, bind the pool to the project, and turn the operation on. See [Provider keys and pools](/dashboard/provider-keys/) and [Project providers](/dashboard/project-providers/) |
| A new binding returns nothing | A new binding starts with no operations enabled | Enable `search` or `fetch` on the binding |
| `fetch` fails on Brave | Brave supports search only | Route `fetch` to another provider |
| `429` from a provider | Rate limit | Wait for `Retry-After`, then retry with backoff |
| `402` from a provider | Budget spent or no access | Top up, wait for the reset, or switch provider. Do not retry immediately |
| Results are `partial` in a fanout call | One provider failed | Read `waterfall` in the answer. See [Routing](/concepts/routing/) |
| Keenable works but another provider does not | Keenable has a keyless tier. Other providers need a key | Add that provider's key in the vault |

## Dashboard

| Symptom | Cause | Fix |
| --- | --- | --- |
| A page or menu item is missing | Your role lacks the permission, and the page is hidden | Ask a project admin for the role. See [Projects and roles](/concepts/projects-and-roles/) |
| `404` on a project you expect to see | You are not a member | Ask a system admin or project admin to add you |
| Dashboard loads but cannot reach the API | The API container is down or unhealthy | Run `docker compose ps` and `docker compose logs api` |
| Activity or Usage is empty | No calls recorded yet | Run a search from the Playground or with a project API key |
| Manual setup: the dashboard shows proxy errors | The dev server cannot reach the API server | Start the API server, and set `POLYWEB_API_PORT` or `VITE_BACKEND_URL` so the dev server finds it |

## Useful commands

```bash
docker compose ps
docker compose logs -f
docker compose logs api
docker compose config --quiet
```

`docker compose config` without `--quiet` prints your environment values, so do not share its output.

## Next steps

- [Configuration](/setup/configuration/) lists every environment variable and port.
- [Security](/reference/security/) covers the master key and secrets.
