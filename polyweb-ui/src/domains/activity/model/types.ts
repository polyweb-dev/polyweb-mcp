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
export type TraceActorType = "human" | "project_api_key"

export interface TraceActor {
  kind: TraceActorType | null
  displayName: string | null
  email: string | null
}

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
  actor: TraceActor
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

/** Event payload kept structured: the viewer decides how to disclose it. */
export interface TraceEvent {
  name: string
  timestamp: string
  attributes: Record<string, unknown>
}

/** One row of the stage timeline, with its offset from the trace start. */
export interface TraceStage {
  spanId: string
  parentSpanId: string | null
  name: string
  label: string
  /** Provider identity recorded on this span, or null for legacy rows. */
  providerId: string | null
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

/**
 * One provider call derived from a `polyweb.provider` span. `providerId` is
 * null when the recorded data never named the provider — the label then says so
 * instead of guessing from span order.
 */
export interface TraceProviderAttempt {
  spanId: string
  providerId: string | null
  providerLabel: string
  offsetMs: number
  durationMs: number
  outcome: TraceOutcome
  error: TraceError | null
  resultCount: number | null
  results: TraceSearchResult[]
}

export interface TraceLatencySegment {
  offsetMs: number
  durationMs: number
}

/** Provider lanes plus the Polyweb time that no provider call covered. */
export interface TraceLatencyBreakdown {
  providerAttempts: TraceProviderAttempt[]
  processingSegments: TraceLatencySegment[]
  processingMs: number
}

/** Parent/child projection of the recorded spans, for the technical view. */
export interface TraceStageNode {
  stage: TraceStage
  children: TraceStageNode[]
}
