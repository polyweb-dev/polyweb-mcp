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

/** CARD-3 fraction oracle: "4500 / 5000 CRD" renders as split spans, never one "4500 CRD" node. */
function expectFraction(remaining: string, total: string): void {
  expect(screen.getByText(remaining)).not.toBeNull()
  expect(screen.getByText(`/ ${total}`)).not.toBeNull()
  expect(screen.getByText("CRD")).not.toBeNull()
  expect(screen.queryByText(`${remaining} CRD`)).toBeNull()
  expect(screen.queryByText("CRD left")).toBeNull()
  const value = screen.getByText(remaining).closest("span")?.parentElement
  expect(value?.textContent?.replace(/\s+/g, "")).toBe(`${remaining}/${total}CRD`)
}

describe("ProviderLimitsCard Brave", () => {
  it("shows one credit bar with 90 percent, CRD only, and no fetch headline (UI7-01, UI7-02, UI7-04, final-polish 3c)", () => {
    renderBraveCard()
    const bar = screen.getByRole("progressbar", { name: "Brave credit units remaining" })
    expect(bar.getAttribute("aria-valuenow")).toBe("90")
    expect(bar.getAttribute("aria-valuemin")).toBe("0")
    expect(bar.getAttribute("aria-valuemax")).toBe("100")
    expect(screen.getByText("90%")).not.toBeNull()
    // CARD-3: credit fraction "4500 / 5000 CRD" via split spans; no "CRD left" label.
    expectFraction("4500", "5000")
    // Final-polish Item 3c: card shows CRD only. USD value sits in hover title and aria-label.
    expect(screen.queryByText("4.500")).toBeNull()
    expect(screen.queryByText("USD left")).toBeNull()
    expect(screen.queryByText("USD use (priced)")).toBeNull()
    const crdValue = screen.getByText("4500")
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
    expectFraction("4500", "5000")
    const crdValue = screen.getByText("4500")
    expect(crdValue.getAttribute("title")).toBe("$4.5 left")
    expect(crdValue.getAttribute("aria-label")).toBe("$4.5 left")
    expect(screen.queryByText("USD left")).toBeNull()
    expect(screen.queryByText("CRD left")).toBeNull()
    const bar = screen.getByRole("progressbar", { name: "Brave credit units remaining" })
    expect(bar.getAttribute("aria-valuetext")).toBe("90% remaining, 4500 CRD left")
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
    await user.click(screen.getByRole("button", { name: "Budget Limit for Brave. Sets a local credit-unit ceiling that adds no vendor funds." }))
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
    expectFraction("4500", "5000")
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
    expectFraction("4495", "5000")
    expect(screen.getByText("89.9%")).not.toBeNull()
    vi.unstubAllGlobals()
  })

  it("holds logo, name, and source statement in the header (CARD-3)", () => {
    renderBraveCard()
    expect(screen.getByTestId("provider-logo-brave")).not.toBeNull()
    expect(screen.getByRole("heading", { name: "Brave" })).not.toBeNull()
    expect(screen.getByText("Observed from the vendor API")).not.toBeNull()
    const headerRow = screen.getByTestId("provider-logo-brave").closest("div.flex")
    expect(headerRow?.textContent).toContain("Brave")
    expect(headerRow?.textContent).toContain("Observed from the vendor API")
    vi.unstubAllGlobals()
  })

  it("places actions at the leading edge and the fraction at the trailing edge below the bar (CARD-3)", () => {
    renderBraveCard()
    const buttons = screen.getAllByRole("button").map((button) => button.textContent)
    expect(buttons.slice(0, 4)).toEqual(["Sync", "Provider Balance", "Budget Limit", "History"])
    const info = screen.getByRole("button", { name: "Credit details for Brave" })
    expect(info.getAttribute("data-testid")).toBe("credit-info-brave")
    const creditRow = screen.getByText("4500").closest("span")?.parentElement?.parentElement
    expect(creditRow?.className).toContain("justify-between")
    const children = Array.from(creditRow?.children ?? [])
    expect(children.length).toBe(2)
    expect(children[0]?.textContent).toContain("Sync")
    expect(children[0]?.textContent).toContain("Provider Balance")
    expect(children[0]?.textContent).toContain("Budget Limit")
    expect(children[0]?.textContent).toContain("History")
    expect(children[1]?.textContent?.replace(/\s+/g, "")).toContain("4500/5000CRD")
    const fractionSpan = screen.getByText("4500").closest("span")?.parentElement
    expect(fractionSpan?.contains(info)).toBe(true)
    const bar = screen.getByRole("progressbar", { name: "Brave credit units remaining" })
    expect((bar.compareDocumentPosition(creditRow as Node) & Node.DOCUMENT_POSITION_FOLLOWING) !== 0).toBe(true)
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
    const bar = screen.getByRole("progressbar", { name: "Keenable credit units remaining" })
    expect(bar.getAttribute("aria-valuemin")).toBe("0")
    expect(bar.getAttribute("aria-valuemax")).toBe("100")
    expect(bar.getAttribute("aria-valuenow")).toBe("100")
    expect(bar.querySelector("div")?.getAttribute("class")).toContain(
      "bg-[var(--status-healthy)]",
    )
    expectFraction("399980", "400000")
    expect(screen.queryByText("Free - unmetered")).toBeNull()
    const value = screen.getByText("399980").closest("span")?.parentElement
    expect(value?.textContent?.replace(/\s+/g, "")).toBe("399980/400000CRD")
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
    expect(screen.getByText("Free - unmetered")).not.toBeNull()
    expect(screen.queryByRole("progressbar", { name: "Keenable credit units remaining" })).toBeNull()
    const struck = screen.getByText("Free - unmetered").closest("s")
    expect(struck).not.toBeNull()
    expect(screen.getByText("free", { exact: true })).not.toBeNull()
    const user = userEvent.setup()
    await user.click(screen.getByRole("button", { name: "Credit details for Keenable" }))
    expect(await screen.findByText("Search hourly rate")).not.toBeNull()
    expect(screen.getByText("990 of 1000 requests")).not.toBeNull()
    vi.unstubAllGlobals()
  })

  it("keenable funds use the shared bar with one aggregate value", () => {
    renderKeenableCard(keenableLimits())
    const bars = screen.getAllByRole("progressbar", {
      name: "Keenable credit units remaining",
    })
    expect(bars).toHaveLength(1)
    expectFraction("399980", "400000")
    expect(screen.getByText("100%")).not.toBeNull()
    vi.unstubAllGlobals()
  })

  it("keenable hourly requests use whole counts on a separate bar line", async () => {
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
    const user = userEvent.setup()
    await user.click(screen.getByRole("button", { name: "Credit details for Keenable" }))
    expect(await screen.findByText("Search hourly rate")).not.toBeNull()
    expect(screen.getByText("Fetch hourly rate")).not.toBeNull()
    expect(screen.getAllByText("990 of 1000 requests")).toHaveLength(2)
    expect(screen.queryByText("990.00000000")).toBeNull()
    const bar = screen.getByRole("progressbar", {
      name: "Keenable search hourly requests remaining",
    })
    const label = screen.getByText("Search hourly rate")
    expect(bar.getAttribute("class")).toContain("w-full")
    expect((label.compareDocumentPosition(bar) & Node.DOCUMENT_POSITION_FOLLOWING) !== 0).toBe(true)
    vi.unstubAllGlobals()
  })

  it("keenable keyless credits keep the prior strike value next to free", () => {
    renderKeenableCard(keenableKeylessLimits())
    const struck = screen.getByText("Free - unmetered").closest("s")
    expect(struck).not.toBeNull()
    expect(struck?.textContent).toContain("Free - unmetered")
    expect(screen.getByText("free", { exact: true })).not.toBeNull()
    expect(
      screen.queryByRole("progressbar", { name: "Keenable credit units remaining" }),
    ).toBeNull()
    expect(screen.queryByText("399980")).toBeNull()
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
    const user = userEvent.setup()
    await user.click(screen.getByRole("button", { name: "Credit details for Keenable" }))
    expect(await screen.findByText("Search hourly rate")).not.toBeNull()
    expect(screen.queryByText("authoritative")).toBeNull()
    vi.unstubAllGlobals()
  })

  it("keenable keyed details preserve authoritative rate confidence", async () => {
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
    const user = userEvent.setup()
    await user.click(screen.getByRole("button", { name: "Credit details for Keenable" }))
    expect(await screen.findByText("Search hourly rate")).not.toBeNull()
    expect(screen.getByText("authoritative")).not.toBeNull()
    vi.unstubAllGlobals()
  })

  it("keenable details preserve search and fetch CRD cost labels", async () => {
    installFetchStub(() => ok({ events: [], next_cursor: null }))
    renderKeenableCard(keenableLimits())
    const user = userEvent.setup()
    await user.click(screen.getByRole("button", { name: "Credit details for Keenable" }))
    expect(await screen.findByText("Search CRD cost")).not.toBeNull()
    expect(screen.getByText("Fetch CRD cost")).not.toBeNull()
    expect(screen.getAllByText("4 CRD").length).toBeGreaterThanOrEqual(2)
    vi.unstubAllGlobals()
  })
})
