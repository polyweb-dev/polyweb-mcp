import { describe, expect, it } from "vitest"
import { render, screen, within } from "@testing-library/react"
import type { CRDUsageTotal } from "@/domains/dashboard"
import { UsageTotals } from "./UsageTotals"

/** One merged usage table: one row per provider, USD cost, and one p95. */

const TOTALS: CRDUsageTotal[] = [
  { provider: "brave", operation: "search", normalized_crd: "5", attempt_count: 1, volume_count: 1 },
  { provider: "tavily", operation: "search", normalized_crd: "8", attempt_count: 1, volume_count: 1200 },
  { provider: "tavily", operation: "fetch", normalized_crd: "16", attempt_count: 2, volume_count: 3 },
]

const PROVIDERS = [
  { id: "brave", name: "Brave", latencyP95Ms: 1192 },
  { id: "tavily", name: "Tavily", latencyP95Ms: null },
]

describe("UsageTotals", () => {
  it("merges every provider into one row with separators and units in the headers", () => {
    render(<UsageTotals crdUsageTotals={TOTALS} providers={PROVIDERS as never} />)
    const table = screen.getByRole("table", { name: "Usage totals" })
    expect(Array.from(table.querySelectorAll("th")).map((th) => th.textContent)).toEqual([
      "Provider",
      "Searches",
      "URLs fetched",
      "Known cost",
      "p95",
    ])
    const rows = table.querySelectorAll("tbody tr")
    expect(rows).toHaveLength(2)
    const tavily = within(rows[1] as HTMLElement)
    expect(tavily.getByText("1,200")).not.toBeNull()
    expect(within(rows[0] as HTMLElement).getByText("$0.005")).not.toBeNull()
    expect(tavily.getByText("$0.024")).not.toBeNull()
    expect(within(rows[0] as HTMLElement).getByText("1,192 ms")).not.toBeNull()
    expect(table.querySelector('[data-testid="provider-logo-brave"]')).not.toBeNull()
  })

  it("shows one quiet line without recorded usage", () => {
    render(<UsageTotals crdUsageTotals={[]} providers={PROVIDERS as never} />)
    expect(screen.getByText("No usage recorded yet")).not.toBeNull()
    expect(screen.queryByRole("table")).toBeNull()
  })

  it("shows USD cost without a price profile", () => {
    render(<UsageTotals crdUsageTotals={TOTALS} providers={PROVIDERS as never} />)
    const table = screen.getByRole("table", { name: "Usage totals" })
    expect(within(table).getByText("$0.024")).toBeInTheDocument()
    expect(table.textContent).not.toContain("Tavily credit")
  })
})
