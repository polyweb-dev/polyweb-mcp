import { describe, expect, it } from "vitest"
import { DEFAULT_PROVIDERS } from "@/test/defaultProviders"
import type { ProviderConfig } from "@/domains/providers"
import type { RoutingPreset } from "@/domains/routing"
import { getEligibleProviders, getProviderReason } from "./routingUtils"

describe("routingUtils.test.ts", () => {

const seedProviders = (): ProviderConfig[] =>
  DEFAULT_PROVIDERS.map((provider) => ({
    ...provider,
    capabilities: [...provider.capabilities],
    quota: { ...provider.quota },
  }))

const idsFor = (providers: ProviderConfig[], operation: "search" | "fetch", preset: RoutingPreset) =>
  (getEligibleProviders(providers, operation, preset) as ProviderConfig[]).map(
    (provider: ProviderConfig) => provider.id
  )

describe("getEligibleProviders", () => {
  it("filters global and capability state for strict-priority search", () => {
    expect(idsFor(seedProviders(), "search", "priority")).toEqual([
      "brave",
      "keenable",
      "tavily",
      "exa",
      "firecrawl",
      "youcom",
    ])
  })

  it("filters fetch to providers with the fetch capability and operation enabled", () => {
    expect(idsFor(seedProviders(), "fetch", "priority")).toEqual([
      "keenable",
      "tavily",
      "exa",
      "firecrawl",
      "youcom",
    ])
  })

  it.each([
    ["cost_optimized", ["keenable", "brave", "tavily", "exa", "firecrawl", "youcom"]],
    ["latency_optimized", ["brave", "keenable", "tavily", "exa", "youcom", "firecrawl"]],
    ["quality_first", ["exa", "brave", "keenable", "tavily", "firecrawl", "youcom"]],
    ["round_robin", ["brave", "keenable", "tavily", "exa", "firecrawl", "youcom"]],
  ] as const)("sorts eligible providers for the %s preset", (preset, expected) => {
    expect(idsFor(seedProviders(), "search", preset)).toEqual(expected)
  })

  it("excludes circuit-open providers even when globally and operationally enabled", () => {
    const providers = seedProviders().map((provider) =>
      provider.id === "brave" ? { ...provider, circuitBreaker: "open" as const } : provider
    )

    expect(idsFor(providers, "search", "priority")).not.toContain("brave")
    expect(idsFor(providers, "search", "priority")).toEqual([
      "keenable",
      "tavily",
      "exa",
      "firecrawl",
      "youcom",
    ])
  })

  it("gates disabled operation flags independently from capability support", () => {
    const providers = seedProviders().map((provider) => {
      if (provider.id === "tavily") return { ...provider, searchEnabled: false }
      if (provider.id === "keenable") return { ...provider, fetchEnabled: false }
      return provider
    })

    expect(idsFor(providers, "search", "priority")).not.toContain("tavily")
    expect(idsFor(providers, "fetch", "priority")).not.toContain("keenable")
  })

  it("excludes a provider when global routing is disabled", () => {
    const providers = seedProviders().map((provider) =>
      provider.id === "brave" ? { ...provider, globalEnabled: false } : provider
    )

    expect(idsFor(providers, "search", "priority")).not.toContain("brave")
  })

  it("excludes providers with missing keys unless they support keyless tier", () => {
    const providers = seedProviders().map((provider) =>
      provider.id === "exa" ? { ...provider, hasKey: false } : provider
    )

    expect(idsFor(providers, "search", "priority")).not.toContain("exa")
    expect(idsFor(providers, "search", "priority")).toContain("keenable")
  })
})

describe("getProviderReason", () => {
  it("explains the selected provider for each routing preset", () => {
    const providers = seedProviders()
    const brave = providers.find((provider) => provider.id === "brave")!
    const keenable = providers.find((provider) => provider.id === "keenable")!
    const exa = providers.find((provider) => provider.id === "exa")!

    expect(getProviderReason(brave, 0, "priority")).toBe("Configured as top priority (P1)")
    expect(getProviderReason(keenable, 0, "cost_optimized")).toBe(
      "Ranked #1 for keyless free tier"
    )
    expect(getProviderReason(brave, 0, "latency_optimized")).toBe(
      "Fastest p95 roundtrip (145ms)"
    )
    expect(getProviderReason(exa, 0, "quality_first")).toBe("Top neural quality score")
  })

  it("uses the priority reason for quality-first fetch providers without neural search", () => {
    const keenable = seedProviders().find((provider) => provider.id === "keenable")!
    const reason = getProviderReason(keenable, 0, "quality_first")

    expect(reason).toBe("Configured as top priority (P2)")
    expect(reason).not.toContain("neural")
  })

  it("describes non-primary providers as ordered fallbacks", () => {
    const tavily = seedProviders().find((provider) => provider.id === "tavily")!
    expect(getProviderReason(tavily, 2, "priority")).toBe(
      "Fallback #2: Ready if prior provider fails"
    )
  })
})
})

