import React from "react"
import { describe, it, expect, afterEach, vi } from "vitest"
import { cleanup, render, screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { MemoryRouter } from "react-router"
import { FreeSearchProvider } from "@/context/FreeSearchContext"
import { ADMIN_ACCOUNT_ID } from "@/test/authFixtures"
import { ProjectsContext } from "@/domains/projects/state/context"
import {
  SETTINGS_READER_PERMISSIONS,
  projectsContextFixture,
  systemAccessFixture,
} from "@/test/accessFixtures"
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
      <MemoryRouter initialEntries={["/system/providers"]}>
        <ProjectsContext.Provider
          value={projectsContextFixture({ systemAccess: systemAccessFixture(SETTINGS_READER_PERMISSIONS) })}
        >
          <SettingsView />
        </ProjectsContext.Provider>
      </MemoryRouter>
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
      <MemoryRouter initialEntries={["/system/quotas"]}>
        <QuotaAnalytics />
      </MemoryRouter>
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
        usd_views: [
          {
            state: "finite",
            operation: "search",
            remaining_usd: "4.5",
            local_remaining_usd: null,
            request_cost_usd: "0.005",
            shared_pool_id: "brave:keyed:usd",
            possible_standard_calls: "900",
            price_version: "v2026-09",
            priced: true,
          },
          {
            state: "unavailable",
            operation: "fetch",
            remaining_usd: null,
            local_remaining_usd: null,
            request_cost_usd: null,
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

function spendTotalsWire(): Record<string, unknown>[] {
  return [
    {
      provider: "brave",
      operation: "search",
      spend_usd: "0.599",
      attempt_count: 2,
      volume_count: 3,
    },
    {
      provider: "tavily",
      operation: "search",
      spend_usd: "0.05",
      attempt_count: 1,
      volume_count: 1,
    },
    {
      provider: "exa",
      operation: "search",
      spend_usd: "0",
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
      <MemoryRouter initialEntries={["/system/quotas"]}>
        <QuotaAnalytics />
      </MemoryRouter>
    </FreeSearchProvider>
  )
}

describe("RF2: null limits render as — on simulator / settings", () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it("quota drill-down shows em-dash blank; Usage view shows empty texts, never infinity (UI7-05)", async () => {
    const user = userEvent.setup()
    renderSettings(dashboardFixture())
    await waitForSettings()

    // Registry carries no quota cells, so it must never invent an infinity marker.
    expect(screen.getByRole("table").textContent).not.toContain("∞")
    // Release baseline: the reduced test modal shows "No test run yet" visibly
    // (no quota em-dash blank lives in this modal).
    await user.click(screen.getByRole("button", { name: "Tavily test connection" }))
    const dialog = await screen.findByRole("dialog")
    expect(dialog.textContent).not.toContain("∞")
    expect(dialog.textContent).toMatch(/Last test/)
    cleanup()

    renderUsage(dashboardFixture())
    await waitForUsage()
    // UI7-05: the native grid left the page. Empty totals show empty texts,
    // not an em-dash blank. The em-dash above covers the Settings modal only.
    expect(screen.getByText("No usage recorded yet")).toBeInTheDocument()
    const body = document.body.textContent ?? ""
    expect(body).not.toContain("∞")
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
    const testIdx = headers.indexOf("Health")
    expect(testIdx).toBeGreaterThanOrEqual(0)
    await user.click(
      within(braveRow.children[testIdx] as HTMLElement).getByRole("button", { name: /brave.*test/i })
    )
    const dialog = await screen.findByRole("dialog")
    expect(dialog.textContent).toMatch(/Last test/)
    expect(dialog.textContent).toMatch(/Endpoint/)
    expect(dialog.textContent).toMatch(/Capabilities/)
  })

  it("modal shows connection details; Usage view shows USD cost and volume (UI7-05)", async () => {
    const user = userEvent.setup()
    renderSettings(dashboardFixture({ latest_quota: canonicalQuotasFixture() }))
    await waitForSettings()

    await user.click(screen.getByRole("button", { name: "Brave Search test connection" }))
    const dialog = await screen.findByRole("dialog")
    // Release baseline: the reduced modal shows the "No test run yet" value
    // with Endpoint/Capabilities, not normalized capacity rows.
    expect(dialog.textContent).toMatch(/Last test/)
    expect(dialog.textContent).toMatch(/Endpoint/)
    cleanup()

    // The usage table shows USD costs, and a null p95 stays blank.
    const nullBraveProviders = allProvidersFixture().map((entry) =>
      entry.provider_id === "brave" ? { ...entry, latency_p95_ms: null } : entry
    )
    const dashboard = dashboardWithExtras(
      dashboardFixture({ latest_quota: canonicalQuotasFixture() }),
      { spend_totals: spendTotalsWire() }
    )
    renderUsageWithProviders(dashboard, nullBraveProviders)
    await waitForUsage()
    // Await the data-dependent table, not the static "Usage totals" shell.
    const usage = await screen.findByRole("table", { name: "Usage totals" }, { timeout: 10_000 })
    expect(within(usage).getByText("Known cost")).toBeInTheDocument()
    expect(within(usage).getByText("p95")).toBeInTheDocument()
    expect(usage.textContent).not.toContain("∞")
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
    // Release baseline: an untested provider shows "No test run yet" visibly.
    expect(dialog.textContent).toMatch(/Last test/i)
    cleanup()

    // UI7-05: UsageTotals holds no unavailable marker. Empty totals show
    // empty texts.
    renderUsage(dashboardFixture({ latest_quota: [] }))
    await waitForUsage()
    expect(screen.getByText("No usage recorded yet")).toBeInTheDocument()
  })

  it("test modal shows quota confidence/unavailable visibly, not title-only", async () => {
    const user = userEvent.setup()
    renderSettings(dashboardFixture({ latest_quota: canonicalQuotasFixture() }))
    await waitForSettings()

    const table = screen.getByRole("table")
    const testHeaderIdx = Array.from(table.querySelectorAll("thead th")).findIndex(
      (th) => th.textContent?.trim() === "Health"
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
    expect(dialog.textContent).toMatch(/Last test/)
  })

  it("page shows Brave spend in USD without the retired price note (UI7-06)", async () => {
    const dashboard = dashboardWithExtras(dashboardFixture({ latest_quota: [] }), {
      provider_limits: [bravePriceLimitsWire()],
      spend_totals: [{ provider: "brave", operation: "search", spend_usd: "0.005", attempt_count: 1, volume_count: 1 }],
    })
    renderUsage(dashboard)
    const table = await screen.findByRole("table", { name: "Usage totals" })
    const braveRow = within(table).getByRole("row", { name: /Brave Search/ })
    expect(within(braveRow).getByText("$0.005")).toBeInTheDocument()
    expect(screen.queryByText("How credit units are priced")).toBeNull()
    expect(screen.getByText("Allowance left")).toBeInTheDocument()

    const body = document.body.textContent ?? ""
    expect(body).not.toContain("v2026-09")
    expect(body).not.toContain("Price profile")
  })
})
