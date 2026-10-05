import type { TraceStage } from "@/domains/activity"

/** Use the backend's stage label, with a readable fallback for generic labels. */
export function traceSpanLabel(stage: TraceStage): string {
  const recordedLabel = stage.label.trim()
  if (recordedLabel !== "" && recordedLabel !== "Stage") return recordedLabel

  const leafName = stage.name.split(".").at(-1) ?? ""
  const words = leafName.replace(/([a-z])([A-Z])/g, "$1 $2").replace(/[_-]+/g, " ").trim()
  return words === "" ? "Recorded step" : words[0]!.toUpperCase() + words.slice(1)
}

/** Plain-language context for a selected stage whose events contain no payload. */
export function traceSpanPurpose(stage: TraceStage): string | null {
  if (stage.events.length > 0) return null
  return "No events were recorded for this step; timing and technical identifiers remain available."
}
