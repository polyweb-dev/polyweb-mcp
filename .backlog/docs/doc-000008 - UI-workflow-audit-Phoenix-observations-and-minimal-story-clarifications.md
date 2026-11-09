---
id: doc-000008
title: UI workflow audit - Phoenix observations and minimal story clarifications
type: guide
created_date: '2026-10-30T19:47:00Z'
updated_date: '2026-10-30T19:50:00Z'
tags:
  - ui
  - projects-first
  - audit
---
# UI workflow audit

Audit date: 2026-10-30. Scope: current FreeSearch UI, project specification, and open UI stories.

## Conclusion

The stories support the intended project workflow. They do not require a major rewrite.

The main gap concerns Activity acceptance criteria. Project isolation alone does not specify how a user finds and inspects a request.

The current trace inspector provides a strong basis for the intended experience.

## Reference method

We used the self-hosted Phoenix v21.0.0 interface in a desktop browser.

We did not inspect Phoenix or Langfuse source code, bundles, stylesheets, or repositories. We did not inspect Langfuse during this audit.

We read the public Phoenix setup documentation and REST API schema for the synthetic data upload.

Two independent agents reviewed the FreeSearch UI and API contracts. A Luna agent produced the initial synthetic data script.

The new [freesearch-ui-audit-demo project](http://localhost:6006/projects/UHJvamVjdDoz) contains 40 synthetic traces, 140 spans, and nine fake sessions.

The data includes successes, failures, fallback, and parallel attempts. No external provider request occurred.

The script is `scripts/seed_phoenix_demo.py`. Repeated uploads append synthetic data.

## Phoenix observations

- The project workspace keeps project identity and local tabs visible.
- A shared time control applies to the project views. The trace table and traffic chart share the workspace.
- The populated table shows compact rows, outcome icons, latency, input/output previews, and a Load More control.
- The trace inspector keeps the list context visible. It separates the trace tree from the selected span.
- The selected span exposes input, output, attributes, events, and latency.
- The fallback example shows a successful request with a failed provider attempt. Each outcome remains distinct.
- A filter for failed root spans reduced the list to six failed requests. The URL retained the filter.
- The Metrics tab shows volume and latency percentiles. The Sessions tab groups related traces.
- Restrained surfaces, compact controls, aligned data, and status colors define the visual hierarchy.

These observations concern behavior and appearance. They do not specify a copy of Phoenix assets or implementation.

## FreeSearch evidence

| Area | Source | Assessment |
| --- | --- | --- |
| Project context | `freesearch-ui/src/app/ProjectWorkspace.tsx:30` | An account/project key provides an isolation boundary |
| Project routes | `freesearch-ui/src/app/ProjectWorkspace.tsx:37` | Only overview and members currently have routes |
| Activity list | `freesearch-ui/src/features/activity/model/useActivityController.ts:47` | Current UI loads 50 traces with an operation filter |
| Trace inspection | `freesearch-ui/src/features/activity/ui/TraceDetailDialog.tsx:50` | Current inspector supports results, provider attempts, errors, and a timeline |
| Inspector panes | `freesearch-ui/src/features/activity/ui/TraceInspectionWorkspace.tsx:191` | Current timeline and span detail use separate panes |
| Playground | `freesearch-ui/src/features/playground/model/usePlaygroundController.ts:128` | Search and fetch share a controller |
| Visual system | `freesearch-ui/src/index.css:8` | Shared surfaces, restrained accents, named fonts, and tabular numerals |

The project routes remain unfinished UI work. This does not indicate a specification defect.

The code review identifies foundations and gaps. It does not certify the unfinished project screens through a live FreeSearch browser session.

## API limits

The project trace endpoint supports limit, operation, outcome, and cursor. It does not support query, provider, or date-range filters.

Trace detail provides ordered spans and permitted input/output. Trace policy can remove payloads.

Trace summaries deliberately omit query and output payloads. Phoenix-style list previews need a contract review before implementation.

Project dashboard and usage endpoints return project usage totals and recent ledger rows. They exclude shared provider quota and health.

A shared upstream balance is not the project's remaining allowance. The contract does not provide time buckets or latency percentiles for selected intervals.

Evidence: `src/freesearch/routers/observability.py:37` and `src/freesearch/models/observability.py:345`.

Identity, API-key, provider, settings, copy-preview, and allocation contracts support the U1 and U3 story intent.

U3 correctly retains its dependency on the unfinished fair-capacity work.

## Minimal story changes

- TASK-000046: one criterion preserves shared controls and visible project/screen context at two desktop sizes.
- TASK-000047: two criteria specify Activity filters, cursor pagination, retained list context, and current inspector views.
- TASK-000002: one criterion requires the same project inspector and clear absent-payload states. It now depends on TASK-000047.
- TASK-000048 and TASK-000049: no criteria or dependencies changed.

All original descriptions and acceptance criteria remain. Status, priority, and completion checks remain unchanged.

This audit does not replace the project specification or an implementation plan.

TASK-000002 remains separate work. The project release does not currently depend on that Playground details enhancement.

## Recommendations without new release requirements

Retain the current design tokens. Favor dense tables and an inspector with clear selected and failed states.

Keep the selected project visible. Preserve keyboard focus and list context when the inspector closes.

Use explicit absent-payload states for metadata-only traces. Do not treat absent payloads as empty successful results.

Display project usage totals and recent rows with their actual scope and units.

Later analytics work can add date filters, time buckets, chart-to-list navigation, and latency percentiles through explicit API contracts.

A trace-to-Playground rerun needs request options that trace detail does not fully retain. Do not promise exact replay from an input string alone.

LLM prompts, evaluations, experiments, datasets, and chat sessions are outside the current project specification.

## Verification

Phoenix accepted the OTLP protobuf payload with HTTP 200. The browser displayed 40 traces, nine sessions, latency metrics, and provider-attempt inspection.

The script passed Ruff lint and format checks. Narrow payload checks cover IDs, parent references, timestamps, and root outcomes.

No application source or project dependencies changed. The audit did not run full application test suites.

## References

- [Phoenix setup documentation](https://arize.com/docs/phoenix/tracing/how-to-tracing/setup-tracing/setup-using-phoenix-otel)
- [Local Phoenix REST API schema](http://localhost:6006/openapi.json)
- Project specification: doc-000002, sections 8 and 9. Delivery gates: doc-000003.
