import { describe, expect, it } from "vitest"
import {
  decodeCRDUsageTotals,
  decodeLimitHistory,
  decodeProviderLimits,
} from "./limitsWire"

/**
 * S0 generic wire decoders: synthetic payloads only, empty CRD state stays
 * empty, exact amount strings stay verbatim, never throws on unknown input.
 */

function synthProvider(
  provider: string,
  overrides: Record<string, unknown> = {},
): Record<string, unknown> {
  return {
    provider,
    active_auth_mode: "keyed",
    version: 1,
    generated_at: "2026-02-01T00:00:00Z",
    documented_keyless_operations: [],
    auths: [],
    ...overrides,
  }
}

function synthAuth(overrides: Record<string, unknown> = {}): Record<string, unknown> {
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
    usd_views: [],
    rate_progress: [],
    grants: null,
    detail: null,
    ...overrides,
  }
}

describe("decodeProviderLimits", () => {
  it("decodes a bare array of synthetic providers", () => {
    const result = decodeProviderLimits([
      synthProvider("synth-a"),
      synthProvider("synth-b"),
    ])
    expect(result.map((entry) => entry.provider)).toEqual(["synth-a", "synth-b"])
  })

  it("decodes a dashboard wrapper with an empty provider_limits list to []", () => {
    expect(decodeProviderLimits({ provider_limits: [] })).toEqual([])
  })

  it("decodes a dashboard wrapper that holds synthetic providers", () => {
    const result = decodeProviderLimits({
      provider_limits: [synthProvider("synth-a")],
    })
    expect(result).toHaveLength(1)
    expect(result[0].provider).toBe("synth-a")
  })

  it("decodes a single provider object to a one-element list", () => {
    const result = decodeProviderLimits(synthProvider("synth-a"))
    expect(result).toHaveLength(1)
    expect(result[0].provider).toBe("synth-a")
  })

  it("returns [] for null", () => {
    expect(decodeProviderLimits(null)).toEqual([])
  })

  it("returns [] for undefined", () => {
    expect(decodeProviderLimits(undefined)).toEqual([])
  })

  it("returns [] for garbage scalar input", () => {
    expect(decodeProviderLimits(42)).toEqual([])
    expect(decodeProviderLimits("synth-a")).toEqual([])
    expect(decodeProviderLimits(true)).toEqual([])
  })

  it("returns [] for a garbage object without a provider", () => {
    expect(decodeProviderLimits({ nope: "synth-a" })).toEqual([])
    expect(decodeProviderLimits({ provider: 42 })).toEqual([])
  })

  it("keeps exact amount strings verbatim and never rounds them", () => {
    const result = decodeProviderLimits([
      synthProvider("synth-a", {
        auths: [
          synthAuth({
            free_tiers: [
              {
                pool_id: "pool-synth-a-free",
                tier: "free",
                native_unit: "REQUEST",
                native_remaining: "100",
                native_allowance: "200",
                remaining_usd: "0.000599",
                allowance_usd: "0.001",
                reset_rule: "monthly_first",
                reset_at: null,
                funding_mode: "prepaid",
                source: "synth-source",
                confidence: "authoritative",
                transport_available: true,
                label: null,
              },
            ],
            usd_views: [
              {
                state: "finite",
                operation: "search",
                remaining_usd: "0.000599",
                local_remaining_usd: "0.000599",
                request_cost_usd: "0.000050",
                shared_pool_id: null,
                possible_standard_calls: "11",
                price_version: null,
                priced: true,
              },
            ],
          }),
        ],
      }),
    ])
    expect(result).toHaveLength(1)
    expect(result[0].auths[0].free_tiers[0].remaining_crd).toBe("0.599")
    expect(result[0].auths[0].free_tiers[0].allowance_crd).toBe("1")
    expect(result[0].auths[0].crd_views[0].remaining_crd).toBe("0.599")
    expect(result[0].auths[0].crd_views[0].request_cost_crd).toBe("0.05")
  })

  it("maps backend you to UI youcom via toUiId", () => {
    const result = decodeProviderLimits([synthProvider("you")])
    expect(result).toHaveLength(1)
    expect(result[0].provider).toBe("youcom")
  })

  it("preserves an unknown synthetic provider id verbatim", () => {
    const result = decodeProviderLimits([synthProvider("synth-unknown-9")])
    expect(result[0].provider).toBe("synth-unknown-9")
  })

  it("falls back an unrecognized auth mode and view state to unknown", () => {
    const result = decodeProviderLimits([
      synthProvider("synth-a", {
        active_auth_mode: "bogus-mode",
        auths: [
          synthAuth({
            auth_mode: "bogus-mode",
            usd_views: [
              {
                state: "bogus-state",
                operation: "search",
                remaining_usd: "0.005",
                local_remaining_usd: "0.005",
                request_cost_usd: null,
                shared_pool_id: null,
                possible_standard_calls: null,
                price_version: null,
                priced: true,
              },
            ],
          }),
        ],
      }),
    ])
    expect(result[0].active_auth_mode).toBe("unknown")
    expect(result[0].auths[0].auth_mode).toBe("unknown")
    expect(result[0].auths[0].crd_views[0].state).toBe("unknown")
  })

  it("drops a view with an unknown operation instead of keeping it", () => {
    const result = decodeProviderLimits([
      synthProvider("synth-a", {
        auths: [
          synthAuth({
            usd_views: [
              {
                state: "finite",
                operation: "bogus",
                remaining_usd: "0.005",
                local_remaining_usd: "0.005",
                request_cost_usd: null,
                shared_pool_id: null,
                possible_standard_calls: null,
                price_version: null,
                priced: true,
              },
            ],
          }),
        ],
      }),
    ])
    expect(result[0].auths[0].crd_views).toEqual([])
  })

  it("never throws on unknown nested input", () => {
    expect(() =>
      decodeProviderLimits([{ provider: "synth-a", auths: "bogus" }]),
    ).not.toThrow()
    expect(
      decodeProviderLimits([{ provider: "synth-a", auths: "bogus" }]),
    ).toEqual([
      expect.objectContaining({ provider: "synth-a", auths: [] }),
    ])
  })
})

