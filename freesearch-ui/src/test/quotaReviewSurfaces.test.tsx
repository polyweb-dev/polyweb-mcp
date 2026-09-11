import React from "react"
import { describe, it, expect, afterEach, vi } from "vitest"
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { FreeSearchProvider } from "@/context/FreeSearchContext"
import { ProviderRanks } from "@/components/routing/ProviderRanks"
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

function renderRanks(dashboard: WireDashboard) {
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
    <FreeSearchProvider>
      <ProviderRanks />
    </FreeSearchProvider>
  )
}

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
    <FreeSearchProvider>
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
    <FreeSearchProvider>
      <SettingsView />
    </FreeSearchProvider>
  )
}

async function waitForRanks() {
  await waitFor(() => {
    expect(screen.getAllByText("Brave Search", { exact: true }).length).toBeGreaterThanOrEqual(1)
  })
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
    <FreeSearchProvider>
      <QuotaAnalytics />
    </FreeSearchProvider>
  )
}

async function waitForUsage() {
  await waitFor(() => {
    expect(screen.getByText("Usage totals", { exact: true })).toBeInTheDocument()
  })
}

describe("RF2: null limits render as — on ranks / simulator / settings", () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it("ranks table shows — for null limits, never ∞", async () => {
    renderRanks(dashboardFixture())
    await waitForRanks()

    const body = document.body.textContent ?? ""
    expect(body).not.toContain("∞")
    expect(body).toContain("—")
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

  it("quota drill-down + Usage view show em-dash blanks for null limits, never infinity", async () => {
    const user = userEvent.setup()
    renderSettings(dashboardFixture())
    await waitForSettings()

    // Registry carries no quota cells, so it must never invent an infinity marker.
    expect(screen.getByRole("table").textContent).not.toContain("∞")
    // Tavily (no snapshot) renders a null-limit blank in the drill-down quota value.
    await user.click(screen.getByRole("button", { name: "Tavily test connection" }))
    const dialog = await screen.findByRole("dialog")
    expect(dialog.textContent).not.toContain("∞")
    expect(dialog.textContent).toMatch(/[\u2014]/)
    cleanup()

    renderUsage(dashboardFixture())
    await waitForUsage()
    const body = document.body.textContent ?? ""
    expect(body).not.toContain("∞")
    expect(body).toMatch(/[\u2014]/)
  })

  it("RF1 verbatim: canonical Tavily limit '100000.10' survives on the ranks surface", async () => {
    renderRanks(dashboardFixture({ latest_quota: canonicalQuotasFixture() }))
    await waitForRanks()

    const body = document.body.textContent ?? ""
    expect(body).toContain("100000.10")
    expect(body).not.toContain("100000.1 ")
  })
})

describe("RF3: normalized-percentage guidance and native tooltip units", () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it("ranks table explains that percentages are comparable and native units stay detailed", async () => {
    renderRanks(dashboardFixture())
    await waitForRanks()

    expect(document.body.textContent).toMatch(
      /remaining percentages are comparable; details keep each provider's native unit/i
    )
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

  it("does not infer routing state from balances (no exhausted/hard/soft pills)", async () => {
    renderRanks(dashboardFixture({ latest_quota: canonicalQuotasFixture() }))
    await waitForRanks()

    const body = (document.body.textContent ?? "").toLowerCase()
    expect(body).not.toContain("exhausted")
    expect(body).not.toContain("hard limit")
    expect(body).not.toMatch(/soft\s+limit/)
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
    expect(rows.length).toBe(7)
    for (const row of rows) {
      expect(row.children).toHaveLength(headers.length)
    }
    // Drill-down still carries visible confidence semantics (not title-only).
    const braveRow = screen.getByText("Brave Search", { exact: true }).closest("tr")!
    const testIdx = headers.indexOf("Test")
    expect(testIdx).toBeGreaterThanOrEqual(0)
    await user.click(
      within(braveRow.children[testIdx] as HTMLElement).getByRole("button", { name: /brave.*test/i })
    )
    const dialog = await screen.findByRole("dialog")
    expect(dialog.textContent).toMatch(/authoritative|observed|estimated|unavailable|no quota/i)
  })

  it("modal + Usage quota view lead with normalized remaining capacity and its period", async () => {
    const user = userEvent.setup()
    renderSettings(dashboardFixture({ latest_quota: canonicalQuotasFixture() }))
    await waitForSettings()

    await user.click(screen.getByRole("button", { name: "Brave Search test connection" }))
    const dialog = await screen.findByRole("dialog")
    expect(dialog.textContent).toMatch(/95% remaining/)
    expect(dialog.textContent).toMatch(/950\/1000 requests/)
    cleanup()

    renderUsage(dashboardFixture({ latest_quota: canonicalQuotasFixture() }))
    await waitForUsage()
    expect(screen.getByTestId("quota-remaining-percent-brave")).toHaveTextContent("95% remaining")
    const usageBody = document.body.textContent ?? ""
    expect(usageBody).toMatch(/95% remaining.*monthly.*950\/1000 requests/i)
    expect(usageBody).toMatch(/hourly quota pending.*Hourly/i)
  })

  it("modal + Usage view show a visible unavailable marker when the dashboard has no snapshots", async () => {
    const user = userEvent.setup()
    renderSettings(dashboardFixture({ latest_quota: [] }))
    await waitForSettings()

    await user.click(screen.getByRole("button", { name: "Brave Search test connection" }))
    const dialog = await screen.findByRole("dialog")
    expect(dialog.textContent).toMatch(/unavailable|no quota|[\u2014]/i)
    cleanup()

    renderUsage(dashboardFixture({ latest_quota: [] }))
    await waitForUsage()
    expect(document.body.textContent).toMatch(/unavailable|no quota|[\u2014]/i)
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
    expect(dialog.textContent).toMatch(/authoritative|observed|estimated|unavailable|no quota/i)
  })
})