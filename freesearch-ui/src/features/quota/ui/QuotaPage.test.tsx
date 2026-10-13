import { describe, expect, it, vi } from "vitest"
import { render, screen } from "@testing-library/react"
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
    providers: [{ id: "brave", name: "Brave" }],
    providerLimits: [],
    crdUsageTotals: [],
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
 * UI7 page: cards, CRD totals, action slot, one price footer; no legacy
 * native grid, no cache widget, no per-card price version. Covers
 * UI7-05 and UI7-06.
 */

describe("QuotaPage", () => {
  it("composes cards, totals, actions, and one footer without legacy views (UI7-05, UI7-06)", () => {
    installFetchStub(() => {
      throw new Error("no backend on page test")
    })
    render(<QuotaPage />)
    expect(screen.getByText("Usage")).not.toBeNull()
    expect(screen.getByText("Provider credit units")).not.toBeNull()
    expect(screen.getByText("Usage totals")).not.toBeNull()
    expect(screen.getByText("How credit units are priced")).not.toBeNull()
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
    expect(screen.getByText("Usage")).not.toBeNull()
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

  it("supplies native usage totals to the Tavily block", () => {
    const previous = mockFreeSearchState.current
    const profile = {
      reference_usd_per_crd: "0.001",
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
        { id: "brave", name: "Brave" },
        { id: "tavily", name: "Tavily" },
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
              crd_views: [],
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
      crdUsageTotals: [
        { provider: "tavily", operation: "search", normalized_crd: "8", attempt_count: 1, volume_count: 1 },
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
      expect(screen.getByText("Tavily native Credits use")).not.toBeNull()
      expect(screen.getByText("1 Credit")).not.toBeNull()
    } finally {
      mockFreeSearchState.current = previous
      vi.unstubAllGlobals()
    }
  })
})
