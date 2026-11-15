import { describe, expect, it } from "vitest"
import {
  displayNameFromProfile,
  fullNameFromProfile,
  identityDetailLabel,
  identityInitial,
  identityLabel,
  UNKNOWN_USER_LABEL,
  contactLabel,
} from "./identity"

describe("memberIdentity.test.ts", () => {
  describe("memberIdentity full and partial names", () => {
    it("joins the saved first and last name with trimming", () => {
      expect(fullNameFromProfile({ first_name: " Ada ", last_name: " Lovelace " })).toBe("Ada Lovelace")
      expect(fullNameFromProfile({ first_name: "Ada", last_name: null })).toBe("Ada")
      expect(fullNameFromProfile({ first_name: null, last_name: "Lovelace" })).toBe("Lovelace")
    })

    it("returns null without a usable name part", () => {
      expect(fullNameFromProfile({})).toBeNull()
      expect(fullNameFromProfile({ first_name: "  ", last_name: " " })).toBeNull()
      expect(fullNameFromProfile({ first_name: null, last_name: null })).toBeNull()
    })

    it("prefers the full name over the username and trims the username fallback", () => {
      expect(
        displayNameFromProfile({ first_name: "Ada", last_name: "Lovelace", username: "ada" })
      ).toBe("Ada Lovelace")
      expect(displayNameFromProfile({ username: "  ops-lead  " })).toBe("ops-lead")
      expect(displayNameFromProfile({})).toBeNull()
      expect(displayNameFromProfile({ first_name: " ", username: "  " })).toBeNull()
    })
  })

  describe("memberIdentity labels and initials", () => {
    it("labels a person by display name only, never an email", () => {
      const named = { first_name: "Ada", last_name: "Lovelace", username: "ada" }
      expect(identityLabel(named)).toBe("Ada Lovelace")
      expect(identityLabel({ username: "ops-lead" })).toBe("ops-lead")
      expect(identityLabel({})).toBe(UNKNOWN_USER_LABEL)
      expect(UNKNOWN_USER_LABEL).toBe("Unknown user")
      // A stray email on the object is never read.
      expect(identityLabel({ email: "lead@example.com" } as object)).toBe("Unknown user")
      expect(identityLabel({ first_name: " ", last_name: "", username: "  " })).toBe("Unknown user")
    })

    it("keeps the email only in the explicit contact helpers", () => {
      const named = { email: "ada@example.com", first_name: "Ada", last_name: "Lovelace", username: "ada" }
      expect(contactLabel(named)).toBe("Ada Lovelace")
      expect(identityDetailLabel(named)).toBe("Ada Lovelace (ada@example.com)")
      expect(contactLabel({ email: "ops@example.com", username: "ops-lead" })).toBe("ops-lead")
      expect(identityDetailLabel({ email: "ops@example.com", username: "ops-lead" })).toBe(
        "ops-lead (ops@example.com)"
      )
      expect(contactLabel({ email: "lead@example.com" })).toBe("lead@example.com")
      expect(identityDetailLabel({ email: "lead@example.com" })).toBe("lead@example.com")
    })

    it("derives the avatar initial from the display name, else the email", () => {
      expect(identityInitial("Ada Lovelace", "ada@example.com")).toBe("A")
      expect(identityInitial("ops-lead", "ops@example.com")).toBe("O")
      expect(identityInitial(null, "lead@example.com")).toBe("L")
      expect(identityInitial(null, "  lead@example.com  ")).toBe("L")
    })
  })
})
