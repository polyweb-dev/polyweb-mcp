import { describe, expect, it } from "vitest"
import { render, screen } from "@testing-library/react"
import { ResultScore } from "./ResultScore"

/**
 * ResultScore (PLAN §4 R1): one recorded score, always as a gold percentage
 * match rate — Playground keeps its percentage match rate, a trace fusion or
 * provider score is shown on the same scale. A null value is stated as
 * unavailable; no zero is invented.
 */
describe("ResultScore", () => {
  it("renders a decimal score as a percentage match", () => {
    render(<ResultScore score={{ label: "Fusion score", value: 0.7, format: "decimal" }} />)

    expect(screen.getByText("70% match")).toBeInTheDocument()
  })

  it("rounds a decimal score to a whole-number percentage", () => {
    render(
      <ResultScore score={{ label: "Provider score", value: 0.686, format: "decimal" }} />
    )

    expect(screen.getByText("69% match")).toBeInTheDocument()
  })

  it("renders a percent score with Playground percentage semantics", () => {
    const value = 0.856
    render(<ResultScore score={{ label: "Score", value, format: "percent" }} />)

    expect(screen.getByText(`${Math.round(value * 100)}% match`)).toBeInTheDocument()
  })

  it("preserves the exact Playground percentage for a whole-number rate", () => {
    render(<ResultScore score={{ label: "Score", value: 0.85, format: "percent" }} />)

    expect(screen.getByText("85% match")).toBeInTheDocument()
  })

  it("renders nothing for a null score", () => {
    const { container } = render(
      <ResultScore score={{ label: "Fusion score", value: null, format: "decimal" }} />
    )

    expect(container).toBeEmptyDOMElement()
    expect(screen.queryByText("Unavailable")).not.toBeInTheDocument()
  })

  it("renders nothing for a zero score", () => {
    const { container } = render(
      <ResultScore score={{ label: "Score", value: 0, format: "percent" }} />
    )

    expect(container).toBeEmptyDOMElement()
    expect(screen.queryByText("0% match")).not.toBeInTheDocument()
    expect(screen.queryByText("Unavailable")).not.toBeInTheDocument()
  })

  it("never shows a decimal score in decimal form", () => {
    render(<ResultScore score={{ label: "Fusion score", value: 0.7, format: "decimal" }} />)

    expect(screen.queryByText("0.70")).not.toBeInTheDocument()
    expect(screen.getByText("70% match")).toBeInTheDocument()
  })

  it("paints every score in the common gold match color", () => {
    render(<ResultScore score={{ label: "Score", value: 0.7, format: "percent" }} />)

    expect(screen.queryByText("0.70")).not.toBeInTheDocument()
    expect(screen.getByText("70% match").getAttribute("style")).toContain("var(--accent-gold)")
  })
})
