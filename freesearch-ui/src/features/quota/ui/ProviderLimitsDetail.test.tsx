import { describe, expect, it } from "vitest"
import { render, screen } from "@testing-library/react"
import type { ProviderAuthLimits } from "@/domains/dashboard"
import { ProviderLimitsDetail } from "./ProviderLimitsDetail"

/**
 * CARD-2 detail: vendor spend + reset + budget-limit rows only.
 * Plan, USD per call, CRD cost rows and the usage link live in the popover.
 * Covers CARD-2 kept-row set and order.
 */

function authFixture(): ProviderAuthLimits {
  return {
    auth_mode: "keyed",
    transport_available: true,
    search: {
      provider: "brave",
      operation: "search",
      auth_mode: "keyed",
      supported: true,
      transport_available: true,
      native_pool_id: "brave:keyed:usd",
      rate: null,
      budget: null,
      conversion_profile: {
        reference_usd_per_crd: "0.001",
        native_usd_per_unit: "1",
        cost_basis: "priced_native_use",
        price_version: "v2026-09",
        source: "documented",
        estimated: false,
      },
      plan_name: "Brave Search",
      usage_url: "https://api-dashboard.search.brave.com/",
      version: 1,
    },
    fetch: {
      provider: "brave",
      operation: "fetch",
      auth_mode: "keyed",
      supported: false,
      transport_available: false,
      native_pool_id: null,
      rate: null,
      budget: null,
      conversion_profile: {
        reference_usd_per_crd: "0.001",
        native_usd_per_unit: null,
        cost_basis: "priced_native_use",
        price_version: "",
        source: "",
        estimated: false,
      },
      plan_name: null,
      usage_url: null,
      version: 1,
    },
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
      reset_at: null,
      observed_at: null,
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
    detail: {
      plan_name: "Brave Search",
      native_unit: "USD",
      native_balance: "4.500",
      native_allowance: "5.000",
      usd_per_call: "0.005",
      actual_spend_usd: null,
      reset_at: null,
      reset_rule: "vendor_period",
      usage_url: "https://api-dashboard.search.brave.com/",
      source: "vendor_headers",
      confidence: "observed",
      last_sync_at: "2026-09-06T10:05:00Z",
      stale: false,
      price_version: "v2026-09",
      crd_split_note: null,
      rate_windows: [
        {
          bucket_id: "brave:search:1s",
          limit: "50",
          window: "1s",
          scope: "org",
          unit: "requests",
          remaining: "50",
          reset_at: null,
          source: "vendor_headers",
          confidence: "observed",
        },
      ],
      tier_split_known: true,
      aggregate_pool_id: "brave:keyed:usd",
    },
  } as unknown as ProviderAuthLimits
}

function grantsFixture() {
  return {
    provider: "brave",
    auth_mode: "keyed",
    period_start: "2026-09-01",
    period_end: "2026-09-30",
    version: 3,
    search_granted_crd: "100",
    search_consumed_crd: "12",
    search_reserved_crd: "0",
    fetch_granted_crd: "50",
    fetch_consumed_crd: "5",
    fetch_reserved_crd: "0",
  }
}

function withSpend(auth: ProviderAuthLimits, spend: string | null): ProviderAuthLimits {
  const detail = { ...(auth.detail as object), actual_spend_usd: spend } as never
  return { ...auth, detail }
}

function withGrants(auth: ProviderAuthLimits, grants: unknown): ProviderAuthLimits {
  return { ...auth, grants: grants as never }
}

function withFetchSupport(auth: ProviderAuthLimits): ProviderAuthLimits {
  return {
    ...auth,
    fetch: {
      ...(auth.fetch as object),
      supported: true,
      transport_available: true,
    } as never,
  }
}

function labels(): Array<string | null> {
  return Array.from(document.querySelectorAll("dt")).map((entry) => entry.textContent)
}

