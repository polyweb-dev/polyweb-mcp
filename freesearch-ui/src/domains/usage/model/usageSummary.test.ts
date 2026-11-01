import { describe, expect, it } from "vitest"
import { summarizeUsageByOperation } from "./usageSummary"
import { usageOperationLabel, usageUnitsText } from "./usageFormat"

describe("summarizeUsageByOperation", () => {
  it("adds events per operation and units per unit kind only", () => {
    expect(
      summarizeUsageByOperation([
        { provider: "tavily", operation: "search", totalUnits: 2.5, eventCount: 2, unitKind: "CREDIT" },
        { provider: "exa", operation: "search", totalUnits: 1.5, eventCount: 1, unitKind: "CREDIT" },
        { provider: "brave", operation: "search", totalUnits: 4, eventCount: 4, unitKind: "REQUEST" },
        { provider: "exa", operation: "fetch", totalUnits: 1, eventCount: 1, unitKind: "REQUEST" },
      ])
    ).toEqual([
      {
        operation: "search",
        eventCount: 7,
        units: [
          { unitKind: "CREDIT", units: 4 },
          { unitKind: "REQUEST", units: 4 },
        ],
      },
      { operation: "fetch", eventCount: 1, units: [{ unitKind: "REQUEST", units: 1 }] },
    ])
  })

  it("summarizes no totals to an empty list", () => {
    expect(summarizeUsageByOperation([])).toEqual([])
  })
})

describe("usage formatting", () => {
  it("labels operations and units with their unit kind", () => {
    expect(usageOperationLabel("search")).toBe("Search")
    expect(usageOperationLabel("cost_estimate")).toBe("Cost estimate")
    expect(usageOperationLabel("answer")).toBe("answer")
    expect(usageUnitsText(1234.5, "CREDIT")).toBe("1,234.5 credits")
    expect(usageUnitsText(2, "REQUEST", "searches")).toBe("2 searches")
    expect(usageUnitsText(1, null)).toBe("1 legacy")
  })
})
