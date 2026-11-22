# Polyweb MCP landing

The marketing site for Polyweb — a standalone Vite + React app, separate
from the `polyweb-ui` dashboard.

## Run

```sh
pnpm install
pnpm dev
```

The dev server reads `POLYWEB_LANDING_PORT` from the repo-root `.env` and
defaults to `5274` when unset.

## Build and check

```sh
pnpm build      # outputs to polyweb-landing/dist
pnpm preview    # serve the production build
pnpm typecheck
pnpm lint
```

## Complexity report

The landing site does not have an automated test suite yet, so its Crapper report
contains complexity only; coverage and CRAP scores are `N/A`. From this directory,
run:

```sh
uv run --project .. --group crapper crapper --no-coverage src
```

This writes the landing site's snapshot to `polyweb-landing/.metrics/crap.edn`,
separate from the repository-root snapshot. The `.metrics` directory is ignored by
Git. Once the site has tests that produce LCOV coverage, Crapper can use that data
to calculate CRAP scores.
