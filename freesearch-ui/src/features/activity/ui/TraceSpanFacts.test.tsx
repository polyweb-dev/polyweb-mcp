import { describe, expect, it } from "vitest"
import { render, screen } from "@testing-library/react"
import { TraceSpanFacts } from "./TraceSpanFacts"

describe("TraceSpanFacts", () => {
  it("shows readable facts without exposing raw attribute keys", () => {
    render(<TraceSpanFacts events={[{
      name: "freesearch.provider.response",
      timestamp: "2026-11-07T12:00:00Z",
      attributes: { result_count: 1, content_length: 31585 },
    }]} />)
    expect(screen.getByLabelText("Recorded facts")).toHaveTextContent("Results1Content length31.6 KB")
    expect(screen.queryByText("result_count")).not.toBeInTheDocument()
    expect(screen.queryByText("content_length")).not.toBeInTheDocument()
  })

  it("omits the facts panel when no known facts were recorded", () => {
    render(<TraceSpanFacts events={[]} />)
    expect(screen.queryByLabelText("Recorded facts")).not.toBeInTheDocument()
  })
})
