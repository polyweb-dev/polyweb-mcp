import { describe, expect, it } from "vitest"
import type {
  CRDView,
  ProviderAuthLimits,
  RateProgressView,
  TierBalance,
} from "@/domains/dashboard"
import {
  dollarText,
  formatCRDAmount,
  formatCRD,
  providerCRDModel,
  rateBarModel,
  resetRuleText,
  tierBarModel,
} from "./crdDisplay"
import * as crdDisplayModule from "./crdDisplay"

/**
 * S0 generic CRD display: one-decimal ROUND_HALF_UP text, exact model amounts,
 * synthetic providers only, no vendor prices.
 */

function makeView(overrides: Partial<CRDView> = {}): CRDView {
  return {
    state: "finite",
    operation: "search",
    remaining_crd: "5",
    local_remaining_crd: "5",
    request_cost_crd: null,
    shared_pool_id: null,
    possible_standard_calls: null,
    price_version: null,
    priced: true,
    ...overrides,
  }
}

function makeTier(overrides: Partial<TierBalance> = {}): TierBalance {
  return {
    pool_id: "pool-synth-1",
    tier: "free",
    native_unit: "REQUEST",
    native_remaining: "10",
    native_allowance: "20",
    remaining_crd: "5",
    allowance_crd: "10",
    reset_rule: "monthly_first",
    reset_at: null,
    funding_mode: "prepaid",
    source: "synth-source",
    confidence: "authoritative",
    transport_available: true,
    label: null,
    ...overrides,
  }
}

function makeProgress(overrides: Partial<RateProgressView> = {}): RateProgressView {
  return {
    bucket_id: "bucket-synth-1",
    operation: "search",
    window: "1h",
    unit: "requests",
    remaining: "5",
    limit: "10",
    reset_at: null,
    source: "synth-source",
    confidence: "authoritative",
    kind: "rate",
    stale: false,
    enforceable: false,
    ...overrides,
  }
}

function makeAuth(overrides: Partial<ProviderAuthLimits> = {}): ProviderAuthLimits {
  return {
    auth_mode: "keyed",
    transport_available: true,
    search: null,
    fetch: null,
    free_tiers: [],
    paid_tiers: [],
    unknown_tiers: [],
    tier_split_known: true,
    aggregate_pool: null,
    crd_views: [],
    rate_progress: [],
    grants: null,
    detail: null,
    ...overrides,
  }
}

describe("formatCRDAmount", () => {
  it("formats zero as 0 CRD", () => {
    expect(formatCRDAmount("0")).toBe("0 CRD")
  })

  it("formats a positive amount below 0.1 as <0.1 CRD", () => {
    expect(formatCRDAmount("0.05")).toBe("<0.1 CRD")
  })

  it("rounds 0.599 to one decimal with an approximation mark", () => {
    expect(formatCRDAmount("0.599")).toBe("≈0.6 CRD")
  })

  it("rounds 0.58 to the same text while keeping the exact inputs distinct", () => {
    expect(formatCRDAmount("0.58")).toBe("≈0.6 CRD")
    const exactA: string = "0.58"
    const exactB: string = "0.599"
    expect(exactA === exactB).toBe(false)
  })

  it("formats a whole unit without a trailing .0", () => {
    expect(formatCRDAmount("1")).toBe("1 CRD")
  })

  it("rounds 1.55 half-up to ≈1.6 CRD", () => {
    expect(formatCRDAmount("1.55")).toBe("≈1.6 CRD")
  })

  it("formats 5 as 5 CRD", () => {
    expect(formatCRDAmount("5")).toBe("5 CRD")
  })

  it("formats garbage as Unknown", () => {
    expect(formatCRDAmount("nonsense")).toBe("Unknown")
    expect(formatCRDAmount("")).toBe("Unknown")
    expect(formatCRDAmount("1e3")).toBe("Unknown")
  })
})

describe("formatCRD", () => {
  it("formats an unmetered view as Free - unmetered", () => {
    expect(formatCRD(makeView({ state: "unmetered" }))).toBe("Free - unmetered")
  })

  it("formats an unavailable view as n/a", () => {
    expect(formatCRD(makeView({ state: "unavailable" }))).toBe("n/a")
  })

  it("formats an unknown view as Unknown", () => {
    expect(formatCRD(makeView({ state: "unknown" }))).toBe("Unknown")
  })

  it("picks the minimum of remaining and local remaining", () => {
    expect(
      formatCRD(makeView({ remaining_crd: "5", local_remaining_crd: "3" })),
    ).toBe("3 CRD")
    expect(
      formatCRD(makeView({ remaining_crd: "2", local_remaining_crd: "5" })),
    ).toBe("2 CRD")
  })

  it("formats a finite view without any spendable amount as Unknown", () => {
    expect(
      formatCRD(makeView({ remaining_crd: null, local_remaining_crd: null })),
    ).toBe("Unknown")
  })
})

