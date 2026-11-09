import { describe, expect, it } from "vitest"
import type { UsdUsageTotal, ProviderAuthLimits, ProviderLimits } from "@/domains/dashboard"
import {
  activeAuth,
  creditCardModel,
  operationAvailable,
  priceNoteRows,
} from "./usdCardModel"

/**
 * UI7 card model: one funds bar from the aggregate pool, exact USD
 * valuation, priced use from exact totals, shared pools counted once,
 * local ceilings kept separate. Covers UI7-02, UI7-03, UI7-06.
 */

function profile(overrides: Record<string, unknown> = {}) {
  return {
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
    usd_views: [
      {
        state: "finite",
        operation: "search",
        remaining_usd: "4.5",
        local_remaining_usd: null,
        request_cost_usd: "0.005",
        shared_pool_id: "brave:keyed:usd",
        possible_standard_calls: "900",
        price_version: "v2026-09",
        priced: true,
      },
      {
        state: "unavailable",
        operation: "fetch",
        remaining_usd: null,
        local_remaining_usd: null,
        request_cost_usd: null,
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
  it.each([
    ["tavily", "keyed"],
    ["tavily", "keyless"],
    ["keenable", "keyed"],
    ["keenable", "keyless"],
  ] as const)(
    "%s selects the backend-reported %s rail when both modes are available",
    (provider, activeAuthMode) => {
      const keyed = braveAuth()
      const keyless = braveAuth({ auth_mode: "keyless" })
      const limits: ProviderLimits = {
        provider,
        active_auth_mode: activeAuthMode,
        auths: [keyed, keyless],
        documented_keyless_operations: [],
        version: 1,
        generated_at: "2026-09-06T10:05:00Z",
      }
      expect(activeAuth(limits)).toBe(activeAuthMode === "keyed" ? keyed : keyless)
    },
  )

  it("falls back to the first reported rail if the active mode is absent", () => {
    const auth = braveAuth()
    const limits: ProviderLimits = {
      provider: "keenable",
      active_auth_mode: "keyless",
      auths: [auth],
      documented_keyless_operations: [],
      version: 1,
      generated_at: "2026-09-06T10:05:00Z",
    }
    expect(activeAuth(limits)).toBe(auth)
  })
})

describe("creditCardModel", () => {
  it("derives 4500 Usd, 4.500 USD, and 90 percent from a USD 5 allowance (UI7-02, UI7-03)", () => {
    const model = creditCardModel({ auth: braveAuth(), usageTotals: [] })
    expect(model.state).toBe("finite")
    expect(model.remainingUsd).toBe("4.500")
    expect(model.allowanceUsd).toBe("5.000")
    expect(model.percentRemaining).toBe(90)

    expect(model.poolIds).toEqual(["brave:keyed:usd"])
  })

  it("derives 4495 Usd, 4.495 USD, and 89.9 percent after one 5-Usd debit (UI7-03)", () => {
    const auth = braveAuth({
      aggregate_pool: { ...(braveAuth().aggregate_pool as unknown as Record<string, unknown>), remaining: "4.495" } as never,
      usd_views: [
        {
          state: "finite",
          operation: "search",
          remaining_usd: "4.495",
          local_remaining_usd: null,
          request_cost_usd: "0.005",
          shared_pool_id: "brave:keyed:usd",
          possible_standard_calls: "899",
          price_version: "v2026-09",
          priced: true,
        },
        {
          state: "unavailable",
          operation: "fetch",
          remaining_usd: null,
          local_remaining_usd: null,
          request_cost_usd: null,
          shared_pool_id: null,
          possible_standard_calls: null,
          price_version: null,
          priced: false,
        },
      ],
    })
    const model = creditCardModel({ auth, usageTotals: [] })
    expect(model.remainingUsd).toBe("4.495")

    expect(model.percentRemaining).toBe(89.9)
  })

  it("values priced use from exact totals without float error (UI7-03)", () => {
    const totals: UsdUsageTotal[] = [
      { provider: "brave", operation: "search", spend_usd: "0.005", attempt_count: 1, volume_count: 1 },
      { provider: "brave", operation: "search", spend_usd: "0.006", attempt_count: 1, volume_count: 1 },
    ]
    const model = creditCardModel({ auth: braveAuth(), usageTotals: totals })
    expect(model.pricedUseUsd).toBe("0.011")
  })

  it("counts each shared pool once and never adds views (UI7-02)", () => {
    const auth = braveAuth({ aggregate_pool: null })
    const model = creditCardModel({ auth, usageTotals: [] })
    expect(model.remainingUsd).toBe("4.5")
    expect(model.allowanceUsd).toBe(null)
    expect(model.percentRemaining).toBe(null)
    expect(model.poolIds).toEqual(["brave:keyed:usd"])
  })

  it("shows known funds without an invented allowance (UI7-02)", () => {
    const auth = braveAuth({ aggregate_pool: null })
    const model = creditCardModel({ auth, usageTotals: [] })
    expect(model.state).toBe("finite")
    expect(model.remainingUsd).toBe("4.5")
    expect(model.percentRemaining).toBe(null)
  })

  it("reports unmetered without a fake bar or USD balance (UI7-02)", () => {
    const auth = braveAuth({
      aggregate_pool: null,
      usd_views: [
        {
          state: "unmetered",
          operation: "search",
          remaining_usd: null,
          local_remaining_usd: null,
          request_cost_usd: null,
          shared_pool_id: null,
          possible_standard_calls: null,
          price_version: null,
          priced: false,
        },
      ],
    })
    const model = creditCardModel({ auth, usageTotals: [] })
    expect(model.state).toBe("unmetered")
    expect(model.remainingUsd).toBe(null)
    expect(model.percentRemaining).toBe(null)

  })

  it("marks a manual anchor with Estimated and Balance entry (UI7-07)", () => {
    const auth = braveAuth({
      aggregate_pool: { ...(braveAuth().aggregate_pool as unknown as Record<string, unknown>), manual_anchor: true } as never,
    })
    const model = creditCardModel({ auth, usageTotals: [] })
    expect(model.provenanceNote).toBe("Estimated · Provider balance")
  })
})

describe("priceNoteRows", () => {
  it("lists Brave search at 0.005 USD and 5 Usd with no fetch row (UI7-04, UI7-06)", () => {
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
    expect(rows[0].usdPerCall).toBe("$0.0050")
    expect(rows[0].usdPerCall).toBe("$0.0050")
    expect(rows[0].priceVersion).toBe("v2026-09")

    const documentedRows = priceNoteRows({
      providers: [
        { id: "keenable", name: "Keenable", hasKey: false, keyVaultStatus: "keyless_public", capabilities: ["search", "fetch", "keyless_tier"] },
        { id: "tinyfish", name: "Tinyfish", hasKey: true, capabilities: ["search", "fetch"] },
        { id: "tavily", name: "Tavily", hasKey: false, keyVaultStatus: "configured", capabilities: ["search", "fetch"] },
        { id: "exa", name: "Exa", hasKey: true, capabilities: ["search", "fetch"] },
        { id: "firecrawl", name: "Firecrawl", hasKey: true, capabilities: ["search", "fetch"] },
        { id: "parallel", name: "Parallel", hasKey: true, capabilities: ["search", "fetch"] },
        { id: "youcom", name: "You.com", hasKey: true, capabilities: ["search", "fetch"] },
      ] as never,
      providerLimits: [],
    })
    const documentedRow = (provider: string, operation: "search" | "fetch") =>
      documentedRows.find((row) => row.provider === provider && row.operation === operation)
    expect(documentedRows).toHaveLength(14)
    expect(documentedRow("keenable", "search")).toMatchObject({
      usdPerCall: "$0.0040", free: true,
    })
    expect(documentedRow("tinyfish", "fetch")).toMatchObject({
      usdPerCall: null, free: true,
    })
    expect(documentedRow("tavily", "search")).toMatchObject({
      usdPerCall: "$0.0080", free: false,
    })
    expect(documentedRow("tavily", "fetch")).toMatchObject({
      usdPerCall: "$0.0016", free: false,
    })
    expect(documentedRow("exa", "fetch")).toMatchObject({
      usdPerCall: "$0.0010", priceBasis: "per page, per content type",
    })
    expect(documentedRow("firecrawl", "search")).toMatchObject({
      usdPerCall: "$0.0076", free: false,
    })
    expect(documentedRow("firecrawl", "search")?.priceBasis).toContain("Hobby reference")
    expect(documentedRow("firecrawl", "fetch")).toMatchObject({
      usdPerCall: "$0.0038", free: false,
    })
    expect(documentedRow("parallel", "search")).toMatchObject({
      usdPerCall: "$0.0010",
    })
    expect(documentedRow("youcom", "fetch")).toMatchObject({
      usdPerCall: "$0.0010",
    })

    const zeroCostAuth = braveAuth({
      search: { ...searchRecord(), budget: { model: "none", usd_per_call: "0", priced: false } } as never,
      usd_views: [{ ...braveAuth().usd_views[0], request_cost_usd: "0" }],
    })
    const zeroCostRows = priceNoteRows({
      providers: [{ id: "custom", name: "Custom", hasKey: true, capabilities: ["search"] }] as never,
      providerLimits: [{
        provider: "custom",
        active_auth_mode: "keyed",
        auths: [zeroCostAuth],
        documented_keyless_operations: [],
        version: 1,
        generated_at: "2026-09-06T10:05:00Z",
      }] as never,
    })
    expect(zeroCostRows[0]).toMatchObject({
      usdPerCall: "$0.0000", free: true,
    })

    const tinyPositiveAuth = braveAuth({
      usd_views: [{
        ...braveAuth().usd_views[0],
        request_cost_usd: "0.000000000000000000000000000000000000001",
      }],
    })
    const tinyPositiveRows = priceNoteRows({
      providers: [{ id: "custom", name: "Custom", hasKey: true, capabilities: ["search"] }] as never,
      providerLimits: [{
        provider: "custom",
        active_auth_mode: "keyed",
        auths: [tinyPositiveAuth],
        documented_keyless_operations: [],
        version: 1,
        generated_at: "2026-09-06T10:05:00Z",
      }] as never,
    })
    expect(tinyPositiveRows[0]?.free).toBe(false)
  })
})

describe("polish provenance (Item 4+5)", () => {
  it("marks a manual anchor as Estimated · Balance entry while keeping exact amounts", () => {
    const auth = braveAuth({
      aggregate_pool: { ...(braveAuth().aggregate_pool as unknown as Record<string, unknown>), manual_anchor: true } as never,
    })
    const totals: UsdUsageTotal[] = [
      { provider: "brave", operation: "search", spend_usd: "0.005", attempt_count: 1, volume_count: 1 },
      { provider: "brave", operation: "search", spend_usd: "0.006", attempt_count: 1, volume_count: 1 },
    ]
    const model = creditCardModel({ auth, usageTotals: totals })
    expect(model.provenanceNote).toBe("Estimated · Provider balance")

    expect(model.pricedUseUsd).toBe("0.011")
  })

  it("shows Vendor headers provenance for a vendor pool while keeping exact amounts", () => {
    const totals: UsdUsageTotal[] = [
      { provider: "brave", operation: "search", spend_usd: "0.005", attempt_count: 1, volume_count: 1 },
      { provider: "brave", operation: "search", spend_usd: "0.006", attempt_count: 1, volume_count: 1 },
    ]
    const model = creditCardModel({ auth: braveAuth(), usageTotals: totals })
    expect(model.provenanceNote).toContain("Vendor headers")
    expect(model.provenanceNote as string).not.toContain("vendor_headers")

    expect(model.pricedUseUsd).toBe("0.011")
  })
})
