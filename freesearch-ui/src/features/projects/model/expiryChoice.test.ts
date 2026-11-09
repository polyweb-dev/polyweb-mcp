import { describe, expect, it } from "vitest"
import { PAST_EXPIRY_MESSAGE, toApiKeyExpiry, todayInputValue } from "./expiryChoice"

const NOW = new Date(2026, 9, 31, 12, 0, 0)

describe("toApiKeyExpiry", () => {
  it("omits the expiry for the default choice", () => {
    expect(toApiKeyExpiry("default", "", NOW)).toEqual({ ok: true, expiry: { kind: "default" } })
  })

  it("sends an explicit null for No expiration", () => {
    expect(toApiKeyExpiry("never", "", NOW)).toEqual({ ok: true, expiry: { kind: "never" } })
  })

  it("sends the end of the chosen local day as an ISO timestamp", () => {
    const result = toApiKeyExpiry("custom", "2026-12-01", NOW)
    expect(result).toEqual({
      ok: true,
      expiry: { kind: "at", isoTimestamp: new Date(2026, 11, 1, 23, 59, 59).toISOString() },
    })
  })

  it("accepts today, whose end still lies in the future", () => {
    expect(toApiKeyExpiry("custom", "2026-10-31", NOW).ok).toBe(true)
  })

  it.each([["2026-10-30"], [""], ["31/10/2026"], ["2027-02-30"], ["2027-13-01"]])("rejects the custom date %j", (value) => {
    expect(toApiKeyExpiry("custom", value, NOW)).toEqual({ ok: false, message: PAST_EXPIRY_MESSAGE })
  })
})

describe("todayInputValue", () => {
  it("formats the local date for a date input", () => {
    expect(todayInputValue(new Date(2026, 0, 5))).toBe("2026-01-05")
  })
})
