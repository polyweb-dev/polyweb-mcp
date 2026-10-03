import type { ReactNode } from "react"
import type { TraceSearchResult } from "@/domains/activity"
import type { RankingMode } from "./TraceRankingExplanation"
import { TraceRankingExplanation } from "./TraceRankingExplanation"

export interface TraceResultInspectorProps {
  result: TraceSearchResult | null
  /** 1-based rank of the selected result, or null when nothing is selected. */
  rank: number | null
  mode: RankingMode
  providerLabel: string
  results: readonly TraceSearchResult[]
}

const SCORE_LABELS: Record<RankingMode, string> = {
  fusion: "Fusion score",
  provider: "Provider score",
}

function metaRow(label: string, value: ReactNode): ReactNode {
  return (
    <div className="min-w-0">
      <dt className="text-[11px] text-[var(--muted)]">{label}</dt>
      <dd className="min-w-0 text-[12px] text-[var(--text-strong)] [overflow-wrap:anywhere]">{value}</dd>
    </div>
  )
}

/** A missing recorded value is stated once as such, never invented. */
function recorded(value: string | null): ReactNode {
  if (value === null || value === "") return <span className="text-[var(--muted)]">Not recorded</span>
  return value
}

/**
 * Side inspector for one selected result: the complete payload the compact row
 * cannot hold, plus the recorded metadata. It replaces itself on the next
 * selection instead of appending, so the dialog height stays bounded.
 */
export function TraceResultInspector({
  result,
  rank,
  mode,
  providerLabel,
  results,
}: TraceResultInspectorProps) {
  if (result === null || rank === null) {
    return (
      <div className="min-w-0 space-y-3 text-[12px]">
        <p className="text-[var(--muted)]">
          {results.length === 0
            ? "This trace recorded no ranked result to inspect."
            : "Select a result to inspect its full snippet, URL, and recorded score."}
        </p>
        {results.length > 0 && (
          <div className="min-w-0 space-y-1">
            <h4 className="text-[12px] text-[var(--muted)]">Why this order</h4>
            <TraceRankingExplanation results={results} mode={mode} providerLabel={providerLabel} />
          </div>
        )}
      </div>
    )
  }

  return (
    <div className="min-w-0 space-y-3 text-[12px]">
      <p className="text-[var(--muted)] tnum">
        Result {rank} of {results.length}
      </p>
      <h4 className="text-[13px] font-medium text-[var(--text-strong)] [overflow-wrap:anywhere]">
        {result.title}
      </h4>
      <a
        href={result.url}
        target="_blank"
        rel="noreferrer noopener"
        className="mono block text-[12px] text-[var(--signal)] [overflow-wrap:anywhere] hover:underline"
      >
        {result.url}
      </a>
      <p className="text-[13px] text-[var(--text)] [overflow-wrap:anywhere]">
        {result.snippet === "" ? <span className="text-[var(--muted)]">Snippet not recorded</span> : result.snippet}
      </p>
      <dl className="grid min-w-0 grid-cols-2 gap-x-3 gap-y-2 border-t border-[var(--border-subtle)] pt-3">
        {metaRow("Rank", rank)}
        {metaRow("Source", recorded(result.source))}
        {metaRow(
          SCORE_LABELS[mode],
          result.score === null ? (
            <span className="text-[var(--muted)]">Not recorded</span>
          ) : (
            <span className="tnum" style={{ color: "var(--accent-gold)" }}>
              {result.score.toFixed(2)}
            </span>
          )
        )}
        {metaRow("Provider", recorded(providerLabel))}
      </dl>
    </div>
  )
}
