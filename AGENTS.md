<!-- CODEGRAPH_START -->
## CodeGraph

In repositories indexed by CodeGraph (a `.codegraph/` directory exists at the repo root), reach for it BEFORE grep/find or reading files when you need to understand or locate code:

- **MCP tool** (when available): `codegraph_explore` answers most code questions in one call — the relevant symbols' verbatim source plus the call paths between them, including dynamic-dispatch hops grep can't follow. Name a file or symbol in the query to read its current line-numbered source. If it's listed but deferred, load it by name via tool search.
- **Shell** (always works): `codegraph explore "<symbol names or question>"` prints the same output.

If there is no `.codegraph/` directory, skip CodeGraph entirely — indexing is the user's decision.
<!-- CODEGRAPH_END -->

## Testing Strategy
- **BDD Tests**: Do not always default or revert to BDD tests. Reserve BDD tests (`behave` on backend, `playwright-bdd` on frontend) strictly for end-to-end flows and scenarios critical to core functionality and user value. Do not write BDD tests for every obscure detail, minor permutation, or edge case.
- **Unit Tests**: Use unit tests to lock down code behavior. They should be fast, isolated, and exercise domain models, calculations, components, and functions directly with proper mocking of external dependencies.
- **Integration Tests**: Use integration tests to verify functionality through the layers, validating critical paths, cross-module communication, real database interactions, migrations, APIs, and edge cases.

## Multi-agent workflow efficiency
These rules for the orchestrator that are distilled from prior agent runs. Following them can save hours: most of the lost time came from strictly sequential agent runs and repeated full-suite runs.
- **Test narrowly while iterating.** Agents run only the test files that cover their change. Run the full `tests/unit tests/integration` suite at most once per agent round. Do not run a baseline full suite unless a regression comparison needs one.
- **Run Behave only when it matters.** Run it when BDD features or steps change, or at the final gate. Leave out the `@latency` scenarios in routine runs: `uv run --no-sync behave --tags="not @live and not @latency"`. Passing `--tags` replaces the default `not @live`, so keep it in the expression. Run them only when the request path changes and at the card's latency gate.
- **Batch feedback.** Review a whole agent round, then send all defects and rulings in one handoff. Ask agents for exact failing test IDs so the next round can run only those tests first.

## Cloud test runs (Woodpecker CI)

- **Local vs cloud**: run **unit tests locally**. All other suites (integration, BDD, latency, live, mutation) must run on Woodpecker CI — they execute on autoscaled GCP Spot workers so the VPS stays free.
- **Triggering**: the `executor` MCP server exposes a `woodpecker` integration. Discover tools inside `execute` with `tools.search({ namespace: "woodpecker", query: "..." })` and inspect shapes via `tools.describe.tool({ path })` before calling.
- **Single workflow**: `tools.woodpecker.org.agent.trigger_pipeline({ repo_id: 1, branch: "<branch>", workflow: "<name>" })` where `<name>` is a `.woodpecker/*.yaml` basename (e.g. `api-latency`). Omitting `workflow` runs ALL manual workflows — expensive (live provider calls, long mutation runs).
- The branch must be **pushed to origin**; local-only branches cannot be triggered. Monitor with `get_pipeline`, debug with `get_step_logs`, stop with `cancel_pipeline`.
- **Artifacts**: each workflow uploads `reports.zip` (log + `test_reports/`) to Gitea as generic package `freesearch-<workflow>` versioned `pipeline-<N>-r<reruns>-<ns>`. Download with `python3 scripts/gitea_packages.py download <pkg> <version> reports.zip` (lands in `.gitea-packages/`; `python` is unavailable — use `python3`).
- **Live suite**: CI has no provider secrets, so `@live` scenarios skip there. Run them locally and sparingly (they spend API credits): `FREESEARCH_RUN_LIVE=1 uv run --no-sync --env-file .env behave --tags="@live"`. The harness reads keys from the process env only. Tinyfish reads `FREESEARCH_TINYFISH_API_KEY` (legacy `TINYFISH_API_KEY` also accepted); blank values count as absent. Keyless Keenable scenarios always run without a key; keyed ones need `FREESEARCH_KEENABLE_API_KEY`.
- **api-latency step order**: the workflow runs the Behave latency feature before `pytest tests/integration/latency` under `set -e`, so the pytest gate only runs when every Behave scenario passes. The gate is p95 added latency under 150 ms; reports also record mean, p90, and p99. Offline added latency on CI is about 65–85 ms p50 and varies by spot agent.

