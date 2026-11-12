/**
 * Wire -> domain decoding for traces. Every payload is treated as `unknown`
 * and validated before it reaches a view: identifiers must be canonical
 * 32-character trace / 16-character span hex, timestamps must parse, and
 * durations/counts must be finite non-negative numbers. A row that does not
 * decode is dropped from the list; a detail payload that has no usable
 * identifier or timing raises `TraceDecodeError`.
 */

import { displayNameFromProfile } from "@/shared/lib/identity"
import type {
  TraceActor,
  TraceDetail,
  TraceError,
  TraceEvent,
  TraceOperation,
  TraceOutcome,
  TraceOutput,
  TraceSearchResult,
  TraceSpanKind,
  TraceStage,
  TraceSummary,
} from "./types"

const TRACE_ID = /^[0-9a-f]{32}$/
const SPAN_ID = /^[0-9a-f]{16}$/
const OPERATIONS: readonly TraceOperation[] = ["search", "fetch"]
const OUTCOMES: readonly TraceOutcome[] = ["success", "partial", "error"]
const KINDS: readonly TraceSpanKind[] = ["internal", "server", "client"]
const ACTOR_TYPES = ["human", "project_api_key"] as const

export class TraceDecodeError extends Error {
  constructor(message: string) {
    super(message)
    this.name = "TraceDecodeError"
  }
}

function asRecord(value: unknown): Record<string, unknown> | null {
  if (typeof value !== "object" || value === null || Array.isArray(value)) return null
  return value as Record<string, unknown>
}

function asString(value: unknown): string | null {
  return typeof value === "string" ? value : null
}

function asCount(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) && value >= 0
    ? Math.round(value)
    : null
}

function asTimestamp(value: unknown): string | null {
  const text = asString(value)
  if (text === null || Number.isNaN(Date.parse(text))) return null
  return text
}

function asOperation(value: unknown): TraceOperation | null {
  return OPERATIONS.find((operation) => operation === value) ?? null
}

function asOutcome(value: unknown): TraceOutcome {
  return OUTCOMES.find((outcome) => outcome === value) ?? "error"
}

function asKind(value: unknown): TraceSpanKind {
  return KINDS.find((kind) => kind === value) ?? "internal"
}

function asOptionalText(value: unknown): string | null {
  if (value === undefined || value === null) return null
  return typeof value === "string" ? value : null
}

/**
 * Decode the trace actor: human rows resolve the saved profile through the
 * shared fallback (full name, then username, then email); API-key rows stay
 * key-identified and never borrow a human profile. Unknown actor fields stay
 * `null`; wrong types drop to `null` rather than failing the row.
 */
function mapTraceActor(record: Record<string, unknown>): TraceActor {
  const kind = (ACTOR_TYPES as readonly string[]).includes(record.actor_type as string)
    ? (record.actor_type as TraceActor["kind"])
    : null
  if (kind === "project_api_key") {
    return { kind, displayName: null, email: null }
  }
  const email = asOptionalText(record.email)
  return {
    kind,
    displayName: displayNameFromProfile({
      username: asOptionalText(record.username),
      first_name: asOptionalText(record.first_name),
      last_name: asOptionalText(record.last_name),
    }),
    email,
  }
}

function asError(value: unknown): TraceError | null {
  const record = asRecord(value)
  if (record === null) return null
  const type = asString(record.type)
  const message = asString(record.message)
  if (type === null && message === null) return null
  const resolved = type ?? "error"
  return { type: resolved, message: message ?? resolved }
}

function providerLabel(provider: string | null): string {
  if (provider === null || provider === "") return "—"
  if (provider === "aggregated") return "All providers"
  return provider.charAt(0).toUpperCase() + provider.slice(1)
}

/** Display label for a provider id known outside a summary (e.g. a span). */
export function traceProviderLabel(provider: string | null): string {
  return providerLabel(provider)
}

/** Decode one list row; `null` means the payload was not a usable summary. */
export function mapTraceSummary(payload: unknown): TraceSummary | null {
  const record = asRecord(payload)
  if (record === null) return null
  const traceId = asString(record.trace_id)
  const startedAt = asTimestamp(record.started_at)
  const durationMs = asCount(record.duration_ms)
  if (traceId === null || !TRACE_ID.test(traceId)) return null
  if (startedAt === null || durationMs === null) return null
  const provider = asString(record.provider)
  return {
    traceId,
    operation: asOperation(record.operation),
    startedAt,
    durationMs,
    provider,
    providerLabel: providerLabel(provider),
    outcome: asOutcome(record.outcome),
    resultCount: asCount(record.result_count),
    error: asError(record.error),
    actor: mapTraceActor(record),
  }
}

