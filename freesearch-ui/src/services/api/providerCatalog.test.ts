import { describe, it, expect } from "vitest"
import { PROVIDER_CATALOG } from "./providerCatalog"
import type { Capability } from "@/types/freesearch"

/**
 * RED: `src/services/api/providerCatalog.ts` does not exist yet. The
 * Developer creates `StaticProviderMeta` + `PROVIDER_CATALOG` with exactly
 * the 7 entries below (UI ids; youcom maps to backend id "you").
 */
describe("PROVIDER_CATALOG", () => {
  const expected: Array<{ id: string; backendId: string; capabilities: Capability[] }> = [
    { id: "brave", backendId: "brave", capabilities: ["search"] },
    { id: "keenable", backendId: "keenable", capabilities: ["search", "fetch", "keyless_tier"] },
    { id: "tavily", backendId: "tavily", capabilities: ["search", "fetch", "extract"] },
    { id: "exa", backendId: "exa", capabilities: ["search", "fetch", "neural_search"] },
    {
      id: "firecrawl",
      backendId: "firecrawl",
      capabilities: ["search", "fetch", "live_crawl"],
    },
    {
      id: "youcom",
      backendId: "you",
      capabilities: ["search", "fetch", "live_crawl"],
    },
    { id: "parallel", backendId: "parallel", capabilities: ["search", "extract", "fetch"] },
  ]

  it("contains exactly 7 static entries", () => {
    expect(PROVIDER_CATALOG).toHaveLength(7)
  })

  it("uses the pinned UI ids in registry order", () => {
    expect(PROVIDER_CATALOG.map((entry) => entry.id)).toEqual(
      expected.map((entry) => entry.id)
    )
  })

  it("maps youcom to backend id 'you' and every other id to itself", () => {
    for (const entry of expected) {
      const actual = PROVIDER_CATALOG.find((candidate) => candidate.id === entry.id)!
      expect(actual.backendId).toBe(entry.backendId)
    }
  })

  it("pins the exact capability set per provider", () => {
    for (const entry of expected) {
      const actual = PROVIDER_CATALOG.find((candidate) => candidate.id === entry.id)!
      expect([...actual.capabilities].sort()).toEqual([...entry.capabilities].sort())
    }
  })

  it("exposes static display metadata with no backend-dependent state", () => {
    for (const entry of PROVIDER_CATALOG) {
      expect(typeof entry.name).toBe("string")
      expect(entry.name.length).toBeGreaterThan(0)
      expect(typeof entry.description).toBe("string")
      expect(entry.description.length).toBeGreaterThan(0)
      expect(entry.baseUrl).toMatch(/^https:\/\//)
      expect(typeof entry.authHeaderName).toBe("string")
      expect(entry.authHeaderName.length).toBeGreaterThan(0)
    }
  })

  it("never invents providers beyond the canonical seven", () => {
    const ids = new Set(PROVIDER_CATALOG.map((entry) => entry.id))
    expect(ids.size).toBe(7)
    for (const extra of ["google", "bing", "openai", "custom"]) {
      expect(ids.has(extra)).toBe(false)
    }
  })
})
