import { describe, expect, it, vi } from "vitest"
import { render, screen, within } from "@testing-library/react"
import { QuotaPage } from "./QuotaPage"
import { installFetchStub } from "@/test/fetchMock"

vi.mock("../model/useManualQuota", () => ({
  useManualQuota: () => ({
    manual: null,
    estimate: null,
    save: () => Promise.resolve({}),
    remove: () => Promise.resolve({}),
  }),
}))

vi.mock("@/context/useFreeSearch", () => ({
  useFreeSearch: () => mockFreeSearchState.current,
}))

const mockFreeSearchState = vi.hoisted(() => ({
  current: {
    providers: [{ id: "brave", name: "Brave", capabilities: ["search"] }],
    providerLimits: [],
    usdUsageTotals: [],
    dashboardQuotas: [],
    dashboardNotice: null,
    usageLoading: false,
    usageError: null,
    refreshDashboard: () => Promise.resolve(),
  },
}))

vi.mock("../model/quotaRowModel", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../model/quotaRowModel")>()
  return { ...actual, manualEligibleProviders: () => new Set<string>() }
})

vi.mock("./ProviderActionSlots", () => ({
  ProviderActionSlots: () => null,
}))

/**
 * UI7 page: cards, Usd totals, action slot, one price footer; no legacy
 * native grid, no cache widget, no per-card price version. Covers
 * UI7-05 and UI7-06.
 */

describe("QuotaPage", () => {
  it("composes cards, totals, actions, and one footer without legacy views (UI7-05, UI7-06)", () => {
    installFetchStub(() => {
      throw new Error("no backend on page test")
    })
    render(<QuotaPage />)
    expect(screen.getByRole("heading", { name: "Quotas" })).not.toBeNull()
    expect(screen.getByText("Provider balances and allowances across all projects")).not.toBeNull()
    expect(screen.getByText("Allowance left")).not.toBeNull()
    expect(screen.getByText("Usage totals")).not.toBeNull()
    expect(screen.queryByText("How credit units are priced")).toBeNull()
    expect(screen.queryByText("Provider quota view")).toBe(null)
    expect(screen.queryByText("—")).toBe(null)
    vi.unstubAllGlobals()
  })

  it("retains actionable errors and load status (UI7-05)", () => {
    installFetchStub(() => {
      throw new Error("no backend on page test")
    })
    render(<QuotaPage />)
    expect(screen.queryByRole("alert")).toBe(null)
    expect(screen.getByRole("heading", { name: "Quotas" })).not.toBeNull()
    vi.unstubAllGlobals()
  })

  it("keeps the OAuth action slot without a native table (UI7-05)", () => {
    installFetchStub(() => {
      throw new Error("no backend on page test")
    })
    render(
      <QuotaPage
        renderOAuthActions={({ providerId }) => (
          <button type="button" data-testid={"oauth-stub-" + providerId}>
            Connect
          </button>
        )}
      />,
    )
    expect(screen.queryByText("Provider quota view")).toBe(null)
    vi.unstubAllGlobals()
  })

  it("supplies precise USD usage totals to the Tavily row", () => {
    const previous = mockFreeSearchState.current
    const profile = {
      native_usd_per_unit: "0.008",
      cost_basis: "paygo_reference",
      price_version: "paygo-reference",
      source: "documented",
      estimated: true,
    }
    const search = {
      provider: "tavily",
      operation: "search",
      auth_mode: "keyed",
      supported: true,
      transport_available: true,
      native_pool_id: "tavily:keyed:credits",
      rate: null,
      budget: null,
      conversion_profile: profile,
      plan_name: "Tavily",
      usage_url: null,
      version: 2,
    }
    mockFreeSearchState.current = {
      providers: [
        { id: "brave", name: "Brave", capabilities: ["search"] },
        { id: "tavily", name: "Tavily", capabilities: ["search", "fetch"] },
      ],
      providerLimits: [
        {
          provider: "tavily",
          active_auth_mode: "keyed",
          auths: [
            {
              auth_mode: "keyed",
              transport_available: true,
              search,
              fetch: { ...search, operation: "fetch" },
              free_tiers: [],
              paid_tiers: [],
              unknown_tiers: [],
              tier_split_known: true,
              aggregate_pool: null,
              usd_views: [],
              rate_progress: [],
              grants: null,
              detail: null,
            },
          ],
          documented_keyless_operations: [],
          version: 2,
          generated_at: "2026-09-06T10:05:00Z",
        },
      ],
      usdUsageTotals: [
        { provider: "tavily", operation: "search", spend_usd: "0.008", attempt_count: 1, volume_count: 1 },
      ],
      dashboardQuotas: [],
      dashboardNotice: null,
      usageLoading: false,
      usageError: null,
      refreshDashboard: () => Promise.resolve(),
    } as never
    try {
      installFetchStub(() => {
        throw new Error("no backend on page test")
      })
      render(<QuotaPage />)
      const table = screen.getByRole("table", { name: "Usage totals" })
      const row = within(table).getByRole("row", { name: /Tavily/ })
      expect(within(row).getByText("1")).toBeInTheDocument()
      expect(within(row).getByText("$0.008")).toBeInTheDocument()
      expect(table).not.toHaveTextContent(/Tavily credits?/i)
    } finally {
      mockFreeSearchState.current = previous
      vi.unstubAllGlobals()
    }
  })
})

