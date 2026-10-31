import { describe, expect, it } from "vitest"
import {
  MAX_PASSWORD_LENGTH,
  MIN_PASSWORD_LENGTH,
  PASSWORD_HINT,
  passwordLengthProblem,
} from "./passwordRule"

describe("passwordLengthProblem", () => {
  it("accepts the 12 and 128 character bounds", () => {
    expect(passwordLengthProblem("a".repeat(MIN_PASSWORD_LENGTH))).toBeNull()
    expect(passwordLengthProblem("a".repeat(MAX_PASSWORD_LENGTH))).toBeNull()
  })

  it("names the minimum and the maximum", () => {
    expect(passwordLengthProblem("a".repeat(11))).toBe("Use at least 12 characters for the password.")
    expect(passwordLengthProblem("a".repeat(129))).toBe("Use no more than 128 characters for the password.")
  })

  it("states the rule in the shared hint", () => {
    expect(PASSWORD_HINT).toBe("Use 12 to 128 characters.")
  })
})
