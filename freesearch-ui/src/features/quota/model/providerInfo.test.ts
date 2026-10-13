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

describe("providerInfo Tavily native", () => {
  function tavilyProfile() {
    return {
      reference_usd_per_crd: "0.001",
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
      crd_views: [
        {
          state: "finite",
          operation: "search",
          remaining_crd: "7992",
          local_remaining_crd: null,
          request_cost_crd: "8",
          shared_pool_id: "tavily:keyed:credits",
          possible_standard_calls: "999",
          price_version: "paygo-reference",
          priced: true,
        },
        {
          state: "finite",
          operation: "fetch",
          remaining_crd: "7992",
          local_remaining_crd: null,
          request_cost_crd: "8",
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

  it("states 1 and 2 Credits search costs", () => {
    const info = providerInfo(tavilyAuth(), "tavily")
    const search = info.facts.find((fact) => fact.label === "Search cost")
    expect(search?.value).toBe("1 Credit")
    expect(search?.note).toBe("(advanced: 2 Credits)")
  })

  it("states 1 to 2 Credits per five URLs extract costs with the Extract label", () => {
    const info = providerInfo(tavilyAuth(), "tavily")
    const extract = info.facts.find((fact) => fact.label === "Extract cost")
    expect(extract?.value).toContain("per 5 URLs")
    expect(extract?.note).toContain("advanced:")
    expect(info.facts.some((fact) => fact.label === "Fetch cost")).toBe(false)
    expect(info.facts.some((fact) => fact.label === "Fetch CRD cost")).toBe(false)
    expect(info.facts.some((fact) => fact.label === "Extract CRD cost")).toBe(true)
  })

  it("shares one minute headroom and states the Retry-After delay", () => {
    const info = providerInfo(tavilyAuth(), "tavily")
    const headroom = info.facts.find((fact) => fact.label === "Minute headroom")
    expect(headroom?.value).toBe("95/100")
    expect(headroom?.note).toBe("(shared search and extract)")
    const retry = info.facts.find((fact) => fact.label === "Retry-After")
    expect(retry?.value).toBe("12 s")
  })

  it("keeps USD inside the disclosure cost note while native rows carry no USD", () => {
    const info = providerInfo(tavilyAuth(), "tavily")
    const native = info.facts.find((fact) => fact.label === "Search cost")
    expect(native?.value).not.toContain("$")
    expect(native?.note).not.toContain("$")
    const crd = info.facts.find((fact) => fact.label === "Search CRD cost")
    expect(crd?.note).toContain("$")
  })

  it("shows keyless numeric headroom as unknown with no minute row", () => {
    const info = providerInfo(
      tavilyAuth({ auth_mode: "keyless", detail: detail({ rate_windows: [] }) }),
      "tavily",
    )
    expect(info.facts.some((fact) => fact.label === "Minute headroom")).toBe(false)
  })
})

describe("providerInfo wholeRequests", () => {
  function view(operation: "search" | "fetch", calls: string | null): Record<string, unknown> {
    return {
      state: "finite",
      operation,
      remaining_crd: "400000",
      local_remaining_crd: null,
      request_cost_crd: "4",
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

  it("floors integer standard calls with the opt-in flag", () => {
    const base = auth({
      search: record("keenable", { supported: true, transport_available: true }),
      fetch: record("keenable", {
        operation: "fetch",
        supported: true,
        transport_available: true,
      }),
      crd_views: [
        view("search", "99995.00000000"),
        view("fetch", "99995.00000000"),
      ] as never,
      detail: detail({ reset_rule: "vendor_period" }),
    })
    const whole = providerInfo(base, "keenable", true)
    expect(
      whole.facts.filter((fact) => fact.label === "Searches left").map((fact) => fact.value),
    ).toEqual(["99995"])
    expect(
      whole.facts.filter((fact) => fact.label === "Fetches left").map((fact) => fact.value),
    ).toEqual(["99995"])
  })

  it("keeps decimal standard calls without the opt-in flag", () => {
    const base = auth({
      search: record("keenable", { supported: true, transport_available: true }),
      crd_views: [view("search", "99995.00000000")] as never,
      detail: detail({ reset_rule: "vendor_period" }),
    })
    const current = providerInfo(base)
    expect(
      current.facts.filter((fact) => fact.label === "Searches left").map((fact) => fact.value),
    ).toEqual(["99995.00000000"])
  })

  it("floors request rate limits only with the opt-in flag", () => {
    const base = auth({
      detail: detail({
        rate_windows: [window("1000.00000000", "requests")] as never,
      }),
    })
    expect(providerInfo(base).facts.map((fact) => fact.value)).toContain("1000.00000000 req/sec")
    expect(providerInfo(base, "keenable", true).facts.map((fact) => fact.value)).toContain("1000 req/sec")
  })

  it("keeps URL rate limits verbatim with the opt-in flag", () => {
    const base = auth({
      detail: detail({ rate_windows: [window("10.5", "urls")] as never }),
    })
    expect(providerInfo(base, "keenable", true).facts.map((fact) => fact.value)).toContain("10.5 urls/sec")
  })

  it("omits invalid counts instead of a fabricated zero", () => {
    const base = auth({
      search: record("keenable", { supported: true, transport_available: true }),
      crd_views: [view("search", "lots")] as never,
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
      reference_usd_per_crd: "0.001",
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
      crd_views: [
        { ...view("search", "99995"), request_cost_crd: "4" },
        { ...view("fetch", "99995"), request_cost_crd: "4" },
      ] as never,
      detail: detail({ reset_rule: "monthly_first" }),
    })
    const info = providerInfo(base, "keenable", true)
    expect(info.facts.map((fact) => fact.label)).toContain("Search CRD cost")
    expect(info.facts.map((fact) => fact.label)).toContain("Fetch CRD cost")
    expect(info.creditNote).toBe("Monthly Credits")
    const searchCost = info.facts.find((fact) => fact.label === "Search CRD cost")
    expect(searchCost?.note).toContain("$0.004")
  })

  it("keeps exact input strings unchanged", () => {
    const base = auth({
      search: record("keenable", { supported: true, transport_available: true }),
      crd_views: [view("search", "99995.00000000")] as never,
      detail: detail({ reset_rule: "vendor_period" }),
    })
    const first = providerInfo(base, "keenable", true)
    const second = providerInfo(base, "keenable", true)
    expect(first).toEqual(second)
    expect(base.crd_views[0]).toMatchObject({ possible_standard_calls: "99995.00000000" })
  })
})
