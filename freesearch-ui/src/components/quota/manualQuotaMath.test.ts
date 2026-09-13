import { describe, expect, it } from "vitest"
import {
  formatManualRange,
  formatPercent1dp,
  isNonNegativeDecimal,
  isPositiveDecimal,
  parseDecimal,
  remainingPercent1dp,
  validateManualQuotaFields,
} from "@/features/quota/model/manualQuotaMath"

describe("manualQuotaMath (Decimal-safe, no float math)", () => {
  it("computes the Brave case 0.88/5.00 as 82.4% remaining", () => {
    expect(remainingPercent1dp("5.00", "0.88")).toBe(82.4)
  })

  it("reuses the same math for an Exa USD budget", () => {
    expect(remainingPercent1dp("5.00", "3.75")).toBe(25)
    expect(formatPercent1dp(25)).toBe("25.0")
  })

  it("handles tiny Exa-scale decimals without exponent drift", () => {
    expect(remainingPercent1dp("0.00000010", "0.00000002")).toBe(80)
  })

  it("clamps over-usage to 0 and full headroom to 100", () => {
    expect(remainingPercent1dp("5.00", "7.50")).toBe(0)
    expect(remainingPercent1dp("5.00", "0")).toBe(100)
  })

  it("rounds half-up to 1 decimal place", () => {
    // 1/6 remaining -> 16.666…% -> 16.7%.
    expect(remainingPercent1dp("6", "5")).toBe(16.7)
  })

  it("returns null for non-decimals and non-positive allowances", () => {
    expect(remainingPercent1dp("abc", "1")).toBeNull()
    expect(remainingPercent1dp("1e-8", "1")).toBeNull()
    expect(remainingPercent1dp("0", "0")).toBeNull()
    expect(remainingPercent1dp("", "0")).toBeNull()
  })

  it("keeps verbatim decimal shapes parseable", () => {
    expect(parseDecimal("100000.10")).toEqual({ int: 10000010n, scale: 2 })
    expect(parseDecimal("-1")).toBeNull()
    expect(isNonNegativeDecimal("0.88")).toBe(true)
    expect(isNonNegativeDecimal("")).toBe(false)
    expect(isPositiveDecimal("0.00")).toBe(false)
    expect(isPositiveDecimal("0.01")).toBe(true)
  })

  it("validates billing windows and amounts", () => {
    expect(
      validateManualQuotaFields({ billingStart: "", billingEnd: "", allowance: "", used: "" })
    ).toEqual({
      billingStart: "Required.",
      billingEnd: "Required.",
      allowance: "Required.",
      used: "Required.",
    })
    expect(
      validateManualQuotaFields({
        billingStart: "2026-09-30",
        billingEnd: "2026-09-01",
        allowance: "5.00",
        used: "0.88",
      }).billingEnd
    ).toBe("Billing end must be after billing start.")
    expect(
      validateManualQuotaFields({
        billingStart: "2026-09-01",
        billingEnd: "2026-09-30",
        allowance: "-2",
        used: "abc",
      })
    ).toMatchObject({ allowance: expect.any(String), used: expect.any(String) })
    expect(
      validateManualQuotaFields({
        billingStart: "2026-09-01",
        billingEnd: "2026-09-30",
        allowance: "0",
        used: "0",
      }).allowance
    ).toBe("Allowance must be greater than zero.")
    expect(
      validateManualQuotaFields({
        billingStart: "2026-09-01",
        billingEnd: "2026-09-30",
        allowance: "5.00",
        used: "0.88",
      })
    ).toEqual({})
  })

  it("formats the manual range as MMM d–MMM d", () => {
    expect(formatManualRange("2026-09-01", "2026-09-30")).toMatch(/\w{3} 1–\w{3} 30/)
  })
})