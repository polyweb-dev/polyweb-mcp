import { describe, expect, it } from "vitest"
import type { ProjectUsageTotal } from "@/domains/usage"
import type { ProjectOrder } from "@/domains/routing"
import { usageFigures } from "./usageFigures"

function total(unitKind: ProjectUsageTotal["unitKind"], totalUnits = 1): ProjectUsageTotal {
  return { provider: "exa", operation: "search", eventCount: 1, unitKind, totalUnits }
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
})
