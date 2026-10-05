import type { ReactNode } from "react"
import { hasRecordedScore, type ResultScoreView } from "./searchResultView"

const PERCENT_SCALE = 100

/**
 * One recorded score, always as a gold percentage match rate: Playground
 * keeps its percentage match rate, and a trace fusion or provider score is
 * shown on the same scale. An unrecorded score renders nothing; this
 * component never invents a zero and never prints "Unavailable".
 */
export function ResultScore({ score }: { score: ResultScoreView }): ReactNode {
  if (!hasRecordedScore(score)) return null
  return (
    <span className="tnum" style={{ color: "var(--accent-gold)" }}>
      {Math.round(score.value * PERCENT_SCALE)}% match
    </span>
  )
}
