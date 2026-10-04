import type { TraceSearchResult } from "@/domains/activity"
import { SearchResultInspector } from "@/shared/ui/SearchResultInspector"
import { toTraceResultView } from "../model/traceResultPresentation"
import type { RankingMode } from "./TraceRankingExplanation"
import { TraceRankingExplanation } from "./TraceRankingExplanation"

export interface TraceResultInspectorProps {
  result: TraceSearchResult | null
  /** 1-based rank of the selected result, or null when nothing is selected. */
  rank: number | null
  mode: RankingMode
  /** Provider the scoped output belongs to, or null for a fused whole trace. */
  providerId: string | null
  providerLabel: string
  results: readonly TraceSearchResult[]
}

function emptyCopy(results: readonly TraceSearchResult[]): string {
  return results.length === 0
    ? "This trace recorded no ranked result to inspect."
    : "Select a result to inspect its full snippet, URL, and recorded score."
}

/**
 * Side inspector for one selected trace result: a thin adapter to the shared
 * inspector, so the recorded rank, attribution, score, and target host come
 * before the snippet exactly as they do in the Playground. The order
 * explanation keeps its place while nothing is selected.
 */
export function TraceResultInspector({
  result,
  rank,
  mode,
  providerId,
  providerLabel,
  results,
}: TraceResultInspectorProps) {
  if (result === null || rank === null) {
    return (
      <div className="min-w-0 space-y-3 text-[12px]">
        <SearchResultInspector
          result={null}
          emptyState={<p className="text-[var(--muted)]">{emptyCopy(results)}</p>}
        />
        {results.length > 0 && (
          <div className="min-w-0 space-y-1">
            <h4 className="text-[12px] text-[var(--muted)]">Why this order</h4>
            <TraceRankingExplanation
              results={results}
              mode={mode}
              providerId={providerId}
              providerLabel={providerLabel}
            />
          </div>
        )}
      </div>
    )
  }

  return (
    <SearchResultInspector
      result={toTraceResultView({ result, rank, total: results.length, mode, providerId })}
    />
  )
}
