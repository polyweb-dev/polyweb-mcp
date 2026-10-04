import { describe, expect, it } from "vitest"
import { render, screen } from "@testing-library/react"
import { LatencyWaterfallValue } from "./LatencyWaterfallValue"

/**
 * LatencyWaterfallValue (PLAN §4 R7): the shared row value for one timeline
 * lane — the recorded duration in milliseconds, the recorded result count
 * when the caller has one, and any outcome that is not a success.
 */
describe("LatencyWaterfallValue", () => {
  it("renders the recorded duration in milliseconds", () => {
    render(<LatencyWaterfallValue durationMs={250} resultCount={null} />)

    expect(screen.getByText("250ms")).toBeInTheDocument()
  })

  it("renders the result count when the caller records one", () => {
    render(<LatencyWaterfallValue durationMs={250} resultCount={5} />)

    expect(screen.getByText("250ms")).toBeInTheDocument()
    expect(screen.getByText("5 res")).toBeInTheDocument()
  })

  it("omits the result count when the caller records none", () => {
    const { container } = render(
      <LatencyWaterfallValue durationMs={250} resultCount={null} />
    )

    expect(screen.getByText("250ms")).toBeInTheDocument()
    expect(container).toHaveTextContent("250ms")
    expect(container.querySelectorAll("span")).toHaveLength(2)
  })

  it("renders a non-success outcome beside the duration", () => {
    render(<LatencyWaterfallValue durationMs={830} resultCount={null} outcome="failed" />)

    expect(screen.getByText("830ms")).toBeInTheDocument()
    expect(screen.getByText("failed")).toBeInTheDocument()
  })

  it("omits the outcome when the caller records none", () => {
    const { container } = render(
      <LatencyWaterfallValue durationMs={130} resultCount={2} />
    )

    expect(screen.getByText("130ms")).toBeInTheDocument()
    expect(screen.getByText("2 res")).toBeInTheDocument()
    expect(container).not.toHaveTextContent("success")
    expect(container).not.toHaveTextContent("failed")
  })
})
