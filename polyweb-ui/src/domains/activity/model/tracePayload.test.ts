import { describe, expect, it } from "vitest"
import {
  TRACE_METADATA_ONLY_MESSAGE,
  TRACE_RESULTS_NOT_STORED_MESSAGE,
  tracePayloadNotice,
} from "./tracePayload"

const output = { kind: "search_results" as const, query: "q", results: [] }

describe("tracePayloadNotice", () => {
  it("explains a metadata-only trace when input and output are both absent", () => {
    expect(tracePayloadNotice({ input: null, output: null, outcome: "success" })).toBe(
      TRACE_METADATA_ONLY_MESSAGE
    )
    expect(tracePayloadNotice({ input: null, output: null, outcome: "error" })).toBe(
      TRACE_METADATA_ONLY_MESSAGE
    )
  })

  it("says the results were not stored for a success with input but no output", () => {
    expect(tracePayloadNotice({ input: "q", output: null, outcome: "success" })).toBe(
      TRACE_RESULTS_NOT_STORED_MESSAGE
    )
  })

  it("stays silent for a failed trace without output and for a full payload", () => {
    expect(tracePayloadNotice({ input: "q", output: null, outcome: "error" })).toBeNull()
    expect(tracePayloadNotice({ input: "q", output, outcome: "success" })).toBeNull()
  })

  it("uses the exact contract copy", () => {
    expect(TRACE_METADATA_ONLY_MESSAGE).toBe(
      "This trace stored metadata only. The project's trace policy did not capture the query or the results."
    )
    expect(TRACE_RESULTS_NOT_STORED_MESSAGE).toBe("The results of this trace were not stored.")
  })
})
