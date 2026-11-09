import { describe, expect, it } from "vitest"
import { decodeUsdView } from "./limitsWireFields"
import { decodeProviderLimits, decodeUsdUsageTotals, decodeLimitHistory } from "./limitsWire"

describe("USD quota transport", () => {
  it("converts exact USD once and preserves native provider credits", () => {
    const [provider] = decodeProviderLimits({ provider: "tavily", auths: [{ free_tiers: [{ pool_id: "p", native_unit: "CREDIT", native_remaining: "1000", remaining_usd: "8" }], usd_views: [{ operation: "search", remaining_usd: "1.234567", request_cost_usd: "0.0016" }] }] })
    expect(provider?.auths[0]?.free_tiers[0]).toMatchObject({ native_remaining: "1000", remaining_usd: "8" })
    expect(provider?.auths[0]?.usd_views[0]).toMatchObject({ remaining_usd: "1.234567", request_cost_usd: "0.0016" })
  })
  it("decodes USD totals and history into the local model", () => {
    expect(decodeUsdUsageTotals({ spend_totals: [{ provider: "tavily", operation: "search", spend_usd: "0.016", attempt_count: 2, volume_count: 2 }] })[0]).toMatchObject({ spend_usd: "0.016", attempt_count: 2 })
    expect(decodeLimitHistory({ events: [{ event_id: "e", old_usd: "0.005", new_usd: "0.010", debit_usd: "0.0016" }] }).events[0]).toMatchObject({ old_usd: "0.005", new_usd: "0.010", debit_usd: "0.0016" })
  })
  it("decodes limits without requiring a ledger reference field", () => {
    const [provider] = decodeProviderLimits({ provider: "tavily", active_auth_mode: "keyed", auths: [{ auth_mode: "keyed", search: { operation: "search", conversion_profile: { native_usd_per_unit: "0.008" } }, usd_views: [{ operation: "search", request_cost_usd: "0.008" }] }] })
    expect(provider?.auths[0]?.search?.conversion_profile.native_usd_per_unit).toBe("0.008")
    expect(provider?.auths[0]?.usd_views[0]?.request_cost_usd).toBe("0.008")
  })
  it("keeps zero, unknown and high precision amounts distinct", () => {
    expect(decodeUsdView({ operation: "search", remaining_usd: "0.000000001", allowance_usd: "0", local_remaining_usd: null })).toMatchObject({ remaining_usd: "0.000000001", local_remaining_usd: null })
  })
  it("decodes USD budgets, balance notes and nested pool tiers", () => {
    const [provider] = decodeProviderLimits({
      provider: "tavily", active_auth_mode: "keyed", auths: [{
        auth_mode: "keyed",
        free_tiers: [{ pool_id: "free", tier: "free", native_unit: "CREDIT", native_remaining: "42", remaining_usd: "0.336" }],
        aggregate_pool: { pool_id: "pool", native_unit: "CREDIT", remaining: "42", tiers: [{ remaining_usd: "0.336" }] },
        grants: { search_granted_usd: "5", search_consumed_usd: "0.5" },
        detail: { balance_split_note: "Provider balance" },
      }],
    })
    const auth = provider?.auths[0]
    expect(auth?.free_tiers[0]).toMatchObject({ native_remaining: "42", remaining_usd: "0.336" })
    expect(auth?.aggregate_pool).toMatchObject({ native_unit: "CREDIT", remaining: "42" })
    expect(auth?.grants).toMatchObject({ search_granted_usd: "5", search_consumed_usd: "0.5" })
    expect(auth?.detail?.balance_split_note).toBe("Provider balance")
  })
})
