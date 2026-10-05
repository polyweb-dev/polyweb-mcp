/**
 * Pure derivations over the recorded spans: which provider calls happened, how
 * much of the trace no provider call covered, and the parent/child shape of the
 * span tree. Nothing here guesses: a missing provider name or a missing rank
 * signal stays missing and the views say so.
 */

import { decodeSearchResults, traceProviderLabel } from "./mappers"
import type {
  TraceLatencyBreakdown,
  TraceLatencySegment,
  TraceProviderAttempt,
  TraceSearchResult,
  TraceStage,
  TraceStageNode,
} from "./types"

const PROVIDER_SPAN_NAME = "freesearch.provider"
const PROVIDER_RESPONSE_EVENT = "freesearch.provider.response"
const AGGREGATED_PROVIDER = "aggregated"

interface ProviderResponse {
  resultCount: number | null
  results: TraceSearchResult[]
}

interface Interval {
  start: number
  end: number
}

/**
 * One provider attempt per `freesearch.provider` span, in wire order. HTTP and
 * parse children describe that same call, so they never become extra rows.
 */
export function deriveProviderAttempts(
  stages: readonly TraceStage[],
  summaryProvider: string | null
): TraceProviderAttempt[] {
  return stages
    .filter((stage) => stage.name === PROVIDER_SPAN_NAME)
    .map((stage, index) => toAttempt(stage, index, summaryProvider))
}

function readProviderResponse(stage: TraceStage): ProviderResponse {
  const event = stage.events.find((candidate) => candidate.name === PROVIDER_RESPONSE_EVENT)
  if (event === undefined) return { resultCount: null, results: [] }
  const results = decodeSearchResults(event.attributes.results)
  const recorded = event.attributes.result_count
  const count =
    typeof recorded === "number" && Number.isFinite(recorded) && recorded >= 0
      ? Math.round(recorded)
      : null
  return { resultCount: count ?? (results.length > 0 ? results.length : null), results }
}

/** The only provider id the results evidence: all of them must agree. */
function consistentSource(results: readonly TraceSearchResult[]): string | null {
  const sources = new Set(results.map((result) => result.source))
  if (sources.size !== 1) return null
  return [...sources][0] ?? null
}

/**
 * Provider identity for one attempt, in precedence order: the identity the
 * span itself recorded, then the legacy result-source evidence, then the
 * non-aggregated summary provider of an old single-provider trace.
 */
function resolveProviderId(
  stage: TraceStage,
  summaryProvider: string | null,
  results: readonly TraceSearchResult[]
): string | null {
  // Legacy stages (decoded before the span carried an identity, or fixtures
  // built without the field) leave it absent rather than null.
  const direct = stage.providerId
  if (typeof direct === "string" && direct !== "") return direct
  const evidenced = consistentSource(results)
  if (evidenced !== null) return evidenced
  if (summaryProvider !== null && summaryProvider !== "") return summaryProvider
  return null
}

function toAttempt(
  stage: TraceStage,
  index: number,
  summaryProvider: string | null
): TraceProviderAttempt {
  const { resultCount, results } = readProviderResponse(stage)
  const fallback = summaryProvider === AGGREGATED_PROVIDER ? null : summaryProvider
  const providerId = resolveProviderId(stage, fallback, results)
  return {
    spanId: stage.spanId,
    providerId,
    providerLabel: providerId === null ? `Provider attempt ${index + 1}` : traceProviderLabel(providerId),
    offsetMs: stage.offsetMs,
    durationMs: stage.durationMs,
    outcome: stage.outcome,
    error: stage.error,
    resultCount,
    results,
  }
}

function clamp(value: number, max: number): number {
  if (!Number.isFinite(value)) return 0
  return Math.min(Math.max(value, 0), max)
}

function attemptInterval(attempt: TraceProviderAttempt, totalMs: number): Interval | null {
  const start = clamp(attempt.offsetMs, totalMs)
  const end = clamp(attempt.offsetMs + attempt.durationMs, totalMs)
  return end > start ? { start, end } : null
}

