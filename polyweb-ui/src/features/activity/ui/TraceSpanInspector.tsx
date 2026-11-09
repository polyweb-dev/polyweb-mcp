import type { ReactNode } from "react"
import {
  type TraceDetail,
  type TraceEvent,
  type TraceStage,
} from "@/domains/activity"
import { providerIdentity } from "@/domains/providers"
import { formatDateTime, formatLatency } from "@/shared/lib/formatTime"
import { JsonViewer } from "@/shared/ui/JsonViewer"
import { AdvancedSection } from "@/shared/ui/AdvancedSection"
import { ProviderBadge } from "@/shared/ui/ProviderBadge"
import {
  traceEventLabel,
  traceEventOffsetText,
  traceSpanLabel,
  traceSpanPurpose,
} from "../model/traceSpanPresentation"
import { TraceScopeDetails } from "./TraceScopeDetails"
import { TraceSpanFacts } from "./TraceSpanFacts"

export interface TraceSpanInspectorProps {
  stage: TraceStage | null
  trace: TraceDetail
  traceId: string
}

const PROVIDER_SPAN_NAME = "polyweb.provider"
const AGGREGATED_PROVIDER = "aggregated"
const REQUEST_EVENT_SUFFIX = ".request"
const RESPONSE_EVENT_SUFFIX = ".response"

function section(title: string, content: ReactNode): ReactNode {
  return (
    <section className="min-w-0 space-y-2 border-t border-[var(--border-subtle)] pt-3">
      <h5 className="text-[12px] text-[var(--muted)]">{title}</h5>
      {content}
    </section>
  )
}

function metaRow(label: string, value: ReactNode): ReactNode {
  return (
    <div className="min-w-0">
      <dt className="text-[11px] text-[var(--muted)]">{label}</dt>
      <dd className="mono min-w-0 text-[11px] text-[var(--text-strong)] [overflow-wrap:anywhere]">
        {value}
      </dd>
    </div>
  )
}

/** The panel title: the row label, with the provider identity as a badge. */
function titleNode(stage: TraceStage): ReactNode {
  const providerId = stage.name === PROVIDER_SPAN_NAME ? stage.providerId : null
  const identity = providerId === null || providerId === "" ? null : providerIdentity(providerId)
  if (identity !== null && identity.id !== "" && identity.id !== AGGREGATED_PROVIDER) {
    return (
      <span className="flex min-w-0 flex-wrap items-center gap-1">
        <ProviderBadge providerId={identity.id} name={identity.name} logoClassName="size-4" />
        <span className="sr-only"> </span>
        <span>request</span>
      </span>
    )
  }
  return <span className="[overflow-wrap:anywhere]">{traceSpanLabel(stage)}</span>
}

/**
 * A span failure, shown only when the span recorded one. The outcome itself
 * lives in the dialog summary above, so a successful span adds no block here.
 */
function spanError(stage: TraceStage): ReactNode {
  if (stage.error === null) return null
  return (
    <p className="min-w-0 text-[12px]" style={{ color: "var(--status-danger)" }}>
      {stage.error.message.trim() === "" ? stage.error.type : stage.error.message}
    </p>
  )
}

/** One timing figure in the product font with tabular numbers. */
function timingCell(label: string, value: string): ReactNode {
  return (
    <div className="min-w-0">
      <dt className="text-[11px] text-[var(--muted)]">{label}</dt>
      <dd className="tnum text-[12px] text-[var(--text-strong)]">{value}</dd>
    </div>
  )
}

/** Duration, and when the step started and ended relative to the trace start. */
function timingSection(stage: TraceStage): ReactNode {
  return section(
    "Timing",
    <dl className="flex min-w-0 flex-wrap items-start gap-x-8 gap-y-2">
      {timingCell("Duration", formatLatency(stage.durationMs))}
      {timingCell("Starts at", `+${formatLatency(stage.offsetMs)}`)}
      {timingCell("Ends at", `+${formatLatency(stage.offsetMs + stage.durationMs)}`)}
    </dl>
  )
}

/**
 * One recorded event: its plain label and when it happened relative to the
 * trace start, then its attributes. The raw event name stays under Technical
 * identifiers.
 */
