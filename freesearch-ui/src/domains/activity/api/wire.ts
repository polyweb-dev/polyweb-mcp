/**
 * Wire types for the trace read API (`GET /api/v1/traces` and its detail).
 *
 * Mirrors the FastAPI contract verbatim (snake_case, ISO-8601 UTC timestamps,
 * numeric milliseconds). Values arriving from the network are still treated as
 * `unknown` by `model/mappers.ts`; these types document the intended shape.
 */

export type BackendTraceOperation = "search" | "fetch"
export type BackendTraceOutcome = "success" | "partial" | "error"
export type BackendTraceSpanKind = "internal" | "server" | "client"

export interface BackendTraceError {
  type: string
  message: string
}

/** Fast, scannable list row: never carries the query or the results. */
export interface BackendTraceSummary {
  trace_id: string
  operation: BackendTraceOperation | null
  started_at: string
  duration_ms: number
  provider: string | null
  outcome: BackendTraceOutcome
  result_count: number | null
  error: BackendTraceError | null
}

export interface BackendTraceSearchResult {
  title: string
  url: string
  snippet: string
  source: string | null
  score: number | null
}

export interface BackendTraceSearchOutput {
  kind: "search_results"
  query: string
  results: BackendTraceSearchResult[]
}

export interface BackendTraceFetchOutput {
  kind: "fetch_document"
  url: string
  title: string | null
  content: string
  content_length: number
  truncated: boolean
}

/** Tagged union: a future operation adds one member and one tag value. */
export type BackendTraceOutput = BackendTraceSearchOutput | BackendTraceFetchOutput

export interface BackendTraceEvent {
  name: string
  timestamp: string
  attributes: Record<string, unknown>
}

export interface BackendTraceSpan {
  span_id: string
  parent_span_id: string | null
  name: string
  stage: string
  kind: BackendTraceSpanKind
  started_at: string
  ended_at: string
  duration_ms: number
  outcome: BackendTraceOutcome
  error: BackendTraceError | null
  events: BackendTraceEvent[]
}

export interface BackendTraceDetail extends BackendTraceSummary {
  input: string | null
  output: BackendTraceOutput | null
  spans: BackendTraceSpan[]
}

export interface BackendTraceList {
  items: BackendTraceSummary[]
  generated_at: string
}
