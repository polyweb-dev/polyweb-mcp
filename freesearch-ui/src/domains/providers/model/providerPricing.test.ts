import { describe, expect, it } from "vitest"
import { decodeCallCosts, formatCallCost, formatCostTotal, providerCallCost } from "./providerPricing"

describe("catalog pricing", () => {
  it.each([
    ["0.005", "$0.0050"], [0.0076, "$0.0076"], ["0.008", "$0.0080"],
    [0, "Free"], [null, "—"], [undefined, "—"], ["invalid", "—"], [-1, "—"],
  ])("formats %s as %s", (cost, text) => {
    expect(formatCallCost(cost)).toBe(text)
  })

  it("uses the same catalog facts for keyed and keyless Tavily", () => {
    const tavily = { callCostUsd: { search: "0.008", fetch: "0.0016" }, keylessCallCostUsd: { search: "0", fetch: "0" } }
    expect(providerCallCost(tavily, "search")).toBe("$0.0080")
    expect(providerCallCost(tavily, "fetch")).toBe("$0.0016")
    expect(providerCallCost(tavily, "search", true)).toBe("Free")
    expect(providerCallCost(tavily, "fetch", true)).toBe("Free")
    expect(providerCallCost({ callCostUsd: { search: 0 } }, "search", true)).toBe("—")
  })

  it("formats totals consistently without hiding small recorded costs", () => {
    expect(formatCostTotal(12.34)).toBe("$12.34")
    expect(formatCostTotal(0.035)).toBe("$0.035")
    expect(formatCostTotal(null)).toBe("—")
  })

  it("drops invalid catalog prices and unsupported fields", () => {
    expect(decodeCallCosts({ search: "0.008", fetch: -1, secret: "hidden" })).toEqual({ search: "0.008" })
    expect(decodeCallCosts(null)).toEqual({})
  })
})
