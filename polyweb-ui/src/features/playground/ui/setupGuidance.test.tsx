import { describe, expect, it } from "vitest"
import { pinnedProviderName } from "./setupGuidance"

function providerStub(id: string, name: string) {
  return { id, name, available: true, enabled: true, effectiveOperations: ["search" as const] }
}

function scopeOf(overrides: { selectedProviderId?: string; eligibleProviders?: ReturnType<typeof providerStub>[] } = {}) {
  return {
    selectedProviderId: "auto",
    eligibleProviders: [],
    ...overrides,
  }
}

describe("pinnedProviderName (TASK-000065 AC#7/AC#8)", () => {
  it("stays unscoped for auto/all runs", () => {
    expect(pinnedProviderName(scopeOf())).toBeUndefined()
    expect(pinnedProviderName(scopeOf({ selectedProviderId: "all" }))).toBeUndefined()
  })

  it("names the pinned eligible provider", () => {
    expect(pinnedProviderName(scopeOf({
      selectedProviderId: "keenable",
      eligibleProviders: [providerStub("keenable", "Keenable"), providerStub("tavily", "Tavily")],
    }))).toBe("Keenable")
  })

  it("stays unscoped when the pinned provider is no longer eligible", () => {
    expect(pinnedProviderName(scopeOf({
      selectedProviderId: "keenable",
      eligibleProviders: [providerStub("tavily", "Tavily")],
    }))).toBeUndefined()
  })
})
