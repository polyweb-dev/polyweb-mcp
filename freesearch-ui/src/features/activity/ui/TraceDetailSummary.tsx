import type { TraceDetail } from "@/domains/activity"
import { TraceDetailCell } from "./TraceDetailCell"
import { TraceStatusPill } from "./TraceStatusPill"

/** Summary strip: the four facts a user needs before reading further. */
export function TraceDetailSummary({ trace }: { trace: TraceDetail }) {
  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
      <div className="rounded border border-[var(--border-subtle)] bg-[var(--elevated)] p-3">
        <span className="block text-[12px] text-[var(--muted)]">Status</span>
        <TraceStatusPill outcome={trace.outcome} />
      </div>
      <TraceDetailCell label="Provider" value={trace.providerLabel} />
      <TraceDetailCell label="Total latency" value={`${trace.durationMs}ms`} />
      <TraceDetailCell
        label="Results"
        value={trace.resultCount === null ? "—" : String(trace.resultCount)}
      />
    </div>
  )
}
