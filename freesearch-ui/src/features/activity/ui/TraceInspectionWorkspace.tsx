import { useState, type ReactNode } from "react"
import {
  selectUserTraceStages,
  tracePayloadNotice,
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

type TraceView = "results" | "timeline"

interface Selection {
  view: TraceView
  resultIndex: number | null
  spanId: string | null
}

const AGGREGATED_PROVIDER = "aggregated"
const RESULTS_LABEL = "Results"
const TIMELINE_LABEL = "Timeline"
const NO_RESULTS_MESSAGE = "No results were recorded for this trace"

/** Each pane scrolls on its own, so the dialog only grows as tall as it needs. */
const PANE_HEIGHT = "max-h-[min(60svh,640px)]"
const SPLIT =
  "grid min-w-0 grid-cols-1 items-stretch gap-0 lg:grid-cols-[minmax(0,5fr)_minmax(0,7fr)]"

/** Identity of the inspected subject: a new trace or scope starts fresh. */
function identityOf(trace: TraceDetail, attempt: TraceProviderAttempt | null): string {
  return `${trace.traceId}:${attempt?.spanId ?? "all"}`
}

function searchOutput(output: TraceOutput | null): TraceSearchOutput | null {
  return output !== null && output.kind === "search_results" ? output : null
}

/** Stored output opens on Results; absent output opens on the compact summary. */
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

/** The one sentence about absent results: not stored by policy, or never returned. */
function emptyOutputMessage(trace: TraceDetail): string {
  if (trace.input === null && trace.output === null) {
    return "Results were not stored (metadata-only trace policy)"
  }
  return (
    tracePayloadNotice({ input: "", output: trace.output, outcome: trace.outcome }) ??
    NO_RESULTS_MESSAGE
  ).replace(/\.$/, "")
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

function resultCountText(count: number, mode: RankingMode): string {
  const noun = count === 1 ? "result" : "results"
  return `${count} ${noun} in ${mode === "fusion" ? "fused" : "provider"} order`
}

interface ScopeTextOptions {
  view: TraceView
  trace: TraceDetail
  output: TraceOutput | null
  attempt: TraceProviderAttempt | null
  mode: RankingMode
}

/** The line beside the view switch: what the pane below shows. */
function scopeText({ view, output, attempt, mode }: ScopeTextOptions): ReactNode {
  if (view === "timeline") {
    return "Select a stage to see its timing and recorded data"
  }
  if (attempt !== null) {
    return (
      <span className="inline-flex min-w-0 flex-wrap items-center gap-1.5">
        {providerNode(attempt.providerId, attempt.providerLabel)}
        {" response"}
      </span>
    )
  }
  if (output === null) return null
  if (output.kind === "fetch_document") return "Fetched document"
  return resultCountText(output.results.length, mode)
}

function viewSwitcher(view: TraceView, onChange: (view: TraceView) => void, hasOutput: boolean) {
  const resultsLabel = hasOutput ? RESULTS_LABEL : "Summary"
  return (
    <SegmentedControl
      options={[resultsLabel, TIMELINE_LABEL]}
      value={view === "timeline" ? TIMELINE_LABEL : resultsLabel}
      onChange={(label) => onChange(label === TIMELINE_LABEL ? "timeline" : "results")}
      ariaLabel="Trace detail views"
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

function resultsView({ trace, output, mode, providerLabel, providerId, selection, onSelectResult }: SelectionPaneOptions) {
  const results = searchOutput(output)
  const shared = {
    output,
    input: trace.input,
    mode,
    providerId,
    results: results?.results ?? [],
    selectedIndex: selection.resultIndex,
    emptyMessage: emptyOutputMessage(trace),
    onSelect: onSelectResult,
  }
  if (results === null) {
    return (
      <section aria-label={output === null ? "Summary" : "Results"} className="min-w-0">
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
      className={SPLIT}
      primary={
        <div className={`${PANE_HEIGHT} min-h-0 min-w-0 overflow-y-auto overscroll-contain [scrollbar-gutter:stable]`}>
          <div className="min-w-0 pr-3 py-2">
            <TraceResults {...shared} />
          </div>
        </div>
      }
      detail={
        <div className={`${PANE_HEIGHT} min-h-0 min-w-0 overflow-y-auto overscroll-contain border-t border-[var(--border-subtle)] lg:border-l lg:border-t-0 [scrollbar-gutter:stable]`}>
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

function timelineView({ trace, selection, onSelectSpan }: SelectionPaneOptions) {
  const stage = selectedStage(trace.stages, selection.spanId)
  return (
    <InspectorSplitPane
      primaryLabel="Trace timeline"
      detailLabel={stage === null ? "Span details" : `${traceTrajectoryLabel(stage)} details`}
      className={`${SPLIT} lg:gap-3`}
      primary={
        <section className={`flex ${PANE_HEIGHT} min-h-0 min-w-0 flex-col overflow-hidden border-b border-[var(--border-subtle)] pb-2 lg:border-b-0 lg:border-r lg:pb-0 lg:pr-3`}>
          <TraceTrajectory
            stages={trace.stages}
            totalMs={trace.totalMs}
            selectedSpanId={selection.spanId}
            onSelect={onSelectSpan}
          />
        </section>
      }
      detail={
        <section className={`${PANE_HEIGHT} min-h-0 min-w-0 overflow-y-auto overscroll-contain [scrollbar-gutter:stable]`}>
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

/**
 * Results beside the selected result, or the stage timeline beside the
 * selected stage. One switch flips between them; a trace without recorded
 * output starts on its compact summary.
 */
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
        {viewSwitcher(selection.view, (view) => setSelection((previous) => ({ ...previous, view })), output !== null)}
        <p className="min-w-0 text-[12px] text-[var(--muted)]">
          {scopeText({ view: selection.view, trace, output, attempt, mode })}
        </p>
      </div>
      <div className="min-h-0 min-w-0">
        {selection.view === "results" && resultsView(options)}
        {selection.view === "timeline" && timelineView(options)}
      </div>
    </div>
  )
}
