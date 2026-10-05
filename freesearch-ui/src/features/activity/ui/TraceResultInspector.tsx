import { ExternalLink } from "lucide-react"
import type { ReactNode } from "react"
import type { TraceSearchResult } from "@/domains/activity"
import { ProviderBadge } from "@/shared/ui/ProviderBadge"
import { ResultScore } from "@/shared/ui/ResultScore"
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

function metadata(label: string, value: ReactNode, className = "") {
  return (
    <div className={`min-w-0 ${className}`}>
      <dt className="text-[10px] text-[var(--muted)]">{label}</dt>
      <dd className="mt-0.5 min-w-0 text-[11px] text-[var(--text-strong)] [overflow-wrap:anywhere]">
        {value}
      </dd>
    </div>
  )
}

function attribution(result: ReturnType<typeof toTraceResultView>) {
  if (result.providers.length === 0) {
    return <span className="text-[var(--muted)]">Not recorded</span>
  }
  return (
    <span className="flex flex-wrap items-center gap-x-2 gap-y-1">
      {result.providers.map((provider) => (
        <ProviderBadge
          key={provider.id}
          providerId={provider.id}
          name={provider.name}
          logoClassName="size-3"
        />
      ))}
    </span>
  )
}

/** The selected result stays readable without a nested snippet scrollbar. */
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
      <div className="min-w-0 space-y-4 text-[12px]">
        <p className="text-[var(--muted)]">{emptyCopy(results)}</p>
        {results.length > 0 && (
          <TraceRankingExplanation
            results={results}
            mode={mode}
            providerId={providerId}
            providerLabel={providerLabel}
          />
        )}
      </div>
    )
  }

  const view = toTraceResultView({ result, rank, total: results.length, mode, providerId })
  const scoreValue: ReactNode =
    view.score.value === null
      ? <span className="text-[var(--muted)]">Not recorded</span>
      : view.score.value === 0
        ? <span className="text-[var(--muted)]">0 (no ranking signal)</span>
        : <ResultScore score={view.score} />
  return (
    <div className="min-w-0 space-y-4 text-[13px]">
      <header className="flex min-w-0 items-start justify-between gap-3 border-b border-[var(--border-subtle)] pb-3">
        <div className="min-w-0">
          <p className="tnum text-[11px] text-[var(--signal)]">
            Result {rank} of {results.length}
          </p>
          <h3 className="mt-1 text-[14px] font-medium leading-snug text-[var(--text-strong)] [overflow-wrap:anywhere]">
            {result.title || "Untitled result"}
          </h3>
        </div>
        <a
          href={result.url}
          target="_blank"
          rel="noreferrer"
          title="Open target URL"
          aria-label="Open target URL in a new tab"
          className="shrink-0 rounded border border-[var(--border-subtle)] p-1.5 text-[var(--muted)] transition-colors hover:text-[var(--text-strong)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--signal)]/40"
        >
          <ExternalLink aria-hidden="true" className="size-3.5" />
        </a>
      </header>

      <dl className="flex min-w-0 flex-wrap items-start justify-between gap-x-6 gap-y-3">
        {metadata(view.attributionLabel, attribution(view), "min-w-0 flex-1")}
        {metadata(view.score.label, scoreValue, "shrink-0 text-right")}
      </dl>

      <section className="min-w-0 space-y-1">
        <h4 className="text-[12px] text-[var(--muted)]">Target URL</h4>
        <a
          href={result.url}
          target="_blank"
          rel="noreferrer"
          title={result.url}
          className="mono block text-[12px] leading-relaxed text-[var(--signal)] [overflow-wrap:anywhere] hover:underline"
        >
          {result.url}
        </a>
      </section>

      <section className="min-w-0 space-y-1">
        <h4 className="text-[12px] text-[var(--muted)]">Snippet summary</h4>
        <p className="whitespace-pre-wrap text-[14px] leading-relaxed text-[var(--text)] [overflow-wrap:anywhere]">
          {result.snippet || <span className="text-[var(--muted)]">Snippet not recorded</span>}
        </p>
      </section>

      <details className="min-w-0 border-t border-[var(--border-subtle)] pt-3">
        <summary className="cursor-pointer text-[11px] text-[var(--muted)]">Why this order</summary>
        <div className="mt-2">
          <TraceRankingExplanation
            results={results}
            mode={mode}
            providerId={providerId}
            providerLabel={providerLabel}
          />
        </div>
      </details>
    </div>
  )
}
