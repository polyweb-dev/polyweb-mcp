import type { TraceSearchResult } from "@/domains/activity"

/** Which ranking this view explains: the fused output, or one provider's own. */
export type RankingMode = "fusion" | "provider"

const FUSION_SCORED =
  "Results are shown in FreeSearch's final fused order. Higher recorded fusion scores appear first."
const FUSION_UNSCORED =
  "Results are shown in the order stored by FreeSearch. This trace did not record fusion scores or raw rank inputs, so the exact calculation is unavailable."
const RRF_ABSENT =
  "Raw reciprocal-rank inputs and per-provider ranks are not recorded, so exact RRF arithmetic is unavailable."

/** One sentence per mode: the order is explained once, never per result. */
function providerCopy(provider: string, scored: boolean): string {
  if (scored) {
    return `Results keep the order returned by ${provider}. Recorded provider scores are shown as metadata; FreeSearch did not reorder this response.`
  }
  return `Results keep the order returned by ${provider}. This trace did not record provider scores, so returned order is the only ranking signal.`
}

/**
 * Ranking transparency from recorded data only: one mode-appropriate sentence
 * about the order and, when fusion scores exist, the honest note that the RRF
 * inputs behind them were never stored. The result list itself carries the
 * order, so nothing is repeated here.
 */
export function TraceRankingExplanation({
  results,
  mode,
  providerLabel,
}: {
  results: readonly TraceSearchResult[]
  mode: RankingMode
  providerLabel: string
}) {
  const scored = results.some((result) => result.score !== null)
  const sentence =
    mode === "fusion"
      ? scored
        ? FUSION_SCORED
        : FUSION_UNSCORED
      : providerCopy(providerLabel, scored)
  return (
    <div className="min-w-0 space-y-2 text-[12px]">
      <p className="text-[var(--muted)]">{sentence}</p>
      {mode === "fusion" && scored && <p className="text-[var(--muted)]">{RRF_ABSENT}</p>}
    </div>
  )
}
