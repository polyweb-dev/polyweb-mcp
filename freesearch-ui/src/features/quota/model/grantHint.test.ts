import { describe, expect, it } from "vitest"
import { grantHint } from "./grantHint"
import { formatDate } from "@/shared/lib/formatTime"

describe("grantHint", () => {
  it("uses the provided reference price and updates with the budget", () => {
    expect(grantHint({ name: "search", value: "5000", conversion: null, reference: "0.001" })).toBe("≈ $5.00 at provider list price")
    expect(grantHint({ name: "fetch", value: "2500", conversion: null, reference: "0.002" })).toBe("≈ $5.00 at provider list price")
    expect(grantHint({ name: "search", value: "", conversion: null, reference: "0.001" })).toBeNull()
    expect(grantHint({ name: "search", value: "invalid", conversion: null, reference: "0.001" })).toBeNull()
  })

  it("shows the selected calendar date in the app format", () => {
    expect(grantHint({ name: "start", value: "2026-11-01", conversion: null, reference: "0.001" })).toBe(formatDate("2026-11-01T00:00:00"))
  })
})
