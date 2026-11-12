# Polyweb docs

Markdown docs site for Polyweb, built with
[Starlight](https://starlight.astro.build/getting-started/).
Pages live in `src/content/docs/` as Markdown/MDX files.

## Run

```sh
pnpm install
pnpm dev
```

The dev server reads `POLYWEB_DOCS_PORT` from the repo-root `.env` file
and defaults to `5284` when unset. Shell values beat `.env` values:

```sh
POLYWEB_DOCS_PORT=5285 pnpm dev
```

Other ports for reference: UI `5174`, landing `5274`, API `8001`, MCP `8000`.

## Build and check

```sh
pnpm build      # static output in polyweb-docs/dist
pnpm preview    # serve the production build
pnpm typecheck
```

## Write pages

- Add a Markdown file under `src/content/docs/<section>/`.
- Keep language simple: short steps, one idea per sentence.
- Add a screenshot only where it helps. Store real dashboard screenshots in `src/assets/`.
- Add a copy-paste example for every call shown.
- Register new sections in the `sidebar` list in `astro.config.mjs`.
