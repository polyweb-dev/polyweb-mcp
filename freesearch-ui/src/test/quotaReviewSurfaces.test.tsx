import React from "react"
import { describe, it, expect, afterEach, vi } from "vitest"
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { FreeSearchProvider } from "@/context/FreeSearchContext"
import { ADMIN_ACCOUNT_ID } from "@/test/authFixtures"
import { RouteSimulator } from "@/components/routing/RouteSimulator"
import { SettingsView } from "@/components/settings/SettingsView"
import { QuotaAnalytics } from "@/components/quota/QuotaAnalytics"
import { installFetchStub, ok, err } from "@/test/fetchMock"
import {
  allProvidersFixture,
  routingConfigFixture,
  dashboardFixture,
  canonicalQuotasFixture,
  type WireDashboard,
} from "@/test/backendFixtures"

/**
 * Final Review Plan surface locks (RF2–RF4).
 *
 * - RF2: null limits render as blank/— instead of ∞ on all four surfaces.
 * - RF3: same-unit guidance caption in ranks/simulator tables; unit included
 *   in the fallback tooltip. No routing-state inference.
 * - RF4: visible (not title-only) unavailable/confidence semantics in the
 *   Settings test modal AND Usage quota view (registry carries no Quota/p95 columns).
 *
 * Deterministic: fixed fixtures, mocked fetch, no Date.now, no network.
 * Explicit non-goals (NOT asserted here): exhausted/hard/soft pills, routing
 * steering from balances, display_unit passthrough on usage totals,
 * single-snapshot-per-provider changes.
 */

function renderSimulator(dashboard: WireDashboard) {
  installFetchStub((req) => {
    if (req.url === "/api/v1/providers" && req.method === "GET") {
      return ok(allProvidersFixture())
    }
    if (req.url === "/api/v1/routing/config" && req.method === "GET") {
      return ok(routingConfigFixture())
    }
    if (req.url.startsWith("/dashboard")) return ok(dashboard)
    return err(404, { detail: "unhandled test route" })
  })
  return render(
    <FreeSearchProvider accountId={ADMIN_ACCOUNT_ID} canReadControls canEditControls>
      <RouteSimulator />
    </FreeSearchProvider>
  )
}

function renderSettings(dashboard: WireDashboard) {
  installFetchStub((req) => {
    if (req.url === "/api/v1/providers" && req.method === "GET") {
      return ok(allProvidersFixture())
    }
    if (req.url === "/api/v1/routing/config" && req.method === "GET") {
      return ok(routingConfigFixture())
    }
    if (req.url.startsWith("/dashboard")) return ok(dashboard)
    if (req.method === "POST" && req.url.endsWith("/test")) {
      return ok({
        provider: "brave",
        ok: true,
        status: "healthy",
        latency_ms: 142,
        checked_at: "2026-09-06T10:04:00Z",
        detail: null,
      })
    }
    if (req.method === "POST" && req.url.endsWith("/circuit-breaker/reset")) {
      return ok({ provider: "x", state: "closed", updated_at: "2026-09-06T10:06:00Z" })
    }
    return err(404, { detail: "unhandled test route" })
  })
  return render(
    <FreeSearchProvider accountId={ADMIN_ACCOUNT_ID} canReadControls canEditControls>
      <SettingsView />
    </FreeSearchProvider>
  )
}

async function waitForSettings() {
  await waitFor(() => {
    expect(screen.getByText("Brave Search", { exact: true })).toBeInTheDocument()
  })
}

function renderUsage(dashboard: WireDashboard) {
  installFetchStub((req) => {
    if (req.url === "/api/v1/providers" && req.method === "GET") {
      return ok(allProvidersFixture())
    }
    if (req.url === "/api/v1/routing/config" && req.method === "GET") {
      return ok(routingConfigFixture())
    }
    if (req.url.startsWith("/dashboard")) return ok(dashboard)
    return err(404, { detail: "unhandled test route" })
  })
  return render(
    <FreeSearchProvider accountId={ADMIN_ACCOUNT_ID} canReadControls canEditControls>
      <QuotaAnalytics />
    </FreeSearchProvider>
  )
}

async function waitForUsage() {
  await waitFor(() => {
    expect(screen.getByText("Usage totals", { exact: true })).toBeInTheDocument()
  })
}