/**
 * FIX page: QuotaPage forwards the Tavily-only renderRateTier slot to the
 * card list while the OAuth slot composition stays intact.
 */

describe("QuotaPage rate-tier slot (FIX)", () => {
  function pageProfile() {
    return {
      native_usd_per_unit: "0.008",
      cost_basis: "paygo_reference",
      price_version: "paygo-reference",
      source: "documented",
      estimated: true,
    }
  }

  function tavilyLimitsEntry() {
    const record = (operation: string, nativeCost: string) => ({
      provider: "tavily",
      operation,
      auth_mode: "keyed",
      supported: true,
      transport_available: true,
      native_pool_id: "tavily:keyed:credits",
      rate: null,
      budget: {
        model: "credits",
        free_allowance: "1000",
        allowance_unit: "Credits",
        allowance_period: "monthly",
        cost_per_1k: null,
        standard_native_cost: nativeCost,
        usd_per_call: "0.008",
        on_exhausted: "402",
        usage_api: "/usage",
        priced: true,
      },
      conversion_profile: pageProfile(),
      plan_name: "Tavily",
      usage_url: null,
      version: 2,
    })
    return {
      provider: "tavily",
      active_auth_mode: "keyed",
      auths: [
        {
          auth_mode: "keyed",
          transport_available: true,
          search: record("search", "1"),
          fetch: record("fetch", "0.2"),
          free_tiers: [],
          paid_tiers: [],
          unknown_tiers: [],
          tier_split_known: true,
          aggregate_pool: {
            pool_id: "tavily:keyed:credits",
            provider: "tavily",
            auth_mode: "keyed",
            native_unit: "CREDIT",
            remaining: "999",
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
          },
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
          ],
          rate_progress: [],
          grants: null,
          detail: null,
        },
      ],
      documented_keyless_operations: [],
      version: 2,
      generated_at: "2026-09-06T10:05:00Z",
    }
  }

  function braveLimitsEntry() {
    return {
      provider: "brave",
      active_auth_mode: "keyed",
      auths: [
        {
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
              native_usd_per_unit: "1",
              cost_basis: "priced_native_use",
              price_version: "v2026-09",
              source: "documented",
              estimated: false,
            },
            plan_name: "Brave Search",
            usage_url: null,
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
          ],
          rate_progress: [],
          grants: null,
          detail: null,
        },
      ],
      documented_keyless_operations: [],
      version: 1,
      generated_at: "2026-09-06T10:05:00Z",
    }
  }

  it("passes renderRateTier through to the Tavily card only with OAuth intact", () => {
    const previous = mockFreeSearchState.current
    const seen: string[] = []
    let confirmedKind = "missing"
    mockFreeSearchState.current = {
      providers: [
        { id: "tavily", name: "Tavily" },
        { id: "brave", name: "Brave" },
      ],
      providerLimits: [tavilyLimitsEntry(), braveLimitsEntry()],
      usdUsageTotals: [],
      dashboardQuotas: [],
      dashboardNotice: null,
      usageLoading: false,
      usageError: null,
      refreshDashboard: () => Promise.resolve(),
    } as never
    try {
      installFetchStub(() => {
        throw new Error("no backend on page test")
      })
      render(
        <QuotaPage
          renderOAuthActions={({ providerId }) => (
            <button type="button" data-testid={"oauth-stub-" + providerId}>
              Connect
            </button>
          )}
          renderRateTier={(args) => {
            seen.push(args.providerId)
            confirmedKind = typeof args.onConfirmed
            return <span data-testid="tier-stub">Tier</span>
          }}
        />,
      )
      expect([...new Set(seen)]).toEqual(["tavily"])
      expect(confirmedKind).toBe("function")
      expect(screen.getByTestId("tier-stub")).not.toBeNull()
      expect(screen.getByTestId("oauth-stub-tavily")).not.toBeNull()
      expect(screen.getByTestId("oauth-stub-brave")).not.toBeNull()
    } finally {
      mockFreeSearchState.current = previous
      vi.unstubAllGlobals()
    }
  })
})
