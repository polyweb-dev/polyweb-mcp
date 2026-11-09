import { describe, expect, it } from "vitest"
import { render, screen, within } from "@testing-library/react"
import type { UsdUsageTotal } from "@/domains/dashboard"
import { UsageTotals } from "./UsageTotals"

/** One merged usage table: one row per provider, USD cost, and one p95. */

const TOTALS: UsdUsageTotal[] = [
  { provider: "brave", operation: "search", spend_usd: "0.005", attempt_count: 1, volume_count: 1 },
  { provider: "tavily", operation: "search", spend_usd: "0.008", attempt_count: 1, volume_count: 1200 },
  { provider: "tavily", operation: "fetch", spend_usd: "0.016", attempt_count: 2, volume_count: 3 },
]

const PROVIDERS = [
  { id: "brave", name: "Brave", latencyP95Ms: 1192 },
  { id: "tavily", name: "Tavily", latencyP95Ms: null },
]

describe("UsageTotals", () => {
  it("merges every provider into one row with separators and units in the headers", () => {
    render(<UsageTotals usdUsageTotals={TOTALS} providers={PROVIDERS as never} />)
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
    expect(within(rows[0] as HTMLElement).getByText("$0.01")).not.toBeNull()
    expect(tavily.getByText("$0.02")).not.toBeNull()
    expect(tavily.getByText("—")).toBeInTheDocument()
    expect(within(rows[0] as HTMLElement).getByText("1,192 ms")).not.toBeNull()
    expect(table.querySelector('[data-testid="provider-logo-brave"]')).not.toBeNull()
  })

  it("shows one quiet line without recorded usage", () => {
    render(<UsageTotals usdUsageTotals={[]} providers={PROVIDERS as never} />)
    expect(screen.getByText("No usage recorded yet")).not.toBeNull()
    expect(screen.queryByRole("table")).toBeNull()
  })

  it("shows USD cost without a price profile", () => {
    render(<UsageTotals usdUsageTotals={TOTALS} providers={PROVIDERS as never} />)
    const table = screen.getByRole("table", { name: "Usage totals" })
    expect(within(table).getByText("$0.02")).toBeInTheDocument()
    expect(table.textContent).not.toContain("Tavily credit")
  })
})