describe("decodeLimitHistory", () => {
  it("returns an empty page for null", () => {
    expect(decodeLimitHistory(null)).toEqual({ events: [], next_cursor: null })
  })

  it("returns an empty page for undefined and garbage scalars", () => {
    expect(decodeLimitHistory(undefined)).toEqual({
      events: [],
      next_cursor: null,
    })
    expect(decodeLimitHistory(42)).toEqual({ events: [], next_cursor: null })
    expect(decodeLimitHistory("synth-a")).toEqual({
      events: [],
      next_cursor: null,
    })
  })

  it("preserves the paging cursor verbatim", () => {
    const result = decodeLimitHistory({ events: [], next_cursor: "cursor-abc" })
    expect(result).toEqual({ events: [], next_cursor: "cursor-abc" })
  })

  it("keeps exact audit amounts verbatim", () => {
    const result = decodeLimitHistory({
      events: [
        {
          event_id: "evt-synth-1",
          provider: "synth-a",
          auth_mode: "keyed",
          operation: "search",
          pool_id: "pool-synth-1",
          observed_at: "2026-02-01T00:00:00Z",
          source: "synth-source",
          reason: "sync",
          old_native: null,
          new_native: null,
          old_usd: "0.000599",
          new_usd: "0.000500",
          debit_usd: "0.000099",
          native_debit: null,
          actual_usd: null,
          confidence: "authoritative",
          local_attempt_id: null,
          detail: {},
        },
      ],
      next_cursor: "cursor-1",
    })
    expect(result.next_cursor).toBe("cursor-1")
    expect(result.events).toHaveLength(1)
    expect(result.events[0].old_crd).toBe("0.599")
    expect(result.events[0].new_crd).toBe("0.5")
    expect(result.events[0].crd_debit).toBe("0.099")
  })

  it("maps backend you to UI youcom in history events", () => {
    const result = decodeLimitHistory({
      events: [
        {
          event_id: "evt-synth-2",
          provider: "you",
          auth_mode: "keyed",
          operation: null,
          pool_id: null,
          observed_at: "2026-02-01T00:00:00Z",
          source: "synth-source",
          reason: "sync",
          old_native: null,
          new_native: null,
          old_usd: null,
          new_usd: null,
          debit_usd: null,
          native_debit: null,
          actual_usd: null,
          confidence: "unknown",
          local_attempt_id: null,
          detail: {},
        },
      ],
      next_cursor: null,
    })
    expect(result.events[0].provider).toBe("youcom")
  })

  it("never throws on unknown event input", () => {
    expect(() =>
      decodeLimitHistory({ events: "bogus", next_cursor: 42 }),
    ).not.toThrow()
    expect(decodeLimitHistory({ events: "bogus", next_cursor: 42 })).toEqual({
      events: [],
      next_cursor: null,
    })
  })
})

