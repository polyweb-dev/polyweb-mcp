import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/shared/ui/table"
import type { TraceSummary } from "@/domains/activity"
import { TraceStatusPill } from "./TraceStatusPill"

const COLUMNS = ["Time", "Operation", "Provider", "Status", "Latency", "Results"]

function timeLabel(startedAt: string): string {
  const parsed = new Date(startedAt)
  return Number.isNaN(parsed.getTime()) ? "—" : parsed.toLocaleTimeString()
}

function resultLabel(summary: TraceSummary): string {
  if (summary.resultCount === null) return "—"
  return String(summary.resultCount)
}

/**
 * Activity list: one scannable row per trace. Rows carry no query text and no
 * results — clicking a row is the convenience path into the detail, and "View
 * details" is the explicit, keyboard-reachable control that discloses the same
 * content (PLAN §6, REQUIREMENTS §3.4).
 */
export function ActivityList({
  summaries,
  onSelect,
}: {
  summaries: TraceSummary[]
  onSelect: (traceId: string) => void
}) {
  return (
    <div className="overflow-hidden rounded-lg border border-[var(--border-subtle)]">
      <Table className="text-[13px]">
        <TableHeader>
          <TableRow className="border-b border-[var(--border-subtle)] bg-[var(--elevated)] hover:bg-[var(--elevated)]">
            {COLUMNS.map((column, index) => (
              <TableHead
                key={column}
                className={`h-9 px-4 text-[12px] text-[var(--muted)] ${
                  index >= 4 ? "text-right" : index === 3 ? "text-center" : ""
                }`}
              >
                {column}
              </TableHead>
            ))}
            <TableHead className="h-9 px-4 text-[12px] text-[var(--muted)] text-right">
              <span className="sr-only">Details</span>
            </TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {summaries.map((summary) => (
            <TableRow
              key={summary.traceId}
              onClick={() => onSelect(summary.traceId)}
              className="cursor-pointer border-b border-[var(--border-subtle)] last:border-b-0"
            >
              <TableCell className="px-4 py-2.5 text-[var(--muted)] tnum">
                {timeLabel(summary.startedAt)}
              </TableCell>
              <TableCell className="px-4 py-2.5 capitalize text-[var(--text)]">
                {summary.operation ?? "—"}
              </TableCell>
              <TableCell className="px-4 py-2.5 font-medium text-[var(--text-strong)]">
                {summary.providerLabel}
              </TableCell>
              <TableCell className="px-4 py-2.5 text-center">
                <TraceStatusPill outcome={summary.outcome} />
              </TableCell>
              <TableCell className="px-4 py-2.5 text-right text-[var(--text)] tnum">
                {summary.durationMs}ms
              </TableCell>
              <TableCell className="px-4 py-2.5 text-right text-[var(--muted)] tnum">
                {resultLabel(summary)}
              </TableCell>
              <TableCell className="px-4 py-2.5 text-right">
                <button
                  type="button"
                  onClick={(event) => {
                    // The row is a click target too: stop the bubble so one
                    // interaction selects the trace exactly once.
                    event.stopPropagation()
                    onSelect(summary.traceId)
                  }}
                  className="rounded px-2 py-1 text-[12px] font-medium text-[var(--signal)] hover:text-[var(--text-strong)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--signal)]/40"
                >
                  View details
                </button>
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  )
}