function eventBlock(event: TraceEvent, eventKey: string, traceStartedAt: string): ReactNode {
  const label = traceEventLabel(event.name)
  return (
    <div key={`${eventKey}:${event.name}:${event.timestamp}`} className="min-w-0 space-y-1">
      <p className="text-[11px] text-[var(--muted)]">
        <span className="text-[var(--text-strong)]">{label}</span>
        {" · "}
        <span className="tnum" title={formatDateTime(event.timestamp)}>
          {traceEventOffsetText(event.timestamp, traceStartedAt)}
        </span>
      </p>
      <JsonViewer
        value={event.attributes}
        ariaLabel={`${label} attributes`}
        className="max-h-none overflow-visible"
      />
    </div>
  )
}

interface PayloadSectionOptions {
  title: string
  events: readonly TraceEvent[]
  spanId: string
  traceStartedAt: string
}

function payloadSection({ title, events, spanId, traceStartedAt }: PayloadSectionOptions): ReactNode {
  if (events.length === 0) return null
  return section(
    title,
    <div className="min-w-0 space-y-3">
      {events.map((event) => eventBlock(event, spanId, traceStartedAt))}
    </div>
  )
}

function technicalSection(stage: TraceStage): ReactNode {
  return (
    <AdvancedSection label="Technical identifiers">
      <dl className="mt-2 grid min-w-0 grid-cols-2 gap-x-3 gap-y-2">
        {metaRow("Span name", stage.name)}
        {metaRow("Stage label", stage.label)}
        {metaRow("Kind", stage.kind)}
        {metaRow("Started at", <span title={stage.startedAt}>{formatDateTime(stage.startedAt)}</span>)}
        {metaRow("Outcome", stage.outcome)}
        {metaRow("Span", stage.spanId)}
        {metaRow("Parent", stage.parentSpanId ?? "—")}
        {metaRow("Provider ID", stage.providerId ?? "—")}
        {stage.events.length > 0 &&
          metaRow("Events", stage.events.map((event) => event.name).join(", "))}
      </dl>
    </AdvancedSection>
  )
}

/**
 * Side inspector for one selected trajectory row. The recorded status and
 * timing come first, then the request and response payloads, and the raw
 * identifiers stay inside one disclosure. Selecting another row replaces this
 * panel instead of appending another block.
 */
export function TraceSpanInspector({ stage, trace }: TraceSpanInspectorProps) {
  if (stage === null) {
    return (
      <div className="min-w-0 space-y-3">
        <p className="text-[12px] text-[var(--muted)]">
          No span timing was recorded for this trace
        </p>
        <TraceScopeDetails trace={trace} />
      </div>
    )
  }
  const requestEvents = stage.events.filter((event) => event.name.endsWith(REQUEST_EVENT_SUFFIX))
  const responseEvents = stage.events.filter((event) => event.name.endsWith(RESPONSE_EVENT_SUFFIX))
  const otherEvents = stage.events.filter(
    (event) =>
      !event.name.endsWith(REQUEST_EVENT_SUFFIX) && !event.name.endsWith(RESPONSE_EVENT_SUFFIX)
  )
  const purpose = traceSpanPurpose(stage)
  return (
    <div className="min-w-0 space-y-3 text-[12px]">
      <div className="flex min-w-0 flex-wrap items-center gap-2">
        <h4 className="min-w-0 text-[13px] font-medium text-[var(--text-strong)]">
          {titleNode(stage)}
        </h4>
      </div>

      {spanError(stage)}
      {purpose !== null && <p className="text-[12px] text-[var(--muted)]">{purpose}</p>}
      {timingSection(stage)}
      <TraceSpanFacts events={stage.events} />
      {stage.events.length > 0 && (
        <AdvancedSection label="Show raw data">
          <div className="mt-3 space-y-3">
            {payloadSection({ title: "Request", events: requestEvents, spanId: stage.spanId, traceStartedAt: trace.startedAt })}
            {payloadSection({ title: "Response", events: responseEvents, spanId: stage.spanId, traceStartedAt: trace.startedAt })}
            {payloadSection({ title: "Events", events: otherEvents, spanId: stage.spanId, traceStartedAt: trace.startedAt })}
          </div>
        </AdvancedSection>
      )}
      {technicalSection(stage)}
      <TraceScopeDetails trace={trace} />
    </div>
  )
}
