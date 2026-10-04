import { describe, expect, it } from "vitest"
import { providerIdentity } from "./providerIdentity"

/**
 * providerIdentity (PLAN §4 R5): any provider id the UI receives resolves to
 * the one identity it shows — the canonical UI id plus the catalog name. An
 * unknown id keeps its own text; an empty id stays empty.
 */
describe("providerIdentity", () => {
  it("maps the wire id you to the canonical youcom identity", () => {
    expect(providerIdentity("you")).toEqual({ id: "youcom", name: "You.com" })
  })

  it("keeps the canonical youcom identity stable", () => {
    expect(providerIdentity("youcom")).toEqual({ id: "youcom", name: "You.com" })
  })

  it.each([
    ["brave", "Brave Search"],
    ["keenable", "Keenable"],
    ["tavily", "Tavily"],
    ["exa", "Exa"],
    ["firecrawl", "Firecrawl"],
    ["parallel", "Parallel"],
  ])("resolves the catalog label for %s", (providerId, name) => {
    expect(providerIdentity(providerId)).toEqual({ id: providerId, name })
  })

  it("keeps an unknown provider id as its own text", () => {
    expect(providerIdentity("acme-search")).toEqual({
      id: "acme-search",
      name: "acme-search",
    })
  })

  it("returns an empty identity for an empty id", () => {
    expect(providerIdentity("")).toEqual({ id: "", name: "" })
  })

  it("returns an empty identity for a whitespace-only id", () => {
    expect(providerIdentity("   ")).toEqual({ id: "", name: "" })
  })

  it("trims surrounding whitespace before resolving", () => {
    expect(providerIdentity("  tavily  ")).toEqual({ id: "tavily", name: "Tavily" })
  })
})
