import { describe, expect, it } from "vitest"
import type { TraceEvent } from "@/domains/activity"
import { traceAttributeFacts } from "./traceAttributeFacts"

function event(attributes: Record<string, unknown>): TraceEvent {
  return { name: "freesearch.provider.response", timestamp: "2026-11-07T12:00:00Z", attributes }
}

describe("traceAttributeFacts", () => {
  it("formats recorded counts and content size with plain labels", () => {
    expect(traceAttributeFacts([event({ result_count: 1, content_length: 31585, pdf_pages: 2, enhanced: false })]))
      .toEqual([
        { label: "Results", value: "1" },
        { label: "Content length", value: "31.6 KB" },
        { label: "PDF pages", value: "2" },
        { label: "Enhanced", value: "No" },
      ])
  })

  it("omits unknown and invalid attributes without losing genuine zero values", () => {
    expect(traceAttributeFacts([event({ result_count: 0, content_length: -1, pdf_pages: "unknown", enhanced: null, secret: "raw" })]))
      .toEqual([{ label: "Results", value: "0" }])
    expect(traceAttributeFacts([])).toEqual([])
  })

  it("uses the latest valid recorded value of a fact", () => {
    expect(traceAttributeFacts([event({ result_count: 1 }), event({ result_count: 3 }), event({ result_count: null })]))
      .toEqual([{ label: "Results", value: "3" }])
  })

  it("hides PDF-only defaults for an HTML response", () => {
    expect(traceAttributeFacts([event({ result_count: 1, pdf_pages: 0, enhanced: false })]))
      .toEqual([{ label: "Results", value: "1" }])
  })
})