describe("ProviderLimitsDetail", () => {
  it("hides the plan, call price, CRD cost rows and usage link that the popover owns (CARD-2)", () => {
    render(<ProviderLimitsDetail providerName="Brave" auth={authFixture()} />)
    expect(screen.queryByText("Brave Search")).toBe(null)
    expect(screen.queryByText("0.005")).toBe(null)
    expect(screen.queryByText("Search CRD cost")).toBe(null)
    expect(screen.queryByText("Fetch CRD cost")).toBe(null)
    expect(screen.queryByRole("link", { name: "Brave usage page" })).toBe(null)
    expect(screen.queryByText("Remaining balance")).toBe(null)
    expect(screen.queryByText("Native balance")).toBe(null)
    expect(screen.queryByText("Native allowance")).toBe(null)
    expect(screen.queryByText("Aggregate pool")).toBe(null)
    expect(screen.queryByText("Unknown")).toBe(null)
    expect(screen.queryByText("n/a")).toBe(null)
    expect(screen.queryByText("Not reported")).toBe(null)
  })

  it("keeps the vendor reset row with exact text (CARD-2)", () => {
    render(<ProviderLimitsDetail providerName="Brave" auth={authFixture()} />)
    expect(screen.getByText("Reset")).not.toBeNull()
    expect(screen.getByText("Resets on the vendor period")).not.toBeNull()
  })

  it("keeps the vendor spend row with exact label when known (CARD-2)", () => {
    render(<ProviderLimitsDetail providerName="Brave" auth={withSpend(authFixture(), "1.23")} />)
    expect(screen.getByText("Vendor-reported USD spend")).not.toBeNull()
    expect(screen.getByText("1.23")).not.toBeNull()
  })

  it("shows no spend row without a known spend (CARD-2)", () => {
    render(<ProviderLimitsDetail providerName="Brave" auth={authFixture()} />)
    expect(screen.queryByText("Vendor-reported USD spend")).toBe(null)
  })

  it("shows the spend-cap period and search budget rows when grants exist (CARD-2)", () => {
    render(
      <ProviderLimitsDetail
        providerName="Brave"
        auth={withGrants(authFixture(), grantsFixture())}
      />,
    )
    expect(screen.getByText("Budget Limit period")).not.toBeNull()
    expect(screen.getByText("Search budget limit")).not.toBeNull()
    expect(screen.queryByText("Fetch budget limit")).toBe(null)
  })

  it("locks the kept-row set and order: credit units, plain facts, USD last (CARD-2)", () => {
    const auth = withGrants(withSpend(withFetchSupport(authFixture()), "1.23"), grantsFixture())
    render(<ProviderLimitsDetail providerName="Brave" auth={auth} />)
    expect(labels()).toEqual([
      "Search budget limit",
      "Fetch budget limit",
      "Reset",
      "Budget Limit period",
      "Vendor-reported USD spend",
    ])
  })

  it("keeps exact zero as known data (UI7-01)", () => {
    render(<ProviderLimitsDetail providerName="Brave" auth={withSpend(authFixture(), "0")} />)
    expect(screen.getByText("Vendor-reported USD spend")).not.toBeNull()
    expect(screen.getByText("0")).not.toBeNull()
  })

  it("renders no block without a known row or split note (CARD-2)", () => {
    const auth = authFixture()
    const detail = { ...(auth.detail as object), reset_rule: "unknown" } as never
    const { container } = render(
      <ProviderLimitsDetail providerName="Brave" auth={{ ...auth, detail, grants: null }} />,
    )
    expect(container.firstChild).toBe(null)
  })

  it("shows Tavily local caps in Credits through the conversion context", () => {
    const grants = {
      provider: "tavily",
      auth_mode: "keyed",
      period_start: "2026-09-01",
      period_end: "2026-09-30",
      version: 3,
      search_granted_crd: "8",
      search_consumed_crd: "0",
      search_reserved_crd: "0",
      fetch_granted_crd: "16",
      fetch_consumed_crd: "0",
      fetch_reserved_crd: "0",
    }
    const profile = {
      reference_usd_per_crd: "0.001",
      native_usd_per_unit: "0.008",
      cost_basis: "paygo_reference",
      price_version: "paygo-reference",
      source: "documented",
      estimated: true,
    }
    const auth = withGrants(withFetchSupport(authFixture()), grants)
    render(
      <ProviderLimitsDetail
        providerName="Tavily"
        auth={auth}
        nativeDisplay={{ credits: {} as never, profile } as never}
      />,
    )
    expect(screen.getByText("Search budget limit")).not.toBeNull()
    expect(screen.getByText("Extract budget limit")).not.toBeNull()
    expect(screen.getByText("1 Tavily Credit set, 0 Tavily Credits used")).not.toBeNull()
    expect(screen.getByText("2 Tavily Credits set, 0 Tavily Credits used")).not.toBeNull()
    expect(screen.queryByText("8 CRD")).toBeNull()
  })

  it("keeps CRD caps without a conversion profile", () => {
    const grants = {
      provider: "tavily",
      auth_mode: "keyed",
      period_start: "2026-09-01",
      period_end: "2026-09-30",
      version: 3,
      search_granted_crd: "8",
      search_consumed_crd: "0",
      search_reserved_crd: "0",
      fetch_granted_crd: "16",
      fetch_consumed_crd: "0",
      fetch_reserved_crd: "0",
    }
    const auth = withGrants(withFetchSupport(authFixture()), grants)
    render(<ProviderLimitsDetail providerName="Tavily" auth={auth} />)
    expect(screen.getByText("Fetch budget limit")).not.toBeNull()
    expect(screen.queryByText("Extract budget limit")).toBeNull()
  })
})

