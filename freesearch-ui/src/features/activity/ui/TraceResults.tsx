import type { TraceOutput, TraceSearchResult } from "@/domains/activity"
import type { RankingMode } from "./TraceRankingExplanation"
import { TraceFetchDocument } from "./TraceFetchDocument"
import { TraceSearchResults } from "./TraceSearchResults"

export interface TraceResultsProps {
  output: TraceOutput | null
  mode: RankingMode
  /** Provider the scoped output belongs to, or null for a fused whole trace. */
  providerId: string | null
  /** Decoded results of the scoped search output (empty for other shapes). */
  results: readonly TraceSearchResult[]
  selectedIndex: number | null
  onSelect: (index: number) => void
}

/**
 * Results-out disclosure: dispatches the tagged output to the shape that
 * matches it, so a new operation adds one branch here and one component. A
 * search output renders the selectable result cards; a fetch output keeps its
 * document view; an absent output says so instead of inventing an empty list.
 */
export function TraceResults({
  output,
  mode,
  providerId,
  results,
  selectedIndex,
  onSelect,
}: TraceResultsProps) {
  if (output === null) {
    return (
      <p className="text-[13px] text-[var(--muted)]">
        No results were recorded for this trace.
      </p>
    )
  }
  if (output.kind === "search_results") {
    return (
      <TraceSearchResults
        results={results}
        mode={mode}
        providerId={providerId}
        selectedIndex={selectedIndex}
        onSelect={onSelect}
      />
    )
  }
  return <TraceFetchDocument output={output} />
}