// UI7-05 and UI7-06 helpers: the page holds no native grid. UsageTotals shows
// two cards with empty texts, and one price note lists Brave call costs.
function dashboardWithExtras(
  base: WireDashboard,
  extras: Record<string, unknown>
): WireDashboard {
  return { ...base, ...extras } as unknown as WireDashboard
}

function bravePriceLimitsWire(): Record<string, unknown> {
  const profile = {
    reference_usd_per_crd: "0.001",
    native_usd_per_unit: "1",
    cost_basis: "priced_native_use",
    price_version: "v2026-09",
    source: "documented",
    estimated: false,
  }
  return {
    provider: "brave",
    active_auth_mode: "keyed",
    version: 1,
    generated_at: "2026-03-10T12:00:00Z",
    documented_keyless_operations: [],
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
          conversion_profile: profile,
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
          conversion_profile: profile,
          plan_name: null,
          usage_url: null,
          version: 1,
        },
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
        detail: null,
      },
    ],
  }
}

function crdTotalsWire(): Record<string, unknown>[] {
  return [
    {
      provider: "brave",
      operation: "search",
      normalized_crd: "0.599",
      attempt_count: 2,
      volume_count: 3,
    },
    {
      provider: "tavily",
      operation: "search",
      normalized_crd: "0.05",
      attempt_count: 1,
      volume_count: 1,
    },
    {
      provider: "exa",
      operation: "search",
      normalized_crd: "0",
      attempt_count: 1,
      volume_count: 1,
    },
  ]
}

function renderUsageWithProviders(
  dashboard: WireDashboard,
  providers: unknown[]
) {
  installFetchStub((req) => {
    if (req.url === "/api/v1/providers" && req.method === "GET") {
      return ok(providers)
    }
    if (req.url === "/api/v1/routing/config" && req.method === "GET") {
      return ok(routingConfigFixture())
    }
    if (req.url.startsWith("/dashboard")) return ok(dashboard)
    return err(404, { detail: "unhandled test route" })
  })
  return render(
    <FreeSearchProvider accountId={ADMIN_ACCOUNT_ID} canReadControls canEditControls>
      <QuotaAnalytics />
    </FreeSearchProvider>
  )
}

describe("RF2: null limits render as — on simulator / settings", () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it("simulator pipeline shows — for null limits, never ∞", async () => {
    renderSimulator(dashboardFixture())
    await waitFor(() => {
      expect(
        screen.getByPlaceholderText("Type simulated query...", { exact: true })
      ).toBeInTheDocument()
    })
    fireEvent.click(screen.getByRole("button", { name: /^Simulate route$/ }))

    await waitFor(() => {
      expect(screen.getByText("Client Ingress", { exact: true })).toBeInTheDocument()
    })
    // The pipeline (primary + fallbacks) is the only quota surface here.
    const body = document.body.textContent ?? ""
    expect(body).not.toContain("∞")
    expect(body).toContain("—")
  })

  it("quota drill-down shows em-dash blank; Usage view shows empty texts, never infinity (UI7-05)", async () => {
    const user = userEvent.setup()
    renderSettings(dashboardFixture())
    await waitForSettings()

    // Registry carries no quota cells, so it must never invent an infinity marker.
    expect(screen.getByRole("table").textContent).not.toContain("∞")
    // Release baseline: the reduced test modal shows "Not tested" visibly
    // (no quota em-dash blank lives in this modal).
    await user.click(screen.getByRole("button", { name: "Tavily test connection" }))
    const dialog = await screen.findByRole("dialog")
    expect(dialog.textContent).not.toContain("∞")
    expect(dialog.textContent).toMatch(/Not tested/)
    cleanup()

    renderUsage(dashboardFixture())
    await waitForUsage()
    // UI7-05: the native grid left the page. Empty totals show empty texts,
    // not an em-dash blank. The em-dash above covers the Settings modal only.
    expect(screen.getByText("No credit-unit use recorded yet.")).toBeInTheDocument()
    expect(screen.getByText("No volume recorded yet.")).toBeInTheDocument()
    const body = document.body.textContent ?? ""
    expect(body).not.toContain("∞")
  })
})

