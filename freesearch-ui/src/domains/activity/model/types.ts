/**
 * UI-safe Activity types. Decoded from the wire by `mappers.ts`; the views only
 * ever see validated ids, parsed timestamps, and finite durations.
 */

export type TraceOperation = "search" | "fetch"
export type TraceOutcome = "success" | "partial" | "error"
export type TraceSpanKind = "internal" | "server" | "client"

export interface TraceError {
  type: string
  message: string
}

/** One Activity list row. Deliberately carries no query and no results. */
export interface TraceSummary {
  traceId: string
  operation: TraceOperation | null
  startedAt: string
  durationMs: number
  provider: string | null
  providerLabel: string
  outcome: TraceOutcome
  resultCount: number | null
  error: TraceError | null
}

export interface TraceSearchResult {
  title: string
  url: string
  snippet: string
  source: string | null
  score: number | null
}

export interface TraceSearchOutput {
  kind: "search_results"
  query: string
  results: TraceSearchResult[]
}

export interface TraceFetchOutput {
  kind: "fetch_document"
  url: string
  title: string | null
  content: string
  contentLength: number
  truncated: boolean
}

/** Tagged union: a future operation adds one member and one tag value. */
export type TraceOutput = TraceSearchOutput | TraceFetchOutput

export interface TraceEvent {
  name: string
  timestamp: string
  attributes: string
}

/** One row of the stage timeline, with its offset from the trace start. */
export interface TraceStage {
  spanId: string
  parentSpanId: string | null
  name: string
  label: string
  kind: TraceSpanKind
  startedAt: string
  durationMs: number
  offsetMs: number
  outcome: TraceOutcome
  error: TraceError | null
  events: TraceEvent[]
}

/** Full detail: summary plus the disclosed input, results, and timeline. */
export interface TraceDetail extends TraceSummary {
  input: string | null
  output: TraceOutput | null
  stages: TraceStage[]
  totalMs: number
}
