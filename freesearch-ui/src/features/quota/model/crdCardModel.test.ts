import { describe, expect, it } from "vitest"
import type { CRDUsageTotal, ProviderAuthLimits } from "@/domains/dashboard"
import {
  activeAuth,
  creditCardModel,
  operationAvailable,
  priceNoteRows,
} from "./crdCardModel"

/**
 * UI7 card model: one funds bar from the aggregate pool, exact USD
 * valuation, priced use from exact totals, shared pools counted once,
 * local ceilings kept separate. Covers UI7-02, UI7-03, UI7-06.
 */

function profile(overrides: Record<string, unknown> = {}) {
  return {
    reference_usd_per_crd: "0.001",
    native_usd_per_unit: "1",
    cost_basis: "priced_native_use",
    price_version: "v2026-09",
    source: "documented",
    estimated: false,
    ...overrides,
  }
}

function searchRecord() {
  return {
    provider: "brave",
    operation: "search",
    auth_mode: "keyed",
    supported: true,
    transport_available: true,
    native_pool_id: "brave:keyed:usd",
    rate: null,
    budget: null,
    conversion_profile: profile(),
    plan_name: "Brave Search",
    usage_url: "https://api-dashboard.search.brave.com/",
    version: 1,
  }
}

function fetchRecord() {
  return {
    provider: "brave",
    operation: "fetch",
    auth_mode: "keyed",
    supported: false,
    transport_available: false,
    native_pool_id: null,
    rate: null,
    budget: null,
    conversion_profile: profile({ native_usd_per_unit: null }),
    plan_name: null,
    usage_url: null,
    version: 1,
  }
}

function braveAuth(overrides: Partial<ProviderAuthLimits> = {}): ProviderAuthLimits {
  return {
    auth_mode: "keyed",
    transport_available: true,
    search: searchRecord(),
    fetch: fetchRecord(),
    free_tiers: [],
    paid_tiers: [],
    unknown_tiers: [],
    tier_split_known: true,
    aggregate_pool: {
      pool_id: "brave:keyed:usd",
      provider: "brave",
      auth_mode: "keyed",
      native_unit: "USD",
      remaining: "4.500",
      allowance: "5.000",
      actual_spend_usd: null,
      source: "vendor_headers",
      confidence: "observed",
      reset_at: "2026-10-01T00:00:00Z",
      observed_at: "2026-09-06T10:05:00Z",
      version: 1,
      credential_generation: 1,
      next_sync_at: null,
      stale: false,
      manual_anchor: false,
    },
    crd_views: [
      {
        state: "finite",
        operation: "search",
        remaining_crd: "4500",
        local_remaining_crd: null,
        request_cost_crd: "5",
        shared_pool_id: "brave:keyed:usd",
        possible_standard_calls: "900",
        price_version: "v2026-09",
        priced: true,
      },
      {
        state: "unavailable",
        operation: "fetch",
        remaining_crd: null,
        local_remaining_crd: null,
        request_cost_crd: null,
        shared_pool_id: null,
        possible_standard_calls: null,
        price_version: null,
        priced: false,
      },
    ],
    rate_progress: [],
    grants: null,
    detail: null,
    ...overrides,
  } as ProviderAuthLimits
}

describe("operationAvailable", () => {
  it("gates fetch on support and transport (UI7-04)", () => {
    const auth = braveAuth()
    expect(operationAvailable(auth, "search")).toBe(true)
    expect(operationAvailable(auth, "fetch")).toBe(false)
  })
})

describe("activeAuth", () => {
  it("prefers the active rail with fallback to the first", () => {
    const auth = braveAuth()
    const limits = {
      provider: "brave",
      active_auth_mode: "keyed",
      auths: [auth],
      documented_keyless_operations: [],
      version: 1,
      generated_at: "2026-09-06T10:05:00Z",
    }
    expect(activeAuth(limits as never)?.auth_mode).toBe("keyed")
  })
})

