/**
 * Activity trace fixtures: the trace read API wire shape with fixed, synthetic
 * ids and timestamps. Mirrors the backend fixtures in
 * `tests/fixtures/observability/*.json`, so unit, component, and E2E suites
 * assert the same success and error traces.
 *
 * Success trace:  e1c2…  search through keenable with two normalized results.
 * Error trace:    0f1e…  fetch whose provider stage failed.
 * Aggregated:     a1b2…  all-providers fanout (brave, keenable, tavily, exa,
 *                 firecrawl, youcom, parallel — incl. a failed `parallel`
 *                 attempt and empty responses that still carry provider,
 *                 hostile long URL token for wrapping proof).
 */

export const SUCCESS_TRACE_ID = "e1c2d3a4b5c6d7e8f9012345678abcde"
export const ERROR_TRACE_ID = "0f1e2d3c4b5a69788796a5b4c3d2e1f0"
export const AGGREGATED_TRACE_ID = "a1b2c3d4e5f60718293a4b5c6d7e8f90"

const SUCCESS_STARTED_AT = "2026-09-29T09:15:00.000000Z"
const ERROR_STARTED_AT = "2026-09-29T09:20:00.000000Z"
const AGGREGATED_STARTED_AT = "2026-09-29T09:10:00.000000Z"

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

/** Summary row for an aggregated all-providers fanout (two concurrent attempts). */
export function aggregatedTraceSummaryFixture(
  overrides: Record<string, unknown> = {}
): Record<string, unknown> {
  return {
    trace_id: AGGREGATED_TRACE_ID,
    operation: "search",
    started_at: AGGREGATED_STARTED_AT,
    duration_ms: 3381,
    provider: "aggregated",
    outcome: "success",
    result_count: 6,
    error: null,
    ...overrides,
  }
}

/** `GET /api/v1/traces` payload: newest first. */
export function traceListFixture(
  overrides: Record<string, unknown> = {}
): Record<string, unknown> {
  return {
    items: [
      aggregatedTraceSummaryFixture(),
      traceSummaryFixture(),
      errorTraceSummaryFixture(),
    ],
    generated_at: "2026-09-29T09:25:00.000000Z",
    ...overrides,
  }
}

/**
 * Hostile unbreakable token: a recorded CNBC quote URL with no natural break
 * points. Wrapping (not horizontal scrolling) is the acceptance behavior.
 */