describe("decodeCRDUsageTotals", () => {
  it("decodes an empty wrapped list to []", () => {
    expect(decodeCRDUsageTotals({ spend_totals: [] })).toEqual([])
  })

  it("decodes a bare array of synthetic totals", () => {
    const result = decodeCRDUsageTotals([
      {
        provider: "synth-a",
        operation: "search",
        spend_usd: "0.000599",
        attempt_count: 2,
        volume_count: 3,
      },
    ])
    expect(result).toHaveLength(1)
    expect(result[0]).toEqual({
      provider: "synth-a",
      operation: "search",
      normalized_crd: "0.599",
      attempt_count: 2,
      volume_count: 3,
    })
  })

  it("decodes a wrapped list of synthetic totals", () => {
    const result = decodeCRDUsageTotals({
      spend_totals: [
        {
          provider: "synth-b",
          operation: "fetch",
          spend_usd: "0.001250",
          attempt_count: 1,
          volume_count: 1,
        },
      ],
    })
    expect(result).toHaveLength(1)
    expect(result[0].normalized_crd).toBe("1.25")
  })

  it("returns [] for null and undefined", () => {
    expect(decodeCRDUsageTotals(null)).toEqual([])
    expect(decodeCRDUsageTotals(undefined)).toEqual([])
  })

  it("defaults missing spend_usd to 0", () => {
    const result = decodeCRDUsageTotals([
      {
        provider: "synth-a",
        operation: "search",
        attempt_count: 1,
        volume_count: 1,
      },
    ])
    expect(result).toHaveLength(1)
    expect(result[0].normalized_crd).toBe("0")
  })

  it("drops a total with an unknown operation", () => {
    const result = decodeCRDUsageTotals([
      {
        provider: "synth-a",
        operation: "bogus",
        spend_usd: "0.005",
        attempt_count: 1,
        volume_count: 1,
      },
    ])
    expect(result).toEqual([])
  })

  it("maps backend you to UI youcom in usage totals", () => {
    const result = decodeCRDUsageTotals([
      {
        provider: "you",
        operation: "search",
        spend_usd: "0.002",
        attempt_count: 1,
        volume_count: 1,
      },
    ])
    expect(result[0].provider).toBe("youcom")
  })

  it("never throws on unknown input", () => {
    expect(() => decodeCRDUsageTotals(42)).not.toThrow()
    expect(decodeCRDUsageTotals(42)).toEqual([])
    expect(() => decodeCRDUsageTotals({ spend_totals: "bogus" })).not.toThrow()
    expect(decodeCRDUsageTotals({ spend_totals: "bogus" })).toEqual([])
  })
})

describe("decodeDetail retry_after_seconds", () => {
  function detailWithRetry(value: unknown) {
    const result = decodeProviderLimits([
      synthProvider("synth-a", {
        auths: [
          synthAuth({
            detail: {
              plan_name: null,
              native_unit: null,
              native_balance: null,
              native_allowance: null,
              usd_per_call: null,
              actual_spend_usd: null,
              reset_at: null,
              reset_rule: "unknown",
              usage_url: null,
              source: "synth-source",
              confidence: "unknown",
              last_sync_at: null,
              stale: false,
              price_version: "1",
              balance_split_note: null,
              rate_windows: [],
              retry_after_seconds: value,
              tier_split_known: true,
              aggregate_pool_id: null,
            },
          }),
        ],
      }),
    ])
    return result[0].auths[0].detail?.retry_after_seconds ?? null
  }

  it("maps negative delays to null", () => {
    expect(detailWithRetry(-5)).toBeNull()
    expect(detailWithRetry("-3")).toBeNull()
  })

  it("keeps zero as zero", () => {
    expect(detailWithRetry(0)).toBe(0)
    expect(detailWithRetry("0")).toBe(0)
  })

  it("keeps a finite positive delay and drops unknown input", () => {
    expect(detailWithRetry(12)).toBe(12)
    expect(detailWithRetry("45")).toBe(45)
    expect(detailWithRetry(null)).toBeNull()
    expect(detailWithRetry(undefined)).toBeNull()
    expect(detailWithRetry("bogus")).toBeNull()
    expect(detailWithRetry(Number.NaN)).toBeNull()
  })
})
