<!-- CODEGRAPH_START -->
## CodeGraph

In repositories indexed by CodeGraph (a `.codegraph/` directory exists at the repo root), reach for it BEFORE grep/find or reading files when you need to understand or locate code:

- **MCP tool** (when available): `codegraph_explore` answers most code questions in one call — the relevant symbols' verbatim source plus the call paths between them, including dynamic-dispatch hops grep can't follow. Name a file or symbol in the query to read its current line-numbered source. If it's listed but deferred, load it by name via tool search.
- **Shell** (always works): `codegraph explore "<symbol names or question>"` prints the same output.

If there is no `.codegraph/` directory, skip CodeGraph entirely — indexing is the user's decision.
<!-- CODEGRAPH_END -->

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
