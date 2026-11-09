# FreeSearch landing

The marketing site for FreeSearch — a standalone Vite + React app, separate
from the `freesearch-ui` dashboard.

## Run

```sh
pnpm install
pnpm dev
```

The dev server reads `FREESEARCH_LANDING_PORT` from the repo-root `.env` and
defaults to `5274` when unset.

## Build and check

```sh
pnpm build      # outputs to landing/dist
pnpm preview    # serve the production build
pnpm typecheck
pnpm lint
```
