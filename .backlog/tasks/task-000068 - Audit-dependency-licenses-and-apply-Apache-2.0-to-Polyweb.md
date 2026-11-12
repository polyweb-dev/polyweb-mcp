---
id: TASK-000068
title: Audit dependency licenses and apply Apache-2.0 to Polyweb
status: Done
assignee:
  - codex
created_date: '2026-11-12T23:19:00Z'
updated_date: '2026-11-12T23:41:00Z'
labels: []
dependencies: []
type: chore
ordinal: 57000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Prepare Polyweb for an Apache-2.0 public release. User confirms ownership of the application code and requests a GPT-6.1 Sol dependency audit, including AGPL and redistribution obligations. Bundled skill licenses remain separate pending user instructions.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 Dependency audit covers locked Python and JavaScript dependency graphs and distinguishes runtime from development tooling
- [x] #2 Audit identifies AGPL, GPL, other copyleft, uncertain licenses, and applicable redistribution obligations with sources
- [x] #3 Original Polyweb application code has Apache-2.0 licensing metadata and distributed license files
- [x] #4 Bundled skills and third-party materials retain their own terms and are not relicensed
- [x] #5 Packaging and licensing metadata are validated without changing unrelated work
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
Delegate the dependency license audit to GPT-6.1 Sol. Prepare Apache license text and explicit licensing scope. Review findings and address required attribution or packaging changes. Validate release artifacts and summarize any unresolved licensing issues.

5. Credit the three user-confirmed names and preserve JavaScript, font, Lucide, and Pagefind license texts in static builds.
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
User confirmed notices should name Sharath Chandra Nirmala, Abhishek Manohar, and Dhruv Thakkar. Added NOTICE and CONTRIBUTORS.md. Apache metadata and legal files now ship in Python packages and Docker source recipes. Restricted Python source-distribution selection to avoid skills and local tool caches. Auditor checked 1392 locked versions; report pending. Added automatic Vite dependency-license output and a shared postbuild copier for legal files, OFL fonts, full Lucide notices, and Pagefind license directory. UI, docs, and landing builds/typechecks passed; scoped config lint and copied-file validation passed. Docker was not rebuilt or restarted.

Final GPT-6.1 Sol audit reviewed 1392 locked versions (97 Python, 1295 npm), with 1231 license documents, 129 upstream source licenses, and 32 explicitly marked registry-only cases. No declared AGPL/GPL-only package was found. Remaining boundaries include base-image packages, unpinned toolchains, standalone asset provenance, and skill terms. Resolved generated-static notice gaps, including separately embedded mark.js 8.11.1. All three web builds/typechecks, scoped config lint, audit-script Ruff checks, Python wheel/sdist build, frozen lock validation, and exact artifact license-file comparisons passed. Docker state and unrelated skill edits were preserved.
<!-- SECTION:NOTES:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
Applied Apache-2.0 to original Polyweb application code with explicit skill and third-party exceptions. Copyright and contributor notices name Sharath Chandra Nirmala, Abhishek Manohar, and Dhruv Thakkar. Added reproducible dependency audit, report and complete inventory. No declared AGPL/GPL-only dependency was found; required MPL/LGPL/OFL and attribution considerations are documented. Static builds now retain JS, font, Lucide, Pagefind and embedded mark.js notices. Package and build validation passed. The report explicitly retains evidence gaps and binary/image/asset release checks, rather than claiming unconditional legal clearance. No commits or pushes.
<!-- SECTION:FINAL_SUMMARY:END -->
