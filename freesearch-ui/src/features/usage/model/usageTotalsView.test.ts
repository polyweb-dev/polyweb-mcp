import { describe, expect, it } from "vitest"
import type { ProjectUsageTotal } from "@/domains/usage"
import type { ProjectOrder } from "@/domains/routing"
import { usageAmountText, usageTotalsView } from "./usageTotalsView"

function total(overrides: Partial<ProjectUsageTotal>): ProjectUsageTotal {
  return {
    provider: "brave",
    operation: "search",
    totalUnits: 0,
    eventCount: 0,
    unitKind: null,
    ...overrides,
  }
}

describe("usageTotalsView", () => {
  it("uses operation-specific zero prices but keeps unknown and mixed costs distinct", () => {
    const order: ProjectOrder = {
      revision: 1,
      search: { strategy: "custom", hasSavedCustom: true, notAllowed: [], providers: [
        { provider: "you", name: "You.com", callCostUsd: "0", keyless: false },
        { provider: "keenable", name: "Keenable", callCostUsd: null, keyless: true },
        { provider: "tavily", name: "Tavily", callCostUsd: null, keyless: false },
      ] },
      fetch: { strategy: "custom", hasSavedCustom: true, notAllowed: [], providers: [
        { provider: "you", name: "You.com", callCostUsd: "0.01", keyless: false },
      ] },
    }
    const view = usageTotalsView([
      total({ provider: "youcom", operation: "search", eventCount: 1, unitKind: "REQUEST" }),
      total({ provider: "you", operation: "fetch", eventCount: 1, unitKind: "REQUEST" }),
      total({ provider: "keenable", eventCount: 1, unitKind: "CREDIT" }),
      total({ provider: "tavily", eventCount: 1, unitKind: "REQUEST" }),
    ], order)
    expect(view.rows.map((row) => usageAmountText(row, "usd"))).toEqual([
      "Free", "Not reported", "Free", "Not reported",
    ])
    expect(usageAmountText(view.total, "usd")).toBe("Not reported")
  })

  it("shows recorded zero dollar costs as free without masking unknown mixed costs", () => {
    const view = usageTotalsView([
      total({ provider: "exa", unitKind: "USD", eventCount: 1 }),
      total({ provider: "tavily", unitKind: "REQUEST", eventCount: 1 }),
    ])
    expect(usageAmountText(view.rows[0]!, "usd")).toBe("Free")
    expect(usageAmountText(view.total, "usd")).toBe("$0.00")
  })
  it("merges unit kinds of one provider and operation into one row with separate columns", () => {
    const view = usageTotalsView([
      total({ provider: "exa", totalUnits: 0.035, eventCount: 6, unitKind: "USD" }),
      total({ provider: "exa", totalUnits: 1, eventCount: 1, unitKind: "CREDIT" }),
      total({ provider: "brave", totalUnits: 9, eventCount: 9, unitKind: "REQUEST" }),
    ])

    expect(view.rows).toHaveLength(2)
    const exa = view.rows.find((row) => row.provider === "exa")!
    expect(exa).toMatchObject({ calls: 7, usd: 0.035, credits: 1, requests: null })
    expect(view.columns).toEqual(["usd", "credits"])
  })

  it("sums every column on its own and never across unit kinds", () => {
    const view = usageTotalsView([
      total({ provider: "exa", totalUnits: 0.03, eventCount: 3, unitKind: "USD" }),
      total({ provider: "tavily", totalUnits: 0.005, eventCount: 1, unitKind: "USD" }),
      total({ provider: "brave", totalUnits: 9, eventCount: 9, unitKind: "REQUEST" }),
    ])

    expect(view.total).toMatchObject({ calls: 13, requests: 9, credits: null })
    expect(view.total.usd).toBeCloseTo(0.035, 6)
    expect(usageAmountText(view.total, "usd")).toBe("$0.035")
  })

  it("shows billed requests when a provider bills a different number of calls", () => {
    const view = usageTotalsView([
      total({ provider: "brave", totalUnits: 8, eventCount: 9, unitKind: "REQUEST" }),
    ])
    expect(view.columns).toContain("requests")
  })

  it("shows only the unit columns some row uses, legacy units in their own column", () => {
    const view = usageTotalsView([
      total({ provider: "keenable", operation: "fetch", totalUnits: 0.5, eventCount: 5, unitKind: null }),
    ])

    expect(view.columns).toEqual(["usd", "other"])
    expect(usageAmountText(view.rows[0]!, "usd")).toBe("Not reported")
    expect(usageAmountText(view.rows[0]!, "other")).toBe("0.5")
  })

  it("labels a keyless provider as free in the cost column", () => {
    const view = usageTotalsView([
      total({ provider: "keenable", totalUnits: 0, eventCount: 4, unitKind: "FREE" }),
    ])

    expect(view.columns).toEqual(["usd"])
    expect(usageAmountText(view.rows[0]!, "usd")).toBe("Free")
  })

  it("formats dollars with two to four decimals and dashes an absent kind", () => {
    const view = usageTotalsView([
      total({ provider: "exa", totalUnits: 0.007, eventCount: 1, unitKind: "USD" }),
      total({ provider: "tavily", totalUnits: 12, eventCount: 4, unitKind: "CREDIT" }),
    ])
    const exa = view.rows.find((row) => row.provider === "exa")!
    const tavily = view.rows.find((row) => row.provider === "tavily")!

    expect(usageAmountText(exa, "usd")).toBe("$0.007")
    expect(usageAmountText(tavily, "usd")).toBe("Not reported")
    expect(usageAmountText(tavily, "credits")).toBe("12")
    expect(usageAmountText(view.total, "usd")).toBe("$0.007")
  })

  it("uses thousands separators for large amounts", () => {
    const view = usageTotalsView([
      total({ provider: "brave", totalUnits: 12500, eventCount: 12500, unitKind: "REQUEST" }),
      total({ provider: "exa", totalUnits: 1234.5, eventCount: 3, unitKind: "USD" }),
    ])
    const brave = view.rows.find((row) => row.provider === "brave")!
    const exa = view.rows.find((row) => row.provider === "exa")!

    expect(usageAmountText(brave, "requests")).toBe("12,500")
    expect(usageAmountText(exa, "usd")).toBe("$1,234.50")
  })

  it("does not label a mixed free and unreported-cost row or total as free", () => {
    const view = usageTotalsView([
      total({ provider: "keenable", unitKind: "FREE", eventCount: 1 }),
      total({ provider: "keenable", unitKind: "CREDIT", totalUnits: 1, eventCount: 1 }),
    ])
    expect(usageAmountText(view.rows[0]!, "usd")).toBe("Not reported")
    expect(usageAmountText(view.total, "usd")).toBe("Not reported")
  })
})
