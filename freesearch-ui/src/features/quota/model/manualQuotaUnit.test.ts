import { describe, expect, it } from "vitest"
import type { NativePool, ProviderAuthLimits } from "@/domains/dashboard"
import { manualUnit } from "./manualQuotaUnit"

function auth(unit: NativePool["native_unit"]): ProviderAuthLimits {
  return {
    auth_mode: "keyed", transport_available: true, search: null, fetch: null,
    free_tiers: [], paid_tiers: [], unknown_tiers: [], tier_split_known: false,
    crd_views: [], rate_progress: [], grants: null, detail: null,
    aggregate_pool: {
      pool_id: "provider:pool", provider: "provider", auth_mode: "keyed", native_unit: unit,
      remaining: "1000", allowance: "2000", actual_spend_usd: null, source: "vendor_api",
      confidence: "observed", reset_at: null, observed_at: null, version: 1,
      credential_generation: 1, next_sync_at: null, stale: false, manual_anchor: false,
    },
  }
}

describe("manual quota units", () => {
  it.each(["tavily", "firecrawl", "custom"])("labels %s native credits in words", (provider) => {
    expect(manualUnit(auth("CREDIT"), provider)).toEqual({
      unitKind: "CREDIT", displayUnit: "credits", amountMode: "usage",
    })
  })

  it("keeps dollar entries in USD balance mode", () => {
    expect(manualUnit(auth("USD"), "exa")).toEqual({
      unitKind: "USD", displayUnit: "USD", amountMode: "balance",
    })
  })

  it("does not treat a legacy ledger unit as native credits", () => {
    expect(manualUnit(auth("CRD"), "brave")).toEqual({
      unitKind: null, displayUnit: null, amountMode: "usage",
    })
  })

  it("labels free units as Free", () => {
    expect(manualUnit(auth("FREE"), "keenable").displayUnit).toBe("Free")
  })
})
