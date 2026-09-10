import React from "react"
import { describe, it, expect, afterEach, vi } from "vitest"
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { FreeSearchProvider } from "@/context/FreeSearchContext"
import { ProviderRanks } from "@/components/routing/ProviderRanks"
import { RouteSimulator } from "@/components/routing/RouteSimulator"
import { SettingsView } from "@/components/settings/SettingsView"
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
 *   Settings registry table AND test modal.
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

  it("settings registry shows — for null limits, never ∞", async () => {
    renderSettings(dashboardFixture())
    await waitForSettings()

    const table = screen.getByRole("table")
    expect(table.textContent).not.toContain("∞")
    expect(table.textContent).toContain("—")
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

describe("RF4: visible unavailable/confidence semantics in Settings", () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it("registry quota cells show confidence/unavailable visibly, not title-only", async () => {
    renderSettings(dashboardFixture({ latest_quota: canonicalQuotasFixture() }))
    await waitForSettings()

    const table = screen.getByRole("table")
    const headers = Array.from(table.querySelectorAll("thead th")).map(
      (th) => th.textContent?.trim() ?? ""
    )
    const quotaIdx = headers.indexOf("Quota")
    expect(quotaIdx).toBeGreaterThanOrEqual(0)
    const rows = Array.from(table.querySelectorAll("tbody tr"))
    expect(rows.length).toBe(7)
    // Visible text (not title attributes) must carry confidence semantics.
    const visibleQuotaText = rows
      .map((row) => row.children[quotaIdx]?.textContent ?? "")
      .join(" | ")
    expect(visibleQuotaText).toMatch(/authoritative|observed|estimated|unavailable|no quota|—/i)
    // And the confidence must not hide in title-only attributes.
    const quotaCells = rows.map((row) => row.children[quotaIdx] as HTMLElement)
    const anyVisibleConfidence = quotaCells.some((cell) =>
      /authoritative|observed|estimated|unavailable/i.test(cell.textContent ?? "")
    )
    expect(anyVisibleConfidence).toBe(true)
  })

  it("registry leads with normalized remaining capacity and its period", async () => {
    renderSettings(dashboardFixture({ latest_quota: canonicalQuotasFixture() }))
    await waitForSettings()

    expect(screen.getByTestId("settings-quota-headline-brave")).toHaveTextContent("95% remaining")
    const braveRow = screen.getByText("Brave Search", { exact: true }).closest("tr")!
    expect(braveRow.textContent).toMatch(/95% remaining.*monthly.*950\/1000 requests/i)

    const keenableRow = screen.getByText("Keenable", { exact: true }).closest("tr")!
    expect(keenableRow.textContent).toMatch(/hourly quota pending.*rolling hour/i)
  })

  it("registry shows a visible unavailable marker when the dashboard has no snapshots", async () => {
    renderSettings(dashboardFixture({ latest_quota: [] }))
    await waitForSettings()

    const table = screen.getByRole("table")
    expect(table.textContent).toMatch(/unavailable|no quota|—/i)
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
