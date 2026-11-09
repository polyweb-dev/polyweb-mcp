import { describe, expect, it } from "vitest"
import type {
  UsdConversionProfile,
  LimitRateWindow,
  NativePool,
  ProviderAuthLimits,
  TierBalance,
} from "@/domains/dashboard"
import {
  DEFAULT_TAVILY_PROFILE,
  displayAdapterOf,
  formatCreditAmount,
  formatCreditValue,
  formatTavilyPopoverAmount,
  minuteHeadroomOf,
  profileOf,
  tavilyUsdToCredits,
  tavilyCredits,
  tavilyCreditsToUsd,
} from "./tavilyCredits"

/**
 * Tavily native Credits display model: aggregate-first selection without a
 * double sum, exact 8 Usd per Credit conversion, and honest finite, unknown,
 * keyless, paygo, and unavailable states.
 */

function profile(overrides: Partial<UsdConversionProfile> = {}): UsdConversionProfile {
  return {
    native_usd_per_unit: "0.008",
    cost_basis: "paygo_reference",
    price_version: "paygo-reference",
    source: "documented",
    estimated: true,
    ...overrides,
  }
}

function pool(overrides: Partial<NativePool> = {}): NativePool {
  return {
    pool_id: "tavily:keyed:credits",
    provider: "tavily",
    auth_mode: "keyed",
    native_unit: "CREDIT",
    remaining: "1000",
    allowance: "1000",
    actual_spend_usd: null,
    source: "vendor_api",
    confidence: "observed",
    reset_at: "2026-10-01T00:00:00Z",
    observed_at: "2026-09-06T10:05:00Z",
    version: 2,
    credential_generation: 1,
    next_sync_at: null,
    stale: false,
    manual_anchor: false,
    ...overrides,
  }
}

function tier(overrides: Partial<TierBalance> = {}): TierBalance {
  return {
    pool_id: "tavily:keyed:free",
    tier: "free",
    native_unit: "CREDIT",
    native_remaining: "600",
    native_allowance: "1000",
    remaining_usd: "4.8",
    allowance_usd: "8",
    reset_rule: "monthly_first",
    reset_at: "2026-10-01T00:00:00Z",
    funding_mode: "prepaid",
    source: "vendor_api",
    confidence: "observed",
    transport_available: true,
    label: null,
    ...overrides,
  }
}

function record(operation: "search" | "fetch", supported = true) {
  return {
    provider: "tavily",
    operation,
    auth_mode: "keyed",
    supported,
    transport_available: supported,
    native_pool_id: "tavily:keyed:credits",
    rate: null,
    budget: {
      model: "credits",
      free_allowance: "1000",
      allowance_unit: "Credits",
      allowance_period: "monthly",
      cost_per_1k: null,
      standard_native_cost: operation === "search" ? "1" : "0.2",
      usd_per_call: "0.008",
      on_exhausted: "402",
      usage_api: "/usage",
      priced: true,
    },
    conversion_profile: profile(),
    plan_name: "Tavily",
    usage_url: null,
    version: 2,
  }
}

function auth(overrides: Partial<ProviderAuthLimits> = {}): ProviderAuthLimits {
  return {
    auth_mode: "keyed",
    transport_available: true,
    search: record("search") as never,
    fetch: record("fetch") as never,
    free_tiers: [],
    paid_tiers: [],
    unknown_tiers: [],
    tier_split_known: true,
    aggregate_pool: pool(),
    usd_views: [],
    rate_progress: [],
    grants: null,
    detail: null,
    ...overrides,
  }
}

function windowEntry(overrides: Partial<LimitRateWindow> = {}): LimitRateWindow {
  return {
    bucket_id: "tavily:keyed:search:requests",
    limit: "100",
    window: "1m",
    scope: "key",
    unit: "requests",
    remaining: "99",
    reset_at: null,
    source: "local",
    confidence: "observed",
    ...overrides,
  }
}

