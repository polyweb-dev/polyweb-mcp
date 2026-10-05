import { describe, expect, it } from "vitest"
import { isManualQuotaEligible } from "./quotaEligibility"

describe("isManualQuotaEligible", () => {
  it("extends missing-budget entry to Tinyfish without changing other providers", () => {
    expect(isManualQuotaEligible("tinyfish", true)).toBe(true)
    expect(isManualQuotaEligible("tinyfish", false)).toBe(false)
    expect(isManualQuotaEligible("brave", false)).toBe(true)
    for (const provider of ["exa", "parallel"]) {
      expect(isManualQuotaEligible(provider, true)).toBe(true)
      expect(isManualQuotaEligible(provider, false)).toBe(false)
    }
    for (const provider of ["firecrawl", "tavily", "keenable", "youcom", "unknown"]) {
      expect(isManualQuotaEligible(provider, true)).toBe(false)
    }
  })
})
