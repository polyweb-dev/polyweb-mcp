import type { TraceEvent } from "@/domains/activity"
import { traceAttributeFacts } from "../model/traceAttributeFacts"

export function TraceSpanFacts({ events }: { events: readonly TraceEvent[] }) {
  const facts = traceAttributeFacts(events)
  if (facts.length === 0) return null
  return (
    <dl aria-label="Recorded facts" className="flex flex-wrap gap-x-8 gap-y-2">
      {facts.map((fact) => (
        <div key={fact.label}>
          <dt className="text-[11px] text-[var(--muted)]">{fact.label}</dt>
          <dd className="tnum m-0 text-[12px] text-[var(--text-strong)]">{fact.value}</dd>
        </div>
      ))}
    </dl>
  )
}
