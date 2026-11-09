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
    balance_split_note: null,
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
    usd_views: [],
    rate_progress: [],
    grants: null,
    detail: null,
    ...overrides,
  }
}

describe("providerInfo prices", () => {
  it("uses the active keyless catalog price instead of a stale priced projection", () => {
    const base = record("keenable", { supported: true, transport_available: true, auth_mode: "keyless" })
    const search = { ...base, conversion_profile: { ...base.conversion_profile, source: "unbilled_keyless" } }
    const info = providerInfo(auth({
      auth_mode: "keyless",
      search,
      usd_views: [{ operation: "search", request_cost_usd: "0.004" } as never],
    }), "keenable")
    expect(info.facts).toContainEqual({ label: "Search cost", value: "Free", note: null })
    expect(info.facts.some((fact) => fact.value.includes("USD"))).toBe(false)
  })

  it("converts a priced operation to dollars", () => {
    const search = record("brave", { supported: true, transport_available: true })
    const info = providerInfo(auth({
      search,
      usd_views: [{ operation: "search", request_cost_usd: "0.005" } as never],
    }), "brave")
    expect(info.facts).toContainEqual({ label: "Search cost (USD)", value: "$0.0050", note: null })
  })
})

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
    expect(info.creditNote).toBe("Monthly credits")
    expect(info.creditNote).not.toBe("Free Monthly credits")
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

describe("providerInfo Tavily native", () => {
  function tavilyProfile() {
    return {
      native_usd_per_unit: "0.008",
      cost_basis: "paygo_reference",
      price_version: "paygo-reference",
      source: "documented",
      estimated: true,
    }
  }

  function tavilyAuth(overrides: Partial<ProviderAuthLimits> = {}): ProviderAuthLimits {
    return auth({
      search: record("tavily", {
        operation: "search",
        supported: true,
        transport_available: true,
        budget: budget({ standard_native_cost: "1" }),
        conversion_profile: tavilyProfile(),
      }),
      fetch: record("tavily", {
        operation: "fetch",
        supported: true,
        transport_available: true,
        budget: budget({ standard_native_cost: "0.2" }),
        conversion_profile: tavilyProfile(),
      }),
      usd_views: [
        {
          state: "finite",
          operation: "search",
          remaining_usd: "7.992",
          local_remaining_usd: null,
          request_cost_usd: "0.008",
          shared_pool_id: "tavily:keyed:credits",
          possible_standard_calls: "999",
          price_version: "paygo-reference",
          priced: true,
        },
        {
          state: "finite",
          operation: "fetch",
          remaining_usd: "7.992",
          local_remaining_usd: null,
          request_cost_usd: "0.008",
          shared_pool_id: "tavily:keyed:credits",
          possible_standard_calls: "999",
          price_version: "paygo-reference",
          priced: true,
        },
      ] as never,
      detail: detail({
        rate_windows: [
          {
            bucket_id: "tavily:keyed:search:requests",
            limit: "100",
            window: "1m",
            scope: "key",
            unit: "requests",
            remaining: "95",
            reset_at: null,
            source: "local",
            confidence: "observed",
          },
        ] as never,
        retry_after_seconds: 12,
      }),
      ...overrides,
    })
  }

  it("states 1 and 2 Tavily Credits search costs", () => {
    const info = providerInfo(tavilyAuth(), "tavily")
    const search = info.facts.find((fact) => fact.label === "Search cost")
    expect(search?.value).toBe("1 Tavily credit")
    expect(search?.note).toBe("(advanced: 2 Tavily credits)")
  })

  it("states 1 to 2 Tavily Credits per five URLs extract costs with the Extract label", () => {
    const info = providerInfo(tavilyAuth(), "tavily")
    const extract = info.facts.find((fact) => fact.label === "Extract cost")
    expect(extract?.value).toBe("1 Tavily credit per 5 URLs")
    expect(extract?.note).toBe("(advanced: 2 Tavily credits)")
    expect(info.facts.some((fact) => fact.label === "Fetch cost")).toBe(false)
    expect(info.facts.some((fact) => fact.label === "Extract cost (USD)")).toBe(true)
    expect(info.facts.some((fact) => fact.label === "Fetch cost in Usd")).toBe(false)
  })

  it("shares one Search and Fetch Rate Limit row and states the Retry-After delay", () => {
    const info = providerInfo(tavilyAuth(), "tavily")
    const rate = info.facts.find((fact) => fact.label === "Search and fetch rate limit")
    expect(rate?.value).toBe("95/100 requests per minute")
    expect(rate?.note).toBe(null)
    expect(info.facts.some((fact) => fact.label === "Minute headroom")).toBe(false)
    expect(info.facts.some((fact) => fact.label === "Rate limit")).toBe(false)
    const retry = info.facts.find((fact) => fact.label === "Retry after")
    expect(retry?.value).toBe("12 s")
  })

  it("keeps USD inside the disclosure cost note while native rows carry no USD", () => {
    const info = providerInfo(tavilyAuth(), "tavily")
    const native = info.facts.find((fact) => fact.label === "Search cost")
    expect(native?.value).not.toContain("$")
    expect(native?.note).not.toContain("$")
    const usd = info.facts.find((fact) => fact.label === "Search cost (USD)")
    expect(usd?.value).toBe("$0.0080")
    expect(usd?.note).toBe(null)
  })

  it("shows keyless numeric headroom as unknown with no rate row", () => {
    const info = providerInfo(
      tavilyAuth({ auth_mode: "keyless", detail: detail({ rate_windows: [] }) }),
      "tavily",
    )
    expect(info.facts.some((fact) => fact.label === "Search and fetch rate limit")).toBe(false)
    expect(info.facts.some((fact) => fact.label === "Minute headroom")).toBe(false)
  })
})

