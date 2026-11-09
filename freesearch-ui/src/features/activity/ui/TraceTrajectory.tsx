import { useMemo, type ReactNode } from "react"
import {
  deriveProviderAttempts,
  deriveTraceLatencySummary,
  selectUserTraceStages,
  type TraceLatencySummary,
  type TraceStage,
} from "@/domains/activity"
import { providerIdentity } from "@/domains/providers"
import { formatLatency } from "@/shared/lib/formatTime"
import {
  LatencyWaterfall,
  type LatencyWaterfallRow,
} from "@/shared/ui/LatencyWaterfall"
import { ProviderBadge } from "@/shared/ui/ProviderBadge"
import { traceSpanLabel } from "../model/traceSpanPresentation"

export interface TraceTrajectoryProps {
  stages: readonly TraceStage[]
  totalMs: number
  selectedSpanId: string | null
  onSelect: (spanId: string) => void
}

const PROVIDER_SPAN_NAME = "freesearch.provider"
const AGGREGATED_PROVIDER = "aggregated"
const TOTAL_SPAN_NAMES: readonly string[] = ["POST /search", "POST /fetch"]
/** One accent for provider time; FreeSearch's own stages sit in a neutral step. */
const TRACK_COLOR = "var(--accent-cyan)"
const PROCESSING_COLOR = "color-mix(in srgb, var(--text) 38%, transparent)"
const ERROR_COLOR = "var(--status-danger)"

/** Shallow, user-level depth: the total is the root, a provider attempt is nested. */
function stageDepth(stage: TraceStage): number {
  if (TOTAL_SPAN_NAMES.includes(stage.name)) return 0
  return stage.name === PROVIDER_SPAN_NAME ? 2 : 1
}

function outcomeNote(stage: TraceStage): ReactNode {
  if (stage.outcome === "success") return null
  return (
    <>
      {" "}
      <span className="text-[11px]" style={{ color: ERROR_COLOR }}>
        {stage.outcome === "error" ? "Error" : "Partial"}
      </span>
    </>
  )
}

/**
 * The row label: a provider attempt shows its identity badge followed by
 * `request`, every other user-level stage keeps the label the backend recorded.
 * The explicit spaces keep the row's accessible name readable, because the
 * logo, the name, and the stage word are separate elements.
 */
function rowLabel(stage: TraceStage): ReactNode {
  const providerId = stage.name === PROVIDER_SPAN_NAME ? stage.providerId : null
  const identity = providerId === null || providerId === "" ? null : providerIdentity(providerId)
  if (identity !== null && identity.id !== "" && identity.id !== AGGREGATED_PROVIDER) {
    return (
      <span className="flex min-w-0 items-center gap-1.5 overflow-hidden whitespace-nowrap" title={`${identity.name} request`}>
        {/* The recorded stage stays announced even when the badge replaces it. */}
        <span className="sr-only">{stage.label}</span>
        {" "}
        <span className="min-w-0 truncate">
          <ProviderBadge providerId={identity.id} name={identity.name} logoClassName="size-3.5" />
          {" request"}
        </span>
        {outcomeNote(stage)}
      </span>
    )
  }
  return (
    <span className="block min-w-0">
      <span className="[overflow-wrap:anywhere]">{traceSpanLabel(stage)}</span>
      {outcomeNote(stage)}
    </span>
  )
}

function trackColor(stage: TraceStage): string {
  if (stage.outcome === "error") return ERROR_COLOR
  if (stage.name === PROVIDER_SPAN_NAME) return TRACK_COLOR
  return PROCESSING_COLOR
}

function summaryCell(label: string, milliseconds: number): ReactNode {
  return (
    <div key={label} className="min-w-0">
      <dt className="whitespace-nowrap text-[11px] leading-4 text-[var(--muted)]">{label}</dt>
      <dd className="tnum whitespace-nowrap text-[12px] text-[var(--text-strong)]">
        {formatLatency(milliseconds)}
      </dd>
    </div>
  )
}

/**
 * The two-hop latency story in one compact line: how much of the trace ran
 * before, between, and after the provider calls, and how much of it provider
 * time covered. It never claims low overhead — the recorded numbers decide.
 */
function latencySummary(summary: TraceLatencySummary, hasAttempts: boolean): ReactNode {
  if (!hasAttempts) {
    return (
      <p className="text-[12px] text-[var(--muted)]">
        Provider phases were not recorded for this trace
      </p>
    )
  }
  return (
    <div className="min-w-0">
      <dl className="flex min-w-0 flex-wrap gap-x-6 gap-y-2">
        {summaryCell("Before providers", summary.beforeProvidersMs)}
        {summaryCell("Provider active", summary.providerActiveMs)}
        {summary.betweenProvidersMs > 0 &&
          summaryCell("Between providers", summary.betweenProvidersMs)}
        {summaryCell("After providers", summary.afterProvidersMs)}
      </dl>
    </div>
  )
}

function toRow(
  stage: TraceStage,
  selectedSpanId: string | null,
  onSelect: (spanId: string) => void
): LatencyWaterfallRow {
  return {
    id: stage.spanId,
    label: rowLabel(stage),
    segments: [{ offsetMs: stage.offsetMs, durationMs: stage.durationMs, color: trackColor(stage) }],
    value: formatLatency(stage.durationMs),
    depth: stageDepth(stage),
    selected: stage.spanId === selectedSpanId,
    onSelect: () => onSelect(stage.spanId),
  }
}

/**
 * The recorded trajectory at user level: total, route selection, backend
 * handling, one row per provider attempt, results assembly, and the response to
 * the caller, all on one shared time axis (PLAN §4).
 */
export function TraceTrajectory({
  stages,
  totalMs,
  selectedSpanId,
  onSelect,
}: TraceTrajectoryProps) {
  const visible = useMemo(() => selectUserTraceStages(stages), [stages])
  const attempts = useMemo(() => deriveProviderAttempts(stages, null), [stages])
  const summary = useMemo(() => deriveTraceLatencySummary(attempts, totalMs), [attempts, totalMs])
  const rows = visible.map((stage) => toRow(stage, selectedSpanId, onSelect))

  return (
    // Fills the trajectory pane it is given: the summary keeps its natural
    // height and the rows take the rest, so the pane owns one scrollbar and the
    // ruler stays visible on it. `h-full` falls back to content height when a
    // parent has none, and the row floor keeps that fallback usable.
    <div className="flex h-full min-h-0 min-w-0 flex-col gap-2">
      {latencySummary(summary, attempts.length > 0)}
      <div className="min-h-[4rem] min-w-0 flex-1 overflow-x-hidden overflow-y-auto overscroll-contain [scrollbar-gutter:stable]">
        <div className="min-w-0 pr-3 py-2">
          <LatencyWaterfall
            rows={rows}
            totalMs={totalMs}
            ariaLabel="Trace trajectory"
            stickyRuler
            compactRuler
            expandedTrack
          />
        </div>
      </div>
    </div>
  )
}
