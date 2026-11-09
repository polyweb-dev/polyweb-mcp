import type { ReactNode } from "react"
import type { TraceDetail } from "@/domains/activity"
import { formatDateTime, formatLatency } from "@/shared/lib/formatTime"
import { JsonViewer } from "@/shared/ui/JsonViewer"
import { AdvancedSection } from "@/shared/ui/AdvancedSection"

function field(label: string, value: ReactNode) {
  return (
    <div className="min-w-0">
      <dt className="text-[10px] text-[var(--muted)]">{label}</dt>
      <dd className="mono mt-0.5 min-w-0 text-[10px] leading-relaxed text-[var(--text-strong)] [overflow-wrap:anywhere]">
        {value}
      </dd>
    </div>
  )
}

/** Trace-wide fields and output live beside the selected span, but stay folded. */
export function TraceScopeDetails({ trace }: { trace: TraceDetail }) {
  return (
    <div className="min-w-0 space-y-3">
      <AdvancedSection label="Trace metadata">
        <dl className="mt-2 grid min-w-0 grid-cols-2 gap-x-3 gap-y-2">
          {field("Trace ID", trace.traceId)}
          {field("Operation", trace.operation ?? "Not recorded")}
          {field("Summary provider ID", trace.provider ?? "Not recorded")}
          {field("Started at", <span title={trace.startedAt}>{formatDateTime(trace.startedAt)}</span>)}
          {field("Timeline duration", formatLatency(trace.totalMs))}
        </dl>
      </AdvancedSection>
      {trace.output !== null && (
        <AdvancedSection label="Recorded output">
          <div className="mt-2 min-w-0">
            <JsonViewer
              value={trace.output}
              ariaLabel="Recorded output JSON"
              className="max-h-none overflow-visible"
            />
          </div>
        </AdvancedSection>
      )}
    </div>
  )
}
