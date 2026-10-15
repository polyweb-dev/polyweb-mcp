import { describe, expect, it } from "vitest"
import { render, screen } from "@testing-library/react"
import { UsageTotals } from "./UsageTotals"

/**
 * Tavily native usage totals: converted Credits state themselves in their own
 * block while every other provider keeps its CRD rows.
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

function tavilyLimits() {
  const search = {
    provider: "tavily",
    operation: "search",
    auth_mode: "keyed",
    supported: true,
    transport_available: true,
    native_pool_id: "tavily:keyed:credits",
    rate: null,
    budget: null,
    conversion_profile: tavilyProfile(),
    plan_name: "Tavily",
    usage_url: null,
    version: 2,
  }
  const fetch = {
    provider: "tavily",
    operation: "fetch",
    auth_mode: "keyed",
    supported: true,
    transport_available: true,
    native_pool_id: "tavily:keyed:credits",
    rate: null,
    budget: null,
    conversion_profile: tavilyProfile(),
    plan_name: "Tavily",
    usage_url: null,
    version: 2,
  }
  return {
    provider: "tavily",
    active_auth_mode: "keyed",
    auths: [
      {
        auth_mode: "keyed",
        transport_available: true,
        search,
        fetch,
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
  }
}

function providers() {
  return [
    { id: "brave", name: "Brave", latencyP95Ms: null },
    { id: "tavily", name: "Tavily", latencyP95Ms: null },
  ]
}

describe("UsageTotals native Credits", () => {
  it("separates Tavily native Credits from other providers CRD rows", () => {
    render(
      <UsageTotals
        crdUsageTotals={[
          { provider: "brave", operation: "search", normalized_crd: "5", attempt_count: 1, volume_count: 1 },
          { provider: "tavily", operation: "search", normalized_crd: "8", attempt_count: 1, volume_count: 1 },
          { provider: "tavily", operation: "fetch", normalized_crd: "16", attempt_count: 2, volume_count: 10 },
        ]}
        providers={providers() as never}
        providerLimits={[tavilyLimits()] as never}
      />,
    )
    expect(screen.getByText("Credit-unit use")).not.toBeNull()
    expect(screen.getByText("Tavily native Credits use")).not.toBeNull()
    expect(screen.getByText("5 CRD")).not.toBeNull()
    expect(screen.queryByText("8 CRD")).toBeNull()
    expect(screen.queryByText("16 CRD")).toBeNull()
    expect(screen.getByText("1 Credit")).not.toBeNull()
    expect(screen.getByText("2 Credits")).not.toBeNull()
    expect(screen.getAllByText("extract")).toHaveLength(2)
  })

  it("keeps recorded CRD rows unchanged without price profiles", () => {
    render(
      <UsageTotals
        crdUsageTotals={[
          { provider: "tavily", operation: "search", normalized_crd: "8", attempt_count: 1, volume_count: 1 },
        ]}
        providers={providers() as never}
      />,
    )
    expect(screen.getByText("8 CRD")).not.toBeNull()
    expect(screen.queryByText("Tavily native Credits use")).toBeNull()
  })
})
