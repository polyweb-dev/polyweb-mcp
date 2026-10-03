import type { TraceSearchResult } from "@/domains/activity"
import type { RankingMode } from "./TraceRankingExplanation"
import { TraceResultRow } from "./TraceResultRow"

export interface TraceSearchResultsProps {
  results: readonly TraceSearchResult[]
  mode: RankingMode
  /** Index of the selected result inside `results`; the selection identity. */
  selectedIndex: number | null
  onSelect: (index: number) => void
}

const SCORE_LABELS: Record<RankingMode, string> = {
  fusion: "Fusion score",
  provider: "Provider score",
}

/**
 * Every recorded result as one compact, selectable row, in recorded order. The
 * full snippet is deliberately absent: it belongs to the side inspector, so a
 * long payload never turns the list into a scroll wall (PLAN §5.3).
 */
export function TraceSearchResults({
  results,
  mode,
  selectedIndex,
  onSelect,
}: TraceSearchResultsProps) {
  if (results.length === 0) {
    return <p className="text-[13px] text-[var(--muted)]">No result was returned.</p>
  }
  return (
    <ul aria-label="Ranked results" className="m-0 min-w-0 list-none space-y-1 p-0">
      {results.map((result, index) => (
        <TraceResultRow
          key={index}
          result={result}
          rank={index + 1}
          selected={selectedIndex === index}
          onSelect={() => onSelect(index)}
          scoreLabel={SCORE_LABELS[mode]}
        />
      ))}
    </ul>
  )
}