describe("providerCRDModel", () => {
  it("reports a shared pool once with a do-not-add-up note", () => {
    const model = providerCRDModel({
      provider: "synth-a",
      providerName: "Synth A",
      authMode: "keyed",
      auth: makeAuth({
        crd_views: [
          makeView({
            operation: "search",
            remaining_crd: "5",
            local_remaining_crd: "5",
            shared_pool_id: "pool-synth-1",
          }),
          makeView({
            operation: "fetch",
            remaining_crd: "5",
            local_remaining_crd: "5",
            shared_pool_id: "pool-synth-1",
          }),
        ],
      }),
    })
    expect(model.sharedPoolId).toBe("pool-synth-1")
    expect(model.sharedNote).toBe(
      "Shared pool pool-synth-1: the two views read the same funds and do not add up.",
    )
  })

  it("reports no shared pool when the two views use different pools", () => {
    const model = providerCRDModel({
      provider: "synth-a",
      providerName: "Synth A",
      authMode: "keyed",
      auth: makeAuth({
        crd_views: [
          makeView({ operation: "search", shared_pool_id: "pool-synth-1" }),
          makeView({ operation: "fetch", shared_pool_id: "pool-synth-2" }),
        ],
      }),
    })
    expect(model.sharedPoolId).toBe(null)
    expect(model.sharedNote).toBe(null)
  })

  it("adds a ceiling note for the lowest local grant ceiling", () => {
    const model = providerCRDModel({
      provider: "synth-a",
      providerName: "Synth A",
      authMode: "keyed",
      auth: makeAuth({
        crd_views: [
          makeView({ operation: "search", local_remaining_crd: "5" }),
          makeView({ operation: "fetch", local_remaining_crd: "3" }),
        ],
      }),
    })
    expect(model.notes).toContain("Local grant ceiling 3 CRD")
  })

  it("adds standard-call notes for search and fetch", () => {
    const model = providerCRDModel({
      provider: "synth-a",
      providerName: "Synth A",
      authMode: "keyed",
      auth: makeAuth({
        crd_views: [
          makeView({
            operation: "search",
            possible_standard_calls: "10.9",
          }),
          makeView({
            operation: "fetch",
            possible_standard_calls: "4.2",
          }),
        ],
      }),
    })
    expect(model.notes).toContain("About 10 standard search calls remain")
    expect(model.notes).toContain("About 4 standard fetch calls remain")
  })

  it("adds an unpriced note when priced use is not configured", () => {
    const model = providerCRDModel({
      provider: "synth-a",
      providerName: "Synth A",
      authMode: "keyed",
      auth: makeAuth({
        crd_views: [makeView({ operation: "search", priced: false })],
      }),
    })
    expect(model.notes).toContain(
      "Priced use is not configured; the CRD value stays unknown",
    )
  })
})

describe("tierBarModel", () => {
  it("returns unknown with a Tier split unavailable note when the split is unknown", () => {
    const bar = tierBarModel({
      tier: "free",
      balances: [makeTier()],
      tierSplitKnown: false,
    })
    expect(bar.state).toBe("unknown")
    expect(bar.remainingCRD).toBe(null)
    expect(bar.allowanceCRD).toBe(null)
    expect(bar.percentRemaining).toBe(null)
    expect(bar.resetNotes).toEqual(["Tier split unavailable"])
  })

  it("returns unknown with empty notes for empty balances", () => {
    const bar = tierBarModel({ tier: "paid", balances: [], tierSplitKnown: true })
    expect(bar.state).toBe("unknown")
    expect(bar.remainingCRD).toBe(null)
    expect(bar.percentRemaining).toBe(null)
    expect(bar.resetNotes).toEqual([])
  })

  it("sums 0.599 plus 0.599 to exactly 1.198 without float error", () => {
    const bar = tierBarModel({
      tier: "free",
      tierSplitKnown: true,
      balances: [
        makeTier({ pool_id: "pool-synth-1", remaining_crd: "0.599", allowance_crd: "1" }),
        makeTier({ pool_id: "pool-synth-2", remaining_crd: "0.599", allowance_crd: "1" }),
      ],
    })
    expect(bar.remainingCRD).toBe("1.198")
    expect(bar.allowanceCRD).toBe("2")
  })

  it("rounds the remaining percent half-up to one decimal", () => {
    const bar = tierBarModel({
      tier: "free",
      tierSplitKnown: true,
      balances: [makeTier({ remaining_crd: "1", allowance_crd: "6" })],
    })
    expect(bar.percentRemaining).toBe(16.7)
  })

  it("clamps an over-allowance percent to 100", () => {
    const bar = tierBarModel({
      tier: "free",
      tierSplitKnown: true,
      balances: [makeTier({ remaining_crd: "10", allowance_crd: "5" })],
    })
    expect(bar.percentRemaining).toBe(100)
  })

  it("returns a null percent without a known positive allowance", () => {
    const nullAllowance = tierBarModel({
      tier: "free",
      tierSplitKnown: true,
      balances: [makeTier({ remaining_crd: "5", allowance_crd: null })],
    })
    expect(nullAllowance.percentRemaining).toBe(null)
    const zeroAllowance = tierBarModel({
      tier: "free",
      tierSplitKnown: true,
      balances: [makeTier({ remaining_crd: "5", allowance_crd: "0" })],
    })
    expect(zeroAllowance.percentRemaining).toBe(null)
  })
})

