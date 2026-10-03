import type { ReactNode } from "react"
import type { TraceStage } from "@/domains/activity"
import { JsonViewer } from "@/shared/ui/JsonViewer"
import { TraceStatusPill } from "./TraceStatusPill"

export interface TraceSpanInspectorProps {
  stage: TraceStage | null
  traceId: string
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

/** One recorded event: its name, timestamp, and its attributes as JSON. */
function eventBlock(name: string, timestamp: string, attributes: unknown, eventKey: string): ReactNode {
  return (
    <div key={`${eventKey}:${timestamp}`} className="min-w-0 space-y-1">
      <p className="mono text-[11px] text-[var(--accent-cyan)] [overflow-wrap:anywhere]">{name}</p>
      <p className="text-[11px] text-[var(--muted)] tnum">{new Date(timestamp).toISOString()}</p>
      <JsonViewer value={attributes} ariaLabel={`${name} attributes`} />
    </div>
  )
}

/**
 * Side inspector for one selected trajectory row: the recorded timing and
 * identity of that span, then the payload it recorded. Selecting another row
 * replaces this panel instead of appending another disclosure block.
 */
export function TraceSpanInspector({ stage, traceId }: TraceSpanInspectorProps) {
  if (stage === null) {
    return (
      <p className="text-[12px] text-[var(--muted)]">
        Select a trajectory row to inspect its timing and payload.
      </p>
    )
  }
  return (
    <div className="min-w-0 space-y-3 text-[12px]">
      <div className="min-w-0 space-y-1">
        <h4 className="text-[13px] font-medium text-[var(--text-strong)] [overflow-wrap:anywhere]">
          {stage.name}
        </h4>
        <p className="flex flex-wrap items-center gap-2 text-[12px] text-[var(--muted)]">
          <span>{stage.label}</span>
          <TraceStatusPill outcome={stage.outcome} />
        </p>
      </div>

      <dl className="grid min-w-0 grid-cols-2 gap-x-3 gap-y-2 border-y border-[var(--border-subtle)] py-3">
        {metaRow("Offset", `${stage.offsetMs}ms`)}
        {metaRow("Duration", `${stage.durationMs}ms`)}
        {metaRow("Kind", stage.kind)}
        {metaRow("Trace", traceId)}
        {metaRow("Span", stage.spanId)}
        {metaRow("Parent", stage.parentSpanId ?? "—")}
      </dl>

      {stage.error !== null && (
        <p className="text-[12px]" style={{ color: "var(--status-danger)" }}>
          {stage.error.type}: {stage.error.message}
        </p>
      )}

      {stage.events.length === 0 ? (
        <p className="text-[12px] text-[var(--muted)]">This span recorded no event.</p>
      ) : (
        <div className="min-w-0 space-y-3">
          {stage.events.map((event) =>
            eventBlock(event.name, event.timestamp, event.attributes, stage.spanId)
          )}
        </div>
      )}
    </div>
  )
}
