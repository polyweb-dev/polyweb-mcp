import type { TraceDetail } from "@/domains/activity"

/**
 * Collapsed technical projection: span names, durations, outcomes, and the
 * recorded events as JSON. Exists for debugging, never the primary reading.
 */
export function TraceTechnicalDetails({ trace }: { trace: TraceDetail }) {
  return (
    <div className="space-y-3">
      <p className="mono break-all text-[12px] text-[var(--muted)]">
        trace {trace.traceId} · {trace.operation ?? "unknown"} · {trace.provider ?? "—"}
      </p>
      <ul className="space-y-2">
        {trace.stages.map((stage) => (
          <li key={stage.spanId} className="rounded bg-[var(--surface)] p-2">
            <p className="mono break-all text-[12px] text-[var(--text)]">
              {stage.name} · {stage.durationMs}ms · {stage.outcome}
            </p>
            {stage.events.map((event) => (
              <div key={`${stage.spanId}-${event.name}-${event.timestamp}`} className="mt-2">
                <p className="text-[12px] text-[var(--muted)]">{event.name}</p>
                <pre className="max-h-40 overflow-auto whitespace-pre-wrap rounded bg-[var(--elevated)] p-2 text-[12px] text-[var(--text)]">
                  {event.attributes}
                </pre>
              </div>
            ))}
          </li>
        ))}
      </ul>
    </div>
  )
}
