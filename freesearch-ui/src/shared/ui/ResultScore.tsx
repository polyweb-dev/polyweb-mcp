import type { ReactNode } from "react"
import type { ResultScoreView } from "./searchResultView"

const DECIMAL_PLACES = 2
const PERCENT_SCALE = 100

/**
 * One result score in the unit its source recorded: Playground keeps its
 * percentage match rate, a trace keeps its decimal fusion or provider score.
 * A null value is stated as unavailable; this component never invents a zero.
 */
export function ResultScore({ score }: { score: ResultScoreView }): ReactNode {
  if (score.value === null) {
    return <span className="text-[var(--muted)]">Unavailable</span>
  }
  if (score.format === "percent") {
    return <span className="tnum">{Math.round(score.value * PERCENT_SCALE)}% match</span>
  }
  return (
    <span className="tnum" style={{ color: "var(--accent-gold)" }}>
      {score.value.toFixed(DECIMAL_PLACES)}
    </span>
  )
}
