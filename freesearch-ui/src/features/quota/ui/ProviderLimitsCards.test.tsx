import { describe, expect, it, vi } from "vitest"
import { render, screen } from "@testing-library/react"
import { ProviderLimitsCards } from "./ProviderLimitsCards"

vi.mock("../model/useManualQuota", () => ({
  useManualQuota: () => ({
    manual: null,
    estimate: null,
    save: () => Promise.resolve({}),
    remove: () => Promise.resolve({}),
  }),
}))

vi.mock("@/test/fetchMock", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/test/fetchMock")>()
  return { ...actual }
})

/**
 * UI7 card list: reported cards only, per-provider totals, no invented
 * cards for unreported providers. Covers UI7-02 and UI7-05.
 */

function braveEntry() {
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
            reference_usd_per_crd: "0.001",
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

describe("ProviderLimitsCards", () => {
  it("renders the reported Brave card with its own totals only (UI7-02, final-polish 3c)", () => {
    render(
      <ProviderLimitsCards
        providers={[{ id: "brave", name: "Brave" }, { id: "parallel", name: "Parallel" }] as never}
        providerLimits={[braveEntry()] as never}
        crdUsageTotals={[
          { provider: "brave", operation: "search", normalized_crd: "5", attempt_count: 1, volume_count: 1 },
        ]}
        refreshDashboard={() => Promise.resolve()}
        manualEligible={new Set(["brave"])}
      />,
    )
    expect(screen.getByText("1 reported")).not.toBeNull()
    // CARD-3: no "CRD left" label; the fraction "4500 / 5000 CRD" renders as split spans.
    expect(screen.queryByText("CRD left")).toBe(null)
    expect(screen.queryByText("USD left")).toBe(null)
    expect(screen.getByText("4500")).not.toBeNull()
    expect(screen.getByText("/ 5000")).not.toBeNull()
    expect(screen.getByText("CRD")).not.toBeNull()
    expect(screen.queryByText("4500 CRD")).toBe(null)
    const crdValue = screen.getByText("4500")
    expect(crdValue.getAttribute("title")).toBe("$4.5 left")
    expect(crdValue.getAttribute("aria-label")).toBe("$4.5 left")
    expect(screen.queryByText("USD use (priced)")).toBe(null)
    expect(screen.queryByText("Parallel")).toBe(null)
  })

  it("holds logo, name, statement, ordered actions, and trailing fraction (CARD-3)", () => {
    render(
      <ProviderLimitsCards
        providers={[{ id: "brave", name: "Brave" }, { id: "parallel", name: "Parallel" }] as never}
        providerLimits={[braveEntry()] as never}
        crdUsageTotals={[
          { provider: "brave", operation: "search", normalized_crd: "5", attempt_count: 1, volume_count: 1 },
        ]}
        refreshDashboard={() => Promise.resolve()}
        manualEligible={new Set(["brave"])}
      />,
    )
    expect(screen.getByTestId("provider-logo-brave")).not.toBeNull()
    expect(screen.getByRole("heading", { name: "Brave" })).not.toBeNull()
    expect(screen.getByText("Observed from the vendor API")).not.toBeNull()
    const buttons = screen.getAllByRole("button").map((button) => button.textContent)
    expect(buttons.slice(0, 4)).toEqual(["Refresh Limits", "Provider Balance", "Budget Limit", "History"])
    const creditRow = screen.getByText("4500").closest("span")?.parentElement?.parentElement
    const children = Array.from(creditRow?.children ?? [])
    expect(children.length).toBe(2)
    expect(children[0]?.textContent).toContain("Refresh Limits")
    expect(children[1]?.textContent?.replace(/\s+/g, "")).toContain("4500/5000CRD")
    const bar = screen.getByRole("progressbar", { name: "Brave credit units remaining" })
    expect((bar.compareDocumentPosition(creditRow as Node) & Node.DOCUMENT_POSITION_FOLLOWING) !== 0).toBe(true)
  })

  it("shows an honest empty state with no invented card (UI7-05)", () => {
    render(
      <ProviderLimitsCards
        providers={[{ id: "brave", name: "Brave" }] as never}
        providerLimits={[]}
        crdUsageTotals={[]}
        refreshDashboard={() => Promise.resolve()}
        manualEligible={new Set<string>()}
      />,
    )
    expect(screen.getByText("No provider limit data reported by the backend.")).not.toBeNull()
    expect(screen.queryByRole("progressbar")).toBe(null)
  })
})

/**
 * FIX list: ProviderLimitsCards forwards the Tavily-only renderRateTier slot
 * to the card while credential/auth selection and OAuth composition stay
 * intact.
 */

describe("ProviderLimitsCards rate-tier slot (FIX)", () => {
  function tavilyEntry() {
    const profile = {
      reference_usd_per_crd: "0.001",
      native_usd_per_unit: "0.008",
      cost_basis: "paygo_reference",
      price_version: "paygo-reference",
      source: "documented",
      estimated: true,
    }
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
      conversion_profile: profile,
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
  }

  it("renders the tier slot inside the Tavily card only with OAuth intact", () => {
    const calls: string[] = []
    let confirmedKind = "missing"
    render(
      <ProviderLimitsCards
        providers={[{ id: "tavily", name: "Tavily" }, { id: "brave", name: "Brave" }] as never}
        providerLimits={[tavilyEntry(), braveEntry()] as never}
        crdUsageTotals={[]}
        refreshDashboard={() => Promise.resolve()}
        manualEligible={new Set<string>()}
        renderOAuthActions={({ providerId }) => (
          <button type="button" data-testid={"oauth-" + providerId}>
            Connect
          </button>
        )}
        renderRateTier={(args) => {
          calls.push(args.providerId)
          confirmedKind = typeof args.onConfirmed
          return <span data-testid="tier-slot">Tier</span>
        }}
      />,
    )
    expect(calls).toEqual(["tavily"])
    expect(confirmedKind).toBe("function")
    const tavilyArticle = screen.getByRole("heading", { name: "Tavily" }).closest("article") as HTMLElement
    expect(tavilyArticle.querySelector('[data-testid="tier-slot"]')).not.toBeNull()
    const braveArticle = screen.getByRole("heading", { name: "Brave" }).closest("article") as HTMLElement
    expect(braveArticle.querySelector('[data-testid="tier-slot"]')).toBeNull()
    expect(screen.getByTestId("oauth-tavily")).not.toBeNull()
    expect(screen.getByTestId("oauth-brave")).not.toBeNull()
  })
})