describe("tavilyCredits selection", () => {
  it("selects the aggregate pool first without summing operation views", () => {
    const result = tavilyCredits(
      auth({
        aggregate_pool: pool({ remaining: "1000", allowance: "1000", source: "vendor_api" }),
        free_tiers: [
          tier({ pool_id: "tavily:keyed:search", native_remaining: "600", native_allowance: "1000" }),
        ],
        paid_tiers: [
          tier({ pool_id: "tavily:keyed:extract", tier: "paid", native_remaining: "600", native_allowance: "1000" }),
        ],
        detail: {
          plan_name: null,
          native_unit: "CREDIT",
          native_balance: "5",
          native_allowance: "5",
          usd_per_call: null,
          actual_spend_usd: null,
          reset_at: null,
          reset_rule: "monthly_first",
          usage_url: null,
          source: "vendor_api",
          confidence: "observed",
          last_sync_at: null,
          stale: false,
          price_version: "v2",
          balance_split_note: null,
          rate_windows: [],
          tier_split_known: true,
          aggregate_pool_id: "tavily:keyed:credits",
        } as never,
      }),
    )
    expect(result.remaining).toBe("1000")
    expect(result.allowance).toBe("1000")
    expect(result.unit).toBe("Credits")
    expect(result.state).toBe("finite")
    expect(result.source).toBe("vendor_api")
  })

  it("falls back to known vendor tiers when the aggregate pool is absent", () => {
    const result = tavilyCredits(
      auth({
        aggregate_pool: null,
        free_tiers: [tier({ native_remaining: "999", native_allowance: "1000" })],
      }),
    )
    expect(result.remaining).toBe("999")
    expect(result.allowance).toBe("1000")
    expect(result.state).toBe("finite")
  })

  it("falls back to native detail when pool and tiers are absent", () => {
    const result = tavilyCredits(
      auth({
        aggregate_pool: null,
        detail: {
          plan_name: null,
          native_unit: "CREDIT",
          native_balance: "998",
          native_allowance: "1000",
          usd_per_call: null,
          actual_spend_usd: null,
          reset_at: null,
          reset_rule: "monthly_first",
          usage_url: null,
          source: "vendor_api",
          confidence: "observed",
          last_sync_at: null,
          stale: false,
          price_version: "v2",
          balance_split_note: null,
          rate_windows: [],
          tier_split_known: true,
          aggregate_pool_id: null,
        } as never,
      }),
    )
    expect(result.remaining).toBe("998")
    expect(result.allowance).toBe("1000")
  })

  it("keeps stored values verbatim without normalization", () => {
    const result = tavilyCredits(auth({ aggregate_pool: pool({ remaining: "1000.00", allowance: "1000.00" }) }))
    expect(result.remaining).toBe("1000.00")
    expect(result.allowance).toBe("1000.00")
  })

  it("ignores an operator grant tier when selecting vendor funds", () => {
    const result = tavilyCredits(
      auth({
        aggregate_pool: null,
        free_tiers: [tier({ source: "operator_grant", native_remaining: "5", native_allowance: "5" })],
      }),
    )
    expect(result.remaining).toBeNull()
    expect(result.state).toBe("unknown")
  })
})

describe("tavilyCredits states", () => {
  it("reports 1000/1000 finite for the free budget", () => {
    const result = tavilyCredits(auth({ aggregate_pool: pool({ remaining: "1000", allowance: "1000" }) }))
    expect(result.state).toBe("finite")
    expect(result.remaining).toBe("1000")
    expect(result.allowance).toBe("1000")
  })

  it("reports 999 after one basic search debit", () => {
    const result = tavilyCredits(auth({ aggregate_pool: pool({ remaining: "999", allowance: "1000" }) }))
    expect(result.state).toBe("finite")
    expect(result.remaining).toBe("999")
  })

  it("reports 998 after one advanced search debit", () => {
    const result = tavilyCredits(auth({ aggregate_pool: pool({ remaining: "998", allowance: "1000" }) }))
    expect(result.state).toBe("finite")
    expect(result.remaining).toBe("998")
  })

  it("reports unknown without inventing a zero or dev limit", () => {
    const result = tavilyCredits(auth({ aggregate_pool: null, detail: null }))
    expect(result.state).toBe("unknown")
    expect(result.remaining).toBeNull()
    expect(result.allowance).toBeNull()
  })

  it("reports keyless without a numeric remaining amount", () => {
    const result = tavilyCredits(
      auth({ auth_mode: "keyless", aggregate_pool: pool({ remaining: "100", allowance: "100" }) }),
    )
    expect(result.state).toBe("keyless")
    expect(result.remaining).toBeNull()
    expect(result.allowance).toBeNull()
  })

  it("reports keyless headroom as no numeric selection with a free denominator", () => {
    const result = tavilyCredits(auth({ auth_mode: "keyless", aggregate_pool: null, detail: null }))
    expect(result.state).toBe("keyless")
    expect(result.remaining).toBeNull()
    expect(result.allowance).toBeNull()
  })

  it("reports paygo for observed paid access", () => {
    const result = tavilyCredits(
      auth({
        aggregate_pool: pool({ remaining: "0", allowance: "1000" }),
        paid_tiers: [tier({ pool_id: "tavily:keyed:paygo", tier: "paid", confidence: "observed" })],
      }),
    )
    expect(result.state).toBe("paygo")
    expect(result.paygo).toBe(true)
  })

  it("reports unavailable for an unreachable keyed rail", () => {
    const result = tavilyCredits(
      auth({ transport_available: false, aggregate_pool: pool({ remaining: "10", allowance: "1000" }) }),
    )
    expect(result.state).toBe("unavailable")
    expect(result.remaining).toBeNull()
    expect(result.allowance).toBeNull()
  })
})

