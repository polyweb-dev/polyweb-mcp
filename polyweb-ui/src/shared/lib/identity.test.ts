import { describe, expect, it } from "vitest"
import {
  displayNameFromProfile,
  fullNameFromProfile,
  identityDetailLabel,
  identityInitial,
  identityLabel,
  traceActorLabel,
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
    it("uses the display name primary with the email kept for contact", () => {
      const named = { email: "ada@example.com", first_name: "Ada", last_name: "Lovelace", username: "ada" }
      expect(identityLabel(named)).toBe("Ada Lovelace")
      expect(identityDetailLabel(named)).toBe("Ada Lovelace (ada@example.com)")
    })

    it("falls back from the username to the email alone", () => {
      expect(identityLabel({ email: "ops@example.com", username: "ops-lead" })).toBe("ops-lead")
      expect(identityDetailLabel({ email: "ops@example.com", username: "ops-lead" })).toBe(
        "ops-lead (ops@example.com)"
      )
      expect(identityLabel({ email: "lead@example.com" })).toBe("lead@example.com")
      expect(identityDetailLabel({ email: "lead@example.com" })).toBe("lead@example.com")
    })

    it("derives the avatar initial from the display name, else the email", () => {
      expect(identityInitial("Ada Lovelace", "ada@example.com")).toBe("A")
      expect(identityInitial("ops-lead", "ops@example.com")).toBe("O")
      expect(identityInitial(null, "lead@example.com")).toBe("L")
      expect(identityInitial(null, "  lead@example.com  ")).toBe("L")
    })

    it("labels trace actors with disambiguating email only, keeping legacy quiet", () => {
      expect(traceActorLabel({ displayName: "Ada Lovelace", email: "ada@example.com" })).toBe(
        "Ada Lovelace (ada@example.com)"
      )
      expect(traceActorLabel({ displayName: "Ada Lovelace", email: "Ada Lovelace" })).toBe(
        "Ada Lovelace"
      )
      expect(traceActorLabel({ displayName: null, email: "ada@example.com" })).toBe(
        "ada@example.com"
      )
      expect(traceActorLabel({ displayName: null, email: null })).toBeNull()
    })
  })
})
