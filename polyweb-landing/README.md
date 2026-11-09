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