describe("providerInfo Tavily row order", () => {
  function orderedAuth(overrides: Partial<ProviderAuthLimits> = {}): ProviderAuthLimits {
    return auth({
      search: record("tavily", {
        operation: "search",
        supported: true,
        transport_available: true,
        budget: budget({ standard_native_cost: "1" }),
        conversion_profile: {
          native_usd_per_unit: "0.008",
          cost_basis: "paygo_reference",
          price_version: "paygo-reference",
          source: "documented",
          estimated: true,
        },
      }),
      fetch: record("tavily", {
        operation: "fetch",
        supported: true,
        transport_available: true,
        budget: budget({ standard_native_cost: "0.2" }),
        conversion_profile: {
          native_usd_per_unit: "0.008",
          cost_basis: "paygo_reference",
          price_version: "paygo-reference",
          source: "documented",
          estimated: true,
        },
      }),
      usd_views: [
        {
          state: "finite",
          operation: "search",
          remaining_usd: "7.992",
          local_remaining_usd: null,
          request_cost_usd: "0.008",
          shared_pool_id: "tavily:keyed:credits",
          possible_standard_calls: "999",
          price_version: "paygo-reference",
          priced: true,
        },
        {
          state: "finite",
          operation: "fetch",
          remaining_usd: "7.992",
          local_remaining_usd: null,
          request_cost_usd: "0.008",
          shared_pool_id: "tavily:keyed:credits",
          possible_standard_calls: "999",
          price_version: "paygo-reference",
          priced: true,
        },
      ] as never,
      detail: detail({
        last_sync_at: "2026-09-06T10:05:00Z",
        rate_windows: [
          {
            bucket_id: "tavily:keyed:search:requests",
            limit: "100",
            window: "1m",
            scope: "key",
            unit: "requests",
            remaining: "95",
            reset_at: null,
            source: "local",
            confidence: "observed",
          },
        ] as never,
        retry_after_seconds: 12,
      }),
      ...overrides,
    })
  }

  it("orders native costs, counts, Usd costs, rate, then Retry-After and Last sync", () => {
    const info = providerInfo(orderedAuth(), "tavily")
    expect(info.facts.map((fact) => fact.label)).toEqual([
      "Search cost",
      "Extract cost",
      "Searches left",
      "Fetches left",
      "Search cost (USD)",
      "Extract cost (USD)",
      "Search and fetch rate limit",
      "Retry after",
      "Last sync",
    ])
  })

  it("floors fractional call counts through callsText", () => {
    const rail = orderedAuth({
      usd_views: [
        {
          state: "finite",
          operation: "search",
          remaining_usd: "7.992",
          local_remaining_usd: null,
          request_cost_usd: "0.008",
          shared_pool_id: "tavily:keyed:credits",
          possible_standard_calls: "999.9",
          price_version: "paygo-reference",
          priced: true,
        },
        {
          state: "finite",
          operation: "fetch",
          remaining_usd: "7.992",
          local_remaining_usd: null,
          request_cost_usd: "0.008",
          shared_pool_id: "tavily:keyed:credits",
          possible_standard_calls: "999.9",
          price_version: "paygo-reference",
          priced: true,
        },
      ] as never,
    })
    const info = providerInfo(rail, "tavily")
    expect(
      info.facts.filter((fact) => fact.label === "Searches left").map((fact) => fact.value),
    ).toEqual(["999"])
    expect(
      info.facts.filter((fact) => fact.label === "Fetches left").map((fact) => fact.value),
    ).toEqual(["999"])
  })
})

