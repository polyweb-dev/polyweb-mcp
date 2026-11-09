import type { TraceStage } from "@/domains/activity"

/** Use the backend's stage label, with a readable fallback for generic labels. */
export function traceSpanLabel(stage: TraceStage): string {
  const recordedLabel = stage.label.trim()
  if (recordedLabel === "Route selection") return "Provider selection"
  if (recordedLabel !== "" && recordedLabel !== "Stage") return recordedLabel

  const leafName = stage.name.split(".").at(-1) ?? ""
  const words = leafName.replace(/([a-z])([A-Z])/g, "$1 $2").replace(/[_-]+/g, " ").trim()
  return words === "" ? "Recorded step" : words[0]!.toUpperCase() + words.slice(1)
}

const EVENT_LABELS: Readonly<Record<string, string>> = {
  "polyweb.provider.request": "Provider request",
  "polyweb.provider.response": "Provider response",
  "polyweb.request": "Request",
  "polyweb.response": "Response",
}

/**
 * Plain label of one recorded event, e.g. `polyweb.provider.request` →
 * "Provider request". Unknown names read as their last two segments.
 */
export function traceEventLabel(name: string): string {
  const known = EVENT_LABELS[name]
  if (known !== undefined) return known
  const segments = name.split(".").filter((segment) => segment !== "" && segment !== "polyweb")
  const words = segments.slice(-2).join(" ").replace(/[_-]+/g, " ").trim()
  return words === "" ? "Event" : words[0]!.toUpperCase() + words.slice(1)
}

/**
 * When an event happened, as an offset from the trace start ("+204 ms"); the
 * raw timestamp when either time cannot be read.
 */
export function traceEventOffsetText(timestamp: string, traceStartedAt: string): string {
  const at = new Date(timestamp).getTime()
  const start = new Date(traceStartedAt).getTime()
  if (Number.isNaN(at) || Number.isNaN(start)) return timestamp
  const offset = Math.max(0, Math.round(at - start))
  return `+${offset.toLocaleString("en-US")} ms`
}

/** Plain-language context for a selected stage whose events contain no payload. */
export function traceSpanPurpose(stage: TraceStage): string | null {
  if (stage.events.length > 0) return null
  return "No events were recorded for this step. Timing and technical identifiers remain available"
}
