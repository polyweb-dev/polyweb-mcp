import { describe, expect, it } from "vitest"
import { render, screen } from "@testing-library/react"
import { ResultScore } from "./ResultScore"

/**
 * ResultScore (PLAN §4 R1): one recorded score in its own unit — Playground
 * keeps its percentage match rate, a trace keeps its decimal score. A null
 * value is stated as unavailable; no zero is invented and no mode converts.
 */
describe("ResultScore", () => {
  it("renders a decimal score with exactly two decimals", () => {
    render(<ResultScore score={{ label: "Fusion score", value: 0.7, format: "decimal" }} />)

    expect(screen.getByText("0.70")).toBeInTheDocument()
  })

  it("rounds a decimal score to two decimals", () => {
    render(
      <ResultScore score={{ label: "Provider score", value: 0.686, format: "decimal" }} />
    )

    expect(screen.getByText("0.69")).toBeInTheDocument()
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

  it("shows Unavailable for a null decimal score", () => {
    render(
      <ResultScore score={{ label: "Fusion score", value: null, format: "decimal" }} />
    )

    expect(screen.getByText("Unavailable")).toBeInTheDocument()
  })

  it("shows Unavailable for a null percent score", () => {
    render(<ResultScore score={{ label: "Score", value: null, format: "percent" }} />)

    expect(screen.getByText("Unavailable")).toBeInTheDocument()
  })

  it("does not convert a decimal score into a percentage", () => {
    render(<ResultScore score={{ label: "Fusion score", value: 0.7, format: "decimal" }} />)

    expect(screen.queryByText("70% match")).not.toBeInTheDocument()
  })

  it("does not convert a percent score into a decimal", () => {
    render(<ResultScore score={{ label: "Score", value: 0.7, format: "percent" }} />)

    expect(screen.queryByText("0.70")).not.toBeInTheDocument()
    expect(screen.getByText("70% match")).toBeInTheDocument()
  })
})