describe("providerInfo Tavily combined rate", () => {
  function rateAuth(remaining: string | null, limit: string | null): ProviderAuthLimits {
    return auth({
      detail: detail({
        rate_windows:
          remaining === null && limit === null
            ? []
            : [
                {
                  bucket_id: "tavily:keyed:search:requests",
                  limit,
                  window: "1m",
                  scope: "key",
                  unit: "requests",
                  remaining,
                  reset_at: null,
                  source: "local",
                  confidence: "observed",
                },
              ] as never,
      }),
    })
  }

  it.each([
    ["100", "100", "100 requests per minute"],
    ["1000", "1000", "1,000 requests per minute"],
    ["90", "100", "90/100 requests per minute"],
    ["900", "1000", "900/1,000 requests per minute"],
    ["0", "100", "0/100 requests per minute"],
  ])("shows dev/prod headroom %s/%s", (remaining, limit, value) => {
    const info = providerInfo(rateAuth(remaining, limit), "tavily")
    const rate = info.facts.find((fact) => fact.label === "Search and fetch rate limit")
    expect(rate?.value).toBe(value)
  })

  it("floors fractional dashboard headroom through callsText", () => {
    const info = providerInfo(rateAuth("100.000000000", "100.000000000"), "tavily")
    const rate = info.facts.find((fact) => fact.label === "Search and fetch rate limit")
    expect(rate?.value).toBe("100 requests per minute")
  })

  it("shows unknown headroom with a confirmed ceiling override", () => {
    const info = providerInfo(rateAuth("90", "100"), "tavily", false, "1000")
    const rate = info.facts.find((fact) => fact.label === "Search and fetch rate limit")
    expect(rate?.value).toBe("Limit 1,000 requests per minute")
  })

  it("keeps dashboard headroom once it confirms the override ceiling", () => {
    const info = providerInfo(rateAuth("95", "100"), "tavily", false, "100")
    const rate = info.facts.find((fact) => fact.label === "Search and fetch rate limit")
    expect(rate?.value).toBe("95/100 requests per minute")
  })

  it("keeps keyless numeric rate unknown without a dev/prod denominator", () => {
    const info = providerInfo(
      auth({ auth_mode: "keyless", detail: detail({ rate_windows: [] }) }),
      "tavily",
    )
    expect(info.facts.some((fact) => fact.label === "Search and fetch rate limit")).toBe(false)
  })
})

