import type { TraceSearchResult } from "@/domains/activity"
import { providerIdentity } from "@/domains/providers"

/** Which ranking this view explains: the fused output, or one provider's own. */
export type RankingMode = "fusion" | "provider"

const FUSION_SCORED =
  "Results are shown in FreeSearch's final fused order. Higher recorded fusion scores appear first."
const FUSION_UNSCORED =
  "Results are shown in the order stored by FreeSearch. This trace did not record fusion scores or raw rank inputs, so the exact calculation is unavailable."
const RRF_ABSENT =
  "Raw reciprocal-rank inputs and per-provider ranks are not recorded, so exact RRF arithmetic is unavailable."

/** One sentence per mode, split around the provider identity it names. */
function providerCopy(scored: boolean): { before: string; after: string } {
  const before = "Results keep the order returned by "
  if (scored) {
    return {
      before,
      after:
        ". Recorded provider scores are shown as metadata; FreeSearch did not reorder this response.",
    }
  }
  return {
    before,
    after:
      ". This trace did not record provider scores, so returned order is the only ranking signal.",
  }
}

/**
 * The provider name inside a sentence: plain text at the surrounding size,
 * never a badge, so the sentence reads as one line. An unrecorded provider
 * keeps the plain label for the same reason.
 */
function providerInline(providerId: string | null, providerLabel: string) {
  if (providerId === null || providerId === "") return <span>{providerLabel}</span>
  const identity = providerIdentity(providerId)
  if (identity.id === "" || identity.id === "aggregated") return <span>{identity.name}</span>
  return <span>{identity.name}</span>
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
  providerId,
  providerLabel,
}: {
  results: readonly TraceSearchResult[]
  mode: RankingMode
  providerId: string | null
  providerLabel: string
}) {
  const scored = results.some((result) => result.score !== null)
  const copy = providerCopy(scored)
  return (
    <div className="min-w-0 space-y-2 text-[12px]">
      <p className="text-[var(--muted)]">
        {mode === "fusion" ? (
          scored ? (
            FUSION_SCORED
          ) : (
            FUSION_UNSCORED
          )
        ) : (
          <>
            {copy.before}
            {providerInline(providerId, providerLabel)}
            {copy.after}
          </>
        )}
      </p>
      {mode === "fusion" && scored && <p className="text-[var(--muted)]">{RRF_ABSENT}</p>}
    </div>
  )
}
