import type { TraceSearchResult } from "@/domains/activity"
import { ProviderBadge } from "@/shared/ui/ProviderBadge"
import { ResultScore } from "@/shared/ui/ResultScore"
import { toTraceResultView } from "../model/traceResultPresentation"
import type { RankingMode } from "./TraceRankingExplanation"

export interface TraceResultRowProps {
  result: TraceSearchResult
  /** 1-based position in the scoped output; also the selection identity. */
  rank: number
  /** Recorded size of the scoped output, shown as "Result rank of total". */
  total: number
  /** Score meaning for the mode being shown (fusion or provider). */
  mode: RankingMode
  /** Provider the scoped output belongs to, or null for a fused whole trace. */
  providerId: string | null
  selected: boolean
  onSelect: () => void
}

function resultHost(url: string): string {
  try {
    return new URL(url).host
  } catch {
    return url
  }
}

/** A readable trace row separates the target and excerpt from its attribution. */
export function TraceResultRow({
  result,
  rank,
  total,
  mode,
  providerId,
  selected,
  onSelect,
}: TraceResultRowProps) {
  const view = toTraceResultView({ result, rank, total, mode, providerId })
  const providers = view.providers
  const firstProvider = providers[0]
  return (
    <li className="min-w-0">
      <button
        type="button"
        aria-pressed={selected}
        onClick={onSelect}
        className={`flex w-full min-w-0 gap-3 border-b border-l-2 border-[var(--border-subtle)] px-3 py-1.5 text-left transition-colors motion-reduce:transition-none focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-[var(--signal)]/40 ${
          selected
            ? "border-l-[var(--signal)] bg-[var(--signal-muted)]"
            : "border-l-transparent hover:bg-[var(--surface)]"
        }`}
      >
        <span className="tnum w-6 shrink-0 pt-0.5 text-[12px] text-[var(--muted)]">
          {String(rank).padStart(2, "0")}
        </span>
        <span className="grid min-w-0 flex-1 gap-y-0.5">
          <span
            className="text-[14px] font-medium leading-5 text-[var(--text-strong)] [overflow-wrap:anywhere]"
            title={result.title || "Untitled result"}
            style={{ display: "-webkit-box", WebkitBoxOrient: "vertical", WebkitLineClamp: 2, overflow: "hidden" }}
          >
            {result.title || "Untitled result"}
          </span>
          <span className="mono min-w-0 truncate text-[11px] leading-4 text-[var(--muted)]" title={result.url}>
            {resultHost(result.url)}
          </span>
          <span
            className="text-[13px] leading-[1.35] text-[var(--text)] [overflow-wrap:anywhere]"
            title={result.snippet || "Snippet not recorded"}
            style={{ display: "-webkit-box", WebkitBoxOrient: "vertical", WebkitLineClamp: 2, overflow: "hidden" }}
          >
            {result.snippet || <span className="text-[var(--muted)]">Snippet not recorded</span>}
          </span>
          <span className="flex min-w-0 items-center justify-between gap-3 border-t border-[var(--border-subtle)]/70 pt-0.5">
            <span className="flex min-w-0 items-center gap-x-2 text-[11px] leading-4 text-[var(--muted)]">
              {firstProvider !== undefined ? (
                <>
                  <ProviderBadge
                    providerId={firstProvider.id}
                    name={firstProvider.name}
                    className="shrink-0 text-[var(--muted)]"
                    logoClassName="size-3.5"
                  />
                  {providers.length > 1 && <span className="shrink-0">+{providers.length - 1}</span>}
                </>
              ) : (
                <span className="shrink-0">Source not recorded</span>
              )}
            </span>
            <span className="shrink-0 text-[11px] text-[var(--text-strong)]">
              <ResultScore score={view.score} />
            </span>
          </span>
        </span>
      </button>
    </li>
  )
}
