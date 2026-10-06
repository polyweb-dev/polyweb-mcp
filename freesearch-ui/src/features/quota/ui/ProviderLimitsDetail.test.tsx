import { describe, expect, it, vi } from "vitest"
import { render, screen } from "@testing-library/react"
import type { ProviderAuthLimits } from "@/domains/dashboard"
import { ProviderLimitsDetail } from "./ProviderLimitsDetail"

/**
 * UI7 detail: known fields only, no Unknown/n/a/dash rows, fetch rows
 * gated by operation support, safe usage links only. Covers UI7-01, UI7-04.
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

describe("ProviderLimitsDetail", () => {
  it("shows known vendor rows with no invented placeholder (UI7-01)", () => {
    render(<ProviderLimitsDetail providerName="Brave" auth={authFixture()} />)
    expect(screen.getByText("Brave Search")).not.toBeNull()
    expect(screen.getByText("0.005")).not.toBeNull()
    expect(screen.queryByText("Unknown")).toBe(null)
    expect(screen.queryByText("n/a")).toBe(null)
    expect(screen.queryByText("Not reported")).toBe(null)
  })

  it("labels the balance Remaining balance with dollar form and human pool name (final-polish 3a, 3d, 3e)", () => {
    render(<ProviderLimitsDetail providerName="Brave" auth={authFixture()} />)
    expect(screen.getByText("Remaining balance")).not.toBeNull()
    expect(screen.queryByText("Native balance")).toBe(null)
    expect(screen.getByText("$4.5")).not.toBeNull()
    expect(screen.getByText("Native allowance")).not.toBeNull()
    expect(screen.getByText("$5")).not.toBeNull()
    expect(screen.getByText("Keyed USD: $4.5 left of $5")).not.toBeNull()
    expect(screen.queryByText("brave:keyed:usd")).toBe(null)
    expect(screen.queryByText("4.500 USD")).toBe(null)
  })

  it("groups credit units above plain facts above USD amounts with no alternation (final-polish 3b)", () => {
    render(<ProviderLimitsDetail providerName="Brave" auth={authFixture()} />)
    const labels = Array.from(document.querySelectorAll("dt")).map((entry) => entry.textContent)
    expect(labels[0]).toBe("Search CRD cost")
    const usdLabels = ["Remaining balance", "Native allowance", "USD per call", "Aggregate pool"]
    const firstUsd = Math.min(...usdLabels.map((label) => labels.indexOf(label)))
    expect(firstUsd).toBeGreaterThan(0)
    for (const label of usdLabels) {
      expect(labels.indexOf(label)).toBeGreaterThanOrEqual(firstUsd)
    }
    expect(labels.slice(-4)).toEqual(usdLabels)
    expect(screen.queryByText("Native balance")).toBe(null)
  })

  it("hides the fetch cost row without fetch support (UI7-04)", () => {
    render(<ProviderLimitsDetail providerName="Brave" auth={authFixture()} />)
    expect(screen.getByText("Search CRD cost")).not.toBeNull()
    expect(screen.queryByText("Fetch CRD cost")).toBe(null)
  })

  it("opens the safe usage link with noopener and noreferrer (UI7-01)", () => {
    render(<ProviderLimitsDetail providerName="Brave" auth={authFixture()} />)
    const link = screen.getByRole("link", { name: "Brave usage page" })
    expect(link.getAttribute("href")).toBe("https://api-dashboard.search.brave.com/")
    expect(link.getAttribute("target")).toBe("_blank")
    expect(link.getAttribute("rel")).toContain("noopener")
    expect(link.getAttribute("rel")).toContain("noreferrer")
    void vi
  })

  it("keeps exact zero as known data (UI7-01)", () => {
    const auth = authFixture()
    const detail = { ...(auth.detail as object), actual_spend_usd: "0" } as never
    render(<ProviderLimitsDetail providerName="Brave" auth={{ ...auth, detail }} />)
    expect(screen.getByText("0")).not.toBeNull()
  })
})
