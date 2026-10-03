/**
 * Activity trace fixtures: the trace read API wire shape with fixed, synthetic
 * ids and timestamps. Mirrors the backend fixtures in
 * `tests/fixtures/observability/*.json`, so unit, component, and E2E suites
 * assert the same success and error traces.
 *
 * Success trace:  e1c2…  search through keenable with two normalized results.
 * Error trace:    0f1e…  fetch whose provider stage failed.
 */

export const SUCCESS_TRACE_ID = "e1c2d3a4b5c6d7e8f9012345678abcde"
export const ERROR_TRACE_ID = "0f1e2d3c4b5a69788796a5b4c3d2e1f0"

const SUCCESS_STARTED_AT = "2026-09-29T09:15:00.000000Z"
const ERROR_STARTED_AT = "2026-09-29T09:20:00.000000Z"

function spanId(prefix: string): string {
  return `${prefix}00000000000000`.slice(0, 16)
}

/** Summary row for a successful search trace (list payload item). */
export function traceSummaryFixture(
  overrides: Record<string, unknown> = {}
): Record<string, unknown> {
  return {
    trace_id: SUCCESS_TRACE_ID,
    operation: "search",
    started_at: SUCCESS_STARTED_AT,
    duration_ms: 248,
    provider: "keenable",
    outcome: "success",
    result_count: 2,
    error: null,
    ...overrides,
  }
}

/** Summary row for a failed fetch trace. */
export function errorTraceSummaryFixture(
  overrides: Record<string, unknown> = {}
): Record<string, unknown> {
  return {
    trace_id: ERROR_TRACE_ID,
    operation: "fetch",
    started_at: ERROR_STARTED_AT,
    duration_ms: 512,
    provider: "keenable",
    outcome: "error",
    result_count: null,
    error: { type: "http_error", message: "HTTP 502" },
    ...overrides,
  }
}

/** `GET /api/v1/traces` payload: newest first. */
export function traceListFixture(
  overrides: Record<string, unknown> = {}
): Record<string, unknown> {
  return {
    items: [traceSummaryFixture(), errorTraceSummaryFixture()],
    generated_at: "2026-09-29T09:25:00.000000Z",
    ...overrides,
  }
}

/** Search stages with realistic offsets for the proportional timeline. */
const SUCCESS_SPANS: Record<string, unknown>[] = [
    {
      span_id: spanId("aa"),
      parent_span_id: null,
      name: "POST /search",
      stage: "Search request",
      kind: "server",
      started_at: SUCCESS_STARTED_AT,
      ended_at: "2026-09-29T09:15:00.248000Z",
      duration_ms: 248,
      outcome: "success",
      error: null,
      events: [],
    },
    {
      span_id: spanId("bb"),
      parent_span_id: spanId("aa"),
      name: "freesearch.backend",
      stage: "Backend handling",
      kind: "internal",
      started_at: "2026-09-29T09:15:00.004000Z",
      ended_at: "2026-09-29T09:15:00.240000Z",
      duration_ms: 236,
      outcome: "success",
      error: null,
      events: [],
    },
    {
      span_id: spanId("cc"),
      parent_span_id: spanId("bb"),
      name: "freesearch.provider",
      stage: "Provider request",
      kind: "client",
      started_at: "2026-09-29T09:15:00.020000Z",
      ended_at: "2026-09-29T09:15:00.228000Z",
      duration_ms: 208,
      outcome: "success",
      error: null,
      events: [
        {
          name: "freesearch.provider.request",
          timestamp: "2026-09-29T09:15:00.020000Z",
          attributes: { query: "distributed consensus algorithms", limit: 10 },
        },
        {
          name: "freesearch.provider.response",
          timestamp: "2026-09-29T09:15:00.228000Z",
          attributes: { result_count: 2 },
        },
      ],
    },
    {
      span_id: spanId("dd"),
      parent_span_id: spanId("cc"),
      name: "freesearch.provider.http",
      stage: "Provider HTTP call",
      kind: "client",
      started_at: "2026-09-29T09:15:00.022000Z",
      ended_at: "2026-09-29T09:15:00.224000Z",
      duration_ms: 202,
      outcome: "success",
      error: null,
      events: [],
    },
    {
      span_id: spanId("ee"),
      parent_span_id: spanId("cc"),
      name: "freesearch.provider.parse",
      stage: "Provider response parse",
      kind: "internal",
      started_at: "2026-09-29T09:15:00.224000Z",
      ended_at: "2026-09-29T09:15:00.226000Z",
      duration_ms: 2,
      outcome: "success",
      error: null,
      events: [],
    },
    {
      span_id: spanId("ff"),
      parent_span_id: spanId("bb"),
      name: "freesearch.results",
      stage: "Results assembly",
      kind: "internal",
      started_at: "2026-09-29T09:15:00.230000Z",
      ended_at: "2026-09-29T09:15:00.234000Z",
      duration_ms: 4,
      outcome: "success",
      error: null,
      events: [],
    },
    {
      span_id: spanId("12"),
      parent_span_id: spanId("aa"),
      name: "freesearch.response",
      stage: "Response to caller",
      kind: "internal",
      started_at: "2026-09-29T09:15:00.240000Z",
      ended_at: "2026-09-29T09:15:00.248000Z",
      duration_ms: 8,
      outcome: "success",
      error: null,
      events: [],
    },
  ]

/** `GET /api/v1/traces/{id}` payload for the successful search trace. */
export function traceDetailFixture(
  overrides: Record<string, unknown> = {}
): Record<string, unknown> {
  return {
    ...traceSummaryFixture(),
    input: "distributed consensus algorithms",
    output: {
      kind: "search_results",
      query: "distributed consensus algorithms",
      results: [
        {
          title: "Consensus algorithms explained",
          url: "https://docs.freesearch.dev/consensus",
          snippet: "Raft, Paxos, and where each applies.",
          source: "keenable",
          score: 0.94,
        },
        {
          title: "Raft vs Paxos",
          url: "https://docs.freesearch.dev/raft-vs-paxos",
          snippet: "A practical comparison.",
          source: "keenable",
          score: 0.81,
        },
      ],
    },
    spans: SUCCESS_SPANS.map((span) => ({ ...span })),
    ...overrides,
  }
}

/** Detail payload for the failed fetch trace (error callout + failed stage). */
export function errorTraceDetailFixture(
  overrides: Record<string, unknown> = {}
): Record<string, unknown> {
  return {
    ...errorTraceSummaryFixture(),
    input: "https://docs.freesearch.dev/getting-started",
    output: null,
    spans: [
      {
        span_id: spanId("21"),
        parent_span_id: null,
        name: "POST /fetch",
        stage: "Fetch request",
        kind: "server",
        started_at: ERROR_STARTED_AT,
        ended_at: "2026-09-29T09:20:00.512000Z",
        duration_ms: 512,
        outcome: "error",
        error: { type: "RuntimeError", message: "provider unavailable" },
        events: [],
      },
      {
        span_id: spanId("22"),
        parent_span_id: spanId("21"),
        name: "freesearch.provider",
        stage: "Provider request",
        kind: "client",
        started_at: "2026-09-29T09:20:00.006000Z",
        ended_at: "2026-09-29T09:20:00.500000Z",
        duration_ms: 494,
        outcome: "error",
        error: { type: "http_error", message: "HTTP 502" },
        events: [
          {
            name: "exception",
            timestamp: "2026-09-29T09:20:00.500000Z",
            attributes: { "exception.type": "ProviderOperationError" },
          },
        ],
      },
    ],
    ...overrides,
  }
}