describe("providerInfo Tavily precision", () => {
  function preciseAuth(searchCost: string, fetchCost: string): ProviderAuthLimits {
    return auth({
      search: record("tavily", {
        operation: "search",
        supported: true,
        transport_available: true,
        budget: budget({ standard_native_cost: searchCost }),
        conversion_profile: {
          native_usd_per_unit: "0.008",
          cost_basis: "paygo_reference",
          price_version: "paygo-reference",
          source: "documented",
          estimated: true,
        },
      }),
      fetch: record("tavily", {
        operation: "fetch",
        supported: true,
        transport_available: true,
        budget: budget({ standard_native_cost: fetchCost }),
        conversion_profile: {
          native_usd_per_unit: "0.008",
          cost_basis: "paygo_reference",
          price_version: "paygo-reference",
          source: "documented",
          estimated: true,
        },
      }),
      usd_views: [
        {
          state: "finite",
          operation: "search",
          remaining_usd: "7.992",
          local_remaining_usd: null,
          request_cost_usd: "0.008000000",
          shared_pool_id: "tavily:keyed:credits",
          possible_standard_calls: "999",
          price_version: "paygo-reference",
          priced: true,
        },
        {
          state: "finite",
          operation: "fetch",
          remaining_usd: "7.992",
          local_remaining_usd: null,
          request_cost_usd: "0.001600000",
          shared_pool_id: "tavily:keyed:credits",
          possible_standard_calls: "999",
          price_version: "paygo-reference",
          priced: true,
        },
      ] as never,
      detail: detail({ rate_windows: [] }),
    })
  }

  it("floors native amounts and trims Usd/USD zeros", () => {
    const info = providerInfo(preciseAuth("1.9", "0.2"), "tavily")
    const search = info.facts.find((fact) => fact.label === "Search cost")
    expect(search?.value).toBe("1 Tavily credit")
    const searchUsd = info.facts.find((fact) => fact.label === "Search cost (USD)")
    expect(searchUsd?.value).toBe("$0.0080")
    expect(searchUsd?.note).toBe(null)
  })

  it("keeps the 1.6 Usd extract fraction with its USD fraction", () => {
    const info = providerInfo(preciseAuth("1", "0.2"), "tavily")
    const fetchUsd = info.facts.find((fact) => fact.label === "Extract cost (USD)")
    expect(fetchUsd?.value).toBe("$0.0016")
    expect(fetchUsd?.note).toBe(null)
  })

  it("names Monthly Tavily Credits for a monthly Tavily rail", () => {
    const rail = auth({
      search: record("tavily", {
        supported: true,
        transport_available: true,
        budget: budget({ allowance_period: "monthly", free_allowance: "1000" }),
      }),
    })
    expect(providerInfo(rail, "tavily").creditNote).toBe("Monthly Tavily credits")
  })

  it("rounds a fractional Retry-After delay up to whole seconds", () => {
    const rail = auth({ detail: detail({ retry_after_seconds: 12.2 }) })
    const info = providerInfo(rail, "tavily")
    expect(info.facts.find((fact) => fact.label === "Retry after")?.value).toBe("13 s")
  })
})