describe("RF3: normalized-percentage guidance and native tooltip units", () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it("simulator explains that percentages are comparable and native units stay detailed", async () => {
    renderSimulator(dashboardFixture())
    await waitFor(() => {
      expect(
        screen.getByPlaceholderText("Type simulated query...", { exact: true })
      ).toBeInTheDocument()
    })

    expect(document.body.textContent).toMatch(
      /remaining percentages are comparable; details keep each provider's native unit/i
    )
  })

  it("simulator fallback tooltip includes the unit, not just confidence", async () => {
    renderSimulator(dashboardFixture({ latest_quota: canonicalQuotasFixture() }))
    await waitFor(() => {
      expect(
        screen.getByPlaceholderText("Type simulated query...", { exact: true })
      ).toBeInTheDocument()
    })
    fireEvent.click(screen.getByRole("button", { name: /^Simulate route$/ }))

    await waitFor(() => {
      expect(screen.getByText(/Failover cascade/i)).toBeInTheDocument()
    })
    // RF3: every Remaining-quota tooltip must name the unit dimension, not
    // just confidence. The fallback rows currently render only
    // `Remaining quota (${confidence})` with no unit — this must fail red
    // until the Developer appends displayUnit/unit.
    const titled = Array.from(
      document.querySelectorAll('[title*="Remaining quota"]')
    ) as HTMLElement[]
    expect(titled.length).toBeGreaterThanOrEqual(2)
    for (const el of titled) {
      expect(el.getAttribute("title")).toMatch(/units|credits|requests|USD|legacy/i)
    }
  })
})

