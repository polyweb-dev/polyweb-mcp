import { describe, expect, it } from "vitest"
import type { ProjectUsageTotal } from "@/domains/usage"
import type { ProjectOrder } from "@/domains/routing"
import { usageFigures } from "./usageFigures"

/** A ledger total as a server before priced usage decodes it. */
function total(unitKind: ProjectUsageTotal["unitKind"], totalUnits = 1): ProjectUsageTotal {
  return {
    provider: "exa", operation: "search", eventCount: 1, unitKind, totalUnits,
    costUsd: unitKind === "USD" ? totalUnits : null,
    costEstimated: false,
    unpricedCount: unitKind === "USD" || unitKind === "FREE" ? 0 : 1,
  }
}

const order: ProjectOrder = {
  revision: 1,
  search: {
    strategy: "lowest_cost", hasSavedCustom: false, notAllowed: [],
    providers: [
      { provider: "keenable", name: "Keenable", keyless: true, callCostUsd: null },
      { provider: "exa", name: "Exa", keyless: false, callCostUsd: "0" },
      { provider: "tavily", name: "Tavily", keyless: false, callCostUsd: null },
    ],
  },
  fetch: { strategy: "lowest_cost", hasSavedCustom: false, notAllowed: [], providers: [] },
}

describe("usageFigures", () => {
  it("keeps partial USD charges separate from native credits and requests", () => {
    expect(usageFigures([total("USD", 0.035), total("CREDIT", 10), total("REQUEST", 5)]))
      .toMatchObject({ searches: 3, usd: 0.035, costIncomplete: true, free: false })
  })

  it("treats an all-USD or confirmed-free ledger as complete", () => {
    expect(usageFigures([total("USD"), total("FREE", 0)])).toMatchObject({ usd: 1, costIncomplete: false })
    expect(usageFigures([total("FREE", 0)])).toMatchObject({ usd: null, costIncomplete: false, free: true })
  })

  it("never infers free usage from a missing cost or an empty ledger", () => {
    expect(usageFigures([total(null)])).toMatchObject({ usd: null, costIncomplete: true, free: false })
    expect(usageFigures([])).toMatchObject({ usd: 0, free: false })
  })

  it("uses project pricing for keyless and zero-cost calls without hiding unknown costs", () => {
    const keyless = { ...total("REQUEST"), provider: "keenable" }
    const zero = { ...total("REQUEST"), provider: "exa" }
    const unknown = { ...total("REQUEST"), provider: "tavily" }
    expect(usageFigures([keyless, zero], order)).toMatchObject({ searches: 2, free: true, costIncomplete: false })
    expect(usageFigures([keyless, unknown], order)).toMatchObject({ free: false, costIncomplete: true })
    expect(usageFigures([{ ...zero, operation: "fetch" }], order)).toMatchObject({ free: false, costIncomplete: true })
    expect(usageFigures([total("USD", 0)])).toMatchObject({ free: true, costIncomplete: false })
  })

  it("adds estimated request costs to reported dollars and marks the sum as estimated", () => {
    const brave = { ...total("REQUEST", 3), provider: "brave", costUsd: 0.015, costEstimated: true, unpricedCount: 0 }
    const figures = usageFigures([total("USD", 0.035), brave])

    expect(figures).toMatchObject({ estimated: true, costIncomplete: false, free: false })
    expect(figures.usd).toBeCloseTo(0.05, 6)
    expect(usageFigures([total("USD", 0.035)])).toMatchObject({ estimated: false })
  })

  it("sums cents without binary addition noise", () => {
    const costs = [0.005, 0.007, 0.005, 0.008, 0.005].map((cost) => total("USD", cost))
    expect(usageFigures(costs).usd).toBe(0.03)
  })
})
