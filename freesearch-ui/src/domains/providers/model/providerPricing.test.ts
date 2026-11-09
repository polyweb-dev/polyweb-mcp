import { describe, expect, it } from "vitest"
import { decodeCallCosts, formatCallCost, formatCostTotal, providerCallCost } from "./providerPricing"

describe("catalog pricing", () => {
  it.each([
    ["call", "0.005", "$0.0050"], ["call", 0.0076, "$0.0076"], ["call", "0.008", "$0.0080"],
    ["call", 0, "Free"], ["call", null, "—"], ["call", undefined, "—"], ["call", " ", "—"],
    ["call", "invalid", "—"], ["call", -1, "—"], ["total", 12.34, "$12.34"], ["total", 0, "$0.00"],
    ["total", 0.035, "$0.035"], ["total", "0.00000001", "$0.00000001"],
    ["total", 1e-25, "$0.0000000000000000000000001"],
    ["total", "12345678901234567890.1234500", "$12,345,678,901,234,567,890.12345"],
    ["total", "4.500", "$4.50"], ["total", null, "—"], ["total", "", "—"], ["total", "invalid", "—"], ["total", -1, "—"],
  ])("formats %s %s as %s", (kind, cost, text) => {
    expect((kind === "call" ? formatCallCost : formatCostTotal)(cost)).toBe(text)
  })

  it("uses the same catalog facts for keyed and keyless Tavily", () => {
    const tavily = { callCostUsd: { search: "0.008", fetch: "0.0016" }, keylessCallCostUsd: { search: "0", fetch: "0" } }
    expect(providerCallCost(tavily, "search")).toBe("$0.0080")
    expect(providerCallCost(tavily, "fetch")).toBe("$0.0016")
    expect(providerCallCost(tavily, "search", true)).toBe("Free")
    expect(providerCallCost(tavily, "fetch", true)).toBe("Free")
    expect(providerCallCost({ callCostUsd: { search: 0 } }, "search", true)).toBe("—")
  })

  it("drops invalid catalog prices and unsupported fields", () => {
    expect(decodeCallCosts({ search: "0.008", fetch: -1, secret: "hidden" })).toEqual({ search: "0.008" })
    expect(decodeCallCosts(null)).toEqual({})
  })
})
