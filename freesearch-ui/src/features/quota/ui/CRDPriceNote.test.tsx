import { describe, expect, it } from "vitest"
import { render, screen } from "@testing-library/react"
import { CRDPriceNote } from "./CRDPriceNote"

/** UI7 price note: per-operation provider costs, with free tiers marked inline. */

function profile(overrides: Record<string, unknown> = {}) {
  return {
    reference_usd_per_crd: "0.001",
    native_usd_per_unit: "1",
    cost_basis: "priced_native_use",
    price_version: "v2026-09",
    source: "documented",
    estimated: false,
    ...overrides,
  }
}

function braveLimits() {
  const search = {
    provider: "brave",
    operation: "search",
    auth_mode: "keyed",
    supported: true,
    transport_available: true,
    native_pool_id: "brave:keyed:usd",
    rate: null,
    budget: null,
    conversion_profile: profile(),
    plan_name: "Brave Search",
    usage_url: null,
    version: 1,
  }
  const fetch = {
    provider: "brave",
    operation: "fetch",
    auth_mode: "keyed",
    supported: false,
    transport_available: false,
    native_pool_id: null,
    rate: null,
    budget: null,
    conversion_profile: profile({ native_usd_per_unit: null }),
    plan_name: null,
    usage_url: null,
    version: 1,
  }
  return {
    provider: "brave",
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

describe("CRDPriceNote", () => {
  it("states the CRD reference with one Brave search row and one version (UI7-06)", () => {
    render(
      <CRDPriceNote
        providers={[{ id: "brave", name: "Brave" }] as never}
        providerLimits={[braveLimits()] as never}
      />,
    )
    expect(screen.getByText("How credit units are priced")).not.toBeNull()
    expect(screen.getByText(/1 CRD = USD 0.001 of priced native use/)).not.toBeNull()
    expect(screen.getByText("0.005 USD")).not.toBeNull()
    expect(screen.getByText("5 CRD")).not.toBeNull()
    expect(screen.queryByText("fetch", { exact: false })).toBeNull()
    const headers = screen.getAllByRole("columnheader")
    expect(headers.map((entry) => entry.textContent)).toEqual([
      "Provider",
      "Operation",
      "USD per operation",
      "CRD per operation",
    ])
    expect(screen.getByText(/Price profile: v2026-09/)).not.toBeNull()
  })

  it("frames the table with rounded edges and keeps the colored operation border", () => {
    render(
      <CRDPriceNote
        providers={[{ id: "brave", name: "Brave" }] as never}
        providerLimits={[braveLimits()] as never}
      />,
    )
    const frame = screen.getByRole("table").closest(".rounded-lg")
    expect(frame?.className).toContain("overflow-hidden")
    expect(frame?.className).toContain("border-[var(--border-subtle)]")
    const rows = screen.getAllByRole("row")
    expect(rows.length).toBeGreaterThan(1)
    const headerClass = rows[0].className
    expect(headerClass).toContain("border-[var(--border-subtle)]")
    for (const row of rows.slice(1)) {
      expect(row.className).not.toContain("border-r!")
      const firstCell = row.querySelector("td")
      expect(firstCell?.style.boxShadow).toContain("inset 2px 0 0")
      expect(firstCell?.style.boxShadow).toContain("var(--accent-cyan)")
    }
  })

  it("shows one muted sentence for an empty catalog (UI7-06)", () => {
    render(<CRDPriceNote providers={[]} providerLimits={[]} />)
    expect(screen.getByText("No provider price is reported in the current catalog.")).not.toBeNull()
    expect(screen.queryByRole("table")).toBe(null)
  })

  it("includes Tavily prices and labels free reference and zero-cost rows", () => {
    const tavilySearch = {
      provider: "tavily",
      operation: "search",
      auth_mode: "keyed",
      supported: true,
      transport_available: true,
      native_pool_id: "tavily:keyed:credits",
      rate: null,
      budget: null,
      conversion_profile: profile(),
      plan_name: "Tavily",
      usage_url: null,
      version: 2,
    }
    const tavilyLimits = {
      provider: "tavily",
      active_auth_mode: "keyed",
      auths: [
        {
          auth_mode: "keyed",
          transport_available: true,
          search: tavilySearch,
          fetch: null,
          free_tiers: [],
          paid_tiers: [],
          unknown_tiers: [],
          tier_split_known: true,
          aggregate_pool: null,
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
    render(
      <CRDPriceNote
        providers={[
          { id: "brave", name: "Brave" },
          { id: "tavily", name: "Tavily", hasKey: true, capabilities: ["search"] },
          {
            id: "keenable",
            name: "Keenable",
            hasKey: false,
            keyVaultStatus: "keyless_public",
            capabilities: ["search", "fetch"],
          },
          { id: "tinyfish", name: "Tinyfish", hasKey: true, capabilities: ["search", "fetch"] },
          { id: "firecrawl", name: "Firecrawl", hasKey: true, capabilities: ["search", "fetch"] },
        ] as never}
        providerLimits={[braveLimits(), tavilyLimits] as never}
      />,
    )
    expect(screen.getByText("0.005 USD")).not.toBeNull()
    expect(screen.getByText("5 CRD")).not.toBeNull()
    expect(screen.getByText("Tavily")).not.toBeNull()
    expect(screen.getByText("0.008 USD")).not.toBeNull()
    expect(screen.getByText("8 CRD")).not.toBeNull()
    expect(screen.getAllByText("Plan-dependent", { exact: true })).toHaveLength(2)
    expect(screen.getAllByText("—", { exact: true })).toHaveLength(2)

    for (const referenceCost of ["0.004 USD (estimated)", "4 CRD"]) {
      const struckPrices = screen.getAllByText(referenceCost, { exact: true })
      expect(struckPrices.length).toBeGreaterThan(0)
      for (const price of struckPrices) {
        expect(price.closest("s")).not.toBeNull()
      }
    }
    expect(screen.getAllByText("Free", { exact: true })).toHaveLength(8)
  })
})