describe("providerInfo wholeRequests", () => {
  function view(operation: "search" | "fetch", calls: string | null): Record<string, unknown> {
    return {
      state: "finite",
      operation,
      remaining_usd: "400",
      local_remaining_usd: null,
      request_cost_usd: "0.004",
      shared_pool_id: "keenable:keyed:request",
      possible_standard_calls: calls,
      price_version: "list_price",
      priced: true,
    }
  }

  function window(limit: string, unit: "requests" | "urls"): Record<string, unknown> {
    return {
      bucket_id: "keenable:keyed:requests",
      limit,
      window: "1s",
      scope: "ip",
      unit,
      remaining: null,
      reset_at: null,
      source: "documented",
      confidence: "observed",
    }
  }

  function exaWindow(limit: string): Record<string, unknown> {
    return { ...window(limit, "requests"), scope: "team" }
  }

  it("floors integer standard calls with the opt-in flag", () => {
    const base = auth({
      search: record("keenable", { supported: true, transport_available: true }),
      fetch: record("keenable", {
        operation: "fetch",
        supported: true,
        transport_available: true,
      }),
      usd_views: [
        view("search", "99995.00000000"),
        view("fetch", "99995.00000000"),
      ] as never,
      detail: detail({ reset_rule: "vendor_period" }),
    })
    const whole = providerInfo(base, "keenable", true)
    expect(
      whole.facts.filter((fact) => fact.label === "Searches left").map((fact) => fact.value),
    ).toEqual(["99,995"])
    expect(
      whole.facts.filter((fact) => fact.label === "Fetches left").map((fact) => fact.value),
    ).toEqual(["99,995"])
  })

  it("keeps decimal standard calls without the opt-in flag", () => {
    const base = auth({
      search: record("keenable", { supported: true, transport_available: true }),
      usd_views: [view("search", "99995.00000000")] as never,
      detail: detail({ reset_rule: "vendor_period" }),
    })
    const current = providerInfo(base)
    expect(
      current.facts.filter((fact) => fact.label === "Searches left").map((fact) => fact.value),
    ).toEqual(["99,995.00000000"])
  })

  it("floors request rate limits only with the opt-in flag", () => {
    const base = auth({
      detail: detail({
        rate_windows: [window("1000.00000000", "requests")] as never,
      }),
    })
    expect(providerInfo(base).facts.map((fact) => fact.value)).toContain("1000.00000000 requests per second")
    expect(providerInfo(base, "keenable", true).facts.map((fact) => fact.value)).toContain("1000 requests per second")
  })

  it("floors Exa whole calls and shows search and fetch rate limits separately", () => {
    const base = auth({
      search: record("exa", {
        supported: true,
        transport_available: true,
        rate: { windows: [exaWindow("10")], published: true } as never,
      }),
      fetch: record("exa", {
        operation: "fetch",
        supported: true,
        transport_available: true,
        rate: { windows: [exaWindow("100")], published: true } as never,
      }),
      usd_views: [view("search", "12.9"), view("fetch", "3.7")] as never,
      detail: detail({ rate_windows: [exaWindow("10")] as never }),
    })

    const facts = providerInfo(base, "exa").facts
    expect(
      facts
        .filter((fact) => fact.label === "Search rate limit" || fact.label === "Fetch rate limit")
        .map((fact) => [fact.label, fact.value, fact.note]),
    ).toEqual([
      ["Search rate limit", "10 requests per second", "(per team)"],
      ["Fetch rate limit", "100 requests per second", "(per team)"],
    ])
    expect(
      facts
        .filter((fact) => fact.label === "Searches left" || fact.label === "Fetches left")
        .map((fact) => [fact.label, fact.value]),
    ).toEqual([
      ["Searches left", "12"],
      ["Fetches left", "3"],
    ])
  })

  it("keeps URL rate limits verbatim with the opt-in flag", () => {
    const base = auth({
      detail: detail({ rate_windows: [window("10.5", "urls")] as never }),
    })
    expect(providerInfo(base, "keenable", true).facts.map((fact) => fact.value)).toContain("10.5 URLs per second")
  })

  it("omits invalid counts instead of a fabricated zero", () => {
    const base = auth({
      search: record("keenable", { supported: true, transport_available: true }),
      usd_views: [view("search", "lots")] as never,
      detail: detail({
        reset_rule: "vendor_period",
        rate_windows: [window("lots", "requests")] as never,
      }),
    })
    const info = providerInfo(base, "keenable", true)
    expect(info.facts.some((fact) => fact.value === "0")).toBe(false)
    expect(info.facts.some((fact) => fact.label === "Searches left")).toBe(false)
  })

  it("preserves cost labels, USD notes, and monthly header notes", () => {
    const profile = {
      native_usd_per_unit: "0.004",
      cost_basis: "priced_native_use",
      price_version: "list_price",
      source: "list_price_assumed",
      estimated: true,
    }
    const base = auth({
      search: record("keenable", {
        supported: true,
        transport_available: true,
        conversion_profile: profile,
        budget: budget({ allowance_period: "month", free_allowance: "100000" }),
      }),
      fetch: record("keenable", {
        operation: "fetch",
        supported: true,
        transport_available: true,
        conversion_profile: profile,
        budget: budget({ allowance_period: "month", free_allowance: "100000" }),
      }),
      usd_views: [
        { ...view("search", "99995"), request_cost_usd: "0.004" },
        { ...view("fetch", "99995"), request_cost_usd: "0.004" },
      ] as never,
      detail: detail({ reset_rule: "monthly_first" }),
    })
    const info = providerInfo(base, "keenable", true)
    expect(info.facts.map((fact) => fact.label)).toContain("Search cost (USD)")
    expect(info.facts.map((fact) => fact.label)).toContain("Fetch cost (USD)")
    expect(info.creditNote).toBe("Monthly credits")
    const searchCost = info.facts.find((fact) => fact.label === "Search cost (USD)")
    expect(searchCost?.value).toBe("$0.0040")
  })

  it("keeps exact input strings unchanged", () => {
    const base = auth({
      search: record("keenable", { supported: true, transport_available: true }),
      usd_views: [view("search", "99995.00000000")] as never,
      detail: detail({ reset_rule: "vendor_period" }),
    })
    const first = providerInfo(base, "keenable", true)
    const second = providerInfo(base, "keenable", true)
    expect(first).toEqual(second)
    expect(base.usd_views[0]).toMatchObject({ possible_standard_calls: "99995.00000000" })
  })
})

