import { describe, expect, it } from "vitest"
import { apiKeyFixture } from "@/test/accessFixtures"
import {
  canRotateKey,
  creatorLabel,
  expiresLabel,
  formatKeyDate,
  lastUsedLabel,
  scopesLabel,
  sortNewestFirst,
  statusLabel,
} from "./apiKeyView"

describe("sortNewestFirst", () => {
  it("orders keys by creation time, newest first, without mutating the input", () => {
    const older = apiKeyFixture({ id: "a", created_at: "2026-10-01T00:00:00Z" })
    const newer = apiKeyFixture({ id: "b", created_at: "2026-10-05T00:00:00Z" })
    const input = [older, newer]
    expect(sortNewestFirst(input).map((key) => key.id)).toEqual(["b", "a"])
    expect(input.map((key) => key.id)).toEqual(["a", "b"])
  })
})

describe("column labels", () => {
  it("shows No expiration for a null expiry and a date otherwise", () => {
    expect(expiresLabel(apiKeyFixture({ expires_at: null }))).toBe("No expiration")
    expect(expiresLabel(apiKeyFixture({ expires_at: "2027-01-01T12:00:00Z" }))).toBe(
      formatKeyDate("2027-01-01T12:00:00Z")
    )
  })

  it("shows Never for a key that was never used", () => {
    expect(lastUsedLabel(apiKeyFixture({ last_used_at: null }))).toBe("Never")
    expect(lastUsedLabel(apiKeyFixture({ last_used_at: "2026-10-03T08:00:00Z" }))).toMatch(/2026/)
  })

  it("labels every status", () => {
    expect(statusLabel("active")).toBe("Active")
    expect(statusLabel("expired")).toBe("Expired")
    expect(statusLabel("revoked")).toBe("Revoked")
  })

  it("labels known scopes and keeps unknown ones verbatim", () => {
    expect(scopesLabel(["search.execute", "fetch.execute"])).toBe("Search, Fetch")
    expect(scopesLabel(["fetch.execute", "search.execute", "future.scope"])).toBe("Search, Fetch, future.scope")
    expect(scopesLabel(["future.scope"])).toBe("future.scope")
  })

  it("returns unparsable dates verbatim", () => {
    expect(formatKeyDate("not-a-date")).toBe("not-a-date")
  })
})

describe("creatorLabel", () => {
  const creator = "11111111-1111-4111-8111-111111111111"

  it("shows the member email when the member list is readable", () => {
    expect(creatorLabel(creator, new Map([[creator, "lead@example.com"]]))).toBe("lead@example.com")
  })

  it("shows a short id without the member list or for a former member", () => {
    expect(creatorLabel(creator, null)).toBe("11111111")
    expect(creatorLabel(creator, new Map())).toBe("11111111")
  })
})

describe("canRotateKey", () => {
  it("allows an active key without a successor only", () => {
    const active = apiKeyFixture({ id: "old" })
    const successor = apiKeyFixture({ id: "new", rotated_from_id: "old" })
    expect(canRotateKey(active, [active])).toBe(true)
    expect(canRotateKey(active, [active, successor])).toBe(false)
    expect(canRotateKey(successor, [active, successor])).toBe(true)
    expect(canRotateKey(apiKeyFixture({ status: "revoked" }), [])).toBe(false)
    expect(canRotateKey(apiKeyFixture({ status: "expired" }), [])).toBe(false)
  })
})
