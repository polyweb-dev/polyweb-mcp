---
title: Back up and upgrade
description: Back up the database and master key, upgrade Polyweb, and reset an old database.
---

Polyweb keeps all of its state in one SQLite database and one master key file. Back up both together. A backup of the database without the key cannot decrypt your provider keys.

Polyweb runs as a single node. The API server and the MCP server share one database file, so do not run replicas.

## Where your data lives

| What | Docker | Manual setup |
| --- | --- | --- |
| Database (accounts, projects, vault, quotas, traces) | `/data/polyweb.db` on the `polyweb-data` volume | The `POLYWEB_DB` path |
| Master key that encrypts provider keys | `/data/.secret_key` on the same volume | `POLYWEB_ENCRYPTION_KEY_FILE`, by default `~/.local/share/polyweb/.secret_key` |

Whoever holds the master key and the database can read your provider keys. Keep backups somewhere private. If you lose the key or the volume, you must enter all provider keys again in the dashboard.

## Back up with Docker

Copy the master key out of the volume once, and again if you ever rotate it.

```bash
docker compose cp api:/data/.secret_key ./polyweb-secret-key.bak
```

Archive the whole volume whenever you want a snapshot. The volume name starts with your project folder name, so check yours with `docker volume ls`. For a clone in a folder named `freesearch`, it is `freesearch_polyweb-data`.

```bash
docker run --rm -v freesearch_polyweb-data:/data -v "$(pwd):/backup" alpine tar czf /backup/polyweb-data-backup.tar.gz -C /data .
```

For a consistent copy, stop the stack first with `docker compose stop`, then start it again with `docker compose start`.

## Back up a manual setup

Stop the API server and the MCP server, then copy the database file and the key file. SQLite may also keep `-wal` and `-shm` files next to the database, so copy those too if they exist.

## Stop, restart, and remove

```bash
docker compose logs -f
```

```bash
docker compose down
```

`docker compose down` keeps your data. Add `-v` to delete the volume.

```bash
docker compose down -v
```

`docker compose down -v` deletes the database, the master key, and every provider key. Run it only when you want a clean slate.

## Upgrade Polyweb

Pull the new code and rebuild. The database lives on the volume, so it survives the rebuild.

```bash
git pull
docker compose up --build -d
```

Take a backup first. The API server creates and checks the database when it starts, so you do not run `polyweb-db upgrade` in Docker. In a manual setup, run `uv sync` and `uv run polyweb-db upgrade` after pulling.

Check the schema at any time. Add `docker compose exec api` in front of the command to run it in Docker.

```bash
uv run polyweb-db status
```

### Reset an old database

Polyweb is in alpha and keeps no compatibility with databases from older revisions. If a new version cannot open your database, it refuses to start and prints a reset message. It changes nothing in the file.

To reset, stop Polyweb, then move or delete the database file and its `-wal` and `-shm` files. The next start creates a fresh database. You must create the admin account and enter provider keys again.

With Docker, the simplest reset is `docker compose down -v`, followed by `docker compose up -d`. Move the database file aside instead of deleting it if you want to keep a copy.

## Run behind a reverse proxy

Put an HTTPS reverse proxy in front of the dashboard, the API server, and the MCP server when you serve Polyweb beyond your own machine. Then set `POLYWEB_AUTH_BROWSER_ORIGINS`, `POLYWEB_AUTH_ISSUER_URL`, and `POLYWEB_MCP_RESOURCE_URL` to your public `https` addresses. See [Configuration](/setup/configuration/#sign-in-from-a-browser).

## Troubleshooting

| Symptom | Fix |
| --- | --- |
| Lock errors or slow writes | Two writers share one database file. Run a single node and stop the other writer. |
| Provider keys cannot be decrypted after a restore | The master key does not match the database. Restore both from the same backup. |
| The server prints a reset message | The database is from an older revision. Follow [Reset an old database](#reset-an-old-database). |
