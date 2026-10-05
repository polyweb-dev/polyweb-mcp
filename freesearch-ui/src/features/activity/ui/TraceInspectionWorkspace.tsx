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

type TraceView = "results" | "trace"

interface Selection {
  view: TraceView
  resultIndex: number | null
  spanId: string | null
}

const AGGREGATED_PROVIDER = "aggregated"

/** Identity of the inspected subject: a new trace or scope starts fresh. */
function identityOf(trace: TraceDetail, attempt: TraceProviderAttempt | null): string {
  return `${trace.traceId}:${attempt?.spanId ?? "all"}`
}

function searchOutput(output: TraceOutput | null): TraceSearchOutput | null {
  return output !== null && output.kind === "search_results" ? output : null
}

function initialSelection(trace: TraceDetail, output: TraceOutput | null): Selection {
  const results = searchOutput(output)?.results ?? []
  const stages = selectUserTraceStages(trace.stages)
  const firstStage = stages.find((stage) => stage.events.length > 0) ?? stages[0]
  return {
    view: "results",
    resultIndex: results.length > 0 ? 0 : null,
    spanId: firstStage?.spanId ?? null,
  }
}

/** Provider the shown output belongs to, if it has one. */
function scopedProviderId(trace: TraceDetail, attempt: TraceProviderAttempt | null): string | null {
  if (attempt !== null) return attempt.providerId
  return trace.provider === AGGREGATED_PROVIDER ? null : trace.provider
}

function selectedStage(stages: readonly TraceStage[], spanId: string | null): TraceStage | null {
  if (spanId === null) return null
  return stages.find((stage) => stage.spanId === spanId) ?? null
}

function providerNode(providerId: string | null, fallbackLabel: string): ReactNode {
  if (providerId === null || providerId === "") return <span>{fallbackLabel}</span>
  const identity = providerIdentity(providerId)
  if (identity.id === "" || identity.id === AGGREGATED_PROVIDER) return <span>{fallbackLabel}</span>
  return <ProviderBadge providerId={identity.id} name={identity.name} logoClassName="size-3.5" />
}

function scopeText(
  view: TraceView,
  output: TraceOutput | null,
  attempt: TraceProviderAttempt | null
): ReactNode {
  if (view === "trace") return "Full trace · select a stage to inspect its timing and recorded data"
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
  const current = view === "trace" ? "Trace" : "Results"
  return (
    <SegmentedControl
      options={["Results", "Trace"]}
      value={current}
      onChange={(label) => onChange(label === "Trace" ? "trace" : "results")}
      ariaLabel="Trace detail views"
      minColumnWidth="auto"
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

function resultsView({ output, mode, providerLabel, providerId, selection, onSelectResult }: SelectionPaneOptions) {
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
    return (
      <section aria-label="Results" className="h-full min-h-0 min-w-0 overflow-y-auto overscroll-contain [scrollbar-gutter:stable]">
        <div className="min-w-0 py-3">
          <TraceResults {...shared} />
        </div>
      </section>
    )
  }
  return (
    <InspectorSplitPane
      primaryLabel="Ranked results"
      detailLabel="Result inspector"
      className="grid h-full min-h-0 min-w-0 grid-rows-[minmax(0,1fr)_minmax(0,1fr)] items-stretch gap-0 lg:grid-cols-[minmax(0,5fr)_minmax(0,7fr)] lg:grid-rows-1"
      primary={
        <div className="h-full min-h-0 min-w-0 overflow-y-auto overscroll-contain [scrollbar-gutter:stable]">
          <div className="min-w-0 pr-3 py-2">
            <TraceResults {...shared} />
          </div>
        </div>
      }
      detail={
        <div className="h-full min-h-0 min-w-0 overflow-y-auto overscroll-contain border-t border-[var(--border-subtle)] lg:border-l lg:border-t-0 [scrollbar-gutter:stable]">
          <div className="min-w-0 px-3 py-3 lg:pl-5">
            <TraceResultInspector
              result={results.results[selection.resultIndex ?? -1] ?? null}
              rank={selection.resultIndex === null ? null : selection.resultIndex + 1}
              mode={mode}
              providerId={providerId}
              providerLabel={providerLabel}
              results={results.results}
            />
          </div>
        </div>
      }
    />
  )
}

function traceView({ trace, selection, onSelectSpan }: SelectionPaneOptions) {
  const stage = selectedStage(trace.stages, selection.spanId)
  return (
    <InspectorSplitPane
      primaryLabel="Trace timeline"
      detailLabel={stage === null ? "Span details" : `${traceTrajectoryLabel(stage)} details`}
      className="grid h-full min-h-0 min-w-0 grid-rows-[minmax(0,1fr)_minmax(0,1fr)] items-stretch gap-0 lg:grid-cols-[minmax(0,5fr)_minmax(0,7fr)] lg:grid-rows-1 lg:gap-3"
      primary={
        <section className="h-full min-h-0 min-w-0 overflow-hidden border-b border-[var(--border-subtle)] pb-2 lg:border-b-0 lg:border-r lg:pb-0 lg:pr-3">
          <TraceTrajectory
            stages={trace.stages}
            totalMs={trace.totalMs}
            selectedSpanId={selection.spanId}
            onSelect={onSelectSpan}
          />
        </section>
      }
      detail={
        <section className="h-full min-h-0 min-w-0 overflow-y-auto overscroll-contain [scrollbar-gutter:stable]">
          <div className="min-w-0 px-3 py-3">
            <TraceSpanInspector
              key={stage?.spanId ?? "none"}
              stage={stage}
              trace={trace}
              traceId={trace.traceId}
            />
          </div>
        </section>
      }
    />
  )
}

/** Results beside one unified trace timeline and selected-span inspector. */
export function TraceInspectionWorkspace({ trace, output, attempt, mode }: TraceInspectionWorkspaceProps) {
  const [identity, setIdentity] = useState(() => identityOf(trace, attempt))
  const [selection, setSelection] = useState(() => initialSelection(trace, output))
  const current = identityOf(trace, attempt)
  if (identity !== current) {
    setIdentity(current)
    setSelection(initialSelection(trace, output))
  }

  const providerLabel = attempt?.providerLabel ?? trace.providerLabel
  const providerId = scopedProviderId(trace, attempt)
  const options: SelectionPaneOptions = {
    trace,
    output,
    attempt,
    mode,
    providerLabel,
    providerId,
    selection,
    onSelectResult: (resultIndex) => setSelection((previous) => ({ ...previous, resultIndex })),
    onSelectSpan: (spanId) => setSelection((previous) => ({ ...previous, spanId })),
  }

  return (
    <div className="flex h-full min-h-0 min-w-0 flex-1 flex-col gap-2">
      <div className="flex min-w-0 shrink-0 flex-wrap items-center justify-between gap-2 border-b border-[var(--border-subtle)] pb-2">
        <p className="min-w-0 text-[11px] text-[var(--muted)]">
          {scopeText(selection.view, output, attempt)}
        </p>
        {viewSwitcher(selection.view, (view) => setSelection((previous) => ({ ...previous, view })))}
      </div>
      <div className="min-h-0 min-w-0 flex-1">
        {selection.view === "results" && resultsView(options)}
        {selection.view === "trace" && traceView(options)}
      </div>
    </div>
  )
}
