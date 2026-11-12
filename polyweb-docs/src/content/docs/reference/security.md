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

## Report a problem

<!-- TODO(owner): Add the address or process for reporting security issues. -->

## Next steps

- [Configuration](/setup/configuration/) lists every environment variable.
- [Admin accounts](/setup/admin-accounts/) covers creating system admins.
