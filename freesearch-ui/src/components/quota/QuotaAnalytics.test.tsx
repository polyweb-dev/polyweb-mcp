import React from "react"
import { describe, it, expect, afterEach, vi } from "vitest"
import { render, screen, waitFor } from "@testing-library/react"
import { FreeSearchProvider } from "@/context/FreeSearchContext"
import { QuotaAnalytics } from "./QuotaAnalytics"
import { installFetchStub, ok, err } from "@/test/fetchMock"
import {
  allProvidersFixture,
  routingConfigFixture,
  dashboardFixture,
  canonicalQuotasFixture,
  canonicalTotalsFixture,
  type WireDashboard,
} from "@/test/backendFixtures"

/**
 * RED (new file): quota telemetry comes from the dashboard — usage_totals
 * aggregates are shown, an empty latest_quota renders a "quota unavailable"
 * notice, per-provider null limits render "—"/blank (RF2: never ∞), and no
 * invented savings/cache numbers (248/814/342) may appear.
 */
function renderWithBackend(dashboard: WireDashboard) {
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

describe("QuotaAnalytics (live backend)", () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it("shows dashboard usage_totals aggregates without invented numbers", async () => {
    renderWithBackend(dashboardFixture())
    await waitFor(() => {
      expect(screen.getByText("Tavily", { exact: true })).toBeInTheDocument()
    })

    // Real aggregate from the wire fixture
    expect(screen.getByText(/3\.5/)).toBeInTheDocument()
    const body = document.body.textContent ?? ""
    for (const invented of ["248", "814", "342"]) {
      expect(body).not.toContain(invented)
    }
    expect(body).not.toMatch(/\$[\d.]+ saved this cycle/)
  })

  it("renders a quota-unavailable notice when latest_quota is empty", async () => {
    renderWithBackend(dashboardFixture({ latest_quota: [] }))
    await waitFor(() => {
      expect(screen.getByText("Tavily", { exact: true })).toBeInTheDocument()
    })

    expect(screen.getAllByText(/quota unavailable|unavailable/i).length).toBeGreaterThan(0)
  })

  it("RF2: renders per-provider null limits as —/blank, never ∞ or numbers", async () => {
    renderWithBackend(dashboardFixture())
    await waitFor(() => {
      expect(screen.getByText("Tavily", { exact: true })).toBeInTheDocument()
    })

    // RF2: null limits stay blank/— on every surface. ∞ is retired.
    const body = document.body.textContent ?? ""
    expect(body).not.toContain("∞")
    expect(screen.getAllByText(/—/).length).toBeGreaterThan(0)
  })

  it("renders authoritative latest_quota values for Brave", async () => {
    renderWithBackend(
      dashboardFixture({
        latest_quota: [
          {
            provider: "brave",
            source: "authoritative",
            observed_at: "2026-09-06T18:00:00Z",
            remaining: "900",
            limit: "1000",
            reset_at: "2026-10-01T00:00:00Z",
          },
        ],
      })
    )
    await waitFor(() => {
      expect(screen.getByText("Brave Search quota", { exact: true })).toBeInTheDocument()
    })

    const row =
      screen.getByText("Brave Search quota", { exact: true }).parentElement!
    expect(row.textContent).toContain("900")
    expect(row.textContent).toContain("1000")
  })

  it("uses the canonical remaining_percent headline while retaining native details", async () => {
    renderWithBackend(dashboardFixture({ latest_quota: canonicalQuotasFixture() }))
    await waitFor(() => {
      expect(screen.getByText("Tavily quota", { exact: true })).toBeInTheDocument()
    })

    const row = screen.getByText("Tavily quota", { exact: true }).parentElement!
    expect(row.querySelector('[data-testid="quota-remaining-percent-tavily"]')?.textContent).toBe(
      "90% remaining"
    )
    expect(row.textContent).toContain("90000.05/100000.10 credits")
  })

  it("labels quota windows and explains providers without a configured budget", async () => {
    renderWithBackend(dashboardFixture({ latest_quota: [] }))
    await waitFor(() => {
      expect(screen.getByText("Parallel quota", { exact: true })).toBeInTheDocument()
    })

    const parallelRow = screen.getByText("Parallel quota", { exact: true }).parentElement!
    expect(parallelRow.textContent).toMatch(/budget not configured.*monthly/i)
    expect(parallelRow.textContent).toMatch(/no api-key balance endpoint/i)

    const keenableRow = screen.getByText("Keenable quota", { exact: true }).parentElement!
    expect(keenableRow.textContent).toMatch(/hourly quota pending.*rolling hour/i)
  })

  it("renders the persistent usageError banner when the dashboard fails", async () => {
    installFetchStub((req) => {
      if (req.url === "/api/v1/providers" && req.method === "GET") {
        return ok(allProvidersFixture())
      }
      if (req.url === "/api/v1/routing/config" && req.method === "GET") {
        return ok(routingConfigFixture())
      }
      if (req.url.startsWith("/dashboard")) {
        // Distinctive detail: must surface in an error banner, not the
        // generic quota/cache notice.
        return err(503, { detail: "quota store exploded zzz9" })
      }
      return err(404, { detail: "unhandled test route" })
    })
    render(
      <FreeSearchProvider>
        <QuotaAnalytics />
      </FreeSearchProvider>
    )

    await waitFor(
      () => {
        expect(screen.getByText(/quota store exploded zzz9/i)).toBeInTheDocument()
      },
      { timeout: 5000 }
    )
  })

  it("exposes cache telemetry as unavailable instead of invented cache stats", async () => {
    renderWithBackend(dashboardFixture())
    await waitFor(() => {
      expect(screen.getByText("Tavily", { exact: true })).toBeInTheDocument()
    })

    expect(screen.getByText(/cache telemetry unavailable|cache.*unavailable/i)).toBeInTheDocument()
    const body = document.body.textContent ?? ""
    expect(body).not.toContain("248")
  })

  it("RF1: preserves exact limit strings verbatim on the quota view", async () => {
    renderWithBackend(dashboardFixture({ latest_quota: canonicalQuotasFixture() }))
    await waitFor(() => {
      expect(screen.getByText("Tavily quota", { exact: true })).toBeInTheDocument()
    })

    const tavilyRow = screen.getByText("Tavily quota", { exact: true }).parentElement!
    expect(tavilyRow.textContent).toContain("100000.10")
    expect(tavilyRow.textContent).not.toContain("100000.1 ")

    const exaRow = screen.getByText("Exa quota", { exact: true }).parentElement!
    expect(exaRow.textContent).toContain("0.00000001")
    expect(exaRow.textContent).not.toContain("1e-8")
  })

  it("renders AUTHORITATIVE credits with a visible confidence badge", async () => {
    renderWithBackend(dashboardFixture({ latest_quota: canonicalQuotasFixture() }))
    await waitFor(() => {
      expect(screen.getByText("Tavily quota", { exact: true })).toBeInTheDocument()
    })

    const row = screen.getByText("Tavily quota", { exact: true }).parentElement!
    expect(row.textContent).toContain("authoritative")
    expect(row.textContent).toContain("90000.05")
    expect(row.textContent).toContain("100000.10")
    expect(row.textContent).toContain("credits")
  })

  it("renders OBSERVED requests with reset timing and confidence", async () => {
    renderWithBackend(dashboardFixture({ latest_quota: canonicalQuotasFixture() }))
    await waitFor(() => {
      expect(screen.getByText("Brave Search quota", { exact: true })).toBeInTheDocument()
    })

    const row = screen.getByText("Brave Search quota", { exact: true }).parentElement!
    expect(row.textContent).toContain("observed")
    expect(row.textContent).toContain("950")
    expect(row.textContent).toContain("1000")
    expect(row.textContent).toMatch(/reset/i)
  })

  it("renders You.com ESTIMATED USD with limit null as remaining-only plus the no-hard-limit note", async () => {
    renderWithBackend(dashboardFixture({ latest_quota: canonicalQuotasFixture() }))
    await waitFor(() => {
      expect(screen.getByText("You.com quota", { exact: true })).toBeInTheDocument()
    })

    const row = screen.getByText("You.com quota", { exact: true }).parentElement!
    expect(row.textContent).toContain("estimated")
    expect(row.textContent).toContain("4.75")
    // RF2 (null-limit —) is locked by the dedicated RF2 test above; here we
    // lock the You.com remaining-only note semantics.
    expect(row.textContent).toMatch(/no hard limit/i)
    expect(row.textContent).toMatch(/call equivalents are derived, not a vendor limit/i)
  })

  it("renders the null-kind legacy quota row without merging it into a known unit", async () => {
    renderWithBackend(dashboardFixture({ latest_quota: canonicalQuotasFixture() }))
    await waitFor(() => {
      expect(screen.getByText("Exa quota", { exact: true })).toBeInTheDocument()
    })

    const row = screen.getByText("Exa quota", { exact: true }).parentElement!
    expect(row.textContent).toContain("0.00000005")
    expect(row.textContent).toContain("0.00000001")
    expect(row.textContent).toMatch(/legacy|estimated/i)
  })

  it("keeps usage totals triple-keyed with a same-unit comparison caption", async () => {
    renderWithBackend(dashboardFixture({ usage_totals: canonicalTotalsFixture() }))
    await waitFor(() => {
      expect(screen.getAllByText("Tavily", { exact: true }).length).toBeGreaterThanOrEqual(2)
    })

    const body = document.body.textContent ?? ""
    expect(body).toMatch(/only within the same unit|comparable within the same unit/i)
    // Both Tavily dimensions stay visible as separate rows.
    expect(body).toContain("3.5")
    expect(body).toContain("0.007")
    expect(body).toMatch(/legacy.*mixed|mixed.*legacy/i)
  })

  it("shows confidence labels for dashboard snapshots", async () => {
    renderWithBackend(dashboardFixture({ latest_quota: canonicalQuotasFixture() }))
    await waitFor(() => {
      expect(screen.getByText("Tavily quota", { exact: true })).toBeInTheDocument()
    })

    const body = document.body.textContent ?? ""
    expect(body).toContain("authoritative")
    expect(body).toContain("observed")
    expect(body).toContain("estimated")
  })
})