describe("providerInfo Firecrawl", () => {
  function firecrawlProfile() {
    return {
      native_usd_per_unit: "0.0038",
      cost_basis: "hobby_reference",
      price_version: "hobby-reference",
      source: "documented",
      estimated: true,
    }
  }

  function firecrawlAuth(overrides: Partial<ProviderAuthLimits> = {}): ProviderAuthLimits {
    return auth({
      search: record("firecrawl", {
        operation: "search",
        supported: true,
        transport_available: true,
        budget: budget({ allowance_period: "monthly", standard_native_cost: "2" }),
        conversion_profile: firecrawlProfile(),
      }),
      fetch: record("firecrawl", {
        operation: "fetch",
        supported: true,
        transport_available: true,
        budget: budget({ allowance_period: "monthly", standard_native_cost: "1" }),
        conversion_profile: firecrawlProfile(),
      }),
      usd_views: [
        {
          state: "finite",
          operation: "search",
          remaining_usd: "3.8",
          local_remaining_usd: null,
          request_cost_usd: "0.0076",
          shared_pool_id: "firecrawl:keyed:credit",
          possible_standard_calls: "500",
          price_version: "hobby-reference",
          priced: true,
        },
        {
          state: "finite",
          operation: "fetch",
          remaining_usd: "3.8",
          local_remaining_usd: null,
          request_cost_usd: "0.0038",
          shared_pool_id: "firecrawl:keyed:credit",
          possible_standard_calls: "1000",
          price_version: "hobby-reference",
          priced: true,
        },
      ] as never,
      detail: detail({
        rate_windows: [
          {
            bucket_id: "firecrawl:keyed:requests",
            limit: "10",
            window: "1m",
            scope: "team",
            unit: "requests",
            remaining: "10",
            reset_at: null,
            source: "local",
            confidence: "observed",
          },
        ] as never,
      }),
      ...overrides,
    })
  }

  it("produces correct facts for Firecrawl", () => {
    const info = providerInfo(firecrawlAuth(), "firecrawl", true)
    const searchUsd = info.facts.find((fact) => fact.label === "Search cost (USD)")
    expect(searchUsd?.value).toBe("$0.0076")
    expect(searchUsd?.note).toBe(null)

    const fetchUsd = info.facts.find((fact) => fact.label === "Fetch cost (USD)")
    expect(fetchUsd?.value).toBe("$0.0038")
    expect(fetchUsd?.note).toBe(null)

    const searchesLeft = info.facts.find((fact) => fact.label === "Searches left")
    expect(searchesLeft?.value).toBe("500")

    const fetchesLeft = info.facts.find((fact) => fact.label === "Fetches left")
    expect(fetchesLeft?.value).toBe("1,000")

    const rate = info.facts.find((fact) => fact.label === "Rate limit")
    expect(rate?.value).toBe("10 requests per minute")

    expect(info.creditNote).toBe("Monthly credits")
  })
})

