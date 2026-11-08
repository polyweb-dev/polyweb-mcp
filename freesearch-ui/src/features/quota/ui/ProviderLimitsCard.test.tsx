import { describe, expect, it, vi } from "vitest"
import type { ReactNode } from "react"
import { act, render, screen, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import type { CRDUsageTotal, CRDView, DashboardQuota, LimitRecord, ProviderAuthLimits, ProviderLimits, RateProgressView } from "@/domains/dashboard"
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

function tinyfishRecord(operation: "search" | "fetch"): LimitRecord {
  return {
    provider: "tinyfish",
    operation,
    auth_mode: "keyed",
    supported: true,
    transport_available: true,
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
    plan_name: "Tinyfish",
    usage_url: null,
    version: 1,
  }
}

function tinyfishProgress(overrides: Partial<RateProgressView> = {}): RateProgressView {
  return {
    bucket_id: "tinyfish-synth",
    operation: "search",
    window: "1h",
    unit: "requests",
    remaining: "498.000000000",
    limit: "500",
    reset_at: null,
    source: "synth-source",
    confidence: "authoritative",
    kind: "rate",
    stale: false,
    enforceable: false,
    ...overrides,
  }
}

function tinyfishAuth(): ProviderAuthLimits {
  return {
    auth_mode: "keyed",
    transport_available: true,
    search: tinyfishRecord("search"),
    fetch: tinyfishRecord("fetch"),
    free_tiers: [],
    paid_tiers: [],
    unknown_tiers: [],
    tier_split_known: true,
    aggregate_pool: null,
    crd_views: [
      {
        state: "unmetered",
        operation: "search",
        remaining_crd: null,
        local_remaining_crd: null,
        request_cost_crd: null,
        shared_pool_id: null,
        possible_standard_calls: null,
        price_version: null,
        priced: false,
      },
      {
        state: "unmetered",
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
    rate_progress: [
      tinyfishProgress({
        bucket_id: "tinyfish-search-hourly",
        operation: "search",
        window: "1h",
        unit: "requests",
        remaining: "498.000000000",
        limit: "500",
      }),
      tinyfishProgress({
        bucket_id: "tinyfish-fetch-daily",
        operation: "fetch",
        window: "1d",
        unit: "urls",
        remaining: "1000.000000000",
        limit: "1000",
      }),
    ],
    grants: null,
    detail: {
      plan_name: "Tinyfish",
      native_unit: null,
      native_balance: null,
      native_allowance: null,
      usd_per_call: null,
      actual_spend_usd: null,
      reset_at: null,
      reset_rule: "unknown",
      usage_url: "https://api.search.tinyfish.ai/",
      source: "vendor_api",
      confidence: "authoritative",
      last_sync_at: null,
      stale: false,
      price_version: "v2026-09",
      crd_split_note: null,
      rate_windows: [
        {
          bucket_id: "tinyfish-search-1m",
          limit: "30",
          window: "1m",
          scope: "key",
          unit: "requests",
          remaining: null,
          reset_at: null,
          source: "synth-source",
          confidence: "authoritative",
        },
      ],
      tier_split_known: true,
      aggregate_pool_id: null,
    },
  }
}

function tinyfishLimits(): ProviderLimits {
  return {
    provider: "tinyfish",
    active_auth_mode: "keyed",
    auths: [tinyfishAuth()],
    documented_keyless_operations: [],
    version: 1,
    generated_at: "2026-03-10T12:00:00Z",
  }
}

/** CARD-3 fraction oracle: "4500 / 5000 CRD" renders as split spans, never one "4500 CRD" node. */
function expectFraction(remaining: string, total: string, unit = "USD"): void {
  expect(screen.getByText(remaining)).not.toBeNull()
  expect(screen.getByText(`/ ${total}`)).not.toBeNull()
  expect(screen.getByText(unit)).not.toBeNull()
  expect(screen.queryByText(`${remaining} CRD`)).toBeNull()
  expect(screen.queryByText("CRD left")).toBeNull()
  const value = screen.getByText(remaining).closest("span")?.parentElement
  expect(value?.textContent?.replace(/\s+/g, "")).toBe(`${remaining}/${total}${unit}`)
}

describe("ProviderLimitsCard Brave", () => {
  it("shows one credit bar with 90 percent, CRD only, and no fetch headline (UI7-01, UI7-02, UI7-04, final-polish 3c)", () => {
    renderBraveCard()
    const bar = screen.getByRole("progressbar", { name: "Brave balance remaining" })
    expect(bar.getAttribute("aria-valuenow")).toBe("90")
    expect(bar.getAttribute("aria-valuemin")).toBe("0")
    expect(bar.getAttribute("aria-valuemax")).toBe("100")
    expect(screen.getByText("90%")).not.toBeNull()
    // CARD-3: credit fraction "4500 / 5000 CRD" via split spans; no "CRD left" label.
    expectFraction("$4.5", "$5")
    // Final-polish Item 3c: card shows CRD only. USD value sits in hover title and aria-label.
    expect(screen.queryByText("4.500")).toBeNull()
    expect(screen.queryByText("USD left")).toBeNull()
    expect(screen.queryByText("USD use (priced)")).toBeNull()
    const crdValue = screen.getByText("$4.5")
    expect(crdValue.getAttribute("title")).toBe("$4.5 left")
    expect(crdValue.getAttribute("aria-label")).toBe("$4.5 left")
    // Polish Item 6: no auth_mode chip, no "keyed rail" text on the card.
    expect(screen.queryByText("keyed rail")).toBeNull()
    expect(screen.queryByText("n/a")).toBeNull()
    expect(screen.queryByText("Fetch credit units left")).toBeNull()
    expect(screen.queryByText(/keyless/i)).toBeNull()
    vi.unstubAllGlobals()
  })

  it("exposes USD value in hover title and aria-label only with CRD bar text intact (final-polish 3c, 3e)", () => {
    renderBraveCard()
    expectFraction("$4.5", "$5")
    const crdValue = screen.getByText("$4.5")
    expect(crdValue.getAttribute("title")).toBe("$4.5 left")
    expect(crdValue.getAttribute("aria-label")).toBe("$4.5 left")
    expect(screen.queryByText("USD left")).toBeNull()
    expect(screen.queryByText("CRD left")).toBeNull()
    const bar = screen.getByRole("progressbar", { name: "Brave balance remaining" })
    expect(bar.getAttribute("aria-valuetext")).toBe("90% remaining, $4.50 left")
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
      screen.queryByRole("button", { name: "Refresh limits for Brave" }),
    ).toBeNull()
    expect(stub.requestsTo(/limits/).length).toBeLessThan(2)
    vi.unstubAllGlobals()
  })

  it("opens the grant dialog with search only and no fetch field (UI7-04, UI7-08)", async () => {
    installFetchStub(() => ok({ events: [], next_cursor: null }))
    renderBraveCard()
    const user = userEvent.setup()
    await user.click(screen.getByRole("button", { name: "Actions for Brave" }))
    await user.click(await screen.findByRole("button", { name: "Budget limit" }))
    expect(await screen.findByText("Search budget (USD)")).not.toBeNull()
    expect(screen.queryByLabelText(/Fetch budget/i)).toBeNull()
    expect(screen.queryByText(/n\/a for this provider/)).toBeNull()
    vi.unstubAllGlobals()
  })

  it("opens the history dialog with a titled modal (UI7-09)", async () => {
    installFetchStub(() => ok({ events: [], next_cursor: null }))
    renderBraveCard()
    const user = userEvent.setup()
    await user.click(screen.getByRole("button", { name: "Actions for Brave" }))
    await user.click(await screen.findByRole("button", { name: "Balance history" }))
    expect(await screen.findByRole("dialog", { name: "Balance history for Brave" })).not.toBeNull()
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
    expectFraction("$4.5", "$5")
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
    expectFraction("$4.495", "$5")
    expect(screen.getByText("89.9%")).not.toBeNull()
    vi.unstubAllGlobals()
  })

  it("holds logo, name, and source statement in the header (CARD-3)", () => {
    renderBraveCard()
    expect(screen.getByTestId("provider-logo-brave")).not.toBeNull()
    expect(screen.getByRole("heading", { name: "Brave" })).not.toBeNull()
    expect(screen.getByText("Reported by provider")).not.toBeNull()
    const headerRow = screen.getByTestId("provider-logo-brave").closest("div.flex")
    expect(headerRow?.textContent).toContain("Brave")
    expect(headerRow?.textContent).toContain("Reported by provider")
    vi.unstubAllGlobals()
  })

  it("places Refresh at the leading edge, the fraction at the trailing edge, and the menu in the header (CARD-3)", async () => {
    renderBraveCard()
    const menu = screen.getByRole("button", { name: "Actions for Brave" })
    const heading = screen.getByRole("heading", { name: "Brave" })
    expect((heading.compareDocumentPosition(menu) & Node.DOCUMENT_POSITION_FOLLOWING) !== 0).toBe(true)
    const info = screen.getByRole("button", { name: "Credit details for Brave" })
    expect(info.getAttribute("data-testid")).toBe("credit-info-brave")
    const creditRow = screen.getByText("$4.5").closest("span")?.parentElement?.parentElement
    expect(creditRow?.className).toContain("justify-between")
    const children = Array.from(creditRow?.children ?? [])
    expect(children.length).toBe(2)
    expect(children[0]?.textContent).toBe("")
    expect(children[1]?.textContent?.replace(/\s+/g, "")).toContain("$4.5/$5USD")
    const user = userEvent.setup()
    await user.click(menu)
    expect(await screen.findByRole("button", { name: "Set balance" })).not.toBeNull()
    expect(screen.getByRole("button", { name: "Budget limit" })).not.toBeNull()
    expect(screen.getByRole("button", { name: "Balance history" })).not.toBeNull()
    expect(heading.parentElement?.contains(info)).toBe(true)
    const bar = screen.getByRole("progressbar", { name: "Brave balance remaining" })
    expect((bar.compareDocumentPosition(creditRow as Node) & Node.DOCUMENT_POSITION_FOLLOWING) !== 0).toBe(true)
    vi.unstubAllGlobals()
  })
})

describe("ProviderLimitsCard Tavily native", () => {
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

  function tavilyAuth(): ProviderAuthLimits {
    return {
      auth_mode: "keyed",
      transport_available: true,
      search: {
        provider: "tavily",
        operation: "search",
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
          standard_native_cost: "1",
          usd_per_call: "0.008",
          on_exhausted: "402",
          usage_api: "/usage",
          priced: true,
        },
        conversion_profile: tavilyProfile(),
        plan_name: "Tavily",
        usage_url: null,
        version: 2,
      },
      fetch: {
        provider: "tavily",
        operation: "fetch",
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
          standard_native_cost: "0.2",
          usd_per_call: "0.008",
          on_exhausted: "402",
          usage_api: "/usage",
          priced: true,
        },
        conversion_profile: tavilyProfile(),
        plan_name: "Tavily",
        usage_url: null,
        version: 2,
      },
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
        {
          state: "finite",
          operation: "fetch",
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
      detail: {
        plan_name: "Tavily",
        native_unit: "CREDIT",
        native_balance: "999",
        native_allowance: "1000",
        usd_per_call: "0.008",
        actual_spend_usd: "0.008",
        reset_at: "2026-10-01T00:00:00Z",
        reset_rule: "monthly_first",
        usage_url: null,
        source: "vendor_api",
        confidence: "observed",
        last_sync_at: "2026-09-06T10:05:00Z",
        stale: false,
        price_version: "paygo-reference",
        crd_split_note: null,
        rate_windows: [
          {
            bucket_id: "tavily:keyed:search:requests",
            limit: "100",
            window: "1m",
            scope: "key",
            unit: "requests",
            remaining: "95",
            reset_at: null,
            source: "local",
            confidence: "observed",
          },
        ],
        retry_after_seconds: null,
        tier_split_known: true,
        aggregate_pool_id: "tavily:keyed:credits",
      },
    } as unknown as ProviderAuthLimits
  }

  function tavilyLimits(): ProviderLimits {
    return {
      provider: "tavily",
      active_auth_mode: "keyed",
      auths: [tavilyAuth()],
      documented_keyless_operations: ["search", "fetch"],
      version: 2,
      generated_at: "2026-03-10T12:00:00Z",
    }
  }

  function renderTavilyCard(): void {
    installFetchStub(() => ok({ events: [], next_cursor: null }))
    render(
      <ProviderLimitsCard
        providerId="tavily"
        providerName="Tavily"
        limits={tavilyLimits()}
        crdUsageTotals={[]}
        refreshDashboard={() => Promise.resolve()}
        manualEligible
      />,
    )
  }

  it("selects native Credits with a native bar and no closed USD", () => {
    renderTavilyCard()
    const bar = screen.getByRole("progressbar", { name: "Tavily native Credits remaining" })
    expect(bar.getAttribute("aria-valuenow")).toBe("99.9")
    expect(screen.getByText("999")).not.toBeNull()
    expect(screen.getByText("/ 1,000")).not.toBeNull()
    expect(screen.getByText("Balance left")).not.toBeNull()
    expect(screen.queryByText("CRD")).toBeNull()
    expect(screen.queryByText("0.008")).toBeNull()
    expect(screen.queryByText("$0.008")).toBeNull()
    vi.unstubAllGlobals()
  })

  it("keeps USD absent while closed and shows USD inside the open disclosure", async () => {
    renderTavilyCard()
    expect(screen.queryByText("0.008")).toBeNull()
    const user = userEvent.setup()
    await user.click(screen.getByRole("button", { name: "Credit details for Tavily" }))
    expect(await screen.findByText("Quota details")).not.toBeNull()
    expect(screen.getByText("0.008")).not.toBeNull()
    vi.unstubAllGlobals()
  })
})

/**
 * Keenable card: one aggregate bar for the shared keyed pool, and an
 * unmetered keyless rail with a separate shared hourly rate bar.
 * Keeps the Brave fixture and cases above unchanged.
 */

function keenableKeyedSearchView(): CRDView {
  return {
    state: "finite",
    operation: "search",
    remaining_crd: "399980",
    local_remaining_crd: null,
    request_cost_crd: "4",
    shared_pool_id: "keenable:keyed:request",
    possible_standard_calls: "99995",
    price_version: "list_price",
    priced: true,
  }
}

function keenableKeyedFetchView(): CRDView {
  return {
    state: "finite",
    operation: "fetch",
    remaining_crd: "399980",
    local_remaining_crd: null,
    request_cost_crd: "4",
    shared_pool_id: "keenable:keyed:request",
    possible_standard_calls: "99995",
    price_version: "list_price",
    priced: true,
  }
}

function keenableKeyedSearchRecord(): LimitRecord {
  return {
    provider: "keenable",
    operation: "search",
    auth_mode: "keyed",
    supported: true,
    transport_available: true,
    native_pool_id: "keenable:keyed:request",
    rate: null,
    budget: null,
    conversion_profile: {
      reference_usd_per_crd: "0.001",
      native_usd_per_unit: "0.004",
      cost_basis: "priced_native_use",
      price_version: "list_price",
      source: "list_price_assumed",
      estimated: true,
    },
    plan_name: "Monthly free requests",
    usage_url: "https://app.keenable.ai/console",
    version: 1,
  }
}

function keenableKeyedFetchRecord(): LimitRecord {
  return {
    provider: "keenable",
    operation: "fetch",
    auth_mode: "keyed",
    supported: true,
    transport_available: true,
    native_pool_id: "keenable:keyed:request",
    rate: null,
    budget: null,
    conversion_profile: {
      reference_usd_per_crd: "0.001",
      native_usd_per_unit: "0.004",
      cost_basis: "priced_native_use",
      price_version: "list_price",
      source: "list_price_assumed",
      estimated: true,
    },
    plan_name: "Monthly free requests",
    usage_url: "https://app.keenable.ai/console",
    version: 1,
  }
}

function keenableKeyedAuth(): ProviderAuthLimits {
  return {
    auth_mode: "keyed",
    transport_available: true,
    search: keenableKeyedSearchRecord(),
    fetch: keenableKeyedFetchRecord(),
    free_tiers: [],
    paid_tiers: [],
    unknown_tiers: [],
    tier_split_known: true,
    aggregate_pool: {
      pool_id: "keenable:keyed:request",
      provider: "keenable",
      auth_mode: "keyed",
      native_unit: "REQUEST",
      remaining: "99995",
      allowance: "100000",
      actual_spend_usd: null,
      source: "local_ledger",
      confidence: "estimated",
      reset_at: "2026-11-01T00:00:00Z",
      observed_at: "2026-03-10T12:00:00Z",
      version: 1,
      credential_generation: 7,
      next_sync_at: null,
      stale: false,
      manual_anchor: false,
    },
    crd_views: [keenableKeyedSearchView(), keenableKeyedFetchView()],
    rate_progress: [],
    grants: null,
    detail: null,
  }
}

function keenableLimits(): ProviderLimits {
  return {
    provider: "keenable",
    active_auth_mode: "keyed",
    auths: [keenableKeyedAuth()],
    documented_keyless_operations: ["search", "fetch"],
    version: 1,
    generated_at: "2026-03-10T12:00:00Z",
  }
}

function keenableKeylessSearchView(): CRDView {
  return {
    state: "unmetered",
    operation: "search",
    remaining_crd: null,
    local_remaining_crd: null,
    request_cost_crd: null,
    shared_pool_id: null,
    possible_standard_calls: null,
    price_version: null,
    priced: false,
  }
}

function keenableKeylessFetchView(): CRDView {
  return {
    state: "unmetered",
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

function keenableKeylessRecord(operation: "search" | "fetch"): LimitRecord {
  return {
    provider: "keenable",
    operation,
    auth_mode: "keyless",
    supported: true,
    transport_available: true,
    native_pool_id: null,
    rate: null,
    budget: null,
    conversion_profile: {
      reference_usd_per_crd: "0.001",
      native_usd_per_unit: "0",
      cost_basis: "priced_native_use",
      price_version: "",
      source: "unbilled_keyless",
      estimated: false,
    },
    plan_name: "Keyless public pool",
    usage_url: null,
    version: 1,
  }
}

function keenableKeylessAuth(): ProviderAuthLimits {
  return {
    auth_mode: "keyless",
    transport_available: true,
    search: keenableKeylessRecord("search"),
    fetch: keenableKeylessRecord("fetch"),
    free_tiers: [],
    paid_tiers: [],
    unknown_tiers: [],
    tier_split_known: true,
    aggregate_pool: null,
    crd_views: [keenableKeylessSearchView(), keenableKeylessFetchView()],
    rate_progress: [
      {
        bucket_id: "keenable:keyless:requests",
        operation: "search",
        window: "1h",
        unit: "requests",
        remaining: "990",
        limit: "1000",
        reset_at: null,
        source: "documented_keyless",
        confidence: "observed",
        kind: "rate",
        stale: false,
        enforceable: true,
      },
    ],
    grants: null,
    detail: {
      plan_name: "Keyless public pool",
      native_unit: null,
      native_balance: null,
      native_allowance: null,
      usd_per_call: null,
      actual_spend_usd: null,
      reset_at: null,
      reset_rule: "unknown",
      usage_url: null,
      source: "documented_keyless",
      confidence: "observed",
      last_sync_at: null,
      stale: false,
      price_version: "",
      crd_split_note: null,
      rate_windows: [
        {
          bucket_id: "keenable:keyless:requests",
          limit: "10",
          window: "1s",
          scope: "ip",
          unit: "requests",
          remaining: null,
          reset_at: null,
          source: "documented_keyless",
          confidence: "observed",
        },
        {
          bucket_id: "keenable:keyless:requests",
          limit: "1000",
          window: "1h",
          scope: "ip",
          unit: "requests",
          remaining: null,
          reset_at: null,
          source: "documented_keyless",
          confidence: "observed",
        },
      ],
      tier_split_known: true,
      aggregate_pool_id: null,
    },
  }
}

function keenableKeylessLimits(): ProviderLimits {
  return {
    provider: "keenable",
    active_auth_mode: "keyless",
    auths: [keenableKeylessAuth()],
    documented_keyless_operations: ["search", "fetch"],
    version: 1,
    generated_at: "2026-03-10T12:00:00Z",
  }
}

function keenableDecimalKeylessLimits(): ProviderLimits {
  const auth = keenableKeylessAuth()
  return {
    provider: "keenable",
    active_auth_mode: "keyless",
    auths: [
      {
        ...auth,
        rate_progress: [
          {
            bucket_id: "keenable:keyless:requests",
            operation: "search",
            window: "1h",
            unit: "requests",
            remaining: "990.00000000",
            limit: "1000.00000000",
            reset_at: null,
            source: "documented_keyless",
            confidence: "authoritative",
            kind: "rate",
            stale: false,
            enforceable: true,
          },
          {
            bucket_id: "keenable:keyless:requests",
            operation: "fetch",
            window: "1h",
            unit: "requests",
            remaining: "990.00000000",
            limit: "1000.00000000",
            reset_at: null,
            source: "documented_keyless",
            confidence: "authoritative",
            kind: "rate",
            stale: false,
            enforceable: true,
          },
        ],
      },
    ],
    documented_keyless_operations: ["search", "fetch"],
    version: 1,
    generated_at: "2026-03-10T12:00:00Z",
  }
}

function keenableAuthoritativeKeylessLimits(): ProviderLimits {
  const auth = keenableKeylessAuth()
  return {
    provider: "keenable",
    active_auth_mode: "keyless",
    auths: [
      {
        ...auth,
        rate_progress: [
          {
            bucket_id: "keenable:keyless:requests",
            operation: "search",
            window: "1h",
            unit: "requests",
            remaining: "1000.00000000",
            limit: "1000",
            reset_at: null,
            source: "documented_keyless",
            confidence: "authoritative",
            kind: "rate",
            stale: false,
            enforceable: true,
          },
          {
            bucket_id: "keenable:keyless:requests",
            operation: "fetch",
            window: "1h",
            unit: "requests",
            remaining: "1000.00000000",
            limit: "1000",
            reset_at: null,
            source: "documented_keyless",
            confidence: "authoritative",
            kind: "rate",
            stale: false,
            enforceable: true,
          },
        ],
      },
    ],
    documented_keyless_operations: ["search", "fetch"],
    version: 1,
    generated_at: "2026-03-10T12:00:00Z",
  }
}

function keenableAuthoritativeKeyedLimits(): ProviderLimits {
  const auth = keenableKeyedAuth()
  return {
    provider: "keenable",
    active_auth_mode: "keyed",
    auths: [
      {
        ...auth,
        rate_progress: [
          {
            bucket_id: "keenable:keyed:requests",
            operation: "search",
            window: "1h",
            unit: "requests",
            remaining: "500",
            limit: "1000",
            reset_at: null,
            source: "documented",
            confidence: "authoritative",
            kind: "rate",
            stale: false,
            enforceable: true,
          },
        ],
      },
    ],
    documented_keyless_operations: ["search", "fetch"],
    version: 1,
    generated_at: "2026-03-10T12:00:00Z",
  }
}

function renderKeenableCard(limits: ProviderLimits): void {
  installFetchStub(() => {
    throw new Error("no backend in card test")
  })
  render(
    <ProviderLimitsCard
      providerId="keenable"
      providerName="Keenable"
      limits={limits}
      crdUsageTotals={noUseTotals()}
      refreshDashboard={() => Promise.resolve()}
      manualEligible
    />,
  )
}

describe("ProviderLimitsCard Keenable", () => {
  it("shows one aggregate bar for the shared keyed pool with a single funds fraction", () => {
    renderKeenableCard(keenableLimits())
    const bar = screen.getByRole("progressbar", { name: "Keenable balance remaining" })
    expect(bar.getAttribute("aria-valuemin")).toBe("0")
    expect(bar.getAttribute("aria-valuemax")).toBe("100")
    expect(bar.getAttribute("aria-valuenow")).toBe("100")
    expect(bar.querySelector("div")?.getAttribute("class")).toContain(
      "bg-[var(--status-healthy)]",
    )
    expectFraction("99,995", "100,000", "requests")
    expect(screen.queryByText("Free - unmetered")).toBeNull()
    const value = screen.getByText("99,995").closest("span")?.parentElement
    expect(value?.textContent?.replace(/\s+/g, "")).toBe("99,995/100,000requests")
    expect(screen.getByText("100%")).not.toBeNull()
    const percent = screen.getByText("100%")
    expect(bar.getAttribute("class")).toContain("w-full")
    expect((bar.compareDocumentPosition(percent) & Node.DOCUMENT_POSITION_FOLLOWING) !== 0).toBe(true)
    vi.unstubAllGlobals()
  })

  it("shows unmetered keyless funds with a separate shared hourly rate bar", async () => {
    installFetchStub(() => ok({ events: [], next_cursor: null }))
    render(
      <ProviderLimitsCard
        providerId="keenable"
        providerName="Keenable"
        limits={keenableKeylessLimits()}
        crdUsageTotals={noUseTotals()}
        refreshDashboard={() => Promise.resolve()}
        manualEligible
      />,
    )
    expect(screen.getByText("Free tier", { exact: true })).not.toBeNull()
    expect(screen.queryByText("Free - unmetered")).toBeNull()
    expect(screen.queryByRole("progressbar", { name: "Keenable balance remaining" })).toBeNull()
    expect(screen.getByText("Search and fetch")).not.toBeNull()
    expect(screen.getByText("990 of 1,000 left this hour")).not.toBeNull()
    vi.unstubAllGlobals()
  })

  it("keenable funds use the shared bar with one aggregate value", () => {
    renderKeenableCard(keenableLimits())
    const bars = screen.getAllByRole("progressbar", {
      name: "Keenable balance remaining",
    })
    expect(bars).toHaveLength(1)
    expectFraction("99,995", "100,000", "requests")
    expect(screen.getByText("100%")).not.toBeNull()
    vi.unstubAllGlobals()
  })

  it("keenable hourly requests use whole counts on one shared bar line", () => {
    installFetchStub(() => ok({ events: [], next_cursor: null }))
    render(
      <ProviderLimitsCard
        providerId="keenable"
        providerName="Keenable"
        limits={keenableDecimalKeylessLimits()}
        crdUsageTotals={noUseTotals()}
        refreshDashboard={() => Promise.resolve()}
        manualEligible
      />,
    )
    // One shared row covers both operations: the duplicate bucket and window
    // collapses to the first entry, and decimal counts floor to whole calls.
    expect(screen.getByText("Search and fetch")).not.toBeNull()
    expect(screen.getByText("990 of 1,000 left this hour")).not.toBeNull()
    expect(screen.queryByText("990.00000000")).toBeNull()
    const bar = screen.getByRole("progressbar", {
      name: "Keenable search and fetch limits remaining",
    })
    expect(bar.getAttribute("class")).toContain("w-full")
    vi.unstubAllGlobals()
  })

  it("keenable keyless credits show Free with the strike value inside the details popover", async () => {
    installFetchStub(() => {
      throw new Error("no backend in card test")
    })
    const first = render(
      <ProviderLimitsCard
        providerId="keenable"
        providerName="Keenable"
        limits={keenableKeylessLimits()}
        crdUsageTotals={noUseTotals()}
        refreshDashboard={() => Promise.resolve()}
        manualEligible
      />,
    )
    expect(screen.getByText("Free tier", { exact: true })).not.toBeNull()
    expect(screen.queryByText("Free - unmetered")).toBeNull()
    expect(
      screen.queryByRole("progressbar", { name: "Keenable balance remaining" }),
    ).toBeNull()
    expect(screen.queryByText("399,980")).toBeNull()
    first.unmount()
    render(
      <ProviderLimitsCard
        providerId="keenable"
        providerName="Keenable"
        limits={keenableLimits()}
        crdUsageTotals={noUseTotals()}
        refreshDashboard={() => Promise.resolve()}
        manualEligible
      />,
    )
    const user = userEvent.setup()
    await user.click(screen.getByRole("button", { name: "Credit details for Keenable" }))
    expect(await screen.findByText("Quota details")).not.toBeNull()
    expect(document.querySelector("s")).toBeNull()
    expect(screen.queryByText("Free")).toBeNull()
    vi.unstubAllGlobals()
  })

  it("keenable keyless details omit authoritative rate confidence", async () => {
    installFetchStub(() => ok({ events: [], next_cursor: null }))
    render(
      <ProviderLimitsCard
        providerId="keenable"
        providerName="Keenable"
        limits={keenableAuthoritativeKeylessLimits()}
        crdUsageTotals={noUseTotals()}
        refreshDashboard={() => Promise.resolve()}
        manualEligible
      />,
    )
    expect(screen.getByText("Search and fetch")).not.toBeNull()
    expect(screen.queryByText("authoritative")).toBeNull()
    vi.unstubAllGlobals()
  })

  it("keenable keyed rate rows suppress authoritative confidence on the shared bar", () => {
    installFetchStub(() => ok({ events: [], next_cursor: null }))
    render(
      <ProviderLimitsCard
        providerId="keenable"
        providerName="Keenable"
        limits={keenableAuthoritativeKeyedLimits()}
        crdUsageTotals={noUseTotals()}
        refreshDashboard={() => Promise.resolve()}
        manualEligible
      />,
    )
    expect(screen.getByText("Search and fetch")).not.toBeNull()
    expect(screen.getByText("500 of 1,000 left this hour")).not.toBeNull()
    expect(screen.queryByText("authoritative")).toBeNull()
    vi.unstubAllGlobals()
  })

  it("keenable details preserve search and fetch CRD cost labels", async () => {
    installFetchStub(() => ok({ events: [], next_cursor: null }))
    renderKeenableCard(keenableLimits())
    const user = userEvent.setup()
    await user.click(screen.getByRole("button", { name: "Credit details for Keenable" }))
    expect(await screen.findByText("Search cost (USD)")).not.toBeNull()
    expect(screen.getByText("Fetch cost (USD)")).not.toBeNull()
    expect(screen.getAllByText("$0.004").length).toBeGreaterThanOrEqual(2)
    vi.unstubAllGlobals()
  })
})

describe("ProviderLimitsCard Tinyfish", () => {
  it("keeps_rate_bars_in_the_own_card_body", async () => {
    installFetchStub(() => {
      throw new Error("no backend in card test")
    })
    render(
      <>
        <ProviderLimitsCard
          providerId="tinyfish"
          providerName="Tinyfish"
          limits={tinyfishLimits()}
          crdUsageTotals={noUseTotals()}
          refreshDashboard={() => Promise.resolve()}
          manualEligible
        />
        <ProviderLimitsCard
          providerId="brave"
          providerName="Brave"
          limits={braveLimits()}
          crdUsageTotals={noUseTotals()}
          refreshDashboard={() => Promise.resolve()}
          manualEligible
        />
      </>,
    )
    const tinyfishCard = screen.getByRole("heading", { name: "Tinyfish" }).closest("article")
    expect(tinyfishCard).not.toBeNull()
    const braveCard = screen.getByRole("heading", { name: "Brave" }).closest("article")
    expect(braveCard).not.toBeNull()
    const tinyfish = within(tinyfishCard as HTMLElement)
    const brave = within(braveCard as HTMLElement)

    expect(tinyfish.getByText("Search")).not.toBeNull()
    expect(tinyfish.getByText("Fetch")).not.toBeNull()
    expect(tinyfish.getByText("498 of 500 requests left this hour")).not.toBeNull()
    expect(tinyfish.getByText("1,000 of 1,000 URLs left today")).not.toBeNull()
    expect(tinyfish.getAllByRole("progressbar")).toHaveLength(2)
    expect(
      tinyfish
        .getByRole("progressbar", { name: "Tinyfish search hourly requests remaining" })
        .getAttribute("aria-valuenow"),
    ).toBe("99.6")
    expect(
      tinyfish
        .getByRole("progressbar", { name: "Tinyfish fetch daily URLs remaining" })
        .getAttribute("aria-valuenow"),
    ).toBe("100")
    expect(brave.queryByText("Search hourly rate")).toBe(null)
    expect(brave.queryByText("498 of 500 requests left this hour")).toBe(null)

    const user = userEvent.setup()
    const infoButton = tinyfish.getByRole("button", { name: "Credit details for Tinyfish" })
    await user.click(infoButton)
    expect(await screen.findByText("Quota details")).not.toBeNull()
    expect(tinyfish.getAllByRole("progressbar")).toHaveLength(2)
    // The Brave card holds its own funds bar, so the page holds three bars.
    expect(screen.getAllByRole("progressbar")).toHaveLength(3)

    await user.keyboard("{Escape}")
    expect(screen.queryByText("Quota details")).toBe(null)
    expect(infoButton).toHaveFocus()
    expect(tinyfish.getByText("498 of 500 requests left this hour")).not.toBeNull()
    expect(tinyfish.getByText("1,000 of 1,000 URLs left today")).not.toBeNull()
    expect(tinyfish.getAllByRole("progressbar")).toHaveLength(2)
    vi.unstubAllGlobals()
  })
})

/**
 * Tavily FIX: no Tavily rate bars, a separate renderRateTier metadata row, the
 * confirmed-ceiling snapshot with derived clearance, and no reset subtitle.
 * Brave, Tinyfish, and Keenable cases above stay intact.
 */

describe("ProviderLimitsCard Tavily FIX", () => {
  function fixProfile() {
    return {
      reference_usd_per_crd: "0.001",
      native_usd_per_unit: "0.008",
      cost_basis: "paygo_reference",
      price_version: "paygo-reference",
      source: "documented",
      estimated: true,
    }
  }

  function fixRecord(operation: "search" | "fetch", nativeCost: string) {
    return {
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
      conversion_profile: fixProfile(),
      plan_name: "Tavily",
      usage_url: null,
      version: 2,
    }
  }

  function fixAuth(): ProviderAuthLimits {
    return {
      auth_mode: "keyed",
      transport_available: true,
      search: fixRecord("search", "1"),
      fetch: fixRecord("fetch", "0.2"),
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
        {
          state: "finite",
          operation: "fetch",
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
      detail: {
        plan_name: "Tavily",
        native_unit: "CREDIT",
        native_balance: "999",
        native_allowance: "1000",
        usd_per_call: "0.008",
        actual_spend_usd: "0.008",
        reset_at: "2026-10-01T00:00:00Z",
        reset_rule: "monthly_first",
        usage_url: null,
        source: "vendor_api",
        confidence: "observed",
        last_sync_at: "2026-09-06T10:05:00Z",
        stale: false,
        price_version: "paygo-reference",
        crd_split_note: null,
        rate_windows: [
          {
            bucket_id: "tavily:keyed:search:requests",
            limit: "100",
            window: "1m",
            scope: "key",
            unit: "requests",
            remaining: "95",
            reset_at: null,
            source: "local",
            confidence: "observed",
          },
        ],
        retry_after_seconds: null,
        tier_split_known: true,
        aggregate_pool_id: "tavily:keyed:credits",
      },
    } as unknown as ProviderAuthLimits
  }

  function fixLimits(): ProviderLimits {
    return {
      provider: "tavily",
      active_auth_mode: "keyed",
      auths: [fixAuth()],
      documented_keyless_operations: ["search", "fetch"],
      version: 2,
      generated_at: "2026-03-10T12:00:00Z",
    }
  }

  function renderFixCard(
    slot?: (args: { providerId: string; onConfirmed: (environment: "dev" | "prod") => void }) => ReactNode,
  ): void {
    installFetchStub(() => ok({ events: [], next_cursor: null }))
    render(
      <ProviderLimitsCard
        providerId="tavily"
        providerName="Tavily"
        limits={fixLimits()}
        crdUsageTotals={[]}
        refreshDashboard={() => Promise.resolve()}
        manualEligible
        {...(slot !== undefined ? { renderRateTier: slot } : {})}
      />,
    )
  }

  it("shows no Tavily rate bars with one funds bar and no reset subtitle", () => {
    renderFixCard()
    const article = screen.getByRole("heading", { name: "Tavily" }).closest("article") as HTMLElement
    const bars = within(article).getAllByRole("progressbar")
    expect(bars).toHaveLength(1)
    expect(bars[0].getAttribute("aria-label")).toBe("Tavily native Credits remaining")
    expect(within(article).queryByText(/requests per (minute|hour)/)).toBeNull()
    expect(within(article).queryByText("95/100")).toBeNull()
    expect(within(article).queryByText(/Resets /)).toBeNull()
    vi.unstubAllGlobals()
  })

  it("places the renderRateTier slot above the funds bar for Tavily only", () => {
    const seen: string[] = []
    const slot = (args: { providerId: string }) => {
      seen.push(args.providerId)
      return <button type="button">Tier control</button>
    }
    installFetchStub(() => ok({ events: [], next_cursor: null }))
    render(
      <>
        <ProviderLimitsCard
          providerId="tavily"
          providerName="Tavily"
          limits={fixLimits()}
          crdUsageTotals={[]}
          refreshDashboard={() => Promise.resolve()}
          manualEligible
          renderRateTier={slot}
        />
        <ProviderLimitsCard
          providerId="brave"
          providerName="Brave"
          limits={braveLimits()}
          crdUsageTotals={[]}
          refreshDashboard={() => Promise.resolve()}
          manualEligible
          renderRateTier={slot}
        />
      </>,
    )
    expect([...new Set(seen)]).toEqual(["tavily"])
    const tavilyArticle = screen.getByRole("heading", { name: "Tavily" }).closest("article") as HTMLElement
    const tier = within(tavilyArticle).getByRole("button", { name: "Tier control" })
    const progressBar = within(tavilyArticle).getByRole("progressbar")
    expect(progressBar.compareDocumentPosition(tier) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
    expect(tier.closest("article")).toBe(tavilyArticle)
    expect(tier.closest("article")?.textContent).toContain("Refresh")
    expect(tier.closest("article")?.textContent).not.toContain("Resets")
    expect(within(tavilyArticle).getByRole("button", { name: /Refresh limits/i })).toBeTruthy()
    const braveArticle = screen.getByRole("heading", { name: "Brave" }).closest("article") as HTMLElement
    expect(within(braveArticle).queryByRole("button", { name: "Tier control" })).toBeNull()
    vi.unstubAllGlobals()
  })

  it("shows the confirmed ceiling at once with unknown headroom until the dashboard confirms it", async () => {
    let confirmed: ((environment: "dev" | "prod") => void) | null = null
    renderFixCard((args) => {
      confirmed = args.onConfirmed
      return null
    })
    expect(confirmed).not.toBeNull()
    const user = userEvent.setup()
    await user.click(screen.getByRole("button", { name: "Credit details for Tavily" }))
    expect(await screen.findByText("Search and fetch rate limit")).not.toBeNull()
    expect(screen.getByText("95/100 requests per minute")).not.toBeNull()
    await act(async () => {
      confirmed?.("prod")
    })
    expect(await screen.findByText("Limit 1,000 requests per minute")).not.toBeNull()
    vi.unstubAllGlobals()
  })

  it("clears the confirmed override after the dashboard confirms the same ceiling", async () => {
    let confirmed: ((environment: "dev" | "prod") => void) | null = null
    const slot = (args: { providerId: string; onConfirmed: (environment: "dev" | "prod") => void }) => {
      confirmed = args.onConfirmed
      return null
    }
    installFetchStub(() => ok({ events: [], next_cursor: null }))
    const view = render(
      <ProviderLimitsCard
        providerId="tavily"
        providerName="Tavily"
        limits={fixLimits()}
        crdUsageTotals={[]}
        refreshDashboard={() => Promise.resolve()}
        manualEligible
        renderRateTier={slot}
      />,
    )
    await act(async () => {
      confirmed?.("prod")
    })
    const auth = fixAuth()
    const confirmedAuth = {
      ...auth,
      detail: auth.detail === null ? null : {
        ...auth.detail,
        rate_windows: (auth.detail.rate_windows ?? []).map((entry) =>
          entry.window === "1m" ? { ...entry, limit: "1000", remaining: "1000" } : entry,
        ),
      },
    } as unknown as ProviderAuthLimits
    view.rerender(
      <ProviderLimitsCard
        providerId="tavily"
        providerName="Tavily"
        limits={{ ...fixLimits(), auths: [confirmedAuth] }}
        crdUsageTotals={[]}
        refreshDashboard={() => Promise.resolve()}
        manualEligible
        renderRateTier={slot}
      />,
    )
    const user = userEvent.setup()
    await user.click(screen.getByRole("button", { name: "Credit details for Tavily" }))
    expect(await screen.findByText("1,000 requests per minute")).not.toBeNull()
    expect(screen.queryByText("Limit 1,000 requests per minute")).toBeNull()
    vi.unstubAllGlobals()
  })
})


describe("ProviderLimitsCard Firecrawl", () => {
  function firecrawlProfile() {
    return {
      reference_usd_per_crd: "0.001",
      native_usd_per_unit: "0.0038",
      cost_basis: "hobby_reference",
      price_version: "hobby-reference",
      source: "documented",
      estimated: true,
    }
  }

  function firecrawlAuth(): ProviderAuthLimits {
    return {
      auth_mode: "keyed",
      transport_available: true,
      search: {
        provider: "firecrawl",
        operation: "search",
        auth_mode: "keyed",
        supported: true,
        transport_available: true,
        native_pool_id: "firecrawl:keyed:credit",
        rate: null,
        budget: {
          model: "credits",
          free_allowance: "1000",
          allowance_unit: "Credits",
          allowance_period: "monthly",
          cost_per_1k: null,
          standard_native_cost: "2",
          usd_per_call: "0.0076",
          on_exhausted: "402",
          usage_api: "https://api.firecrawl.dev/v2/team/credit-usage",
          priced: true,
        },
        conversion_profile: firecrawlProfile(),
        plan_name: "Free plan (1,000 monthly credits)",
        usage_url: "https://firecrawl.dev/app/settings",
        version: 1,
      },
      fetch: {
        provider: "firecrawl",
        operation: "fetch",
        auth_mode: "keyed",
        supported: true,
        transport_available: true,
        native_pool_id: "firecrawl:keyed:credit",
        rate: null,
        budget: {
          model: "credits",
          free_allowance: "1000",
          allowance_unit: "Credits",
          allowance_period: "monthly",
          cost_per_1k: null,
          standard_native_cost: "1",
          usd_per_call: "0.0038",
          on_exhausted: "402",
          usage_api: "https://api.firecrawl.dev/v2/team/credit-usage",
          priced: true,
        },
        conversion_profile: firecrawlProfile(),
        plan_name: "Free plan (1,000 monthly credits)",
        usage_url: "https://firecrawl.dev/app/settings",
        version: 1,
      },
      free_tiers: [],
      paid_tiers: [],
      unknown_tiers: [],
      tier_split_known: true,
      aggregate_pool: {
        pool_id: "firecrawl:keyed:credit",
        provider: "firecrawl",
        auth_mode: "keyed",
        native_unit: "CREDIT",
        remaining: "850",
        allowance: "1000",
        actual_spend_usd: null,
        source: "vendor_api",
        confidence: "authoritative",
        reset_at: "2026-04-01T00:00:00Z",
        observed_at: "2026-03-10T12:00:00Z",
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
          remaining_crd: "3230",
          local_remaining_crd: null,
          request_cost_crd: "7.6",
          shared_pool_id: "firecrawl:keyed:credit",
          possible_standard_calls: "425",
          price_version: "hobby-reference",
          priced: true,
        },
        {
          state: "finite",
          operation: "fetch",
          remaining_crd: "3230",
          local_remaining_crd: null,
          request_cost_crd: "3.8",
          shared_pool_id: "firecrawl:keyed:credit",
          possible_standard_calls: "850",
          price_version: "hobby-reference",
          priced: true,
        },
      ],
      rate_progress: [],
      grants: null,
      detail: {
        plan_name: "Free plan (1,000 monthly credits)",
        native_unit: "CREDIT",
        native_balance: "850",
        native_allowance: "1000",
        usd_per_call: null,
        actual_spend_usd: null,
        reset_at: "2026-04-01T00:00:00Z",
        reset_rule: "monthly_first",
        usage_url: "https://firecrawl.dev/app/settings",
        source: "vendor_api",
        confidence: "authoritative",
        last_sync_at: "2026-03-10T12:00:00Z",
        stale: false,
        price_version: "hobby-reference",
        crd_split_note: null,
        rate_windows: [
          {
            bucket_id: "firecrawl:keyed:requests",
            limit: "10",
            window: "1m",
            scope: "team",
            unit: "requests",
            remaining: "10",
            reset_at: null,
            source: "local",
            confidence: "observed",
          },
        ],
        retry_after_seconds: null,
        tier_split_known: true,
        aggregate_pool_id: "firecrawl:keyed:credit",
      },
    } as unknown as ProviderAuthLimits
  }

  function firecrawlLimits(): ProviderLimits {
    return {
      provider: "firecrawl",
      active_auth_mode: "keyed",
      auths: [firecrawlAuth()],
      documented_keyless_operations: [],
      version: 1,
      generated_at: "2026-03-10T12:00:00Z",
    }
  }

  function renderFirecrawlCard(): void {
    installFetchStub(() => ok({ events: [], next_cursor: null }))
    render(
      <ProviderLimitsCard
        providerId="firecrawl"
        providerName="Firecrawl"
        limits={firecrawlLimits()}
        crdUsageTotals={[]}
        refreshDashboard={() => Promise.resolve()}
        manualEligible
      />,
    )
  }

  it("renders Firecrawl card with Credits display and manual entry modal displays Credits", async () => {
    renderFirecrawlCard()
    expect(screen.getByRole("heading", { name: "Firecrawl" })).not.toBeNull()

    const user = userEvent.setup()
    const infoButton = screen.getByRole("button", { name: "Credit details for Firecrawl" })
    await user.click(infoButton)
    expect(await screen.findByText("Monthly credits")).not.toBeNull()

    await user.keyboard("{Escape}")
    await user.click(screen.getByRole("button", { name: "Actions for Firecrawl" }))
    await user.click(await screen.findByRole("button", { name: "Set balance" }))

    expect(await screen.findByRole("dialog")).not.toBeNull()
    expect(screen.getByText("Allowance (credits)")).not.toBeNull()
    vi.unstubAllGlobals()
  })
})

/**
 * Parallel OAuth balance fallback (Option A, frontend-only): the Account-API
 * balance_to_snapshot returns remaining USD with limit/percent null and no
 * aggregate pool, so the limits model holds no funds. The card shows the
 * authoritative remaining-only latestQuota against the display-only $5/mo
 * free credit (5000 CRD): "24870 / 5000 CRD" with a capped 100% bar (Firecrawl
 * 4761.4/3800 pattern) while Disconnect stays inline. Desktop only.
 */
describe("ProviderLimitsCard Parallel OAuth balance", () => {
  function parallelRecord(operation: "search" | "fetch"): LimitRecord {
    return {
      provider: "parallel",
      operation,
      auth_mode: "keyed",
      supported: true,
      transport_available: true,
      native_pool_id: null,
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
      plan_name: "Parallel",
      usage_url: null,
      version: 1,
    }
  }

  function parallelUnknownView(operation: "search" | "fetch"): CRDView {
    return {
      state: "unknown",
      operation,
      remaining_crd: null,
      local_remaining_crd: null,
      request_cost_crd: null,
      shared_pool_id: null,
      possible_standard_calls: null,
      price_version: null,
      priced: false,
    }
  }

  function parallelNoPoolLimits(): ProviderLimits {
    return {
      provider: "parallel",
      active_auth_mode: "keyed",
      auths: [
        {
          auth_mode: "keyed",
          transport_available: true,
          search: parallelRecord("search"),
          fetch: parallelRecord("fetch"),
          free_tiers: [],
          paid_tiers: [],
          unknown_tiers: [],
          tier_split_known: true,
          aggregate_pool: null,
          crd_views: [parallelUnknownView("search"), parallelUnknownView("fetch")],
          rate_progress: [],
          grants: null,
          detail: null,
        },
      ],
      documented_keyless_operations: [],
      version: 1,
      generated_at: "2026-03-10T12:00:00Z",
    }
  }

  function authoritativeBalanceQuota(): DashboardQuota {
    return {
      provider: "parallel",
      remaining: "24.87",
      remainingPercent: null,
      limit: null,
      observed_at: "2026-09-06T18:00:00Z",
      source: "authoritative",
      unitKind: "USD",
      displayUnit: "USD",
      resetAt: null,
      window: null,
    }
  }

  it("shows the OAuth balance against the $5 free credit with a capped bar after pairing", () => {
    installFetchStub(() => {
      throw new Error("no backend in card test")
    })
    render(
      <ProviderLimitsCard
        providerId="parallel"
        providerName="Parallel"
        limits={parallelNoPoolLimits()}
        crdUsageTotals={[]}
        refreshDashboard={() => Promise.resolve()}
        manualEligible={false}
        latestQuota={authoritativeBalanceQuota()}
        renderOAuthActions={() => <button type="button">Disconnect</button>}
      />,
    )
    expect(screen.getByRole("button", { name: "Disconnect" })).not.toBeNull()
    // No allowance is invented: the OAuth balance shows as the dollar amount
    // left, with its CRD value as hover text, and no bar.
    const amount = screen.getByText("$24.87 left")
    expect(amount.getAttribute("title")).toBe("$24.87")
    expect(screen.queryByText("/ 5,000")).toBeNull()
    expect(screen.queryByRole("progressbar", { name: "Parallel credit units remaining" })).toBeNull()
    expect(
      screen.queryByText("Shown against the $5/mo free credit allowance."),
    ).toBeNull()
    expect(
      screen.queryByText("No allowance is reported, so this card shows no percentage."),
    ).toBeNull()
    vi.unstubAllGlobals()
  })
})

/**
 * You.com Usage card parity with Parallel/Exa (frontend-only, desktop only).
 *
 * UI id `youcom` maps to backend `you` via idMapping. Search ($5/1k, 5 CRD)
 * and fetch ($1/1k live pages, 1 CRD) costs differ, so the card keeps
 * per-operation rate bars (Brave pattern): no shared bar, no shared title.
 * Keyed funds reuse the finite-USD path; without a catalog pool the ESTIMATED
 * cents balance-API snapshot falls back to the display-only $100 signup
 * credit (100000 CRD total, fetch-basis) with a capped bar, like Parallel
 * $5/5000. A vendor-balance pool without a backend allowance shows the same
 * display-only 100000 CRD denominator with a capped 100% bar (Firecrawl
 * 4761/3800 pattern), never the amount-only footnote. Searches left adds the
 * daily 100 to the credit-derived searches from the same balance. Refresh
 * Limits stays visible for keyed; a keyless rail hides it. No Free strike
 * applies (keyed paid rail). Manual entry stays out: the vendor balance API
 * supplies the balance and "you" holds no manual_anchor pool.
 */
describe("ProviderLimitsCard You.com", () => {
  function youcomProfile(): Record<string, unknown> {
    return {
      reference_usd_per_crd: "0.001",
      native_usd_per_unit: "1",
      cost_basis: "priced_native_use",
      price_version: "v2026-09",
      source: "documented",
      estimated: false,
    }
  }

  function youcomRecord(operation: "search" | "fetch", authMode: "keyed" | "keyless" = "keyed"): LimitRecord {
    const supported = authMode === "keyed" || operation === "search"
    return {
      provider: "youcom",
      operation,
      auth_mode: authMode,
      supported,
      transport_available: supported,
      native_pool_id: authMode === "keyed" ? "youcom:keyed:usd" : null,
      rate: null,
      budget: null,
      conversion_profile: youcomProfile(),
      plan_name: "You.com",
      usage_url: "https://you.com/platform/analytics",
      version: 1,
    } as unknown as LimitRecord
  }

  function youcomView(operation: "search" | "fetch", remaining: string, calls: string): CRDView {
    return {
      state: "finite",
      operation,
      remaining_crd: remaining,
      local_remaining_crd: null,
      request_cost_crd: operation === "search" ? "5" : "1",
      shared_pool_id: "youcom:keyed:usd",
      possible_standard_calls: calls,
      price_version: "v2026-09",
      priced: true,
    }
  }

  function youcomUnknownView(operation: "search" | "fetch"): CRDView {
    return {
      state: "unknown",
      operation,
      remaining_crd: null,
      local_remaining_crd: null,
      request_cost_crd: null,
      shared_pool_id: null,
      possible_standard_calls: null,
      price_version: null,
      priced: false,
    }
  }

  function youcomRateProgress(overrides: Partial<RateProgressView>): RateProgressView {
    return {
      bucket_id: "youcom:keyed:search:requests",
      operation: "search",
      window: "1h",
      unit: "requests",
      remaining: "90",
      limit: "100",
      reset_at: null,
      source: "documented",
      confidence: "observed",
      kind: "rate",
      stale: false,
      enforceable: true,
      ...overrides,
    }
  }

  function youcomKeyedLimits(): ProviderLimits {
    return {
      provider: "youcom",
      active_auth_mode: "keyed",
      auths: [
        {
          auth_mode: "keyed",
          transport_available: true,
          search: youcomRecord("search"),
          fetch: youcomRecord("fetch"),
          free_tiers: [],
          paid_tiers: [],
          unknown_tiers: [],
          tier_split_known: true,
          aggregate_pool: {
            pool_id: "youcom:keyed:usd",
            provider: "youcom",
            auth_mode: "keyed",
            native_unit: "USD",
            remaining: "95.500",
            allowance: "100.000",
            actual_spend_usd: null,
            source: "vendor_api",
            confidence: "estimated",
            reset_at: null,
            observed_at: "2026-09-06T10:05:00Z",
            version: 1,
            credential_generation: 1,
            next_sync_at: null,
            stale: false,
            manual_anchor: false,
          },
          crd_views: [youcomView("search", "95500", "19100"), youcomView("fetch", "95500", "95500")],
          rate_progress: [
            youcomRateProgress({}),
            youcomRateProgress({
              bucket_id: "youcom:keyed:fetch:pages",
              operation: "fetch",
              window: "1d",
              unit: "urls",
              remaining: "900",
              limit: "1000",
            }),
          ],
          grants: null,
          detail: null,
        },
      ],
      documented_keyless_operations: ["search"],
      version: 1,
      generated_at: "2026-03-10T12:00:00Z",
    } as unknown as ProviderLimits
  }

  function youcomVendorBalanceNoAllowanceLimits(): ProviderLimits {
    return {
      provider: "youcom",
      active_auth_mode: "keyed",
      auths: [
        {
          auth_mode: "keyed",
          transport_available: true,
          search: youcomRecord("search"),
          fetch: youcomRecord("fetch"),
          free_tiers: [],
          paid_tiers: [],
          unknown_tiers: [],
          tier_split_known: true,
          aggregate_pool: {
            pool_id: "youcom:keyed:usd",
            provider: "youcom",
            auth_mode: "keyed",
            native_unit: "USD",
            remaining: "199.52",
            allowance: null,
            actual_spend_usd: null,
            source: "vendor_api",
            confidence: "estimated",
            reset_at: null,
            observed_at: "2026-09-06T10:05:00Z",
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
              remaining_crd: "100000",
              local_remaining_crd: null,
              request_cost_crd: "5",
              shared_pool_id: "you:keyed:daily-search",
              possible_standard_calls: "100",
              price_version: "v2026-09",
              priced: true,
            },
            {
              state: "finite",
              operation: "fetch",
              remaining_crd: "199520",
              local_remaining_crd: null,
              request_cost_crd: "1",
              shared_pool_id: "youcom:keyed:usd",
              possible_standard_calls: "199520",
              price_version: "v2026-09",
              priced: true,
            },
          ],
          rate_progress: [],
          grants: null,
          detail: null,
        },
      ],
      documented_keyless_operations: ["search"],
      version: 1,
      generated_at: "2026-03-10T12:00:00Z",
    } as unknown as ProviderLimits
  }

  function youcomNoPoolLimits(authMode: "keyed" | "keyless" = "keyed"): ProviderLimits {
    return {
      provider: "youcom",
      active_auth_mode: authMode,
      auths: [
        {
          auth_mode: authMode,
          transport_available: true,
          search: youcomRecord("search", authMode),
          fetch: youcomRecord("fetch", authMode),
          free_tiers: [],
          paid_tiers: [],
          unknown_tiers: [],
          tier_split_known: true,
          aggregate_pool: null,
          crd_views: [youcomUnknownView("search"), youcomUnknownView("fetch")],
          rate_progress: [],
          grants: null,
          detail: null,
        },
      ],
      documented_keyless_operations: ["search"],
      version: 1,
      generated_at: "2026-03-10T12:00:00Z",
    } as unknown as ProviderLimits
  }

  function estimatedBalanceQuota(): DashboardQuota {
    return {
      provider: "youcom",
      remaining: "4.75",
      remainingPercent: null,
      limit: null,
      observed_at: "2026-09-06T18:00:00Z",
      source: "estimated",
      unitKind: "USD",
      displayUnit: "USD",
      resetAt: null,
      window: null,
    }
  }

  it("shows finite-USD funds with per-operation rate bars and a visible refresh for keyed", async () => {
    installFetchStub(() => ok({ events: [], next_cursor: null }))
    render(
      <ProviderLimitsCard
        providerId="youcom"
        providerName="You.com"
        limits={youcomKeyedLimits()}
        crdUsageTotals={[]}
        refreshDashboard={() => Promise.resolve()}
        manualEligible={false}
      />,
    )
    // Finite-USD pool: 95.500/100.000 USD -> 95500/100000 CRD at 95.5%.
    expect(screen.getByText("$95.5")).not.toBeNull()
    expect(screen.getByText("/ $100")).not.toBeNull()
    expect(screen.getByText("USD")).not.toBeNull()
    const bar = screen.getByRole("progressbar", { name: "You.com balance remaining" })
    expect(bar.getAttribute("aria-valuenow")).toBe("95.5")
    expect(bar.getAttribute("aria-valuetext")).toBe("95.5% remaining, $95.50 left")
    expect(screen.getByText("95.5%")).not.toBeNull()
    // Per-operation rate bars (Brave pattern): distinct Search/Fetch titles,
    // never the shared Keenable title.
    expect(screen.getByText("Search")).not.toBeNull()
    expect(screen.getByText("Fetch")).not.toBeNull()
    expect(screen.getByText("90 of 100 requests left this hour")).not.toBeNull()
    expect(screen.getByText("900 of 1,000 URLs left today")).not.toBeNull()
    expect(
      screen.getByRole("progressbar", { name: "You.com search hourly requests remaining" }).getAttribute("aria-valuenow"),
    ).toBe("90")
    expect(
      screen.getByRole("progressbar", { name: "You.com fetch daily URLs remaining" }).getAttribute("aria-valuenow"),
    ).toBe("90")
    expect(screen.queryByText("Search and fetch")).toBeNull()
    // Keyed rail keeps Refresh Limits visible.
    expect(screen.queryByRole("button", { name: "Refresh limits for You.com" })).not.toBeNull()
    // Distinct per-operation call costs in the details popover, with no Free strike.
    const user = userEvent.setup()
    await user.click(screen.getByRole("button", { name: "Credit details for You.com" }))
    expect(await screen.findByText("Search cost (USD)")).not.toBeNull()
    expect(screen.getByText("Fetch cost (USD)")).not.toBeNull()
    expect(document.querySelector("s")).toBeNull()
    await user.keyboard("{Escape}")
    expect(screen.queryByText("Quota details")).toBeNull()
    vi.unstubAllGlobals()
  })

  it("falls back to the estimated balance against the $100 signup credit without a pool", () => {
    installFetchStub(() => {
      throw new Error("no backend in card test")
    })
    render(
      <ProviderLimitsCard
        providerId="youcom"
        providerName="You.com"
        limits={youcomNoPoolLimits()}
        crdUsageTotals={[]}
        refreshDashboard={() => Promise.resolve()}
        manualEligible={false}
        latestQuota={estimatedBalanceQuota()}
      />,
    )
    // No invented signup allowance: the balance shows as dollars left, no bar.
    expect(screen.getByText("$4.75 left").getAttribute("title")).toBe("$4.75")
    expect(screen.queryByText("/ 100,000")).toBeNull()
    expect(screen.queryByRole("progressbar", { name: "You.com credit units remaining" })).toBeNull()
    expect(
      screen.queryByText("No allowance is reported, so this card shows no percentage."),
    ).toBeNull()
    expect(screen.queryByRole("button", { name: "Refresh limits for You.com" })).toBeNull()
    vi.unstubAllGlobals()
  })

  it("shows the fallback amount-only when the CRD conversion is unavailable", () => {
    installFetchStub(() => {
      throw new Error("no backend in card test")
    })
    const limits = youcomNoPoolLimits()
    const auth = limits.auths[0]
    const unpriced = {
      ...auth,
      search: { ...auth.search, conversion_profile: { ...youcomProfile(), reference_usd_per_crd: "0.000" } },
      fetch: { ...auth.fetch, conversion_profile: { ...youcomProfile(), reference_usd_per_crd: "0.000" } },
    }
    render(
      <ProviderLimitsCard
        providerId="youcom"
        providerName="You.com"
        limits={{ ...limits, auths: [unpriced] } as unknown as ProviderLimits}
        crdUsageTotals={[]}
        refreshDashboard={() => Promise.resolve()}
        manualEligible={false}
        latestQuota={estimatedBalanceQuota()}
      />,
    )
    // The dollar balance still shows alone: no fraction, no bar, no percent.
    expect(screen.getByText("$4.75 left")).not.toBeNull()
    expect(screen.queryByRole("progressbar", { name: "You.com credit units remaining" })).toBeNull()
    expect(screen.queryByText("4750")).toBeNull()
    expect(screen.queryByText("4.8%")).toBeNull()
    vi.unstubAllGlobals()
  })

  it("shows the vendor-balance pool without an allowance as dollars left with no bar", async () => {
    installFetchStub(() => ok({ events: [], next_cursor: null }))
    render(
      <ProviderLimitsCard
        providerId="youcom"
        providerName="You.com"
        limits={youcomVendorBalanceNoAllowanceLimits()}
        crdUsageTotals={[]}
        refreshDashboard={() => Promise.resolve()}
        manualEligible={false}
      />,
    )
    // 199.52 USD with no reported allowance: the card shows "$199.52 left",
    // never a fraction against an invented signup allowance.
    expect(screen.getByText("$199.52 left")).not.toBeNull()
    expect(screen.queryByText("/ 100,000")).toBeNull()
    expect(screen.queryByRole("progressbar", { name: "You.com credit units remaining" })).toBeNull()
    expect(
      screen.queryByText("No allowance is reported, so this card shows no percentage."),
    ).toBeNull()
    // Keyed rail keeps Refresh Limits visible.
    expect(screen.queryByRole("button", { name: "Refresh limits for You.com" })).not.toBeNull()
    // Popover: Search CRD cost 5, Searches left total 40004 (daily 100 +
    // credit 39904 from 199520/5), Fetch CRD cost 1, Fetches left 199520.
    const user = userEvent.setup()
    await user.click(screen.getByRole("button", { name: "Credit details for You.com" }))
    expect(await screen.findByText("Search cost (USD)")).not.toBeNull()
    expect(screen.getByText("Fetch cost (USD)")).not.toBeNull()
    expect(screen.getByText("Searches left")).not.toBeNull()
    expect(screen.getByText("40,004")).not.toBeNull()
    expect(screen.getByText("Fetches left")).not.toBeNull()
    expect(screen.getAllByText("199,520").length).toBeGreaterThanOrEqual(1)
    await user.keyboard("{Escape}")
    expect(screen.queryByText("Quota details")).toBeNull()
    vi.unstubAllGlobals()
  })

  it("hides Refresh Limits for a keyless rail", () => {
    installFetchStub(() => {
      throw new Error("no backend in card test")
    })
    render(
      <ProviderLimitsCard
        providerId="youcom"
        providerName="You.com"
        limits={youcomNoPoolLimits("keyless")}
        crdUsageTotals={[]}
        refreshDashboard={() => Promise.resolve()}
        manualEligible={false}
      />,
    )
    expect(screen.getByRole("heading", { name: "You.com" })).not.toBeNull()
    expect(screen.queryByRole("button", { name: "Refresh limits for You.com" })).toBeNull()
    vi.unstubAllGlobals()
  })

  it("does not duplicate refresh when key balances supply the control", () => {
    installFetchStub(() => ok({ events: [], next_cursor: null }))
    render(
      <ProviderLimitsCard
        providerId="youcom"
        providerName="You.com"
        limits={youcomKeyedLimits()}
        crdUsageTotals={[]}
        refreshDashboard={() => Promise.resolve()}
        manualEligible={false}
        keyBalances={<button type="button">Refresh key balances</button>}
      />,
    )
    expect(screen.getByRole("button", { name: "Refresh key balances" })).not.toBeNull()
    expect(screen.queryByRole("button", { name: "Refresh limits for You.com" })).toBeNull()
    vi.unstubAllGlobals()
  })
})
