import { useState, type ReactNode } from "react"
import {
  selectUserTraceStages,
  traceTrajectoryLabel,
  type TraceDetail,
  type TraceOutput,
  type TraceProviderAttempt,
  type TraceSearchOutput,
  type TraceStage,
} from "@/domains/activity"
import { providerIdentity } from "@/domains/providers"
import { InspectorSplitPane } from "@/shared/ui/InspectorSplitPane"
import { ProviderBadge } from "@/shared/ui/ProviderBadge"
import { SegmentedControl } from "@/shared/ui/SegmentedControl"
import type { RankingMode } from "./TraceRankingExplanation"
import { TraceResultInspector } from "./TraceResultInspector"
import { TraceResults } from "./TraceResults"
import { TraceSpanInspector } from "./TraceSpanInspector"
import { TraceTrajectory } from "./TraceTrajectory"

export interface TraceInspectionWorkspaceProps {
  trace: TraceDetail
  output: TraceOutput | null
  attempt: TraceProviderAttempt | null
  mode: RankingMode
}

type TraceView = "results" | "trajectory"

interface Selection {
  view: TraceView
  resultIndex: number | null
  spanId: string | null
}

const NO_SELECTION: Selection = { view: "results", resultIndex: null, spanId: null }
const AGGREGATED_PROVIDER = "aggregated"

/** Identity of the inspected subject: a new trace or scope starts fresh. */
function identityOf(trace: TraceDetail, attempt: TraceProviderAttempt | null): string {
  return `${trace.traceId}:${attempt?.spanId ?? "all"}`
}

function searchOutput(output: TraceOutput | null): TraceSearchOutput | null {
  return output !== null && output.kind === "search_results" ? output : null
}

/**
 * Provider the shown output belongs to: the scoped attempt, or the trace's own
 * provider when the whole trace is a single-provider search. A fused whole
 * trace has no single provider and keeps the null.
 */
function scopedProviderId(trace: TraceDetail, attempt: TraceProviderAttempt | null): string | null {
  if (attempt !== null) return attempt.providerId
  return trace.provider === AGGREGATED_PROVIDER ? null : trace.provider
}

function selectedStage(stages: readonly TraceStage[], spanId: string | null): TraceStage | null {
  if (spanId === null) return null
  return stages.find((stage) => stage.spanId === spanId) ?? null
}

/** The provider identity a line shows, or the recorded label when it is absent. */
function providerNode(providerId: string | null, fallbackLabel: string): ReactNode {
  if (providerId === null || providerId === "") return <span>{fallbackLabel}</span>
  const identity = providerIdentity(providerId)
  if (identity.id === "" || identity.id === AGGREGATED_PROVIDER) return <span>{fallbackLabel}</span>
  return <ProviderBadge providerId={identity.id} name={identity.name} logoClassName="size-3.5" />
}

/** One quiet line naming what the workspace is currently showing. */
function scopeText(output: TraceOutput | null, attempt: TraceProviderAttempt | null): ReactNode {
  if (attempt !== null) {
    return (
      <span className="inline-flex min-w-0 flex-wrap items-center gap-1.5">
        {providerNode(attempt.providerId, attempt.providerLabel)}
        {" response"}
      </span>
    )
  }
  if (output === null) return "No recorded output"
  if (output.kind === "fetch_document") return "Fetched document"
  return `${output.results.length} results in fused order`
}

function viewSwitcher(view: TraceView, onChange: (view: TraceView) => void) {
  return (
    <SegmentedControl
      options={["Results", "Trajectory"]}
      value={view === "results" ? "Results" : "Trajectory"}
      onChange={(label) => onChange(label === "Trajectory" ? "trajectory" : "results")}
      ariaLabel="Trace detail view"
    />
  )
}

interface SelectionPaneOptions {
  trace: TraceDetail
  output: TraceOutput | null
  attempt: TraceProviderAttempt | null
  mode: RankingMode
  providerLabel: string
  providerId: string | null
  selection: Selection
  onSelectResult: (index: number) => void
  onSelectSpan: (spanId: string) => void
}

