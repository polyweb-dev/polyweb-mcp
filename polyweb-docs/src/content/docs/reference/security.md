---
title: Security
description: How Polyweb stores provider keys, what it never logs, and how to rotate the master key.
---

Polyweb holds provider keys for you, so it treats them as secrets from the moment you paste them in. This page covers where secrets live, what stays out of logs, and how to rotate the master key.

## Where secrets live

Provider keys are stored in the encrypted vault, never in `.env`. The vault encrypts each key with AES-256-GCM under a master key. In Docker, the master key is generated on first start and kept at `/data/.secret_key` on the `polyweb-data` volume with mode `0600`. With a manual setup, it defaults to `~/.local/share/polyweb/.secret_key`. You can point `POLYWEB_ENCRYPTION_KEY_FILE` at another path, or supply a passphrase with `POLYWEB_ENCRYPTION_KEY`.

The dashboard shows only a masked fingerprint of a stored key. Once saved, a key cannot be read back.

Polyweb does not read provider keys from `.env`. Add them in the dashboard instead.

## What Polyweb never records

- Raw project API keys. Security events log the key prefix only.
- `Authorization` and `Cookie` headers. Trace rows do not store them, nor any other request headers or configured secrets.
- Passwords. The CLI reads them from a masked prompt, and API responses never include a password hash.

Project API keys are checked on every call, so revoking one takes effect on the next request. See [Authentication and keys](/concepts/authentication/).

## Protect the master key

The database and the master key work as a pair. A backup of the database is useless without the matching key, and anyone who holds both can read your provider keys.

- Store backups of the database and the key in different places.
- Keep a copy of the key file. If you lose it, the stored provider keys cannot be decrypted and you must enter them again.
- Never share the output of `docker compose config`, which prints environment values. Use `docker compose config --quiet` to validate.

Back up the key from Docker with:

```bash
docker compose cp api:/data/.secret_key ./polyweb-secret-key.bak
```

For the full backup procedure, see [Back up and upgrade](/setup/backup-and-upgrade/).

## Rotate the master key

`polyweb-secrets` rewrites every stored secret under the current primary key inside one transaction. Keep the old key file (or the old passphrase) available while you rotate, because Polyweb needs it to read the existing secrets. Neither a key file nor a passphrase alone can decrypt a backup made with the other.

Check what needs rotating first, then rotate:

```bash
docker compose exec api uv run polyweb-secrets status
docker compose exec api uv run polyweb-secrets rekey --dry-run
docker compose exec api uv run polyweb-secrets rekey
```

`status` exits with a nonzero code while anything still needs rekeying or cannot be decrypted. No command prints secret values or key material.

<!-- TODO(owner): Document how to configure the new primary key and retire the old one (POLYWEB_ENCRYPTION_KEY_FILE, POLYWEB_ENCRYPTION_RETIRED_KEY_FILES, POLYWEB_ENCRYPTION_RETIRED_KEYS) with a verified end-to-end Docker example. -->

## Deploying beyond localhost

- Put the dashboard and API behind HTTPS. Outside loopback development, `POLYWEB_AUTH_ISSUER_URL`, `POLYWEB_MCP_RESOURCE_URL`, and browser origins must use `https`.
- Use a random `POLYWEB_AUTH_JWT_SECRET` of at least 32 bytes, and keep it out of version control.
- Polyweb runs as a single node with SQLite, so do not run replicas against one database.
- Plain HTTP for the MCP-to-API hop is acceptable only in the single-host Compose stack. See [MCP-to-API execution forwarding](#mcp-to-api-execution-forwarding).

## MCP-to-API execution forwarding

Unless `POLYWEB_EXECUTION_MCP_STANDALONE` is enabled, the MCP server does not run provider calls itself. For each search and fetch tool call, it forwards the request to the API's execution authority at `POLYWEB_EXECUTION_AUTHORITY_URL`, sending the caller's verified project API key as a bearer token. The API verifies that key again before it runs the call.

The execution authority URL is the one override that may use plain `http://`. The issuer and MCP resource URLs must use HTTPS outside loopback.

- Compose sets `http://api:8001`. The hop stays on the Docker bridge network of one host, and the project key is not encrypted on that hop. This is acceptable only for that single-host topology.
- Polyweb does not enforce where this URL points. The validator accepts plain HTTP to any host, so the setting will not stop you from sending keys to another machine.
- The API port is published on the host (`API_PORT`, 8001 by default) without a bind address, so it listens on every host interface. A client that calls the API directly sends its key over HTTP on loopback or your LAN.

If the MCP server and the API run on different hosts, or the path crosses a network you do not fully control, set `POLYWEB_EXECUTION_AUTHORITY_URL` to an `https://` URL. The API must present a certificate the MCP server can verify. The bundled Compose file serves the API over plain HTTP, so you need TLS in front of it in that case.

Cloud-hosted deployments need the same protection. The hardening work is tracked as TASK-000075. Until that work is done, do not run a cloud-hosted deployment with the plain HTTP setting.

## Report a problem

<!-- TODO(owner): Add the address or process for reporting security issues. -->

## Next steps

- [Configuration](/setup/configuration/) lists every environment variable.
- [Admin accounts](/setup/admin-accounts/) covers creating system admins.
