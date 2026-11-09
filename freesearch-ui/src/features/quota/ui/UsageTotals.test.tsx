import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { render, screen, within } from "@testing-library/react"
import type { UsdUsageTotal } from "@/domains/dashboard"
import { UsageTotals } from "./UsageTotals"
import { installFetchStub, ok } from "@/test/fetchMock"

beforeEach(() => { installFetchStub(() => ok([])) })
afterEach(() => vi.unstubAllGlobals())

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
      "Cost",
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

  it("distinguishes free providers from paid providers with zero spend", () => {
    render(<UsageTotals providers={[
      { id: "keenable", name: "Keenable", callCostUsd: { search: "0", fetch: "0" } },
      { id: "brave", name: "Brave Search", callCostUsd: { search: "0.005" } },
    ] as never} usdUsageTotals={["keenable", "brave"].map((provider) => ({
      provider, operation: "search", spend_usd: "0", attempt_count: 1, volume_count: 1,
    }))} />)
    expect(within(screen.getByRole("row", { name: /Keenable/ })).getByText("Free")).toBeInTheDocument()
    expect(within(screen.getByRole("row", { name: /Brave Search/ })).getByText("$0.00")).toBeInTheDocument()
  })

  it("uses the price catalog when the provider snapshot has no pricing", async () => {
    installFetchStub(() => ok([{ provider_id: "keenable", free: true, keyless: true,
      call_cost_usd: { search: "0", fetch: "0" }, keyless_call_cost_usd: { search: "0", fetch: "0" } }]))
    render(<UsageTotals providers={[{ id: "keenable", name: "Keenable" }] as never}
      usdUsageTotals={[{ provider: "keenable", operation: "search", spend_usd: "0", attempt_count: 1, volume_count: 1 }]} />)
    expect(await screen.findByText("Free")).toBeInTheDocument()
    expect(screen.queryByText("$0.00")).toBeNull()
  })

  it("shows USD cost without a price profile", () => {
    render(<UsageTotals usdUsageTotals={TOTALS} providers={PROVIDERS as never} />)
    const table = screen.getByRole("table", { name: "Usage totals" })
    expect(within(table).getByText("$0.02")).toBeInTheDocument()
    expect(table.textContent).not.toContain("Tavily credit")
  })
})
