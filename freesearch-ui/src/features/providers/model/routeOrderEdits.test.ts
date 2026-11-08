import { describe, expect, it } from "vitest"
import type { ProviderTypeView, RouteEntry } from "@/domains/providers"
import { defaultRouteLabel, nextPriority } from "./routeOrderEdits"

const PROVIDER: ProviderTypeView = {
  providerType: "tavily", name: "Tavily", keyless: false, capability: ["search", "fetch"], killSwitch: false,
  systemEnabledOperations: ["search", "fetch"], available: true, enabled: true, credentials: [], effectiveOperations: [],
  bindings: [
    { id: "b1", credentialId: "own", routeLabel: "tavily", priority: 1, enabledOperations: [], effectiveOperations: [] },
    { id: "b2", credentialId: "own", routeLabel: "tavily-2", priority: 2, enabledOperations: [], effectiveOperations: [] },
  ],
}

function routes(priorities: number[]): RouteEntry[] {
  return priorities.map((priority, index) => ({
    binding: { id: `r${index}`, credentialId: "own", routeLabel: `r${index}`, priority, enabledOperations: [], effectiveOperations: [] },
    provider: PROVIDER,
    credential: null,
  }))
}

describe("nextPriority", () => {
  it("places a new route after the last one", () => {
    expect(nextPriority([])).toBe(10)
    expect(nextPriority(routes([1, 6, 50]))).toBe(60)
    expect(nextPriority(routes([999_995]))).toBe(1_000_000)
  })
})

describe("defaultRouteLabel", () => {
  it("uses the provider type, then the first free number on the same key", () => {
    expect(defaultRouteLabel(PROVIDER, "other")).toBe("tavily")
    expect(defaultRouteLabel(PROVIDER, "own")).toBe("tavily-3")
  })
})
