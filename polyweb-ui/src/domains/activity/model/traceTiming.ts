/**
 * Trace timing envelope: the window the recorded spans cover, used to scale the
 * timeline when the root span is unusable. Pure; nothing here invents a span.
 */

/** Overlap under one millisecond is rounding, not a corrupt root. */
export const ENVELOPE_TOLERANCE_MS = 1

/**
 * The time window the trace covers: from the earliest of the summary start and
 * every consistent span start, to the latest span end. A span whose `ended_at`
 * is before its `started_at` is inconsistent (an old backend bug stored some
 * roots that way): it never sets the envelope start, but its end still counts.
 * Without a single consistent span there is no envelope and callers keep the
 * summary timing.
 */
export interface SpanEnvelope {
  startedAt: string
  startMs: number
  endMs: number
  /** Axis length: the envelope start to the latest span end. */
  totalMs: number
  /** Work length: the earliest consistent span start to the latest span end. */
  spansTotalMs: number
}

export interface SpanTiming {
  record: Record<string, unknown>
  spanId: string
  name: string
  startedAt: string
  startMs: number
  endMs: number
  inconsistent: boolean
}

export function deriveEnvelope(
  timings: readonly SpanTiming[],
  summary: { startedAt: string; startMs: number }
): SpanEnvelope | null {
  let start = summary
  let spansStartMs = Number.POSITIVE_INFINITY
  let endMs = Number.NEGATIVE_INFINITY
  let consistent = 0
  for (const timing of timings) {
    if (Number.isNaN(timing.startMs)) continue
    endMs = Math.max(endMs, timing.endMs)
    if (timing.inconsistent) continue
    consistent += 1
    spansStartMs = Math.min(spansStartMs, timing.startMs)
    if (timing.startMs < start.startMs) start = timing
  }
  if (consistent === 0 || endMs < start.startMs) return null
  return {
    startedAt: start.startedAt,
    startMs: start.startMs,
    endMs,
    totalMs: Math.round(endMs - start.startMs),
    spansTotalMs: Math.round(endMs - spansStartMs),
  }
}