function resultsView(options: SelectionPaneOptions) {
  const { output, attempt, mode, providerLabel, providerId, selection, onSelectResult } = options
  const results = searchOutput(output)
  const shared = {
    output,
    mode,
    providerId,
    results: results?.results ?? [],
    selectedIndex: selection.resultIndex,
    onSelect: onSelectResult,
  }
  if (results === null) {
    // A fetch document (or an absent output) is one payload, not a list with an
    // inspector: it reads better across the full width.
    return <TraceResults {...shared} />
  }
  return (
    <InspectorSplitPane
      primaryLabel={attempt === null ? "Results" : `${providerLabel} response`}
      detailLabel="Result inspector"
      primary={<TraceResults {...shared} />}
      detail={
        <TraceResultInspector
          result={results.results[selection.resultIndex ?? -1] ?? null}
          rank={selection.resultIndex === null ? null : selection.resultIndex + 1}
          mode={mode}
          providerId={providerId}
          providerLabel={providerLabel}
          results={results.results}
        />
      }
    />
  )
}

function trajectoryView(options: SelectionPaneOptions) {
  const { trace, selection, onSelectSpan } = options
  // Only the visible user-level stages can be selected, so a hidden transport
  // or function span never gets a detail panel.
  const stages = selectUserTraceStages(trace.stages)
  const stage = selectedStage(stages, selection.spanId)
  return (
    <InspectorSplitPane
      primaryLabel="Trace trajectory"
      detailLabel={stage === null ? "Span payload" : `${traceTrajectoryLabel(stage)} payload`}
      primary={
        <TraceTrajectory
          stages={stages}
          totalMs={trace.totalMs}
          selectedSpanId={selection.spanId}
          onSelect={onSelectSpan}
        />
      }
      detail={
        <TraceSpanInspector key={stage?.spanId ?? "none"} stage={stage} traceId={trace.traceId} />
      }
    />
  )
}

/**
 * The detail workspace: recorded results and the recorded trajectory in one
 * switchable shell, each with the payload of the current selection at its side.
 * Selection is ephemeral and belongs here — a new trace or provider scope
 * starts with nothing selected (PLAN §5).
 */
export function TraceInspectionWorkspace({
  trace,
  output,
  attempt,
  mode,
}: TraceInspectionWorkspaceProps) {
  const [identity, setIdentity] = useState(() => identityOf(trace, attempt))
  const [selection, setSelection] = useState<Selection>(NO_SELECTION)
  const current = identityOf(trace, attempt)
  if (identity !== current) {
    // Adjusting state during render for a changed subject: the previous
    // selection described another trace or provider, so it must not carry over.
    setIdentity(current)
    setSelection(NO_SELECTION)
  }

  const providerLabel = attempt?.providerLabel ?? trace.providerLabel
  const options: SelectionPaneOptions = {
    trace,
    output,
    attempt,
    mode,
    providerLabel,
    providerId: scopedProviderId(trace, attempt),
    selection,
    onSelectResult: (resultIndex) =>
      setSelection((prev) => ({
        ...prev,
        resultIndex: prev.resultIndex === resultIndex ? null : resultIndex,
      })),
    onSelectSpan: (spanId) =>
      setSelection((prev) => ({ ...prev, spanId: prev.spanId === spanId ? null : spanId })),
  }

  return (
    <div className="min-w-0 space-y-3">
      <div className="flex min-w-0 flex-wrap items-center justify-between gap-3">
        <p className="min-w-0 text-[12px] text-[var(--muted)]">{scopeText(output, attempt)}</p>
        {viewSwitcher(selection.view, (view) => setSelection((prev) => ({ ...prev, view })))}
      </div>
      {selection.view === "results" ? resultsView(options) : trajectoryView(options)}
    </div>
  )
}
