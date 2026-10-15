import { describe, expect, it } from "vitest"
import { isManualQuotaEligible } from "./quotaEligibility"

describe("isManualQuotaEligible", () => {
  it("extends missing-budget entry to Tinyfish without changing other providers", () => {
    expect(isManualQuotaEligible("tinyfish", true)).toBe(true)
    expect(isManualQuotaEligible("tinyfish", false)).toBe(false)
    expect(isManualQuotaEligible("brave", true)).toBe(true)
    expect(isManualQuotaEligible("brave", false)).toBe(false)
    for (const provider of ["exa"]) {
      expect(isManualQuotaEligible(provider, true)).toBe(true)
      expect(isManualQuotaEligible(provider, false)).toBe(false)
    }
    // Parallel stays out: its prepaid USD balance comes from the OAuth Account
    // API (AUTHORITATIVE snapshot), never from a manual seed.
    for (const provider of ["firecrawl", "tavily", "keenable", "youcom", "unknown", "parallel"]) {
      expect(isManualQuotaEligible(provider, true)).toBe(false)
    }
  })
})