/**
 * Tavily native vendor detail: integer Credits caps, trimmed USD spend,
 * Extract vocab, unknown facts stay absent, generic output unchanged.
 */

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

function tavilyGrants(searchGranted: string, fetchGranted: string) {
  return {
    provider: "tavily",
    auth_mode: "keyed",
    period_start: "2026-09-01",
    period_end: "2026-09-30",
    version: 3,
    search_granted_crd: searchGranted,
    search_consumed_crd: "0",
    search_reserved_crd: "0",
    fetch_granted_crd: fetchGranted,
    fetch_consumed_crd: "0",
    fetch_reserved_crd: "0",
  }
}

describe("ProviderLimitsDetail nativeDisplay", () => {
  it("floors fractional grant caps to whole Tavily Credits", () => {
    const auth = withGrants(withFetchSupport(authFixture()), tavilyGrants("9.9", "17.9"))
    render(
      <ProviderLimitsDetail
        providerName="Tavily"
        auth={auth}
        nativeDisplay={{ credits: {} as never, profile: tavilyProfile() } as never}
      />,
    )
    expect(screen.getByText("1 Tavily Credit set, 0 Tavily Credits used")).not.toBeNull()
    expect(screen.getByText("2 Tavily Credits set, 0 Tavily Credits used")).not.toBeNull()
  })

  it("trims USD spend zeros for the native rail", () => {
    const auth = withSpend(authFixture(), "1.230000000")
    render(
      <ProviderLimitsDetail
        providerName="Tavily"
        auth={auth}
        nativeDisplay={{ credits: {} as never, profile: tavilyProfile() } as never}
      />,
    )
    expect(screen.getByText("1.23")).not.toBeNull()
  })

  it("keeps exact USD spend for other providers", () => {
    render(<ProviderLimitsDetail providerName="Brave" auth={withSpend(authFixture(), "1.230000000")} />)
    expect(screen.getByText("1.230000000")).not.toBeNull()
  })

  it("names the Tavily fetch cap Extract with native input and Fetch without it", () => {
    const grants = tavilyGrants("8", "16")
    const native = withGrants(withFetchSupport(authFixture()), grants)
    const { unmount } = render(
      <ProviderLimitsDetail
        providerName="Tavily"
        auth={native}
        nativeDisplay={{ credits: {} as never, profile: tavilyProfile() } as never}
      />,
    )
    expect(screen.getByText("Extract budget limit")).not.toBeNull()
    unmount()
    render(<ProviderLimitsDetail providerName="Tavily" auth={withGrants(withFetchSupport(authFixture()), grants)} />)
    expect(screen.getByText("Fetch budget limit")).not.toBeNull()
  })

  it("shows no grant rows without stored grants", () => {
    const auth = authFixture()
    render(
      <ProviderLimitsDetail
        providerName="Tavily"
        auth={auth}
        nativeDisplay={{ credits: {} as never, profile: tavilyProfile() } as never}
      />,
    )
    expect(screen.queryByText("Search budget limit")).toBe(null)
    expect(screen.queryByText("Extract budget limit")).toBe(null)
  })
})
