import type { TraceSearchResult } from "@/domains/activity"
import { SearchResultCard } from "@/shared/ui/SearchResultCard"
import { toTraceResultView } from "../model/traceResultPresentation"
import type { RankingMode } from "./TraceRankingExplanation"

export interface TraceResultRowProps {
  result: TraceSearchResult
  /** 1-based position in the scoped output; also the selection identity. */
  rank: number
  /** Recorded size of the scoped output, shown as "Result rank of total". */
  total: number
  /** Score meaning for the mode being shown ("Fusion score" / "Provider score"). */
  mode: RankingMode
  /** Provider the scoped output belongs to, or null for a fused whole trace. */
  providerId: string | null
  selected: boolean
  onSelect: () => void
}

/**
 * One recorded result row: a thin adapter to the shared card, so the Activity
 * list and the Playground list show the same title, URL, snippet, provider
 * badges, and score. Selection stays with the workspace.
 */
export function TraceResultRow({
  result,
  rank,
  total,
  mode,
  providerId,
  selected,
  onSelect,
}: TraceResultRowProps) {
  return (
    <li className="min-w-0">
      <SearchResultCard
        result={toTraceResultView({ result, rank, total, mode, providerId })}
        selected={selected}
        onSelect={onSelect}
      />
    </li>
  )
}
