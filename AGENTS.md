<!-- CODEGRAPH_START -->
## CodeGraph

In repositories indexed by CodeGraph (a `.codegraph/` directory exists at the repo root), reach for it BEFORE grep/find or reading files when you need to understand or locate code:

- **MCP tool** (when available): `codegraph_explore` answers most code questions in one call — the relevant symbols' verbatim source plus the call paths between them, including dynamic-dispatch hops grep can't follow. Name a file or symbol in the query to read its current line-numbered source. If it's listed but deferred, load it by name via tool search.
- **Shell** (always works): `codegraph explore "<symbol names or question>"` prints the same output.

If there is no `.codegraph/` directory, skip CodeGraph entirely — indexing is the user's decision.
<!-- CODEGRAPH_END -->

## UI unit tests

- In `freesearch-ui/src`, colocate each unit/component test with its source as `<basename>.test.ts` or `<basename>.test.tsx`; keep one canonical test file per source and never add suffix variants.
- When consolidating historical suites, keep each origin traceable as `describe("<old filename>", ...)` and preserve test titles, bodies, and assertions.
- Keep shared fixtures/helpers shared; deduplicate imports and change paths only when relocation requires it.
- Preserve the before/after Vitest case count, then run `pnpm depcruise`, `pnpm knip`, `pnpm lint`, `pnpm typecheck`, and `pnpm build` with zero new findings.
