---
id: TASK-000067
title: Add concise cross-platform agent connection setup
status: Done
assignee:
  - codex
created_date: '2026-11-12T21:33:00Z'
updated_date: '2026-11-12T23:00:00Z'
labels: []
dependencies: []
type: docs
ordinal: 56000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
After Docker setup and project API-key creation, readers need brief instructions to connect Codex, Claude Code, or OpenCode from Windows, macOS, or Linux.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 Quick start leads from account and API-key setup into agent connection
- [x] #2 Built-in Starlight tabs present Windows, macOS, and Linux environment-variable commands before client-specific steps
- [x] #3 Codex, Claude Code, and OpenCode examples follow official documentation and link to their sources
- [x] #4 Documentation remains brief and passes docs build and typecheck
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
Delegate documentation to Claude Code Sonnet 5.5 at medium effort; review the resulting setup flow and platform syntax; run documentation build and typecheck.

5. Replace session-only API-key setup with persistent per-user Windows variables and macOS/Linux shell profiles, then rebuild the docs.
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Claude Code Sonnet 5.5 at medium effort wrote a shared ConnectAgent MDX component with OS tabs for the API key and client tabs for Codex, Claude Code, and OpenCode. Quick start now includes project and key creation before the shared instructions. Parent reviewed official syntax, specified the OpenCode project config filename, shortened prose, and repaired the README link after the MDX rename. pnpm typecheck and pnpm build pass (35 pages; existing content/sitemap warnings). Generated HTML for quick-start and mcp/connect has two tab groups and six panels with the expected commands. Prose structural check passes with no errors or warnings after excluding MDX imports and tags. Build outputs remain gitignored; Docker was untouched.

Replaced the temporary API-key export examples with persistent per-user setup: Windows User environment variable plus current-process reload, zsh .zshrc respecting ZDOTDIR, and Bash .bashrc plus source. Documented app restarts, login-shell behavior, and launching macOS/Linux agents from the shell. Added primary-source links. Docs typecheck and final build pass, as does the prose structural check.

Clarified the stdio section: Docker published ports serve HTTP, so HTTP is the default setup. The optional Docker stdio example starts a separate process with compose exec -T and requires Docker CLI access to the container. Updated checkout placeholders to polyweb-mcp and added --no-sync to the container command. Docs build and diff checks passed.
<!-- SECTION:NOTES:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
Added concise OS and client tabs to quick start and connection docs, then corrected API-key setup to persist across terminal sessions. Windows uses User-scoped environment settings; macOS and Linux use shell startup files. Official docs are linked. Docs typecheck, build, markup review, and prose structural checks passed. No host environment, Docker, commits, or pushes changed.
<!-- SECTION:FINAL_SUMMARY:END -->
