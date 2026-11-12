import { describe, expect, it } from "vitest"
import { identityFromMember, memberActionLabel, memberDetailLabel, memberSortLabel } from "./memberIdentity"

describe("memberIdentity member labels", () => {
  it("resolves member labels and sorts by the display name case-insensitively", () => {
    const member = {
      project_id: "p1",
      user_id: "u1",
      email: "ada@example.com",
      first_name: "Ada",
      last_name: "Lovelace",
      username: "ada",
      status: "active" as const,
      roles: ["project_admin"],
      role: "admin" as const,
      permissions: 1,
      provider_owner: false,
      account_active: true,
      version: 1,
    }
    expect(identityFromMember(member)).toEqual({
      email: "ada@example.com",
      username: "ada",
      first_name: "Ada",
      last_name: "Lovelace",
    })
    expect(memberDetailLabel(member)).toBe("Ada Lovelace (ada@example.com)")
    expect(memberActionLabel(member)).toBe("Ada Lovelace (ada@example.com)")
    expect(memberSortLabel(member)).toBe("ada lovelace")
  })
})
