import { describe, expect, it } from "vitest"
import { render, screen } from "@testing-library/react"
import { mapTraceDetail } from "@/domains/activity"
import { traceDetailFixture } from "@/test/fixtures/activity"
import { TraceDetailSummary } from "./TraceDetailSummary"

/**
 * TASK-000063 summary-rail attribution: the detail rail carries its own
 * Initiated by cell, so the dialog attribution is covered even when the
 * dialog test targets another scenario.
 */
describe("TraceDetailSummary actor identity", () => {
  it("renders the attribution rail cell with the human label beside the provider", () => {
    const trace = mapTraceDetail(
      traceDetailFixture({
        actor_type: "human",
        first_name: "Ada",
        last_name: "Lovelace",
        username: "ada",
        email: "ada@example.com",
      })
    )
    render(<TraceDetailSummary trace={trace} attempt={null} />)

    const rail = screen.getByText("Initiated by").closest("dl")!
    expect(
      Array.from(rail.querySelectorAll(":scope > div dt")).map((term) => term.textContent)
    ).toEqual(["Status", "Provider", "Initiated by", "Total latency", "Results"])
    const primary = screen.getByText("Ada Lovelace")
    expect(primary).toHaveAttribute("title", "Ada Lovelace (ada@example.com)")
    expect(screen.getByText("ada@example.com")).toBeInTheDocument()
    expect(screen.getByText("Keenable")).toBeInTheDocument()
  })

  it("disambiguates the rail actor with its visible email, preserving the five-cell order", () => {
    const trace = mapTraceDetail(
      traceDetailFixture({
        actor_type: "human",
        first_name: "Ada",
        last_name: "Lovelace",
        email: "ada-two@example.com",
      })
    )
    render(<TraceDetailSummary trace={trace} attempt={null} />)

    const rail = screen.getByText("Initiated by").closest("dl")!
    expect(
      Array.from(rail.querySelectorAll(":scope > div dt")).map((term) => term.textContent)
    ).toEqual(["Status", "Provider", "Initiated by", "Total latency", "Results"])
    const values = Array.from(rail.querySelectorAll(":scope > div dd")).map(
      (value) => value.textContent
    )
    expect(values[2]).toContain("Ada Lovelace")
    expect(values[2]).toContain("ada-two@example.com")
    expect(screen.getByText("Ada Lovelace")).toHaveAttribute(
      "title",
      "Ada Lovelace (ada-two@example.com)"
    )
  })

  it("keeps API-key rows key-identified when stray human profile values arrive", () => {
    const trace = mapTraceDetail(
      traceDetailFixture({
        actor_type: "project_api_key",
        username: "ada",
        first_name: "Ada",
        last_name: "Lovelace",
        email: "ada@example.com",
      })
    )
    render(<TraceDetailSummary trace={trace} attempt={null} />)

    const rail = screen.getByText("Initiated by").closest("dl")!
    expect(rail).toHaveTextContent("API key")
    expect(rail?.textContent).not.toContain("Ada Lovelace")
    expect(rail?.textContent).not.toContain("ada@example.com")
  })

  it("keeps legacy missing payload rows quiet without naming a project", () => {
    const trace = mapTraceDetail(traceDetailFixture())
    render(<TraceDetailSummary trace={trace} attempt={null} />)

    const rail = screen.getByText("Initiated by").closest("dl")!
    expect(rail).toHaveTextContent("—")
    expect(rail?.textContent).not.toContain("Alpha")
  })
})
