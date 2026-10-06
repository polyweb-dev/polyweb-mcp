import { describe, expect, it, vi } from "vitest"
import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import type { CRDView, LimitRecord, ProviderAuthLimits, ProviderLimits } from "@/domains/dashboard"
import { installFetchStub } from "@/test/fetchMock"
import { ProviderLimitsCard } from "./ProviderLimitsCard"

/**
 * S1 Brave card: keyed search is finite, fetch is n/a, no keyless rail,
 * and the grant form grants search units only. Mock fetch only; the card
 * renders from props when the hook load cannot reach a backend.
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
    price_version: "crd-usd-0.001",
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
      native_usd_per_unit: "0.005",
      cost_basis: "priced_native_use",
      price_version: "crd-usd-0.001",
      source: "documented",
      estimated: false,
    },
    plan_name: "Monthly search credit",
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
      price_version: "crd-usd-0.001",
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
    aggregate_pool: null,
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

function renderBraveCard(): void {
  installFetchStub(() => {
    throw new Error("no backend in card test")
  })
  render(<ProviderLimitsCard providerId="brave" providerName="Brave" limits={braveLimits()} />)
}

describe("ProviderLimitsCard Brave", () => {
  it("shows finite search units with an n/a fetch headline on one keyed rail", () => {
    renderBraveCard()
    expect(screen.getByText("Search credit units left")).not.toBeNull()
    expect(screen.getByText("4500 CRD")).not.toBeNull()
    expect(screen.getByText("Fetch credit units left")).not.toBeNull()
    expect(screen.getByText("n/a")).not.toBeNull()
    expect(screen.getByText("keyed rail")).not.toBeNull()
    expect(screen.queryByText(/keyless/i)).toBeNull()
  })

  it("exposes an accessible sync control without firing vendor calls", () => {
    const stub = installFetchStub(() => {
      throw new Error("no backend in card test")
    })
    render(<ProviderLimitsCard providerId="brave" providerName="Brave" limits={braveLimits()} />)
    expect(
      screen.getByRole("button", { name: "Sync limits for Brave" })
    ).not.toBeNull()
    expect(stub.requestsTo(/limits/).length).toBeLessThan(2)
    vi.unstubAllGlobals()
  })

  it("grants search units only with the fetch field absent after expand", async () => {
    renderBraveCard()
    const user = userEvent.setup()
    await user.click(screen.getByRole("button", { name: "Show detail" }))
    expect(await screen.findByText(/n\/a for this provider/)).not.toBeNull()
    expect(screen.queryByLabelText(/fetch/i)).toBeNull()
    vi.unstubAllGlobals()
  })
})
