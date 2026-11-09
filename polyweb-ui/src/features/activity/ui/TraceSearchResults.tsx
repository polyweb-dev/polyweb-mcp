import type { TraceSearchResult } from "@/domains/activity"
import type { RankingMode } from "./TraceRankingExplanation"
import { TraceResultRow } from "./TraceResultRow"

export interface TraceSearchResultsProps {
  results: readonly TraceSearchResult[]
  mode: RankingMode
  /** Provider the scoped output belongs to, or null for a fused whole trace. */
  providerId: string | null
  /** Index of the selected result inside `results`; the selection identity. */
  selectedIndex: number | null
  onSelect: (index: number) => void
}

/**
 * Every recorded result as one selectable card, in recorded order. The card
 * and the side inspector share one presentation with the Playground, so the
 * list never turns a long payload into a scroll wall (PLAN §4–5).
 */
export function TraceSearchResults({
  results,
  mode,
  providerId,
  selectedIndex,
  onSelect,
}: TraceSearchResultsProps) {
  if (results.length === 0) {
    return <p className="text-[13px] text-[var(--muted)]">No result was returned</p>
  }
  return (
    <ul aria-label="Ranked results" className="m-0 min-w-0 list-none border-t border-[var(--border-subtle)] p-0">
      {results.map((result, index) => (
        <TraceResultRow
          key={index}
          result={result}
          rank={index + 1}
          total={results.length}
          mode={mode}
          providerId={providerId}
          selected={selectedIndex === index}
          onSelect={() => onSelect(index)}
        />
      ))}
    </ul>
  )
}