/** Merge overlapping provider calls so concurrent fanout is counted once. */
function mergeIntervals(intervals: readonly Interval[]): Interval[] {
  const merged: Interval[] = []
  for (const interval of [...intervals].sort((a, b) => a.start - b.start || a.end - b.end)) {
    const last = merged[merged.length - 1]
    if (last !== undefined && interval.start <= last.end) {
      last.end = Math.max(last.end, interval.end)
      continue
    }
    merged.push({ ...interval })
  }
  return merged
}

function complementSegments(covered: readonly Interval[], totalMs: number): TraceLatencySegment[] {
  const segments: TraceLatencySegment[] = []
  let cursor = 0
  for (const interval of covered) {
    if (interval.start > cursor) {
      segments.push({ offsetMs: cursor, durationMs: interval.start - cursor })
    }
    cursor = Math.max(cursor, interval.end)
  }
  if (totalMs > cursor) segments.push({ offsetMs: cursor, durationMs: totalMs - cursor })
  return segments
}

/**
 * Provider lanes plus the complement of their union, clipped to the trace
 * window: FreeSearch processing is the time no provider call was running, kept
 * as separate pre/between/post segments instead of one collapsed total.
 */
export function deriveLatencyBreakdown(
  attempts: readonly TraceProviderAttempt[],
  totalMs: number
): TraceLatencyBreakdown {
  const total = Math.max(0, totalMs)
  const intervals = attempts
    .map((attempt) => attemptInterval(attempt, total))
    .filter((interval): interval is Interval => interval !== null)
  const processingSegments = complementSegments(mergeIntervals(intervals), total)
  const processingMs = processingSegments.reduce((sum, segment) => sum + segment.durationMs, 0)
  return { providerAttempts: [...attempts], processingSegments, processingMs }
}

interface TreeEntry {
  id: string
  node: TraceStageNode
}

/**
 * Parent/child tree in stable wire order. A stage whose parent is missing (or
 * whose parent chain loops) stays a top-level node rather than disappearing.
 */
export function buildTraceStageTree(stages: readonly TraceStage[]): TraceStageNode[] {
  const entries: TreeEntry[] = stages.map((stage) => ({
    id: stage.spanId,
    node: { stage, children: [] },
  }))
  const firstById = new Map<string, TreeEntry>()
  for (const entry of entries) {
    if (!firstById.has(entry.id)) firstById.set(entry.id, entry)
  }
  const { parentOf, attaches } = linkParents(entries, firstById)

  const roots: TraceStageNode[] = []
  for (const entry of entries) {
    const parentId = attaches.get(entry)
    if (parentId === undefined || revisitsSelf(entry.id, parentOf)) {
      roots.push(entry.node)
      continue
    }
    firstById.get(parentId)?.node.children.push(entry.node)
  }
  return roots
}

function linkParents(
  entries: readonly TreeEntry[],
  firstById: ReadonlyMap<string, TreeEntry>
): { parentOf: Map<string, string>; attaches: Map<TreeEntry, string> } {
  const parentOf = new Map<string, string>()
  const attaches = new Map<TreeEntry, string>()
  const seen = new Set<string>()
  for (const entry of entries) {
    const isFirstOccurrence = !seen.has(entry.id)
    seen.add(entry.id)
    const parentId = entry.node.stage.parentSpanId
    if (!isFirstOccurrence || parentId === null || parentId === entry.id) continue
    if (!firstById.has(parentId)) continue
    parentOf.set(entry.id, parentId)
    attaches.set(entry, parentId)
  }
  return { parentOf, attaches }
}

/**
 * The label one trajectory row shows. A provider span is named by the identity
 * recorded on that span (`Keenable request`), so concurrent provider calls stay
 * distinguishable instead of collapsing into identical generic labels; every
 * other span keeps the stage label the backend recorded for it.
 */
export function traceTrajectoryLabel(stage: TraceStage): string {
  if (stage.name === PROVIDER_SPAN_NAME && stage.providerId !== null && stage.providerId !== "") {
    return `${traceProviderLabel(stage.providerId)} request`
  }
  return stage.label
}

/** True when following parent links from `id` comes back to `id`. */
function revisitsSelf(id: string, parentOf: ReadonlyMap<string, string>): boolean {
  const visited = new Set<string>([id])
  let current = parentOf.get(id)
  while (current !== undefined) {
    if (current === id) return true
    if (visited.has(current)) return false
    visited.add(current)
    current = parentOf.get(current)
  }
  return false
}
