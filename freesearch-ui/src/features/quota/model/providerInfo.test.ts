import { describe, expect, it } from "vitest"
import type {
  LimitBudget,
  LimitRecord,
  NativePool,
  ProviderAuthLimits,
  ProviderLimitDetail,
} from "@/domains/dashboard"
import { balancePrefill, providerInfo } from "./providerInfo"

function budget(overrides: Partial<LimitBudget> = {}): LimitBudget {
  return {
    model: "credits",
    free_allowance: null,
    allowance_unit: "credits",
    allowance_period: null,
    cost_per_1k: null,
    standard_native_cost: "1",
    usd_per_call: null,
    on_exhausted: "stop",
    usage_api: null,
    priced: true,
    ...overrides,
  }
}

function record(provider: string, overrides: Partial<LimitRecord> = {}): LimitRecord {
  return {
    provider,
    operation: "search",
    auth_mode: "keyed",
    supported: false,
    transport_available: false,
    native_pool_id: null,
    rate: null,
    budget: budget(),
    conversion_profile: {
      reference_usd_per_crd: "0.001",
      native_usd_per_unit: null,
      cost_basis: "test",
      price_version: "1",
      source: "test",
      estimated: false,
    },
    plan_name: null,
    usage_url: null,
    version: 1,
    ...overrides,
  }
}

function detail(overrides: Partial<ProviderLimitDetail> = {}): ProviderLimitDetail {
  return {
    plan_name: null,
    native_unit: null,
    native_balance: null,
    native_allowance: null,
    usd_per_call: null,
    actual_spend_usd: null,
    reset_at: null,
    reset_rule: "unknown",
    usage_url: null,
    source: "unknown",
    confidence: "unknown",
    last_sync_at: null,
    stale: false,
    price_version: "1",
    crd_split_note: null,
    rate_windows: [],
    tier_split_known: false,
    aggregate_pool_id: null,
    ...overrides,
  }
}

function pool(overrides: Partial<NativePool> = {}): NativePool {
  return {
    pool_id: "brave:keyed:usd",
    provider: "brave",
    auth_mode: "keyed",
    native_unit: "USD",
    remaining: null,
    allowance: null,
    actual_spend_usd: null,
    source: "vendor_api",
    confidence: "authoritative",
    reset_at: null,
    observed_at: null,
    version: 1,
    credential_generation: 1,
    next_sync_at: null,
    stale: false,
    manual_anchor: false,
    ...overrides,
  }
}

function auth(overrides: Partial<ProviderAuthLimits> = {}): ProviderAuthLimits {
  return {
    auth_mode: "keyed",
    transport_available: true,
    search: null,
    fetch: null,
    free_tiers: [],
    paid_tiers: [],
    unknown_tiers: [],
    tier_split_known: false,
    aggregate_pool: null,
    crd_views: [],
    rate_progress: [],
    grants: null,
    detail: null,
    ...overrides,
  }
}

describe("providerInfo creditNote", () => {
  it("gives Monthly Credits for the Brave-like rail and never states a tier word", () => {
    const info = providerInfo(
      auth({
        search: record("brave", {
          budget: budget({ allowance_period: "monthly", free_allowance: "10" }),
        }),
      })
    )
    expect(info.creditMode).toBe("free")
    expect(info.creditNote).toBe("Monthly Credits")
    expect(info.creditNote).not.toBe("Free Monthly Credits")
    expect(info.creditNote).not.toContain("Free")
  })

  it("falls back to the plan name for a rail without a period", () => {
    const info = providerInfo(
      auth({ detail: detail({ reset_rule: "never", plan_name: "Acme Standard" }) })
    )
    expect(info.creditNote).toBe("Acme Standard")
  })
})

describe("balancePrefill", () => {
  it("reads the aggregate pool first and keeps exact strings", () => {
    const result = balancePrefill(
      auth({
        aggregate_pool: pool({ allowance: "100.00", remaining: "75.25" }),
        detail: detail({ native_allowance: "999.00", native_balance: "888.00" }),
      })
    )
    expect(result).toEqual({ allowance: "100.00", remaining: "75.25" })
  })

  it("reads the vendor detail second and keeps exact strings", () => {
    const result = balancePrefill(
      auth({
        aggregate_pool: null,
        detail: detail({ native_allowance: "50.50", native_balance: "12.25" }),
      })
    )
    expect(result).toEqual({ allowance: "50.50", remaining: "12.25" })
  })

  it("yields null when neither source reports a balance", () => {
    expect(balancePrefill(auth({ aggregate_pool: null, detail: null }))).toBe(null)
  })
})
