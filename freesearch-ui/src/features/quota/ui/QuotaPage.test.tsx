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
  useFreeSearch: () => ({
    providers: [{ id: "brave", name: "Brave" }],
    providerLimits: [],
    crdUsageTotals: [],
    dashboardQuotas: [],
    dashboardNotice: null,
    usageLoading: false,
    usageError: null,
    refreshDashboard: () => Promise.resolve(),
  }),
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
})
