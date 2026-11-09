import { describe, expect, it } from "vitest"
import type { ProviderTypeView } from "@/domains/providers"
import type { ProjectOrder } from "@/domains/routing"
import { projectOrderProviders } from "./projectOrderProviders"

function provider(providerType: string, systemEnabledOperations: ("search" | "fetch")[]): ProviderTypeView {
  return {
    providerType, name: providerType, keyless: false, capability: ["search", "fetch"],
    killSwitch: false, systemEnabledOperations,
    credentials: [], bindings: [], effectiveOperations: [],
  }
}

describe("projectOrderProviders", () => {
  it("uses the two orders, system switches and pool eligibility instead of legacy bindings", () => {
    const item = (id: string) => ({ provider: id, name: id, callCostUsd: null, keyless: false })
    const order: ProjectOrder = {
      revision: 1,
      search: { strategy: "custom", hasSavedCustom: true, notAllowed: ["keenable"], providers: [
        item("you"), item("keenable"), item("exa"),
      ] },
      fetch: { strategy: "custom", hasSavedCustom: true, notAllowed: [], providers: [
        item("exa"), item("keenable"), item("you"),
      ] },
    }
    const result = projectOrderProviders(order, [
      provider("you", ["search", "fetch"]), provider("keenable", ["search", "fetch"]),
      provider("exa", ["fetch"]),
    ])
    expect(result.byOperation.search.map((entry) => entry.id)).toEqual(["youcom"])
    expect(result.byOperation.fetch.map((entry) => entry.id)).toEqual(["exa", "keenable", "youcom"])
    expect(result.providers.find((entry) => entry.id === "youcom")?.effectiveOperations).toEqual(["search", "fetch"])
  })
})
