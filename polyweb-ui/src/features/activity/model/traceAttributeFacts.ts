import type { TraceEvent } from "@/domains/activity"

interface TraceAttributeFact {
  label: string
  value: string
}

function count(value: unknown): string | null {
  return typeof value === "number" && Number.isFinite(value) && value >= 0
    ? value.toLocaleString("en-US") : null
}

function contentSize(value: unknown): string | null {
  if (typeof value !== "number" || !Number.isFinite(value) || value < 0) return null
  if (value < 1000) return `${value.toLocaleString("en-US")} bytes`
  const [amount, unit] = value < 1_000_000 ? [value / 1000, "KB"] : [value / 1_000_000, "MB"]
  return `${amount.toLocaleString("en-US", { maximumFractionDigits: 1 })} ${unit}`
}

function booleanText(value: unknown): string | null {
  return typeof value === "boolean" ? (value ? "Yes" : "No") : null
}

const FACTS = [
  { key: "result_count", label: "Results", format: count },
  { key: "content_length", label: "Content length", format: contentSize },
  { key: "pdf_pages", label: "PDF pages", format: count },
  { key: "enhanced", label: "Enhanced", format: booleanText },
] as const

export function traceAttributeFacts(events: readonly TraceEvent[]): TraceAttributeFact[] {
  const pdfPages = events.findLast((event) => count(event.attributes.pdf_pages) !== null)?.attributes.pdf_pages
  return FACTS.flatMap(({ key, label, format }) => {
    const event = events.findLast((candidate) => format(candidate.attributes[key]) !== null)
    if (key === "pdf_pages" && event?.attributes[key] === 0) return []
    if (key === "enhanced" && event?.attributes[key] === false && !(typeof pdfPages === "number" && pdfPages > 0)) return []
    const value = event === undefined ? null : format(event.attributes[key])
    return value === null ? [] : [{ label, value }]
  })
}
