import { describe, expect, it } from "vitest"
import { decodeManualQuota } from "./manualQuotaWire"

const entry = {
  provider: "brave",
  billing_start: "2026-11-01",
  billing_end: "2026-12-01",
  allowance: "9007199254740993.123456",
  current_usage: "0.000001",
}

describe("decodeManualQuota", () => {
  it("accepts the empty route response", () => {
    expect(decodeManualQuota(null)).toBeNull()
  })

  it("preserves exact decimal strings and optional null fields", () => {
    expect(decodeManualQuota({ ...entry, note: null })).toEqual({ ...entry, note: null })
  })

  it.each([{}, [], undefined, { ...entry, allowance: 1000 }, { ...entry, note: 2 }])(
    "rejects a malformed response %j", (value) => {
      expect(() => decodeManualQuota(value)).toThrow("Invalid manual quota response")
    },
  )
})