describe("creditCardModel", () => {
  it("derives 4500 CRD, 4.500 USD, and 90 percent from a USD 5 allowance (UI7-02, UI7-03)", () => {
    const model = creditCardModel({ auth: braveAuth(), usageTotals: [] })
    expect(model.state).toBe("finite")
    expect(model.remainingCRD).toBe("4500")
    expect(model.allowanceCRD).toBe("5000")
    expect(model.percentRemaining).toBe(90)
    expect(model.remainingUSD).toBe("4.500")
    expect(model.poolIds).toEqual(["brave:keyed:usd"])
  })

  it("derives 4495 CRD, 4.495 USD, and 89.9 percent after one 5-CRD debit (UI7-03)", () => {
    const auth = braveAuth({
      aggregate_pool: { ...(braveAuth().aggregate_pool as unknown as Record<string, unknown>), remaining: "4.495" } as never,
      crd_views: [
        {
          state: "finite",
          operation: "search",
          remaining_crd: "4495",
          local_remaining_crd: null,
          request_cost_crd: "5",
          shared_pool_id: "brave:keyed:usd",
          possible_standard_calls: "899",
          price_version: "v2026-09",
          priced: true,
        },
        {
          state: "unavailable",
          operation: "fetch",
          remaining_crd: null,
          local_remaining_crd: null,
          request_cost_crd: null,
          shared_pool_id: null,
          possible_standard_calls: null,
          price_version: null,
          priced: false,
        },
      ],
    })
    const model = creditCardModel({ auth, usageTotals: [] })
    expect(model.remainingCRD).toBe("4495")
    expect(model.remainingUSD).toBe("4.495")
    expect(model.percentRemaining).toBe(89.9)
  })

  it("values priced use from exact totals without float error (UI7-03)", () => {
    const totals: CRDUsageTotal[] = [
      { provider: "brave", operation: "search", normalized_crd: "5", attempt_count: 1, volume_count: 1 },
      { provider: "brave", operation: "search", normalized_crd: "6", attempt_count: 1, volume_count: 1 },
    ]
    const model = creditCardModel({ auth: braveAuth(), usageTotals: totals })
    expect(model.pricedUseUSD).toBe("0.011")
  })

  it("counts each shared pool once and never adds views (UI7-02)", () => {
    const auth = braveAuth({ aggregate_pool: null })
    const model = creditCardModel({ auth, usageTotals: [] })
    expect(model.remainingCRD).toBe("4500")
    expect(model.allowanceCRD).toBe(null)
    expect(model.percentRemaining).toBe(null)
    expect(model.poolIds).toEqual(["brave:keyed:usd"])
  })

  it("shows known funds without an invented allowance (UI7-02)", () => {
    const auth = braveAuth({ aggregate_pool: null })
    const model = creditCardModel({ auth, usageTotals: [] })
    expect(model.state).toBe("finite")
    expect(model.remainingCRD).toBe("4500")
    expect(model.percentRemaining).toBe(null)
  })

  it("reports unmetered without a fake bar or USD balance (UI7-02)", () => {
    const auth = braveAuth({
      aggregate_pool: null,
      crd_views: [
        {
          state: "unmetered",
          operation: "search",
          remaining_crd: null,
          local_remaining_crd: null,
          request_cost_crd: null,
          shared_pool_id: null,
          possible_standard_calls: null,
          price_version: null,
          priced: false,
        },
      ],
    })
    const model = creditCardModel({ auth, usageTotals: [] })
    expect(model.state).toBe("unmetered")
    expect(model.remainingCRD).toBe(null)
    expect(model.percentRemaining).toBe(null)
    expect(model.remainingUSD).toBe(null)
  })

  it("marks a manual anchor with Estimated and Balance entry (UI7-07)", () => {
    const auth = braveAuth({
      aggregate_pool: { ...(braveAuth().aggregate_pool as unknown as Record<string, unknown>), manual_anchor: true } as never,
    })
    const model = creditCardModel({ auth, usageTotals: [] })
    expect(model.provenanceNote).toBe("Estimated · Balance entry")
  })
})

describe("priceNoteRows", () => {
  it("lists Brave search at 0.005 USD and 5 CRD with no fetch row (UI7-04, UI7-06)", () => {
    const limits = {
      provider: "brave",
      active_auth_mode: "keyed",
      auths: [braveAuth()],
      documented_keyless_operations: [],
      version: 1,
      generated_at: "2026-09-06T10:05:00Z",
    }
    const rows = priceNoteRows({
      providers: [{ id: "brave", name: "Brave" }] as never,
      providerLimits: [limits] as never,
    })
    expect(rows).toHaveLength(1)
    expect(rows[0].provider).toBe("brave")
    expect(rows[0].operation).toBe("search")
    expect(rows[0].usdPerCall).toBe("0.005")
    expect(rows[0].crdPerCall).toBe("5 CRD")
    expect(rows[0].priceVersion).toBe("v2026-09")
  })
})

describe("polish provenance (Item 4+5)", () => {
  it("marks a manual anchor as Estimated · Balance entry while keeping exact amounts", () => {
    const auth = braveAuth({
      aggregate_pool: { ...(braveAuth().aggregate_pool as unknown as Record<string, unknown>), manual_anchor: true } as never,
    })
    const totals: CRDUsageTotal[] = [
      { provider: "brave", operation: "search", normalized_crd: "5", attempt_count: 1, volume_count: 1 },
      { provider: "brave", operation: "search", normalized_crd: "6", attempt_count: 1, volume_count: 1 },
    ]
    const model = creditCardModel({ auth, usageTotals: totals })
    expect(model.provenanceNote).toBe("Estimated · Balance entry")
    expect(model.remainingUSD).toBe("4.500")
    expect(model.pricedUseUSD).toBe("0.011")
  })

  it("shows Vendor headers provenance for a vendor pool while keeping exact amounts", () => {
    const totals: CRDUsageTotal[] = [
      { provider: "brave", operation: "search", normalized_crd: "5", attempt_count: 1, volume_count: 1 },
      { provider: "brave", operation: "search", normalized_crd: "6", attempt_count: 1, volume_count: 1 },
    ]
    const model = creditCardModel({ auth: braveAuth(), usageTotals: totals })
    expect(model.provenanceNote).toContain("Vendor headers")
    expect(model.provenanceNote as string).not.toContain("vendor_headers")
    expect(model.remainingUSD).toBe("4.500")
    expect(model.pricedUseUSD).toBe("0.011")
  })
})
