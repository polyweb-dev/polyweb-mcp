import { describe, expect, it } from "vitest"
import { groupDigits, nativeLeftText, nativeUnitLabel } from "./numberText"

describe("quota unit display", () => {
  it.each(["CREDIT", "Credits"])("labels %s amounts as credits", (unit) => {
    expect(nativeUnitLabel(unit)).toBe("credits")
    expect(nativeLeftText("1000", unit)).toBe("1,000 credits left")
  })

  it("shows a legacy ledger balance in USD", () => {
    expect(nativeUnitLabel("CRD")).toBe("USD")
    expect(nativeLeftText("1000.5", "CRD")).toBe("$1.0005 left")
    expect(nativeLeftText("invalid", "CRD")).toBeNull()
  })

  it("shows USD balances in dollars", () => {
    expect(nativeLeftText("1234.5", "USD")).toBe("$1,234.50 left")
  })

  it("shows free providers as Free", () => {
    expect(nativeUnitLabel("FREE")).toBe("Free")
    expect(nativeLeftText("0", "FREE")).toBe("Free")
  })

  it("keeps unknown units unknown", () => {
    expect(nativeLeftText("1000", "unknown")).toBeNull()
  })

  it("preserves all digits of large exact balances", () => {
    expect(groupDigits("9007199254740993.12 credits")).toBe("9,007,199,254,740,993.12 credits")
  })
})
