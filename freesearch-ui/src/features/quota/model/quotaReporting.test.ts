import { describe, expect, it } from "vitest"
import type { ProviderAuthLimits, LimitRecord, NativePool } from "@/domains/dashboard"
import { confirmedFree, reportsVendorUsage } from "./quotaReporting"
import { providerCardView } from "./providerCardView"

function record(source = "usd_native", usageApi: string | null = null): LimitRecord {
  return {
    provider: "sample", operation: "search", auth_mode: "keyed", supported: true,
    transport_available: true, native_pool_id: null, rate: null,
    budget: { model: "usd", free_allowance: null, allowance_unit: "USD", allowance_period: null,
      cost_per_1k: null, standard_native_cost: "1", usd_per_call: null, on_exhausted: "unknown",
      usage_api: usageApi, priced: true },
    conversion_profile: { source, native_usd_per_unit: "1",
      cost_basis: "usd_native", price_version: "test", estimated: false },
    plan_name: null, usage_url: null, version: 1,
  }
}

function pool(overrides: Partial<NativePool> = {}): NativePool {
  return { pool_id: "sample:usd", provider: "sample", auth_mode: "keyed", native_unit: "USD",
    remaining: "5", allowance: "5", actual_spend_usd: null, source: "local_ledger",
    confidence: "estimated", observed_at: null, reset_at: null, next_sync_at: null,
    version: 1, credential_generation: 1, stale: false, manual_anchor: false, ...overrides }
}

function auth(overrides: Partial<ProviderAuthLimits> = {}): ProviderAuthLimits {
  return { auth_mode: "keyed", transport_available: true, search: record(), fetch: null,
    free_tiers: [], paid_tiers: [], unknown_tiers: [], tier_split_known: false,
    aggregate_pool: null, usd_views: [], rate_progress: [], grants: null, detail: null, ...overrides }
}

describe("quota reporting evidence", () => {
  it("offers refresh for callable usage APIs and actual provider observations", () => {
    expect(reportsVendorUsage(auth({ search: record("usd_native", "https://api.vendor.com/usage") }))).toBe(true)
    expect(reportsVendorUsage(auth({ aggregate_pool: pool({ source: "vendor_api", confidence: "observed" }) }))).toBe(true)
  })

  it("never offers refresh for documentation links, local balances, or response headers", () => {
    expect(reportsVendorUsage(auth({ search: record("usd_native", "https://exa.ai/docs/reference/team-management/get-api-key-usage") }))).toBe(false)
    expect(reportsVendorUsage(auth({ aggregate_pool: pool() }))).toBe(false)
    expect(reportsVendorUsage(auth({ aggregate_pool: pool({ source: "vendor_headers" }) }))).toBe(false)
  })

  it("requires a free conversion source and keeps keyless refresh hidden", () => {
    expect(confirmedFree(auth({ auth_mode: "keyless" }))).toBe(false)
    expect(confirmedFree(auth({ search: record("unbilled_free") }))).toBe(true)
    expect(confirmedFree(auth({ search: record("unbilled_keyless") }))).toBe(true)
    expect(reportsVendorUsage(auth({ auth_mode: "keyless", search: record("unbilled_keyless", "https://api.vendor.com/usage") }))).toBe(false)
  })

  it("keeps bonus and denominator-free balances out of the measured card grid", () => {
    for (const aggregate of [pool({ remaining: "6" }), pool({ allowance: null })]) {
      const active = auth({ aggregate_pool: aggregate })
      const view = providerCardView({ providerId: "sample", limits: { provider: "sample", active_auth_mode: "keyed", auths: [active], documented_keyless_operations: [], generated_at: "2026-11-08T00:00:00Z", version: 1 }, usageTotals: [], latestQuota: undefined })
      expect(view?.measurable).toBe(false)
      expect(view?.amountText).toMatch(/^\$[56]\.00 left$/)
      expect(view?.refreshable).toBe(false)
    }
  })

  it("shows a native balance when the provider has no conversion price", () => {
    const unpriced = record()
    unpriced.conversion_profile.native_usd_per_unit = null
    const active = auth({ search: unpriced, aggregate_pool: pool({ native_unit: "CREDIT", remaining: "42" }) })
    const view = providerCardView({ providerId: "sample", limits: { provider: "sample", active_auth_mode: "keyed", auths: [active], documented_keyless_operations: [], generated_at: "2026-11-08T00:00:00Z", version: 1 }, usageTotals: [], latestQuota: undefined })
    expect(view?.amountText).toBe("42 credits left")
    expect(view?.reports).toBe(true)
    expect(view?.measurable).toBe(false)
  })
})