## UI unit tests
- We only support desktop view, not the mobile view.
- In `freesearch-ui/src`, colocate each unit/component test with its source as `<basename>.test.ts` or `<basename>.test.tsx`; keep one canonical test file per source and never add suffix variants.
- When consolidating historical suites, keep each origin traceable as `describe("<old filename>", ...)` and preserve test titles, bodies, and assertions.
- Keep shared fixtures/helpers shared; deduplicate imports and change paths only when relocation requires it.
- Preserve the before/after Vitest case count, then run `pnpm depcruise`, `pnpm knip`, `pnpm lint`, `pnpm typecheck`, and `pnpm build` with zero new findings.

## Worktree Port Allocations

Each workspace/worktree has fixed, isolated ports defined in its root `.env` to prevent port collisions between concurrently running agents:

| Workspace | Worktree Directory | MCP Server (`FREESEARCH_MCP_PORT`) | Backend API (`FREESEARCH_API_PORT`) | UI Dev (`VITE_PORT`) |
| :--- | :--- | :--- | :--- | :--- |
| **Main** | `freesearch` | `8000` | `8001` | `5174` |
| **WT 1** | `freesearch_wt_1` | `8010` | `8011` | `5175` |
| **WT 2** | `freesearch_wt_2` | `8020` | `8021` | `5176` |
| **WT 3** | `freesearch_wt_3` | `8030` | `8031` | `5177` |
| **WT 4** | `freesearch_wt_4` | `8040` | `8041` | `5178` |

- **Zero hardcoding**: Always launch servers without hardcoded ports (e.g. `uv run freesearch-api`, `uv run freesearch-mcp`, `pnpm dev`). They automatically read from the local `.env`.
- **Zero merge conflicts**: Port configurations live in the local `.env` (gitignored), keeping committed files identical across all branches.

### Creating worktrees

- `scripts\windows\create_worktree.bat projects/p04-usage-trace-writers freesearch_wt_1 backend --base main`
- Ports are set from `--slot N` or the `freesearch_wt_N` folder name; new branches start from `--base` (default `main`).
- The live `freesearch.db` is not copied unless `--copy-db` (it holds provider credentials; tests must use fresh databases).
- Remove worktrees with `scripts\windows\delete_worktree.bat <branch>`.


<!-- BACKLOG.MD GUIDELINES START -->
<!-- backlog.md-instructions-version: 1.53.0 -->
<CRITICAL_INSTRUCTION>

## Backlog.md Workflow

This project uses Backlog.md for task and project management.

**At the beginning of each conversation in this project, run `backlog instructions overview` before answering or taking action. Re-read it only if you have not read it yet in the current conversation.**

Use the overview to decide whether to search, read, create, or update Backlog tasks.

Before task lifecycle actions, read the matching detailed guide:
- `backlog instructions task-creation` before creating or splitting tasks
- `backlog instructions task-execution` before planning, changing status or assignee, adding a plan or implementation notes, or implementing task work
- `backlog instructions task-finalization` before checking acceptance criteria, writing final summaries, or moving tasks to terminal statuses

Use `backlog <command> --help` before running unfamiliar commands. Help shows options, fields, and examples.

Do not edit Backlog task, draft, document, decision, or milestone markdown files directly. Use the `backlog` CLI so metadata, relationships, and history stay consistent.

</CRITICAL_INSTRUCTION>
<!-- BACKLOG.MD GUIDELINES END -->