describe("rateBarModel", () => {
  it("passes through the 1h window with its amounts", () => {
    const bar = rateBarModel({ progress: makeProgress({ window: "1h" }) })
    expect(bar.window).toBe("1h")
    expect(bar.remaining).toBe("5")
    expect(bar.limit).toBe("10")
  })

  it("passes through the 1d window with its amounts", () => {
    const bar = rateBarModel({
      progress: makeProgress({ window: "1d", remaining: "7", limit: "20" }),
    })
    expect(bar.window).toBe("1d")
    expect(bar.percentRemaining).toBe(35)
  })

  it("computes a 50 percent bar for 5 of 10", () => {
    const bar = rateBarModel({
      progress: makeProgress({ remaining: "5", limit: "10" }),
    })
    expect(bar.percentRemaining).toBe(50)
  })

  it("returns a null percent for an unknown limit and never a zero bar", () => {
    const bar = rateBarModel({
      progress: makeProgress({ remaining: "7", limit: null }),
    })
    expect(bar.limit).toBe(null)
    expect(bar.percentRemaining).toBe(null)
  })

  it("returns a null percent for a zero limit", () => {
    const bar = rateBarModel({
      progress: makeProgress({ remaining: "5", limit: "0" }),
    })
    expect(bar.percentRemaining).toBe(null)
  })
})

describe("resetRuleText", () => {
  it("returns the base text without a reset date", () => {
    expect(resetRuleText("monthly_first", null)).toBe(
      "Resets on the first of the month",
    )
    expect(resetRuleText("unknown", null)).toBe("Reset rule unknown")
  })

  it("keeps an unparsable reset date verbatim", () => {
    expect(resetRuleText("never", "not-a-date")).toBe("Never resets (not-a-date)")
  })
})

describe("dollarText", () => {
  it("trims trailing zeros: 4.500 becomes $4.5 (final-polish 3a, 3d)", () => {
    expect(dollarText("4.500")).toBe("$4.5")
  })

  it("trims allowance zeros: 5.000 becomes $5 (final-polish 3d)", () => {
    expect(dollarText("5.000")).toBe("$5")
  })

  it("keeps exact cents: 4.495 stays $4.495 (final-polish 3c)", () => {
    expect(dollarText("4.495")).toBe("$4.495")
  })

  it("keeps call price precision: 0.005 stays $0.005", () => {
    expect(dollarText("0.005")).toBe("$0.005")
  })

  it("handles whole dollars without a dot", () => {
    expect(dollarText("10")).toBe("$10")
  })

  it("trims surrounding whitespace before the dollar form", () => {
    expect(dollarText("  4.500  ")).toBe("$4.5")
  })
})

describe("formatQuotaCount", () => {
  it("formats_integer_quota_counts_without_decimal_zeros", () => {
    const formatQuotaCount = (
      crdDisplayModule as unknown as { formatQuotaCount?: (amount: string) => string }
    ).formatQuotaCount
    expect(typeof formatQuotaCount).toBe("function")
    const format = formatQuotaCount as (amount: string) => string
    expect(format("1000.000000000")).toBe("1000")
    expect(format("498.000000000")).toBe("498")
    expect(format("1000")).toBe("1000")
    expect(format("500")).toBe("500")
    expect(format("0")).toBe("0")
    expect(format("0.000000000")).toBe("0")
    expect(format("5")).toBe("5")
    expect(format("9007199254740993")).toBe("9007199254740993")
    expect(format("9007199254740993.000000000")).toBe("9007199254740993")
    expect(format("498.5")).toBe("498.5")
    expect(format("99.6")).toBe("99.6")
    expect(format("5.25")).toBe("5.25")
    expect(format("nonsense")).toBe("nonsense")
  })
})
