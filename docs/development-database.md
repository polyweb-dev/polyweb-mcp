# Reproducible local development database

Use this fixture to test project workflows with a known set of users, memberships,
and provider bindings. Run commands from the repository root.

## Create and select the database

Keep the local settings, signing secret, ports, and provider API keys in the
gitignored `.env`. The import variable names are listed in `.env.example`.

```powershell
uv run python scripts/seed_dev.py
```

The script creates `freesearch.dev.db` at the current schema. It refuses an
existing file, a different database filename, a symbolic link, leftover SQLite
sidecars, or an environment other than `development`. It ignores `FREESEARCH_DB`
when choosing its output, so an existing setting cannot redirect the seed into
the normal database. It does not change `.env` itself.

Set this line in `.env`:

```dotenv
FREESEARCH_DB=freesearch.dev.db
```

Restart the backend and any MCP process with their normal commands:

```powershell
uv run freesearch-api
uv run freesearch-mcp
```

The commands use the worktree ports from `.env`. The UI uses the same backend
proxy as before; start it with `pnpm dev` from `freesearch-ui` if needed. Sign out
of the old browser session and sign in with a fixture account. Old session
cookies and saved project URLs refer to the previous database.

A process-level `FREESEARCH_DB` overrides `.env`. Clear that override or set it
to the dev database when switching. To return to the normal database, set
`FREESEARCH_DB=freesearch.db` and restart the backend and MCP.

## Accounts and membership matrix

All five accounts use the deliberately public local fixture password
`FreeSearchDev123!`. To use a different password, set `FREESEARCH_DEV_PASSWORD`
in the process environment or `.env` before creating the database. The script
does not print passwords. These accounts are for a disposable local environment.

| Account | System permission level | Alpha — Shared team | Beta — Single admin | Gamma — Admins only |
| --- | --- | --- | --- | --- |
| `admin1@example.com` | System admin | Project admin | No membership | Project admin |
| `admin2@example.com` | System admin | Project admin | Project admin | Project admin |
| `user1@example.com` | Regular user | Project member | Project member | No membership |
| `user2@example.com` | Regular user | Project member | Project member | No membership |
| `user3@example.com` | Regular user | No membership | Project member | No membership |

This gives Alpha two admins and two regular members, Beta one admin and three
regular members, and Gamma two admins without regular members. System authority
does not grant implicit membership: admin1 cannot open Beta's project screens.
Users receive no extra editor or token-manager roles.

Useful manual checks include last-admin refusal in Beta, removing one of Alpha's
two admins, adding an existing account to Gamma, regular-user control visibility,
and switching between projects and accounts. API-key lists, usage, and execution
history start empty so later test activity is easy to identify. The seed creates
no machine API keys; issue, rotation, and revocation can be tested through the UI.

## Provider credentials

The script imports nonempty provider keys from `.env`; a process variable of the
same name takes precedence. It creates one encrypted system credential for each
configured provider, grants it to all three projects, and creates an enabled
binding per project. Each binding enables the operations supported by its
provider; Brave supports Search only. All three projects use the same upstream
credentials and balances. The fixture does not invent quota pools or allocations.

Missing or blank keys are reported by provider name and skipped. The Tinyfish
import accepts `FREESEARCH_TINYFISH_API_KEY` or the legacy `TINYFISH_API_KEY`
spelling. `FREESEARCH_BRAVE_SEARCH_API_KEY` supplies Brave; the separate legacy
Answers key has no adapter in this runtime and is not imported. The normal app
continues to resolve credentials from its vault, not from these import variables.

Seeding makes no network requests and consumes no provider credits. It verifies
neither key validity nor upstream availability; later live Playground calls use
the real credentials. The script uses the application's encryption-key settings,
so launch the backend with the same settings. Keep the encryption key available
while using the database. The DB, SQLite sidecars, `.env`, and encryption key
files are gitignored.

## Recreate the fixture

Stop the API and MCP first. Delete only the disposable database and its SQLite
sidecars, then run the seed again:

```powershell
Remove-Item -LiteralPath .\freesearch.dev.db -ErrorAction SilentlyContinue
Remove-Item -LiteralPath .\freesearch.dev.db-wal -ErrorAction SilentlyContinue
Remove-Item -LiteralPath .\freesearch.dev.db-shm -ErrorAction SilentlyContinue
Remove-Item -LiteralPath .\freesearch.dev.db-journal -ErrorAction SilentlyContinue
uv run python scripts/seed_dev.py
```

Recreation discards manual changes in the dev database. IDs and password hashes
are new on each seed; account emails, project slugs, and memberships are stable.
Sign in again and select projects from the fresh list. A failed seed can leave a
partial dev database: remove it with the same stopped-backend procedure.

For a separate directory or env file, use
`--database <directory>/freesearch.dev.db --env-file <file>`. The directory must
already exist. The database must still have the exact dev filename.

## Verification

```powershell
uv run pytest tests/integration/scripts/test_seed_dev.py -q
uv run ruff check scripts/seed_dev.py tests/integration/scripts
uv run mypy scripts/seed_dev.py
```

The integration tests use temporary databases and fake provider keys. They cover
password login, system and project permissions, inaccessible memberships,
provider grants and enabled operations, encrypted persistence, foreign keys,
existing-file protection, and safe configuration-error output.
