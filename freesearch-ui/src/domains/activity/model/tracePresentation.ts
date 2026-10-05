/**
 * User-level trajectory projection: which recorded spans become visible rows
 * and how provider time relates to the rest of the trace. Nothing here invents
 * a stage, a timestamp, or a provider: an absent interval stays absent.
 */

import { deriveLatencyBreakdown } from "./traceDerivations"
import type { TraceProviderAttempt, TraceStage } from "./types"

/**
 * Recorded span names that carry user meaning. Function-level and transport
 * children (`freesearch.provider.http`, `freesearch.provider.parse`, unknown
 * names) never become rows, but they stay in the decoded data.
 */
const USER_STAGE_ORDER: ReadonlyMap<string, number> = new Map([
  ["POST /search", 0],
  ["POST /fetch", 0],
  ["freesearch.route", 1],
  ["freesearch.backend", 2],
  ["freesearch.provider", 3],
  ["freesearch.results", 4],
  ["freesearch.response", 5],
])

interface OrderedStage {
  stage: TraceStage
  index: number
  order: number
}

/** Provider time and the recorded time outside it, all in milliseconds. */
export interface TraceLatencySummary {
  beforeProvidersMs: number
  providerActiveMs: number
  betweenProvidersMs: number
  afterProvidersMs: number
  outsideProvidersMs: number
}

function orderedEntry(stage: TraceStage, index: number): OrderedStage | null {
  const order = USER_STAGE_ORDER.get(stage.name)
  return order === undefined ? null : { stage, index, order }
}

/**
 * The visible trajectory rows: total, route selection, backend handling,
 * provider attempts, results assembly, response to caller. Repeated rows of one
 * category keep their offset order, and equal offsets keep the wire order.
 */
export function selectUserTraceStages(stages: readonly TraceStage[]): TraceStage[] {
  const selected: OrderedStage[] = []
  stages.forEach((stage, index) => {
    const entry = orderedEntry(stage, index)
    if (entry !== null) selected.push(entry)
  })
  selected.sort(
    (a, b) => a.order - b.order || a.stage.offsetMs - b.stage.offsetMs || a.index - b.index
  )
  return selected.map((entry) => entry.stage)
}

function noProviderTime(totalMs: number): TraceLatencySummary {
  return {
    beforeProvidersMs: 0,
    providerActiveMs: 0,
    betweenProvidersMs: 0,
    afterProvidersMs: 0,
    outsideProvidersMs: totalMs,
  }
}

/**
 * Two-hop latency from the recorded provider intervals. The provider-active
 * value is the union of those intervals, never their sum, so concurrent fanout
 * counts once. The complement of that union splits into the time before the
 * first provider call, the gaps between calls, and the time after the last one.
 */
export function deriveTraceLatencySummary(
  attempts: readonly TraceProviderAttempt[],
  totalMs: number
): TraceLatencySummary {
  const total = Math.max(0, totalMs)
  if (attempts.length === 0) return noProviderTime(total)
  const breakdown = deriveLatencyBreakdown(attempts, total)
  const coveredMs = total - breakdown.processingMs
  if (coveredMs <= 0) return noProviderTime(total)
  const first = breakdown.processingSegments.at(0)
  const last = breakdown.processingSegments.at(-1)
  const beforeProvidersMs = first !== undefined && first.offsetMs === 0 ? first.durationMs : 0
  const afterProvidersMs =
    last !== undefined && last.offsetMs + last.durationMs >= total ? last.durationMs : 0
  return {
    beforeProvidersMs,
    providerActiveMs: coveredMs,
    betweenProvidersMs: Math.max(
      0,
      breakdown.processingMs - beforeProvidersMs - afterProvidersMs
    ),
    afterProvidersMs,
    outsideProvidersMs: breakdown.processingMs,
  }
}
