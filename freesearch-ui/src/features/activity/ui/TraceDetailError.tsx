import type { TraceDetail } from "@/domains/activity"

/** Plain-language failure callout for a trace that did not complete. */
export function TraceDetailError({ trace }: { trace: TraceDetail }) {
  if (trace.error === null) return null
  return (
    <p
      role="alert"
      className="rounded border p-3 text-[13px]"
      style={{
        borderColor: "var(--status-danger)",
        color: "var(--status-danger)",
        background: "var(--elevated)",
      }}
    >
      {trace.error.type}: {trace.error.message}
    </p>
  )
}
