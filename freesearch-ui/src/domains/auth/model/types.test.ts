import { describe, expect, it } from "vitest"
import { adminAccountFixture } from "@/test/authFixtures"
import { accountDisplayName } from "./types"

describe("accountDisplayName", () => {
  it("prefers the full name", () => {
    expect(
      accountDisplayName(adminAccountFixture({ first_name: "Ada", last_name: "Lovelace", username: "ada" }))
    ).toBe("Ada Lovelace")
  })

  it("uses a single name part when only one is present", () => {
    expect(accountDisplayName(adminAccountFixture({ first_name: "Ada" }))).toBe("Ada")
    expect(accountDisplayName(adminAccountFixture({ last_name: "Lovelace" }))).toBe("Lovelace")
  })

  it("falls back to the username", () => {
    expect(accountDisplayName(adminAccountFixture({ username: "ada" }))).toBe("ada")
  })

  it("returns null without a name or username, and for blank values", () => {
    expect(accountDisplayName(adminAccountFixture())).toBeNull()
    expect(accountDisplayName(adminAccountFixture({ first_name: " ", username: "" }))).toBeNull()
  })
})