describe("tavilyCredits conversion", () => {
  it("converts 8 Usd to 1 Credit through the profile", () => {
    expect(tavilyUsdToCredits("0.008", profile())).toBe("1")
  })

  it("converts 1 Credit to 8 Usd through the profile", () => {
    expect(tavilyCreditsToUsd("1", profile())).toBe("0.008")
  })

  it("gives eight Usd per native Credit under the default profile", () => {
    expect(tavilyCreditsToUsd("2", DEFAULT_TAVILY_PROFILE)).toBe("0.016")
    expect(tavilyUsdToCredits("0.016", DEFAULT_TAVILY_PROFILE)).toBe("2")
  })

  it("returns null on an unknown profile without touching stored values", () => {
    const unknown = profile({ native_usd_per_unit: null })
    expect(tavilyUsdToCredits("8", unknown)).toBeNull()
    expect(tavilyCreditsToUsd("1", unknown)).toBeNull()
  })

  it("returns null for malformed amounts and zero prices", () => {
    expect(tavilyUsdToCredits("abc", profile())).toBeNull()
    expect(tavilyCreditsToUsd("abc", profile())).toBeNull()
    expect(tavilyUsdToCredits("8", profile({ native_usd_per_unit: "0" }))).toBeNull()
    expect(tavilyUsdToCredits("8", profile({ native_usd_per_unit: null }))).toBeNull()
    expect(tavilyCreditsToUsd("1", profile({ native_usd_per_unit: null }))).toBeNull()
  })

  it("exposes the documented default Tavily profile", () => {
    expect(DEFAULT_TAVILY_PROFILE.native_usd_per_unit).toBe("0.008")
    expect(DEFAULT_TAVILY_PROFILE.native_usd_per_unit).toBe("0.008")
  })
})

describe("tavilyCredits metadata", () => {
  it("carries source, stale state, and the vendor retry delay", () => {
    const result = tavilyCredits(
      auth({
        aggregate_pool: pool({ source: "vendor_api", stale: true }),
        detail: {
          plan_name: null,
          native_unit: "CREDIT",
          native_balance: null,
          native_allowance: null,
          usd_per_call: null,
          actual_spend_usd: null,
          reset_at: "2026-10-01T00:00:00Z",
          reset_rule: "monthly_first",
          usage_url: null,
          source: "vendor_api",
          confidence: "observed",
          last_sync_at: null,
          stale: false,
          price_version: "v2",
          balance_split_note: null,
          rate_windows: [windowEntry({ remaining: "95", limit: "100" })],
          retry_after_seconds: 12,
          tier_split_known: true,
          aggregate_pool_id: null,
        } as never,
      }),
    )
    expect(result.source).toBe("vendor_api")
    expect(result.stale).toBe(true)
    expect(result.resetAt).toBe("2026-10-01T00:00:00Z")
    expect(result.rateHeadroom).toBe("95/100")
    expect(result.retryAfterSeconds).toBe(12)
  })

  it("reports the lower stored grant ceiling in unconverted Usd text", () => {
    const result = tavilyCredits(
      auth({
        grants: {
          provider: "tavily",
          auth_mode: "keyed",
          period: "month" as const,
          version: 1,
          search_granted_usd: "0.8",
          search_consumed_usd: "0.008",
          search_reserved_usd: "0",
          fetch_granted_usd: "0.08",
          fetch_consumed_usd: "0.008",
          fetch_reserved_usd: "0",
        },
      }),
    )
    expect(result.localCap).toBe("0.072")
  })

  it("leaves the local cap absent without stored grants", () => {
    expect(tavilyCredits(auth({ grants: null })).localCap).toBeNull()
  })
})

