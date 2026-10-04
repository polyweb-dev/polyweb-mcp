import { useMemo, type ReactNode } from "react"
import {
  deriveProviderAttempts,
  deriveTraceLatencySummary,
  selectUserTraceStages,
  type TraceLatencySummary,
  type TraceProviderAttempt,
  type TraceStage,
} from "@/domains/activity"
import { providerIdentity } from "@/domains/providers"
import {
  LatencyWaterfall,
  LatencyWaterfallValue,
  type LatencyWaterfallRow,
} from "@/shared/ui/LatencyWaterfall"
import { ProviderBadge } from "@/shared/ui/ProviderBadge"

export interface TraceTrajectoryProps {
  stages: readonly TraceStage[]
  totalMs: number
  selectedSpanId: string | null
  onSelect: (spanId: string) => void
}

const PROVIDER_SPAN_NAME = "freesearch.provider"
const AGGREGATED_PROVIDER = "aggregated"
const TOTAL_SPAN_NAMES: readonly string[] = ["POST /search", "POST /fetch"]
const TRACK_COLOR = "var(--accent-cyan)"
const PROCESSING_COLOR = "var(--accent-seafoam)"
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
        {stage.outcome}
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
      <span className="flex min-w-0 flex-wrap items-center gap-1.5">
        {/* The recorded stage stays announced even when the badge replaces it. */}
        <span className="sr-only">{stage.label}</span>
        {" "}
        <ProviderBadge providerId={identity.id} name={identity.name} logoClassName="size-3.5" />
        {" "}
        <span>request</span>
        {outcomeNote(stage)}
      </span>
    )
  }
  return (
    <span className="block min-w-0">
      <span className="[overflow-wrap:anywhere]">{stage.label}</span>
      {outcomeNote(stage)}
    </span>
  )
}

function trackColor(stage: TraceStage): string {
  if (stage.outcome === "error") return ERROR_COLOR
  if (stage.name === PROVIDER_SPAN_NAME) return TRACK_COLOR
  return PROCESSING_COLOR
}

function summaryCell(label: string, value: string): ReactNode {
  return (
    <div key={label} className="min-w-0">
      <dt className="text-[11px] text-[var(--muted)]">{label}</dt>
      <dd className="tnum text-[12px] text-[var(--text-strong)]">{value}</dd>
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
        Time outside provider calls{" "}
        <span className="tnum text-[var(--text-strong)]">{summary.outsideProvidersMs}ms</span>.
        Provider phases were not recorded for this trace.
      </p>
    )
  }
  return (
    <div className="min-w-0 space-y-1">
      <dl className="grid min-w-0 grid-cols-2 gap-x-4 gap-y-1 sm:grid-cols-4">
        {summaryCell("Before providers", `${summary.beforeProvidersMs}ms`)}
        {summaryCell("Provider active", `${summary.providerActiveMs}ms`)}
        {summary.betweenProvidersMs > 0 &&
          summaryCell("Between providers", `${summary.betweenProvidersMs}ms`)}
        {summaryCell("After providers", `${summary.afterProvidersMs}ms`)}
        {summaryCell("Outside provider calls", `${summary.outsideProvidersMs}ms`)}
      </dl>
      <p className="text-[11px] text-[var(--muted)]">
        Provider active counts overlapping provider calls once. The server trace excludes browser
        transport, and Backend handling includes provider time.
      </p>
    </div>
  )
}

function toRow(
  stage: TraceStage,
  attempt: TraceProviderAttempt | undefined,
  selectedSpanId: string | null,
  onSelect: (spanId: string) => void
): LatencyWaterfallRow {
  return {
    id: stage.spanId,
    label: rowLabel(stage),
    segments: [{ offsetMs: stage.offsetMs, durationMs: stage.durationMs, color: trackColor(stage) }],
    value: (
      <LatencyWaterfallValue
        durationMs={stage.durationMs}
        resultCount={attempt?.resultCount ?? null}
        outcome={stage.outcome === "success" ? undefined : stage.outcome}
      />
    ),
    depth: stageDepth(stage),
    selected: stage.spanId === selectedSpanId,
    onSelect: () => onSelect(stage.spanId),
  }
}

/**
 * The recorded trajectory at user level: total, route selection, backend
 * handling, one row per provider attempt, results assembly, and the response to
 * the caller, all on one shared time axis (PLAN §4). Transport and parse
 * children stay out of the rows; selecting a row hands its span id to the side
 * inspector, and nothing here expands or animates.
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
  const attemptBySpan = useMemo(
    () => new Map(attempts.map((attempt) => [attempt.spanId, attempt])),
    [attempts]
  )
  const rows = visible.map((stage) =>
    toRow(stage, attemptBySpan.get(stage.spanId), selectedSpanId, onSelect)
  )

  return (
    <div className="min-w-0 space-y-2">
      {latencySummary(summary, attempts.length > 0)}
      <div className="min-w-0 max-h-[26rem] overflow-y-auto overflow-x-hidden pr-1">
        <LatencyWaterfall
          rows={rows}
          totalMs={totalMs}
          ariaLabel="Trace trajectory"
          stickyRuler
        />
      </div>
    </div>
  )
}
