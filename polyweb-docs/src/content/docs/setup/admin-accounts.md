---
title: Admin accounts
description: Create the first system admin and manage admin accounts with the polyweb-users command.
---

Anyone can register an account in the dashboard, but a new account is an ordinary user. Only the `polyweb-users` command can create a system admin, who can create projects and manage the installation. Run it on the machine that holds the database.

## Create the first admin

The command asks for the password once at a masked prompt, so it needs an interactive terminal, and piping a password in fails. Passwords are never passed as flags, and any password-style flag is refused.

With Docker (the first run can take a few seconds while `uv` syncs inside the container):

```bash
docker compose exec api uv run polyweb-users create-admin --email admin@example.com
```

With a manual setup, from the repository root:

```bash
uv run polyweb-users create-admin --email admin@example.com
```

The database must already exist. Docker creates it when the API server starts. In a manual setup, run `uv run polyweb-db upgrade` first. A successful run prints the account ID and the role.

```text
Account: 123e4567-e89b-12d3-a456-426614174000
System role: system_admin
```

## Manage admins and accounts

The other commands take an account ID, which is a UUID. Add `docker compose exec api` in front of each command when you use Docker.

Give an existing account the system admin role:

```bash
uv run polyweb-users grant-system-admin --user-id ACCOUNT_UUID
```

Remove the role:

```bash
uv run polyweb-users revoke-system-admin --user-id ACCOUNT_UUID
```

Deactivate an account. Repeat `--user-id` to deactivate several accounts in one change.

```bash
uv run polyweb-users deactivate --user-id ACCOUNT_UUID
```

By default the commands use the database from `POLYWEB_DB`. Point them at another existing file with `--database /path/to/polyweb.db`.

## Guard rails

The command refuses changes that would leave the installation without an owner:

- It will not revoke or deactivate the last active system admin.
- It will not deactivate an account if that leaves any project without an active project admin.

Grant the role to another account, or assign another project admin in the dashboard, and then try again.

## Troubleshooting

| Message or symptom | Fix |
| --- | --- |
| `a terminal is required for the masked password prompt` | Run the command in an interactive terminal. In Docker, do not add `-T`. |
| `do not pass a password on the command line` | Remove the password flag and type it at the prompt. |
| The database file is not found | Start the API server (Docker) or run `uv run polyweb-db upgrade` (manual). Check `--database` and `POLYWEB_DB`. |
| `the account id must be a UUID` | Copy the full account ID. |
| `no account has this id` | Check the ID. |
| `an account with this email address already exists` | Use `grant-system-admin` for the existing account. |
| `cannot change: the installation would lose its last active system administrator` | Grant the role to another account first. |
| `cannot deactivate: a project would lose its last active administrator` | Assign another project admin first. |