describe("routingUtils.parallel-fetch.test.ts", () => {

/**
 * S1 — Parallel fetch eligibility (BDD Acceptance, RED phase).
 *
 * FINAL REVIEW PLAN (RTC consensus):
 *   Parallel catalog becomes ["search","extract","fetch"] (keep "extract");
 *   both parallel/extract special-cases in routingUtils + SearchPlayground are
 *   deleted in favor of a plain `capabilities.includes("fetch")` check.
 *
 * This focused test locks the BEHAVIORAL end-state without touching the
 * shared `defaultProviders.ts` global-disable fixture (Parallel stays
 * globally disabled there by design — runtime state comes from the backend).
 * The Parallel row under test is constructed inline as globally enabled +
 * fetch-enabled with the post-fix catalog capabilities.
 *
 * AC mapping:
 *   S1-d  an explicitly enabled Parallel row with ["search","extract","fetch"]
 *         is eligible for "fetch" (plain includes("fetch") path);
 *   S1-e  Brave (search-only) stays fetch-incapable everywhere.
 */

function enabledParallelRow(): ProviderConfig {
  const template = DEFAULT_PROVIDERS.find((p) => p.id === "parallel")!
  return {
    ...template,
    capabilities: ["search", "extract", "fetch"],
    globalEnabled: true,
    searchEnabled: true,
    fetchEnabled: true,
    circuitBreaker: "closed",
    priority: template.priority,
    quota: { ...template.quota },
  }
}

function providersWithEnabledParallel(): ProviderConfig[] {
  return DEFAULT_PROVIDERS.map((p) =>
    p.id === "parallel"
      ? enabledParallelRow()
      : { ...p, capabilities: [...p.capabilities], quota: { ...p.quota } }
  )
}

describe("S1: Parallel fetch eligibility (plain includes fetch)", () => {
  it("contains an explicitly enabled Parallel row for fetch", () => {
    const ids = getEligibleProviders(providersWithEnabledParallel(), "fetch", "priority").map(
      (p) => p.id
    )
    expect(ids).toContain("parallel")
  })

  it("keeps Brave absent from fetch eligibility", () => {
    const ids = getEligibleProviders(providersWithEnabledParallel(), "fetch", "priority").map(
      (p) => p.id
    )
    expect(ids).not.toContain("brave")
    // Brave is search-only in the pinned catalog: no fetch capability, ever.
    const brave = providersWithEnabledParallel().find((p) => p.id === "brave")!
    expect(brave.capabilities).toEqual(["search"])
  })

  it("resolves fetch eligibility through the plain fetch capability (no extract fallback needed)", () => {
    // A Parallel row carrying ONLY ["search","fetch"] (extract stripped) must
    // still be eligible — proving the plain includes("fetch") path, not the
    // legacy `id === "parallel" && includes("extract")` special-case.
    const base = providersWithEnabledParallel()
    const stripped = base.map((p) =>
      p.id === "parallel"
        ? { ...p, capabilities: ["search", "fetch"] as ProviderConfig["capabilities"] }
        : p
    )
    const ids = getEligibleProviders(stripped, "fetch", "priority").map((p) => p.id)
    expect(ids).toContain("parallel")
  })
})
})
