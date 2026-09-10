import { describe, expect, it } from "vitest"
import { quotaDisplay } from "./quotaDisplay"

const input = {
  unitKind: "REQUEST" as const,
  displayUnit: "requests",
  confidence: "observed" as const,
  resetAt: null,
}

describe("quotaDisplay", () => {
  it("normalizes remaining capacity while preserving useful fractional headroom", () => {
    expect(quotaDisplay({ ...input, remaining: "999", limit: "1000" }).remainingPercent).toBe(99.9)
    expect(quotaDisplay({ ...input, remaining: "950", limit: "1000", remainingPercent: "95" }).remainingPercent).toBe(95)
  })

  it("does not fabricate a percentage without a finite native limit", () => {
    const display = quotaDisplay({
      ...input,
      remaining: "4.75",
      limit: null,
      remainingPercent: "95",
    })
    expect(display.remainingPercent).toBeNull()
    expect(display.nativeValue).toBe("4.75/— requests")
    expect(display.detail).toMatch(/no hard limit/i)
  })

  it("describes a keyless rolling window separately from monthly quota", () => {
    const display = quotaDisplay({
      ...input,
      remaining: "999",
      limit: "1000",
      remainingPercent: "99.9",
      keyless: true,
      window: "hourly",
    })
    expect(display.detail).toMatch(/hourly|locally observed|shared rate limits/i)
    expect(display.periodLabel).toBe("Rolling hour")
    expect(display.headline).toBe("99.9% remaining")
  })

  it("names monthly budget gaps instead of claiming an unlimited quota", () => {
    const display = quotaDisplay({
      ...input,
      remaining: null,
      limit: null,
      providerId: "parallel",
    })
    expect(display.headline).toBe("Budget not configured")
    expect(display.periodLabel).toBe("Monthly")
  })

  it("treats You.com remaining USD as an account balance, not a quota percentage", () => {
    const display = quotaDisplay({
      ...input,
      remaining: "199.77",
      limit: null,
      unitKind: "USD",
      displayUnit: "USD",
      providerId: "youcom",
    })
    expect(display.headline).toBe("Balance available")
    expect(display.periodLabel).toBe("Account balance")
    expect(display.remainingPercent).toBeNull()
  })
})