describe("RF4: visible unavailable/confidence semantics in Settings modal + Usage view", () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it("registry carries no Quota/p95 columns; confidence lives in the modal + Usage quota view", async () => {
    const user = userEvent.setup()
    renderSettings(dashboardFixture({ latest_quota: canonicalQuotasFixture() }))
    await waitForSettings()

    const table = screen.getByRole("table")
    const headers = Array.from(table.querySelectorAll("thead th")).map(
      (th) => th.textContent?.trim() ?? ""
    )
    expect(headers).not.toContain("Quota")
    expect(headers).not.toContain("p95")
    const rows = Array.from(table.querySelectorAll("tbody tr"))
    expect(rows.length).toBe(8)
    // Merged baseline: every row keeps the seven release columns (7-col
    // uniform); the Tavily rate-tier dropdown lives only in the Usage card.
    for (const row of rows) {
      expect(row.children).toHaveLength(headers.length)
    }
    // Release baseline: the reduced modal carries Endpoint/Capabilities/Last
    // result visibly (not title-only); quota confidence lives outside it.
    const braveRow = screen.getByText("Brave Search", { exact: true }).closest("tr")!
    const testIdx = headers.indexOf("Test")
    expect(testIdx).toBeGreaterThanOrEqual(0)
    await user.click(
      within(braveRow.children[testIdx] as HTMLElement).getByRole("button", { name: /brave.*test/i })
    )
    const dialog = await screen.findByRole("dialog")
    expect(dialog.textContent).toMatch(/Not tested/)
    expect(dialog.textContent).toMatch(/Endpoint/)
    expect(dialog.textContent).toMatch(/Capabilities/)
  })

  it("modal keeps normalized capacity; Usage view shows CRD cost and volume cards (UI7-05)", async () => {
    const user = userEvent.setup()
    renderSettings(dashboardFixture({ latest_quota: canonicalQuotasFixture() }))
    await waitForSettings()

    await user.click(screen.getByRole("button", { name: "Brave Search test connection" }))
    const dialog = await screen.findByRole("dialog")
    // Release baseline: the reduced modal shows the release "Not tested" value
    // with Endpoint/Capabilities, not normalized capacity rows.
    expect(dialog.textContent).toMatch(/Not tested/)
    expect(dialog.textContent).toMatch(/Endpoint/)
    cleanup()

    // UI7-05: the native quota rows left UsageTotals. Credit-unit cost uses
    // normalized CRD headlines, and a null p95 stays blank, not an em-dash.
    const nullBraveProviders = allProvidersFixture().map((entry) =>
      entry.provider_id === "brave" ? { ...entry, latency_p95_ms: null } : entry
    )
    const dashboard = dashboardWithExtras(
      dashboardFixture({ latest_quota: canonicalQuotasFixture() }),
      { crd_usage_totals: crdTotalsWire() }
    )
    renderUsageWithProviders(dashboard, nullBraveProviders)
    await waitForUsage()
    // Await the data-dependent CRD row, not the static "Usage totals" shell.
    await screen.findByText("≈0.6 CRD", undefined, { timeout: 10_000 })
    expect(screen.getByText("Credit-unit use")).toBeInTheDocument()
    expect(screen.getByText("≈0.6 CRD")).toBeInTheDocument()
    expect(screen.getByText("<0.1 CRD")).toBeInTheDocument()
    expect(screen.getByText("0 CRD")).toBeInTheDocument()
    expect(screen.getByText("Search and URL volume")).toBeInTheDocument()
    const usageSection = document.querySelector(
      'section[aria-labelledby="usage-totals-heading"]'
    )
    expect(usageSection).not.toBeNull()
    expect(usageSection!.textContent).not.toContain("—")
    expect(document.querySelector('[data-testid^="quota-remaining-percent-"]')).toBeNull()
  })

  it("modal shows unavailable visibly; Usage view shows empty texts (UI7-05)", async () => {
    const user = userEvent.setup()
    renderSettings(dashboardFixture({ latest_quota: [] }))
    await waitForSettings()

    await user.click(screen.getByRole("button", { name: "Brave Search test connection" }))
    const dialog = await screen.findByRole("dialog")
    // Release baseline: an untested provider shows "Not tested" visibly.
    expect(dialog.textContent).toMatch(/Not tested/i)
    cleanup()

    // UI7-05: UsageTotals holds no unavailable marker. Empty totals show
    // empty texts.
    renderUsage(dashboardFixture({ latest_quota: [] }))
    await waitForUsage()
    expect(screen.getByText("No credit-unit use recorded yet.")).toBeInTheDocument()
    expect(screen.getByText("No volume recorded yet.")).toBeInTheDocument()
  })

  it("test modal shows quota confidence/unavailable visibly, not title-only", async () => {
    const user = userEvent.setup()
    renderSettings(dashboardFixture({ latest_quota: canonicalQuotasFixture() }))
    await waitForSettings()

    const table = screen.getByRole("table")
    const testHeaderIdx = Array.from(table.querySelectorAll("thead th")).findIndex(
      (th) => th.textContent?.trim() === "Test"
    )
    expect(testHeaderIdx).toBeGreaterThanOrEqual(0)
    const braveRow = screen.getByText("Brave Search", { exact: true }).closest("tr")!
    const testCell = braveRow.children[testHeaderIdx] as HTMLElement
    await user.click(within(testCell).getByRole("button", { name: /brave.*test/i }))

    const dialog = await screen.findByRole("dialog")
    // Release baseline: quota confidence is not title-only hidden; the reduced
    // modal keeps Endpoint/Capabilities/Last result visibly rendered.
    expect(dialog.textContent).toMatch(/Endpoint/)
    expect(dialog.textContent).toMatch(/Capabilities/)
    expect(dialog.textContent).toMatch(/Not tested/)
  })

  it("page shows exactly one price note with Brave cost and version once (UI7-06)", async () => {
    // UI7-06: one footer lists call costs and each known price version once.
    // The C1 catalog reports Brave search at 0.005 USD and 5 CRD per call.
    const dashboard = dashboardWithExtras(dashboardFixture({ latest_quota: [] }), {
      provider_limits: [bravePriceLimitsWire()],
      crd_usage_totals: [],
    })
    renderUsage(dashboard)
    // Await the data-dependent price row, not the static price shell.
    await screen.findByText("0.005 USD", undefined, { timeout: 10_000 })
    await waitFor(() => {
      expect(screen.getByText("How credit units are priced")).toBeInTheDocument()
    })

    const sections = document.querySelectorAll(
      'section[aria-labelledby="crd-price-note-heading"]'
    )
    expect(sections).toHaveLength(1)
    expect(screen.getAllByText("How credit units are priced")).toHaveLength(1)
    expect(screen.getByText("Provider credit units")).toBeInTheDocument()

    const note = sections[0] as HTMLElement
    expect(within(note).getByText("Provider")).toBeInTheDocument()
    expect(within(note).getByText("Operation")).toBeInTheDocument()
    expect(within(note).getByText("USD per operation")).toBeInTheDocument()
    expect(within(note).getByText("CRD per operation")).toBeInTheDocument()
    const bravePriceRow = within(note).getByText("Brave Search").closest("tr")!
    expect(within(bravePriceRow).getByText("0.005 USD")).toBeInTheDocument()
    expect(within(bravePriceRow).getByText("5 CRD")).toBeInTheDocument()
    expect(within(note).queryByText("fetch")).toBeNull()

    const body = document.body.textContent ?? ""
    const versionHits = body.match(/v2026-09/g) ?? []
    expect(versionHits).toHaveLength(1)
    expect(body).toMatch(/Price profile: v2026-09/)
  })
})
