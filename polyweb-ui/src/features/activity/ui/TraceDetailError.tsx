import type { TraceDetail } from "@/domains/activity"

/** Plain words for an error that recorded only its type, e.g. `http_error`. */
function humanize(type: string): string {
  const words = type.replace(/[_.-]+/g, " ").trim()
  return words === "" ? "The request failed" : words.charAt(0).toUpperCase() + words.slice(1)
}

/** Plain-language failure callout for a trace that did not complete. */
export function TraceDetailError({ trace }: { trace: TraceDetail }) {
  if (trace.error === null) return null
  const message = trace.error.message.trim()
  return (
    <p
      role="alert"
      className="rounded-md border p-3 text-[13px]"
      style={{
        borderColor: "color-mix(in srgb, var(--status-danger) 45%, transparent)",
        color: "var(--status-danger)",
        background: "var(--elevated)",
      }}
    >
      {message === "" ? humanize(trace.error.type) : message}
    </p>
  )
}