describe("providerInfo You.com search total", () => {
  function youcomAuth(): ProviderAuthLimits {
    return auth({
      search: record("youcom", {
        operation: "search",
        supported: true,
        transport_available: true,
      }),
      fetch: record("youcom", {
        operation: "fetch",
        supported: true,
        transport_available: true,
      }),
      aggregate_pool: pool({
        pool_id: "youcom:keyed:usd",
        provider: "youcom",
        auth_mode: "keyed",
        native_unit: "USD",
        remaining: "199.52",
        allowance: null,
      }),
      usd_views: [
        {
          state: "finite",
          operation: "search",
          remaining_usd: "100",
          local_remaining_usd: null,
          request_cost_usd: "0.005",
          shared_pool_id: "you:keyed:daily-search",
          possible_standard_calls: "100",
          price_version: "v2026-09",
          priced: true,
        },
        {
          state: "finite",
          operation: "fetch",
          remaining_usd: "199.52",
          local_remaining_usd: null,
          request_cost_usd: "0.001",
          shared_pool_id: "youcom:keyed:usd",
          possible_standard_calls: "199520",
          price_version: "v2026-09",
          priced: true,
        },
      ] as never,
      detail: detail({ reset_rule: "unknown" }),
    })
  }

  it("adds the daily pool to the credit-derived searches without inventing a reset", () => {
    const info = providerInfo(youcomAuth(), "youcom")
    const searchesLeft = info.facts.find((fact) => fact.label === "Searches left")
    // Daily 100 + floor(199520/5) = 100 + 39904 = 40004.
    expect(searchesLeft?.value).toBe("40,004")
    expect(searchesLeft?.note).toBe(null)
    const fetchesLeft = info.facts.find((fact) => fact.label === "Fetches left")
    expect(fetchesLeft?.value).toBe("199,520")
  })

  it("keeps the pool-projected search view verbatim without double-counting", () => {
    const base = youcomAuth()
    const pooled = {
      ...base,
      usd_views: [
        {
          state: "finite",
          operation: "search",
          remaining_usd: "95.5",
          local_remaining_usd: null,
          request_cost_usd: "0.005",
          shared_pool_id: "youcom:keyed:usd",
          possible_standard_calls: "19100",
          price_version: "v2026-09",
          priced: true,
        },
        {
          state: "finite",
          operation: "fetch",
          remaining_usd: "95.5",
          local_remaining_usd: null,
          request_cost_usd: "0.001",
          shared_pool_id: "youcom:keyed:usd",
          possible_standard_calls: "95500",
          price_version: "v2026-09",
          priced: true,
        },
      ],
    } as unknown as ProviderAuthLimits
    const info = providerInfo(pooled, "youcom")
    expect(info.facts.find((fact) => fact.label === "Searches left")?.value).toBe("19,100")
    expect(info.facts.find((fact) => fact.label === "Fetches left")?.value).toBe("95,500")
  })
})
