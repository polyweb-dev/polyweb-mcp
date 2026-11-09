import type { ReactNode } from "react"
import { Fragment, useState } from "react"
import { ChevronRight } from "lucide-react"
import type { TraceSummary } from "@/domains/activity"
import { providerIdentity } from "@/domains/providers"
import { formatDateTime, formatLatency, formatRelativeTime } from "@/shared/lib/formatTime"
import { ProviderBadge } from "@/shared/ui/ProviderBadge"
import type { TraceLoadState } from "../model/useActivityController"
import { ActivityProviderRows } from "./ActivityProviderRows"
import { ActivityRowAction } from "./ActivityRowAction"
import { TraceStatusPill } from "./TraceStatusPill"

const AGGREGATED_PROVIDER = "aggregated"

const COLUMNS = [
  { label: "Time", className: "" },
  { label: "Operation", className: "" },
  { label: "Provider", className: "" },
  { label: "Status", className: "" },
  { label: "Latency", className: "text-right" },
  { label: "Results", className: "text-right" },
]

function timeLabel(startedAt: string, now: number): string {
  const parsed = new Date(startedAt)
  return Number.isNaN(parsed.getTime()) ? "—" : formatRelativeTime(parsed.getTime(), now)
}

function operationLabel(summary: TraceSummary): string {
  if (summary.operation === "search") return "Search"
  if (summary.operation === "fetch") return "Fetch"
  return "—"
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
      className="relative z-10 inline-flex size-5 items-center justify-center rounded-sm text-[var(--muted)] transition-colors hover:bg-[var(--raised)] hover:text-[var(--text-strong)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--signal)]/40"
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
    <tr onClick={() => onSelect(summary.traceId)} className="relative cursor-pointer">
      <td className="tnum whitespace-nowrap text-[var(--muted)]" title={formatDateTime(summary.startedAt)}>{time}</td>
      <td>{operationLabel(summary)}</td>
      <td className="fs-cell-strong">
        <span className="inline-flex items-center gap-1.5">
          {summary.provider === AGGREGATED_PROVIDER &&
            providerExpander(time, expanded, panelId, () =>
              onToggleProviders(summary.traceId)
            )}
          {providerValue(summary)}
        </span>
      </td>
      <td>
        <TraceStatusPill outcome={summary.outcome} />
      </td>
      <td className="tnum text-right">{formatLatency(summary.durationMs)}</td>
      <td className="tnum text-right text-[var(--muted)]">{resultLabel(summary)}</td>
      <td className="fs-cell-actions">
        <ActivityRowAction onOpen={() => onSelect(summary.traceId)} />
      </td>
    </tr>
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
 * Activity list: one scannable row per trace on the shared table. The whole
 * row opens the trace; its trailing chevron is the row's button, so the detail
 * is reachable by keyboard with a visible focus ring. A fanout trace ("All
 * providers") can disclose its per-provider attempts inline.
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
  const [now] = useState(Date.now)
  return (
    <div className="fs-panel min-w-0 overflow-hidden">
      <table aria-label="Activity" className="fs-table">
        <thead>
          <tr>
            {COLUMNS.map((column) => (
              <th key={column.label} scope="col" className={column.className}>
                {column.label}
              </th>
            ))}
            <th scope="col" className="fs-cell-actions">
              <span className="sr-only">Actions</span>
            </th>
          </tr>
        </thead>
        <tbody>
          {summaries.map((summary) => {
            const expanded = expandedTraceId === summary.traceId
            const panelId = `trace-providers-${summary.traceId}`
            return (
              <Fragment key={summary.traceId}>
                {traceRow({
                  summary,
                  time: timeLabel(summary.startedAt, now),
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
        </tbody>
      </table>
    </div>
  )
}
