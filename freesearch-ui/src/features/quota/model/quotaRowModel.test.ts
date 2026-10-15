import { describe, expect, it } from "vitest"
import type { ProviderConfig } from "@/domains/providers"
import type { DashboardQuota } from "@/domains/dashboard"
import { isManualQuotaEligible } from "./quotaEligibility"
import { manualBudgetMissing, manualEligibleProviders, resolveQuotaRow } from "./quotaRowModel"

function quotaProvider(id: string): ProviderConfig {
  return {
    id,
    name: id,
    description: "test",
    baseUrl: "https://api.test",
    isCustom: false,
    capabilities: ["search", "fetch"],
    enableMask: 7,
    supportMask: id === "brave" ? 3 : 7,
    globalEnabled: true,
    searchEnabled: true,
    fetchEnabled: true,
    priority: 2,
    healthStatus: "healthy",
    circuitBreaker: "closed",
    consecutiveFailures: 0,
    latencyP95Ms: 120,
    hasKey: true,
    keyMasked: "",
    keyVaultStatus: "configured",
    quota: {
      used: null,
      limit: null,
      unit: "units",
      confidence: "estimated",
      resetPeriod: "monthly",
      nextReset: null,
      remaining: null,
      remainingPercent: null,
      unitKind: "USD",
      displayUnit: "USD",
      observedAt: null,
      window: "monthly",
    },
  }
}

function snapshot(
  provider: string,
  overrides: Partial<DashboardQuota> = {}
): DashboardQuota {
  return {
    provider,
    remaining: null,
    remainingPercent: null,
    limit: null,
    observed_at: "2026-09-11T12:00:00Z",
    source: "estimated",
    unitKind: "USD",
    displayUnit: "USD",
    resetAt: null,
    window: null,
    ...overrides,
  }
}

/**
 * Slice 2.2 characterization: row-level budget/pairing decisions.
 * Locks the no-snapshot predicate shared with quotaCaptionFor and the
 * authoritative remaining-only pairing evidence used by OAuth slots.
 */
describe("manualBudgetMissing", () => {
  it("offers Manual Entry for Exa only while no vendor budget exists", () => {
    expect(manualBudgetMissing(quotaProvider("exa"), undefined, null)).toBe(true)
    // Parallel stays out: its prepaid USD balance comes from the OAuth Account
    // API (AUTHORITATIVE snapshot), never from a manual seed.
    expect(manualBudgetMissing(quotaProvider("parallel"), snapshot("parallel"), null)).toBe(false)
    expect(manualBudgetMissing(quotaProvider("parallel"), undefined, null)).toBe(false)
  })

  it("stops offering Manual Entry once a snapshot or percentage exists", () => {
    expect(
      manualBudgetMissing(
        quotaProvider("parallel"),
        snapshot("parallel", { remaining: "3.75", limit: "5.00" }),
        null
      )
    ).toBe(false)
    expect(manualBudgetMissing(quotaProvider("exa"), snapshot("exa"), 75)).toBe(false)
  })

  it("offers Tinyfish Manual Entry only without a vendor snapshot or percentage", () => {
    const provider = quotaProvider("tinyfish")
    expect(manualBudgetMissing(provider, undefined, null)).toBe(true)
    expect(manualBudgetMissing(provider, snapshot("tinyfish"), null)).toBe(true)
    expect(manualBudgetMissing(provider, snapshot("tinyfish"), 75)).toBe(false)
    expect(manualBudgetMissing(provider, snapshot("tinyfish", { remaining: "750", limit: "1000" }), null)).toBe(false)
    expect(manualBudgetMissing(provider, snapshot("tinyfish", { remaining: "750" }), null)).toBe(false)
  })

  it("never treats other providers as budget-missing", () => {
    expect(manualBudgetMissing(quotaProvider("firecrawl"), undefined, null)).toBe(false)
    expect(manualBudgetMissing(quotaProvider("tavily"), snapshot("tavily"), null)).toBe(false)
  })
})

describe("manualEligibleProviders", () => {
  it("keeps Exa's balance correction action for a local estimate", () => {
    const eligible = manualEligibleProviders(
      [quotaProvider("exa"), quotaProvider("parallel")],
      [
        snapshot("exa", { remaining: "4.500", remainingPercent: "45", limit: "10.000" }),
        snapshot("parallel", { remaining: "4.500", remainingPercent: "90", limit: "5.000" }),
      ],
      isManualQuotaEligible,
    )
    expect(eligible).toEqual(new Set(["exa"]))
  })
})

describe("resolveQuotaRow", () => {
  it("treats any vendor remaining balance as a usable estimate", () => {
    const row = resolveQuotaRow(
      quotaProvider("parallel"),
      snapshot("parallel", { remaining: "3.75", source: "authoritative" }),
      null,
      null
    )
    expect(row.hasUsableEstimate).toBe(true)
    expect(row.pairedSnapshot).toBe(true)
  })

  it("counts a vendor percent or manual estimate as usable without pairing evidence", () => {
    const percentRow = resolveQuotaRow(quotaProvider("brave"), snapshot("brave"), 95, null)
    expect(percentRow.hasUsableEstimate).toBe(true)
    expect(percentRow.pairedSnapshot).toBe(false)
    const manualRow = resolveQuotaRow(quotaProvider("exa"), undefined, null, {
      percentText: "80.0% remaining",
      rangeText: "Manual Entry range",
      percent: 80,
    })
    expect(manualRow.hasUsableEstimate).toBe(true)
  })

  it("reports no estimate and no pairing for an empty snapshot", () => {
    const row = resolveQuotaRow(quotaProvider("parallel"), snapshot("parallel"), null, null)
    expect(row.hasUsableEstimate).toBe(false)
    expect(row.pairedSnapshot).toBe(false)
  })

  it("reserves pairing evidence for authoritative Parallel balances", () => {
    const estimated = resolveQuotaRow(
      quotaProvider("parallel"),
      snapshot("parallel", { remaining: "3.75", source: "estimated" }),
      null,
      null
    )
    expect(estimated.pairedSnapshot).toBe(false)
    const otherProvider = resolveQuotaRow(
      quotaProvider("youcom"),
      snapshot("youcom", { remaining: "199.77", source: "authoritative" }),
      null,
      null
    )
    expect(otherProvider.pairedSnapshot).toBe(false)
  })
})
