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
  type WireDashboard,
} from "@/test/backendFixtures"

/**
 * RED (new file): quota telemetry comes from the dashboard — usage_totals
 * aggregates are shown, an empty latest_quota renders a "quota unavailable"
 * notice, per-provider null limits render "∞"/unavailable, and no invented
 * savings/cache numbers (248/814/342) may appear.
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

    expect(screen.getByText(/quota unavailable|unavailable/i)).toBeInTheDocument()
  })

  it("renders per-provider null limits as ∞/unavailable, never as numbers", async () => {
    renderWithBackend(dashboardFixture())
    await waitFor(() => {
      expect(screen.getByText("Tavily", { exact: true })).toBeInTheDocument()
    })

    // ProviderQuota.limit is null from the backend → ∞ marker, no fake cap
    expect(screen.getAllByText(/∞/).length).toBeGreaterThan(0)
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
})