/** One decoded list page: the rows plus the opaque cursor of the next page. */
export interface TracePage {
  items: TraceSummary[]
  nextCursor: string | null
}

/** Decode one list page; a missing or empty cursor means the last page. */
export function mapTracePage(payload: unknown): TracePage {
  const cursor = asString(asRecord(payload)?.next_cursor)
  return { items: mapTraceList(payload), nextCursor: cursor === null || cursor === "" ? null : cursor }
}

/** Decode the list payload, ignoring rows that fail validation. */
export function mapTraceList(payload: unknown): TraceSummary[] {
  const items = asRecord(payload)?.items
  if (!Array.isArray(items)) {
    throw new TraceDecodeError("trace list response is not a list of traces")
  }
  const summaries: TraceSummary[] = []
  for (const item of items) {
    const summary = mapTraceSummary(item)
    if (summary !== null) summaries.push(summary)
  }
  return summaries
}

/**
 * Safe decoder for a list of normalized search results. Shared by the root
 * output and by per-provider response events so both keep the same validation
 * and the same original ordering.
 */
export function decodeSearchResults(value: unknown): TraceSearchResult[] {
  if (!Array.isArray(value)) return []
  const results: TraceSearchResult[] = []
  for (const item of value) {
    const record = asRecord(item)
    const url = asString(record?.url)
    if (record === null || url === null) continue
    results.push({
      title: asString(record.title) ?? url,
      url,
      snippet: asString(record.snippet) ?? "",
      source: asString(record.source),
      score: typeof record.score === "number" ? record.score : null,
    })
  }
  return results
}

function mapOutput(value: unknown): TraceOutput | null {
  const record = asRecord(value)
  if (record === null) return null
  if (record.kind === "search_results") {
    return {
      kind: "search_results",
      query: asString(record.query) ?? "",
      results: decodeSearchResults(record.results),
    }
  }
  if (record.kind === "fetch_document") {
    const content = asString(record.content) ?? ""
    return {
      kind: "fetch_document",
      url: asString(record.url) ?? "",
      title: asString(record.title),
      content,
      contentLength: asCount(record.content_length) ?? content.length,
      truncated: record.truncated === true,
    }
  }
  return null
}

function mapEvents(value: unknown): TraceEvent[] {
  if (!Array.isArray(value)) return []
  const events: TraceEvent[] = []
  for (const item of value) {
    const record = asRecord(item)
    const name = asString(record?.name)
    const timestamp = asTimestamp(record?.timestamp)
    if (record === null || name === null || timestamp === null) continue
    events.push({
      name,
      timestamp,
      // Kept structured: a provider response event carries `result_count` and
      // the per-provider `results`, which the derivations decode in place.
      attributes: asRecord(record.attributes) ?? {},
    })
  }
  return events
}

function mapStages(value: unknown, traceStart: number): TraceStage[] {
  if (!Array.isArray(value)) return []
  const stages: TraceStage[] = []
  for (const item of value) {
    const record = asRecord(item)
    if (record === null) continue
    const spanId = asString(record.span_id)
    const name = asString(record.name)
    if (spanId === null || !SPAN_ID.test(spanId) || name === null) continue
    const startedAt = asTimestamp(record.started_at) ?? ""
    const started = Date.parse(startedAt)
    stages.push({
      spanId,
      parentSpanId: asString(record.parent_span_id),
      name,
      label: asString(record.stage) ?? "Stage",
      providerId: asString(record.provider),
      kind: asKind(record.kind),
      startedAt,
      durationMs: asCount(record.duration_ms) ?? 0,
      offsetMs: Number.isNaN(started) ? 0 : Math.max(0, started - traceStart),
      outcome: asOutcome(record.outcome),
      error: asError(record.error),
      events: mapEvents(record.events),
    })
  }
  return stages
}

/** Decode one detail payload; throws when the summary itself is unusable. */
export function mapTraceDetail(payload: unknown): TraceDetail {
  const summary = mapTraceSummary(payload)
  if (summary === null) {
    throw new TraceDecodeError("trace detail is missing a valid identifier or timing")
  }
  const record = asRecord(payload) ?? {}
  return {
    ...summary,
    input: asString(record.input),
    output: mapOutput(record.output),
    stages: mapStages(record.spans, Date.parse(summary.startedAt)),
    totalMs: Math.max(summary.durationMs, 1),
  }
}
