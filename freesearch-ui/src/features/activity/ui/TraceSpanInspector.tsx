import type { ReactNode } from "react"
import { traceTrajectoryLabel, type TraceEvent, type TraceStage } from "@/domains/activity"
import { providerIdentity } from "@/domains/providers"
import { JsonViewer } from "@/shared/ui/JsonViewer"
import { ProviderBadge } from "@/shared/ui/ProviderBadge"

export interface TraceSpanInspectorProps {
  stage: TraceStage | null
  traceId: string
}

const PROVIDER_SPAN_NAME = "freesearch.provider"
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
      <span className="flex min-w-0 flex-wrap items-center gap-2">
        <ProviderBadge providerId={identity.id} name={identity.name} logoClassName="size-4" />
        {" "}
        <span>request</span>
      </span>
    )
  }
  return <span className="[overflow-wrap:anywhere]">{traceTrajectoryLabel(stage)}</span>
}

/**
 * A span failure, shown only when the span recorded one. The outcome itself
 * lives in the dialog summary above, so a successful span adds no block here.
 */
function spanError(stage: TraceStage): ReactNode {
  if (stage.error === null) return null
  return (
    <p className="min-w-0 text-[12px]" style={{ color: "var(--status-danger)" }}>
      {stage.error.type}: {stage.error.message}
    </p>
  )
}

function timingSection(stage: TraceStage): ReactNode {
  return section(
    "Timing",
    <dl className="grid min-w-0 grid-cols-3 gap-x-3 gap-y-2">
      {metaRow("Duration", `${stage.durationMs}ms`)}
      {metaRow("Start offset", `${stage.offsetMs}ms`)}
      {metaRow("End offset", `${stage.offsetMs + stage.durationMs}ms`)}
    </dl>
  )
}

/** One recorded event: its original name and timestamp, then its attributes. */
function eventBlock(event: TraceEvent, eventKey: string): ReactNode {
  return (
    <div key={`${eventKey}:${event.name}:${event.timestamp}`} className="min-w-0 space-y-1">
      <p className="text-[11px] text-[var(--muted)]">
        <span style={{ color: "var(--accent-cyan)" }}>{event.name}</span>
        {" · "}
        <span className="tnum">{new Date(event.timestamp).toISOString()}</span>
      </p>
      <JsonViewer value={event.attributes} ariaLabel={`${event.name} attributes`} />
    </div>
  )
}

function payloadSection(
  title: string,
  events: readonly TraceEvent[],
  spanId: string,
  emptyText: string
): ReactNode {
  return section(
    title,
    events.length === 0 ? (
      <p className="text-[12px] text-[var(--muted)]">{emptyText}</p>
    ) : (
      <div className="min-w-0 space-y-3">
        {events.map((event) => eventBlock(event, spanId))}
      </div>
    )
  )
}

function technicalSection(stage: TraceStage, traceId: string): ReactNode {
  return (
    <details className="min-w-0 border-t border-[var(--border-subtle)] pt-3">
      <summary className="cursor-pointer text-[12px] text-[var(--muted)]">
        Technical identifiers
      </summary>
      <dl className="mt-2 grid min-w-0 grid-cols-2 gap-x-3 gap-y-2">
        {metaRow("Span name", stage.name)}
        {metaRow("Kind", stage.kind)}
        {metaRow("Trace", traceId)}
        {metaRow("Span", stage.spanId)}
        {metaRow("Parent", stage.parentSpanId ?? "—")}
      </dl>
    </details>
  )
}

/**
 * Side inspector for one selected trajectory row. The recorded status and
 * timing come first, then the request and response payloads, and the raw
 * identifiers stay inside one disclosure. Selecting another row replaces this
 * panel instead of appending another block.
 */
export function TraceSpanInspector({ stage, traceId }: TraceSpanInspectorProps) {
  if (stage === null) {
    return (
      <p className="text-[12px] text-[var(--muted)]">
        Select a trajectory row to inspect its timing and payload.
      </p>
    )
  }
  const requestEvents = stage.events.filter((event) => event.name.endsWith(REQUEST_EVENT_SUFFIX))
  const responseEvents = stage.events.filter((event) => event.name.endsWith(RESPONSE_EVENT_SUFFIX))
  const otherEvents = stage.events.filter(
    (event) =>
      !event.name.endsWith(REQUEST_EVENT_SUFFIX) && !event.name.endsWith(RESPONSE_EVENT_SUFFIX)
  )
  return (
    <div className="min-w-0 space-y-3 text-[12px]">
      <div className="flex min-w-0 flex-wrap items-center gap-2">
        <h4 className="min-w-0 text-[13px] font-medium text-[var(--text-strong)]">
          {titleNode(stage)}
        </h4>
      </div>

      {spanError(stage)}
      {timingSection(stage)}
      {payloadSection("Request", requestEvents, stage.spanId, "This span recorded no request payload.")}
      {payloadSection(
        "Response",
        responseEvents,
        stage.spanId,
        "This span recorded no response payload."
      )}
      {otherEvents.length > 0 && payloadSection("Events", otherEvents, stage.spanId, "")}
      {technicalSection(stage, traceId)}
    </div>
  )
}
