---
id: TASK-000098
title: Verify the Windows stack scripts on a Windows host
status: To Do
assignee: []
created_date: '2026-11-17T10:00:00Z'
updated_date: '2026-11-17T10:00:00Z'
labels:
  - dev-tooling
  - windows
dependencies: []
references:
  - TASK-000097
  - scripts/windows/stack.bat
  - scripts/windows/delete_worktree.bat
  - scripts/windows/run_gremlin_mutation_docker.bat
priority: low
ordinal: 83000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
PR #79 (TASK-000097) renamed and rewrote the Windows dev scripts, but they were only reviewed, not run: no Windows host was available. The Linux equivalents were run end to end. Check them on Windows with Docker Desktop.

Scripts:
- scripts/windows/stack.bat: port of scripts/linux/stack.sh (npd|dev up/down/logs/ps, dev seed/cli/live).
- scripts/windows/delete_worktree.bat: step 1 now removes only this worktree's -npd, -dev and legacy -mock Compose projects by name, from %SystemDrive%\, never the pd project 'polyweb'.
- scripts/windows/run_gremlin_mutation_docker.bat: now builds docker/test/Dockerfile.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 stack.bat npd up starts api+mcp healthy on the worktree's loopback ports; down removes them
- [ ] #2 stack.bat dev up starts the mock, seeds polyweb.mock-dev.db once, and api+mcp come up healthy
- [ ] #3 stack.bat dev live runs the @live scenarios against the mock and they pass; a non *_API_KEY export line is rejected
- [ ] #4 stack.bat refuses a POLYWEB_STACK_PROJECT that does not end in -npd/-dev and a reserved host port
- [ ] #5 run_gremlin_mutation_docker.bat builds the image from docker/test/Dockerfile
- [ ] #6 delete_worktree.bat on a throwaway worktree removes only its polyweb-wtN-npd/-dev/-mock projects and volumes; the pd project 'polyweb' and its volume stay untouched
<!-- AC:END -->
