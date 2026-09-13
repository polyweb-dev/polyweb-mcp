import { describe, expect, it } from "vitest"
import { DEFAULT_PROVIDERS } from "@/test/defaultProviders"
import type { ProviderConfig } from "@/domains/providers"
import { getEligibleProviders } from "./routingUtils"

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
