import { describe, expect, it } from "vitest"
import { formatMaskedKey } from "./maskKey"

describe("formatMaskedKey", () => {
  it.each([
    ["abcdefghijklmnop", "abcd_••••••••mnop"],
    ["  abcdefghijklmnop  ", "abcd_••••••••mnop"],
    ["", "••••••••"],
    ["short", "••••••••"],
    ["       ", "••••••••"],
    ["1234567", "••••••••"],
    ["12345678", "1234_••••••••5678"],
  ])("formats %j as %j", (rawKey, expected) => {
    expect(formatMaskedKey(rawKey)).toBe(expected)
  })
})
