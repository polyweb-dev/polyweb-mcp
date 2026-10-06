import { describe, expect, it, vi } from "vitest"
import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import type { CRDUsageTotal, CRDView, LimitRecord, ProviderAuthLimits, ProviderLimits } from "@/domains/dashboard"
import { installFetchStub, ok } from "@/test/fetchMock"
import { ProviderLimitsCard } from "./ProviderLimitsCard"

vi.mock("../model/useManualQuota", () => ({
  useManualQuota: () => ({
    manual: null,
    estimate: null,
    save: () => Promise.resolve({}),
    remove: () => Promise.resolve({}),
  }),
}))

/**
 * UI7 Brave card: one credit bar with percent on the right, CRD and USD
 * below the bar, unknown fields hidden, fetch controls gated, dialogs for
 * grant/history/manual. Replaces the S1 n/a and inline-grant expectations
 * per UI7-01, UI7-02, UI7-04, UI7-08.
 */

function searchView(): CRDView {
  return {
    state: "finite",
    operation: "search",
    remaining_crd: "4500",
    local_remaining_crd: null,
    request_cost_crd: "5",
    shared_pool_id: "brave:keyed:usd",
    possible_standard_calls: "900",
    price_version: "v2026-09",
    priced: true,
  }
}

function fetchView(): CRDView {
  return {
    state: "unavailable",
    operation: "fetch",
    remaining_crd: null,
    local_remaining_crd: null,
    request_cost_crd: null,
    shared_pool_id: null,
    possible_standard_calls: null,
    price_version: null,
    priced: false,
  }
}

function searchRecord(): LimitRecord {
  return {
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
  }
}

function fetchRecord(): LimitRecord {
  return {
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
      price_version: "v2026-09",
      source: "documented",
      estimated: false,
    },
    plan_name: null,
    usage_url: null,
    version: 1,
  }
}

function braveAuth(): ProviderAuthLimits {
  return {
    auth_mode: "keyed",
    transport_available: true,
    search: searchRecord(),
    fetch: fetchRecord(),
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
      reset_at: "2026-10-01T00:00:00Z",
      observed_at: "2026-09-06T10:05:00Z",
      version: 1,
      credential_generation: 1,
      next_sync_at: null,
      stale: false,
      manual_anchor: false,
    },
    crd_views: [searchView(), fetchView()],
    rate_progress: [],
    grants: null,
    detail: null,
  }
}

function braveLimits(): ProviderLimits {
  return {
    provider: "brave",
    active_auth_mode: "keyed",
    auths: [braveAuth()],
    documented_keyless_operations: [],
    version: 1,
    generated_at: "2026-03-10T12:00:00Z",
  }
}

function noUseTotals(): CRDUsageTotal[] {
  return []
}

function renderBraveCard(): void {
  installFetchStub(() => {
    throw new Error("no backend in card test")
  })
  render(
    <ProviderLimitsCard
      providerId="brave"
      providerName="Brave"
      limits={braveLimits()}
      crdUsageTotals={noUseTotals()}
      refreshDashboard={() => Promise.resolve()}
      manualEligible
    />,
  )
}

describe("ProviderLimitsCard Brave", () => {
  it("shows one credit bar with 90 percent, CRD and USD, and no fetch headline (UI7-01, UI7-02, UI7-04)", () => {
    renderBraveCard()
    const bar = screen.getByRole("progressbar", { name: "Brave credit units remaining" })
    expect(bar.getAttribute("aria-valuenow")).toBe("90")
    expect(bar.getAttribute("aria-valuemin")).toBe("0")
    expect(bar.getAttribute("aria-valuemax")).toBe("100")
    expect(screen.getByText("90%")).not.toBeNull()
    expect(screen.getByText("4500 CRD")).not.toBeNull()
    expect(screen.getByText("4.500")).not.toBeNull()
    // Polish Item 6: no auth_mode chip, no "keyed rail" text on the card.
    expect(screen.queryByText("keyed rail")).toBeNull()
    expect(screen.queryByText("n/a")).toBeNull()
    expect(screen.queryByText("Fetch credit units left")).toBeNull()
    expect(screen.queryByText(/keyless/i)).toBeNull()
    vi.unstubAllGlobals()
  })

  it("exposes an accessible sync control without firing vendor calls", () => {
    const stub = installFetchStub(() => {
      throw new Error("no backend in card test")
    })
    render(
      <ProviderLimitsCard
        providerId="brave"
        providerName="Brave"
        limits={braveLimits()}
        crdUsageTotals={noUseTotals()}
        refreshDashboard={() => Promise.resolve()}
        manualEligible
      />,
    )
    expect(
      screen.getByRole("button", { name: "Sync limits for Brave" }),
    ).not.toBeNull()
    expect(stub.requestsTo(/limits/).length).toBeLessThan(2)
    vi.unstubAllGlobals()
  })

  it("opens the grant dialog with search only and no fetch field (UI7-04, UI7-08)", async () => {
    installFetchStub(() => ok({ events: [], next_cursor: null }))
    renderBraveCard()
    const user = userEvent.setup()
    await user.click(screen.getByRole("button", { name: "Spend cap for Brave. Sets a local credit-unit ceiling that adds no vendor funds." }))
    expect(await screen.findByText("Search credit units (CRD)")).not.toBeNull()
    expect(screen.queryByLabelText(/Fetch credit units/i)).toBeNull()
    expect(screen.queryByText(/n\/a for this provider/)).toBeNull()
    vi.unstubAllGlobals()
  })

  it("opens the history dialog with a titled modal (UI7-09)", async () => {
    installFetchStub(() => ok({ events: [], next_cursor: null }))
    renderBraveCard()
    const user = userEvent.setup()
    await user.click(screen.getByRole("button", { name: "Balance history for Brave" }))
    expect(await screen.findByText("Balance history")).not.toBeNull()
    vi.unstubAllGlobals()
  })

  it("refreshes card funds from new props without a private limit copy (UI7-03)", () => {
    installFetchStub(() => {
      throw new Error("no backend in card test")
    })
    const { rerender } = render(
      <ProviderLimitsCard
        providerId="brave"
        providerName="Brave"
        limits={braveLimits()}
        crdUsageTotals={noUseTotals()}
        refreshDashboard={() => Promise.resolve()}
        manualEligible
      />,
    )
    expect(screen.getByText("4500 CRD")).not.toBeNull()
    const auth = braveAuth()
    const debited = {
      ...auth,
      aggregate_pool: auth.aggregate_pool === null ? null : { ...auth.aggregate_pool, remaining: "4.495" },
      crd_views: [{ ...searchView(), remaining_crd: "4495" }, fetchView()],
    }
    rerender(
      <ProviderLimitsCard
        providerId="brave"
        providerName="Brave"
        limits={{ ...braveLimits(), auths: [debited] }}
        crdUsageTotals={[{ provider: "brave", operation: "search", normalized_crd: "5", attempt_count: 1, volume_count: 1 }]}
        refreshDashboard={() => Promise.resolve()}
        manualEligible
      />,
    )
    expect(screen.getByText("4495 CRD")).not.toBeNull()
    expect(screen.getByText("89.9%")).not.toBeNull()
    vi.unstubAllGlobals()
  })
})
