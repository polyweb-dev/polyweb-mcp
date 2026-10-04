import type { ReactNode } from "react"

export interface LatencyWaterfallValueProps {
  durationMs: number
  resultCount: number | null
  /** Recorded outcome, shown only when it is not a success. */
  outcome?: string
}

/**
 * Shared row value for one timeline lane: the recorded duration in
 * milliseconds, the recorded result count when the caller has one, and any
 * outcome that is not a success. The Playground fan-out and the Activity
 * trajectory both render their values through it. The explicit spaces keep a
 * row's accessible name readable, because each value is its own element.
 */
export function LatencyWaterfallValue({
  durationMs,
  resultCount,
  outcome,
}: LatencyWaterfallValueProps): ReactNode {
  return (
    <span className="tnum">
      <span className="text-[var(--text-strong)]">{durationMs}ms</span>
      {resultCount !== null && (
        <>
          {" "}
          <span className="text-[12px] text-[var(--muted)]">{resultCount} res</span>
        </>
      )}
      {outcome !== undefined && (
        <>
          {" "}
          <span className="text-[12px] text-[var(--muted)]">{outcome}</span>
        </>
      )}
    </span>
  )
}
