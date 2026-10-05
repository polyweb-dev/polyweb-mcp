import type { ReactNode } from "react"
import { Fragment } from "react"
import { ChevronRight } from "lucide-react"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/shared/ui/table"
import { Button } from "@/shared/ui/button"
import type { TraceSummary } from "@/domains/activity"
import { providerIdentity } from "@/domains/providers"
import { ProviderBadge } from "@/shared/ui/ProviderBadge"
import type { TraceLoadState } from "../model/useActivityController"
import { ActivityProviderRows } from "./ActivityProviderRows"
import { TraceStatusPill } from "./TraceStatusPill"

const AGGREGATED_PROVIDER = "aggregated"

const COLUMNS = [
  { label: "Time", align: "" },
  { label: "Operation", align: "" },
  { label: "Provider", align: "" },
  { label: "Status", align: "text-center" },
  { label: "Latency", align: "text-right" },
  { label: "Results", align: "text-right" },
  { label: "Actions", align: "text-right" },
]

const CELL = "px-4 py-2.5"

function timeLabel(startedAt: string): string {
  const parsed = new Date(startedAt)
  return Number.isNaN(parsed.getTime()) ? "—" : parsed.toLocaleTimeString()
}

function resultLabel(summary: TraceSummary): string {
  return summary.resultCount === null ? "—" : String(summary.resultCount)
}

/** Chevron disclosure for an all-providers row: discloses one provider per call. */
function providerExpander(
  time: string,
  expanded: boolean,
  panelId: string,
  onToggle: () => void
): ReactNode {
  return (
    <button
      type="button"
      aria-expanded={expanded}
      aria-controls={panelId}
      onClick={(event) => {
        // Row click and expander click are different intents.
        event.stopPropagation()
        onToggle()
      }}
      className="rounded-sm text-[var(--muted)] transition-colors hover:text-[var(--accent-cyan)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--signal)]/40"
    >
      <ChevronRight
        aria-hidden="true"
        className={`size-3.5 transition-transform motion-reduce:transition-none ${
          expanded ? "rotate-90" : ""
        }`}
      />
      <span className="sr-only">
        {expanded ? "Hide" : "Show"} provider responses for {time}
      </span>
    </button>
  )
}

/**
 * The list identity cell: a logo and catalog name for a specific provider, the
 * plain label for the fanout group or for a trace that named no provider.
 */
function providerValue(summary: TraceSummary): ReactNode {
  const providerId = summary.provider
  if (providerId === null || providerId === "" || providerId === AGGREGATED_PROVIDER) {
    return summary.providerLabel
  }
  const identity = providerIdentity(providerId)
  if (identity.id === "") return summary.providerLabel
  return <ProviderBadge providerId={identity.id} name={identity.name} logoClassName="size-3.5" />
}

interface TraceRowOptions {
  summary: TraceSummary
  time: string
  expanded: boolean
  panelId: string
  onSelect: (traceId: string) => void
  onToggleProviders: (traceId: string) => void
}

function traceRow(options: TraceRowOptions): ReactNode {
  const { summary, time, expanded, panelId, onSelect, onToggleProviders } = options
  return (
    <TableRow
      onClick={() => onSelect(summary.traceId)}
      className="cursor-pointer border-b border-[var(--border-subtle)] last:border-b-0"
    >
      <TableCell className={`${CELL} text-[var(--muted)] tnum`}>{time}</TableCell>
      <TableCell className={`${CELL} capitalize text-[var(--text)]`}>
        {summary.operation ?? "—"}
      </TableCell>
      <TableCell className={`${CELL} font-medium text-[var(--text-strong)]`}>
        <span className="inline-flex items-center gap-1.5">
          {summary.provider === AGGREGATED_PROVIDER &&
            providerExpander(time, expanded, panelId, () =>
              onToggleProviders(summary.traceId)
            )}
          {providerValue(summary)}
        </span>
      </TableCell>
      <TableCell className={`${CELL} text-center`}>
        <TraceStatusPill outcome={summary.outcome} />
      </TableCell>
      <TableCell className={`${CELL} text-right text-[var(--text)] tnum`}>
        {summary.durationMs}ms
      </TableCell>
      <TableCell className={`${CELL} text-right text-[var(--muted)] tnum`}>
        {resultLabel(summary)}
      </TableCell>
      <TableCell className={`${CELL} text-right`}>
        <Button
          variant="outline"
          size="default"
          onClick={(event) => {
            // The row is a click target too: stop the bubble so one interaction
            // selects the trace exactly once.
            event.stopPropagation()
            onSelect(summary.traceId)
          }}
        >
          View details
        </Button>
      </TableCell>
    </TableRow>
  )
}

export interface ActivityListProps {
  summaries: TraceSummary[]
  expandedTraceId: string | null
  detailsById: Readonly<Record<string, TraceLoadState>>
  onSelect: (traceId: string) => void
  onToggleProviders: (traceId: string) => void
  onInspect: (traceId: string, providerSpanId: string) => void
  onRetry: (traceId: string) => void
}

/**
 * Activity list: one scannable row per trace with a visible Actions column, so
 * the detail is reachable by keyboard as well as by clicking the row. A fanout
 * trace ("All providers") can disclose its per-provider attempts inline
 * (PLAN §5, REQUIREMENTS §3.2–3.4).
 */
export function ActivityList({
  summaries,
  expandedTraceId,
  detailsById,
  onSelect,
  onToggleProviders,
  onInspect,
  onRetry,
}: ActivityListProps) {
  return (
    <div className="min-w-0 overflow-hidden rounded-lg border border-[var(--border-subtle)]">
      <Table className="text-[13px]">
        <TableHeader>
          <TableRow className="border-b border-[var(--border-subtle)] bg-[var(--elevated)] hover:bg-[var(--elevated)]">
            {COLUMNS.map((column) => (
              <TableHead
                key={column.label}
                className={`h-9 px-4 text-[12px] text-[var(--muted)] ${column.align}`}
              >
                {column.label}
              </TableHead>
            ))}
          </TableRow>
        </TableHeader>
        <TableBody>
          {summaries.map((summary) => {
            const expanded = expandedTraceId === summary.traceId
            const panelId = `trace-providers-${summary.traceId}`
            return (
              <Fragment key={summary.traceId}>
                {traceRow({
                  summary,
                  time: timeLabel(summary.startedAt),
                  expanded,
                  panelId,
                  onSelect,
                  onToggleProviders,
                })}
                {expanded && (
                  <ActivityProviderRows
                    rowId={panelId}
                    state={detailsById[summary.traceId]}
                    onInspect={(providerSpanId) => onInspect(summary.traceId, providerSpanId)}
                    onRetry={() => onRetry(summary.traceId)}
                  />
                )}
              </Fragment>
            )
          })}
        </TableBody>
      </Table>
    </div>
  )
}
