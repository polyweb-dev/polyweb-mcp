import { cn } from "cn"
import type { TraceSearchResult } from "@/domains/activity"

export interface TraceResultRowProps {
  result: TraceSearchResult
  /** 1-based position in the scoped output; also the selection identity. */
  rank: number
  selected: boolean
  onSelect: () => void
  /** Score meaning for the mode being shown ("Fusion score" / "Provider score"). */
  scoreLabel: string
}

/**
 * One compact result row: the recorded rank, title, URL, and score metadata,
 * and nothing that would grow the row to a full snippet. Selecting it hands the
 * payload to the side inspector instead (PLAN §5.3), so the row stays a single
 * quiet line even for a multi-thousand-character result.
 */
export function TraceResultRow({
  result,
  rank,
  selected,
  onSelect,
  scoreLabel,
}: TraceResultRowProps) {
  return (
    <li className="min-w-0">
      <button
        type="button"
        aria-pressed={selected}
        onClick={onSelect}
        className={cn(
          "grid w-full min-w-0 grid-cols-[1.25rem_minmax(0,1fr)] items-baseline gap-x-2 rounded border p-2 text-left transition-colors motion-reduce:transition-none",
          selected
            ? "border-[var(--signal)] bg-[var(--signal-muted)]"
            : "border-[var(--border-subtle)] hover:border-[var(--muted)]"
        )}
      >
        <span
          aria-hidden="true"
          className="text-right text-[12px] tnum"
          style={{ color: "var(--accent-gold)" }}
        >
          {rank}
        </span>
        <span className="sr-only">Rank {rank}</span>
        <span className="block min-w-0">
          <span className="block text-[13px] font-medium text-[var(--text-strong)] [overflow-wrap:anywhere]">
            {result.title}
          </span>
          <span className="mono block text-[12px] text-[var(--muted)] [overflow-wrap:anywhere]">
            {result.url}
          </span>
          <span className="block text-[11px] text-[var(--muted)] tnum">
            {result.source ?? "Source not recorded"}
            {result.score !== null && (
              <>
                {" "}
                <span style={{ color: "var(--accent-gold)" }}>
                  {scoreLabel} {result.score.toFixed(2)}
                </span>
              </>
            )}
          </span>
        </span>
      </button>
    </li>
  )
}