export const LONG_HOSTILE_URL =
  "https://www.cnbc.com/quotes/.DJI?q=%5BDOW%2FUT%2B51_82%5D%5C%5C%2FOverdown%5C_-16_00-0_03%25%5C_%5CLAST%5C_%5B2_38_29%20AM%20EDT%5D%5B5%5Dhttps%3A%2F%2Fwww.cnbc.com%2Fquotes%2F%40DJ.IX%5D%5B5%8%26%2FUT%2B0_00%5D%5C_%5CLAST%5C_%5B2_48_08%20AM%20EDT%5D"

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
      name: "polyweb.backend",
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
      name: "polyweb.provider",
      stage: "Provider request",
      kind: "client",
      provider: "keenable",
      started_at: "2026-09-29T09:15:00.020000Z",
      ended_at: "2026-09-29T09:15:00.228000Z",
      duration_ms: 208,
      outcome: "success",
      error: null,
      events: [
        {
          name: "polyweb.provider.request",
          timestamp: "2026-09-29T09:15:00.020000Z",
          attributes: { query: "distributed consensus algorithms", limit: 10 },
        },
        {
          name: "polyweb.provider.response",
          timestamp: "2026-09-29T09:15:00.228000Z",
          attributes: { result_count: 2 },
        },
      ],
    },
    {
      span_id: spanId("dd"),
      parent_span_id: spanId("cc"),
      name: "polyweb.provider.http",
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
      name: "polyweb.provider.parse",
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
      name: "polyweb.results",
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
      name: "polyweb.response",
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
          url: "https://docs.polyweb.dev/consensus",
          snippet: "Raft, Paxos, and where each applies.",
          source: "keenable",
          score: 0.94,
        },
        {
          title: "Raft vs Paxos",
          url: "https://docs.polyweb.dev/raft-vs-paxos",
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

/** Aggregated fanout spans: seven named provider attempts + micro-span children.
 * Every `polyweb.provider` span carries its span-level `provider` identity,
 * including the failed `parallel` attempt and the empty `exa`/`youcom`
 * responses that record zero results. Legacy result-source inference alone
 * cannot name those attempts; the direct span field is the source of truth. */
const AGGREGATED_SPANS: Record<string, unknown>[] = [
  {
    span_id: "a100000000000001",
    parent_span_id: null,
    name: "POST /search",
    stage: "Search request",
    kind: "server",
    started_at: AGGREGATED_STARTED_AT,
    ended_at: "2026-09-29T09:10:03.381000Z",
    duration_ms: 3381,
    outcome: "success",
    error: null,
    events: [],
  },
  {
    span_id: "a100000000000002",
    parent_span_id: "a100000000000001",
    name: "polyweb.backend",
    stage: "Backend handling",
    kind: "internal",
    started_at: "2026-09-29T09:10:00.004000Z",
    ended_at: "2026-09-29T09:10:03.373000Z",
    duration_ms: 3369,
    outcome: "success",
    error: null,
    events: [],
  },
  {
    span_id: "a100000000000003",
    parent_span_id: "a100000000000002",
    name: "polyweb.provider",
    stage: "Provider request",
    kind: "client",
    provider: "keenable",
    started_at: "2026-09-29T09:10:00.020000Z",
    ended_at: "2026-09-29T09:10:02.045000Z",
    duration_ms: 2025,
    outcome: "success",
    error: null,
    events: [
      {
        name: "polyweb.provider.request",
        timestamp: "2026-09-29T09:10:00.020000Z",
        attributes: { query: "What is the latest financial news?", limit: 10 },
      },
      {
        name: "polyweb.provider.response",
        timestamp: "2026-09-29T09:10:02.045000Z",
        attributes: {
          result_count: 3,
          results: [
            {
              title: "Reuters Latest Finance News | Today Top Headlines",
              url: "https://www.reuters.com/business/finance/",
              snippet: "Exclusive news, data and analytics for financial market professionals.",
              source: "keenable",
              score: 0.92,
            },
            {
              title: "Yahoo Finance - Stock Market Live, Quotes, Business News",
              url: "https://finance.yahoo.com/",
              snippet: "Market coverage six days ago.",
              source: "keenable",
              score: 0.78,
            },
            {
              title: "Stock Markets, Business News, Financials, Earnings - CNBC",
              url: LONG_HOSTILE_URL,
              snippet: "A practical comparison with an unbreakable recorded URL token.",
              source: "keenable",
              score: 0.65,
            },
          ],
        },
      },
    ],
  },
  {
    span_id: "a100000000000004",
    parent_span_id: "a100000000000003",
    name: "polyweb.provider.http",
    stage: "Provider HTTP call",
    kind: "client",
    started_at: "2026-09-29T09:10:00.022000Z",
    ended_at: "2026-09-29T09:10:02.041000Z",
    duration_ms: 2019,
    outcome: "success",
    error: null,
    events: [],
  },
  {
    span_id: "a100000000000005",
    parent_span_id: "a100000000000003",
    name: "polyweb.provider.parse",
    stage: "Provider response parse",
    kind: "internal",
    started_at: "2026-09-29T09:10:02.041000Z",
    ended_at: "2026-09-29T09:10:02.043000Z",
    duration_ms: 2,
    outcome: "success",
    error: null,
    events: [],
  },
  {
    span_id: "a100000000000006",
    parent_span_id: "a100000000000002",
    name: "polyweb.provider",
    stage: "Provider request",
    kind: "client",
    provider: "tavily",
    started_at: "2026-09-29T09:10:00.046000Z",
    ended_at: "2026-09-29T09:10:03.269000Z",
    duration_ms: 3223,
    outcome: "success",
    error: null,
    events: [
      {
        name: "polyweb.provider.request",
        timestamp: "2026-09-29T09:10:00.046000Z",
        attributes: { query: "What is the latest financial news?", limit: 10 },
      },
      {
        name: "polyweb.provider.response",
        timestamp: "2026-09-29T09:10:03.269000Z",
        attributes: {
          result_count: 3,
          results: [
            {
              title: "Financial Times - World business, finance and political news",
              url: "https://www.ft.com/",
              snippet: "Global business coverage.",
              source: "tavily",
              score: 0.88,
            },
            {
              title: "Bloomberg - Business, Financial and Economic News",
              url: "https://www.bloomberg.com/",
              snippet: "Markets and economy coverage.",
              source: "tavily",
              score: 0.71,
            },
            {
              title: "MarketWatch - Stock Market News, Business News, Financial News",
              url: "https://www.marketwatch.com/",
              snippet: "Investor news and analysis.",
              source: "tavily",
              score: 0.6,
            },
          ],
        },
      },
    ],
  },
  {
    span_id: "a100000000000007",
    parent_span_id: "a100000000000006",
    name: "polyweb.provider.http",
    stage: "Provider HTTP call",
    kind: "client",
    started_at: "2026-09-29T09:10:00.048000Z",
    ended_at: "2026-09-29T09:10:03.265000Z",
    duration_ms: 3217,
    outcome: "success",
    error: null,
    events: [],
  },
  {
    span_id: "b100000000000001",
    parent_span_id: "a100000000000002",
    name: "polyweb.provider",
    stage: "Provider request",
    kind: "client",
    provider: "brave",
    started_at: "2026-09-29T09:10:00.030000Z",
    ended_at: "2026-09-29T09:10:01.480000Z",
    duration_ms: 1450,
    outcome: "success",
    error: null,
    events: [
      {
        name: "polyweb.provider.request",
        timestamp: "2026-09-29T09:10:00.030000Z",
        attributes: { query: "What is the latest financial news?", limit: 10 },
      },
    ],
  },
  {
    span_id: "c100000000000001",
    parent_span_id: "a100000000000002",
    name: "polyweb.provider",
    stage: "Provider request",
    kind: "client",
    provider: "exa",
    started_at: "2026-09-29T09:10:00.040000Z",
    ended_at: "2026-09-29T09:10:01.820000Z",
    duration_ms: 1780,
    outcome: "success",
    error: null,
    events: [
      {
        name: "polyweb.provider.request",
        timestamp: "2026-09-29T09:10:00.040000Z",
        attributes: { query: "What is the latest financial news?", limit: 10 },
      },
      {
        name: "polyweb.provider.response",
        timestamp: "2026-09-29T09:10:01.820000Z",
        attributes: { result_count: 0, results: [] },
      },
    ],
  },
  {
    span_id: "d100000000000001",
    parent_span_id: "a100000000000002",
    name: "polyweb.provider",
    stage: "Provider request",
    kind: "client",
    provider: "firecrawl",
    started_at: "2026-09-29T09:10:00.050000Z",
    ended_at: "2026-09-29T09:10:02.100000Z",
    duration_ms: 2050,
    outcome: "success",
    error: null,
    events: [
      {
        name: "polyweb.provider.request",
        timestamp: "2026-09-29T09:10:00.050000Z",
        attributes: { query: "What is the latest financial news?", limit: 10 },
      },
    ],
  },
  {
    span_id: "e100000000000001",
    parent_span_id: "a100000000000002",
    name: "polyweb.provider",
    stage: "Provider request",
    kind: "client",
    provider: "youcom",
    started_at: "2026-09-29T09:10:00.060000Z",
    ended_at: "2026-09-29T09:10:02.370000Z",
    duration_ms: 2310,
    outcome: "success",
    error: null,
    events: [
      {
        name: "polyweb.provider.request",
        timestamp: "2026-09-29T09:10:00.060000Z",
        attributes: { query: "What is the latest financial news?", limit: 10 },
      },
      {
        name: "polyweb.provider.response",
        timestamp: "2026-09-29T09:10:02.370000Z",
        attributes: { result_count: 0, results: [] },
      },
    ],
  },
  {
    span_id: "f100000000000001",
    parent_span_id: "a100000000000002",
    name: "polyweb.provider",
    stage: "Provider request",
    kind: "client",
    provider: "parallel",
    started_at: "2026-09-29T09:10:00.070000Z",
    ended_at: "2026-09-29T09:10:00.900000Z",
    duration_ms: 830,
    outcome: "error",
    error: { type: "http_error", message: "HTTP 502" },
    events: [
      {
        name: "polyweb.provider.request",
        timestamp: "2026-09-29T09:10:00.070000Z",
        attributes: { query: "What is the latest financial news?", limit: 10 },
      },
      {
        name: "exception",
        timestamp: "2026-09-29T09:10:00.900000Z",
        attributes: { "exception.type": "ProviderOperationError" },
      },
    ],
  },
  {
    span_id: "a100000000000008",
    parent_span_id: "a100000000000002",
    name: "polyweb.results",
    stage: "Results assembly",
    kind: "internal",
    started_at: "2026-09-29T09:10:03.270000Z",
    ended_at: "2026-09-29T09:10:03.274000Z",
    duration_ms: 4,
    outcome: "success",
    error: null,
    events: [],
  },
  {
    span_id: "a100000000000009",
    parent_span_id: "a100000000000001",
    name: "polyweb.response",
    stage: "Response to caller",
    kind: "internal",
    started_at: "2026-09-29T09:10:03.373000Z",
    ended_at: "2026-09-29T09:10:03.381000Z",
    duration_ms: 8,
    outcome: "success",
    error: null,
    events: [],
  },
]

/** `GET /api/v1/traces/{aggregated}` payload: fused output + seven provider attempts. */
export function aggregatedTraceDetailFixture(
  overrides: Record<string, unknown> = {}
): Record<string, unknown> {
  return {
    ...aggregatedTraceSummaryFixture(),
    input: "What is the latest financial news?",
    output: {
      kind: "search_results",
      query: "What is the latest financial news?",
      results: [
        {
          title: "Reuters Latest Finance News | Today Top Headlines",
          url: "https://www.reuters.com/business/finance/",
          snippet: "Exclusive news, data and analytics for financial market professionals.",
          source: "keenable",
          score: 0.7,
        },
        {
          title: "Yahoo Finance - Stock Market Live, Quotes, Business News",
          url: "https://finance.yahoo.com/",
          snippet: "Market coverage six days ago.",
          source: "keenable",
          score: 0.68,
        },
        {
          title: "Stock Markets, Business News, Financials, Earnings - CNBC",
          url: LONG_HOSTILE_URL,
          snippet: "A practical comparison with an unbreakable recorded URL token.",
          source: "keenable",
          score: 0.61,
        },
        {
          title: "Financial Times - World business, finance and political news",
          url: "https://www.ft.com/",
          snippet: "Global business coverage.",
          source: "tavily",
          score: 0.55,
        },
        {
          title: "Bloomberg - Business, Financial and Economic News",
          url: "https://www.bloomberg.com/",
          snippet: "Markets and economy coverage.",
          source: "tavily",
          score: 0.44,
        },
        {
          title: "MarketWatch - Stock Market News, Business News, Financial News",
          url: "https://www.marketwatch.com/",
          snippet: "Investor news and analysis.",
          source: "tavily",
          score: 0.39,
        },
      ],
    },
    spans: AGGREGATED_SPANS.map((span) => ({ ...span })),
    ...overrides,
  }
}

/** Detail payload for the failed fetch trace (error callout + failed stage). */
export function errorTraceDetailFixture(
  overrides: Record<string, unknown> = {}
): Record<string, unknown> {
  return {
    ...errorTraceSummaryFixture(),
    input: "https://docs.polyweb.dev/getting-started",
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
        name: "polyweb.provider",
        stage: "Provider request",
        kind: "client",
        provider: "keenable",
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

