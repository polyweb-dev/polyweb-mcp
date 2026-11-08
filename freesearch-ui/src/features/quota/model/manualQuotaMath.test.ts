import { describe, expect, it } from "vitest"
import { validateManualQuotaFields } from "./manualQuotaMath"

describe("validateManualQuotaFields", () => {
  it("rejects a calendar date that JavaScript would normalize", () => {
    const errors = validateManualQuotaFields({
      billingStart: "2026-02-30",
      billingEnd: "2026-03-31",
      allowance: "5",
      used: "1",
    })
    expect(errors.billingStart).toBe("Enter a valid date")
  })
})