describe("minuteHeadroomOf", () => {
  it("shows shared remaining over limit minute text", () => {
    expect(minuteHeadroomOf([windowEntry({ remaining: "95", limit: "100" })])).toBe("95/100")
  })

  it("shows remaining only without a known limit", () => {
    expect(minuteHeadroomOf([windowEntry({ remaining: "95", limit: undefined })])).toBe("95")
  })

  it("stays null without a minute window or a known remaining amount", () => {
    expect(minuteHeadroomOf([])).toBeNull()
    expect(minuteHeadroomOf([windowEntry({ window: "1h" })])).toBeNull()
    expect(minuteHeadroomOf([windowEntry({ remaining: "unknown" })])).toBeNull()
  })
})

describe("profileOf", () => {
  it("prefers the runnable search operation profile", () => {
    const searchProfile = profile({ price_version: "search-v" })
    const fetchProfile = profile({ price_version: "fetch-v" })
    const rail = auth({
      search: { ...(record("search") as object), conversion_profile: searchProfile } as never,
      fetch: { ...(record("fetch") as object), conversion_profile: fetchProfile } as never,
    })
    expect(profileOf(rail)?.price_version).toBe("search-v")
  })

  it("falls back to the first reported profile without a runnable rail", () => {
    const fetchProfile = profile({ price_version: "fetch-v" })
    const rail = auth({
      search: null,
      fetch: { ...(record("fetch", false) as object), conversion_profile: fetchProfile } as never,
    })
    expect(profileOf(rail)?.price_version).toBe("fetch-v")
  })

  it("yields null without any record", () => {
    expect(profileOf(auth({ search: null, fetch: null }))).toBeNull()
  })
})

describe("displayAdapterOf", () => {
  it("returns native inputs for Tavily only", () => {
    const rail = auth({})
    const adapter = displayAdapterOf("tavily", rail)
    expect(adapter?.credits.unit).toBe("Credits")
    expect(adapter?.profile?.native_usd_per_unit).toBe("0.008")
  })

  it("returns null for every other provider", () => {
    expect(displayAdapterOf("brave", auth({}))).toBeNull()
  })
})

describe("formatCreditValue", () => {
  it("formats whole and fractional Credits without trailing zeros", () => {
    expect(formatCreditValue("1")).toBe("1")
    expect(formatCreditValue("1000")).toBe("1000")
    expect(formatCreditAmount("1")).toBe("1 credit")
    expect(formatCreditAmount("2")).toBe("2 credits")
    expect(formatCreditAmount("1000")).toBe("1,000 credits")
    expect(formatCreditAmount("abc")).toBe("Unknown credits")
  })
})

describe("formatTavilyPopoverAmount", () => {
  it("floors nonnegative native amounts to whole units", () => {
    expect(formatTavilyPopoverAmount("1", "native")).toBe("1")
    expect(formatTavilyPopoverAmount("1.9", "native")).toBe("1")
    expect(formatTavilyPopoverAmount("0.2", "native")).toBe("0")
    expect(formatTavilyPopoverAmount("999.9", "native")).toBe("999")
  })

  it("trims long zero decimals on native, Usd, and USD text", () => {
    expect(formatTavilyPopoverAmount("100.000000000", "native")).toBe("100")
    expect(formatTavilyPopoverAmount("8.000000000", "usd")).toBe("8")
    expect(formatTavilyPopoverAmount("0.008000000", "usd")).toBe("0.008")
  })

  it("keeps significant Usd and USD fractions", () => {
    expect(formatTavilyPopoverAmount("1.600000000", "usd")).toBe("1.6")
    expect(formatTavilyPopoverAmount("0.001600000", "usd")).toBe("0.0016")
    expect(formatTavilyPopoverAmount("8", "usd")).toBe("8")
    expect(formatTavilyPopoverAmount("0.008", "usd")).toBe("0.008")
  })

  it("keeps large exact decimals without float conversion", () => {
    expect(formatTavilyPopoverAmount("123456789.987654321", "usd")).toBe("123456789.987654321")
    expect(formatTavilyPopoverAmount("1000.000000000", "native")).toBe("1000")
  })

  it("yields null for malformed, absent, and unknown values", () => {
    expect(formatTavilyPopoverAmount("abc", "native")).toBeNull()
    expect(formatTavilyPopoverAmount("", "usd")).toBeNull()
    expect(formatTavilyPopoverAmount("unknown", "usd")).toBeNull()
    expect(formatTavilyPopoverAmount("n/a", "native")).toBeNull()
    expect(formatTavilyPopoverAmount("lots", "usd")).toBeNull()
  })

  it("yields null for negative values instead of an invented zero", () => {
    expect(formatTavilyPopoverAmount("-1", "native")).toBeNull()
    expect(formatTavilyPopoverAmount("-0.5", "usd")).toBeNull()
    expect(formatTavilyPopoverAmount("-0.008", "usd")).toBeNull()
  })
})
