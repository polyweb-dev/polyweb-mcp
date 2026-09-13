import { describe, expect, it } from "vitest"
import { quotaDisplay } from "@/domains/dashboard"

/**
 * Parallel Account-API balance: an AUTHORITATIVE remaining-only USD snapshot
 * reads as a balance (mirroring You.com) while every unbudgeted/seeded path
 * keeps its existing headline. Decimal strings stay verbatim throughout.
 */
describe("quotaDisplay parallel authoritative balance", () => {
  it("reads an authoritative remaining-only USD snapshot as a balance", () => {
    const display = quotaDisplay({
      remaining: "4.12",
      limit: null,
      unitKind: "USD",
      displayUnit: "USD",
      confidence: "authoritative",
      resetAt: null,
      providerId: "parallel",
    })
    expect(display.headline).toBe("Balance available")
    expect(display.periodLabel).toBe("Account balance")
    expect(display.nativeValue).toBe("4.12/— USD")
    expect(display.remainingPercent).toBeNull()
  })

  it("keeps Budget not configured for unbudgeted Parallel", () => {
    const display = quotaDisplay({
      remaining: null,
      limit: null,
      unitKind: "USD",
      displayUnit: "USD",
      confidence: null,
      resetAt: null,
      providerId: "parallel",
    })
    expect(display.headline).toBe("Budget not configured")
    expect(display.periodLabel).toBe("Monthly")
  })

  it("shows Balance pending and Account balance when Parallel is connected via OAuth before first use", () => {
    const display = quotaDisplay({
      remaining: null,
      limit: null,
      unitKind: "USD",
      displayUnit: "USD",
      confidence: null,
      resetAt: null,
      providerId: "parallel",
      isOAuthPaired: true,
    })
    expect(display.headline).toBe("Balance pending")
    expect(display.periodLabel).toBe("Account balance")
    expect(display.nativeValue).toBe("OAuth connected")
  })


  it("keeps the seeded percent headline for estimated Parallel budgets", () => {
    const display = quotaDisplay({
      remaining: "3.75",
      remainingPercent: "75",
      limit: "5.00",
      unitKind: "USD",
      displayUnit: "USD",
      confidence: "estimated",
      resetAt: null,
      providerId: "parallel",
    })
    expect(display.headline).toBe("75% remaining")
    expect(display.remainingPercent).toBe(75)
  })

  it("leaves the You.com balance branch untouched", () => {
    const display = quotaDisplay({
      remaining: "199.77",
      limit: null,
      unitKind: "USD",
      displayUnit: "USD",
      confidence: "estimated",
      resetAt: null,
      providerId: "youcom",
    })
    expect(display.headline).toBe("Balance available")
    expect(display.periodLabel).toBe("Account balance")
  })
})