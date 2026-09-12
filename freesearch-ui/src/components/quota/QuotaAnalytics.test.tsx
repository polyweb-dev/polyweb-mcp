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
} from "@/test/fixtures"

/**
 * RED (new file): quota telemetry comes from the dashboard — usage_totals
 * aggregates are shown, an empty latest_quota renders a "quota unavailable"
 * notice, per-provider null limits render "—"/blank (RF2: never 8), and no
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
  it("shows hourly resets as local time with minutes and AM/PM", async () => {
    const resetAt = "2026-09-11T13:05:00Z"
    renderWithBackend(dashboardFixture({ latest_quota: [{
      provider: "keenable", source: "observed", observed_at: "2026-09-11T12:00:00Z",
      remaining: "1000", limit: "1000", remaining_percent: "100",
      unit_kind: "REQUEST", reset_at: resetAt,
    }] }))
    const expected = new Date(resetAt).toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit", hour12: true })
    await waitFor(() => {
      expect(screen.getByText("Keenable quota", { exact: true }).closest("tr"))
        .toHaveTextContent(`Resets ${expected}`)
    })
  })

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

  it("RF2: renders per-provider null limits as —/blank, never 8 or numbers", async () => {
    renderWithBackend(dashboardFixture())
    await waitFor(() => {
      expect(screen.getByText("Tavily", { exact: true })).toBeInTheDocument()
    })

    // RF2: null limits stay blank/— on every surface. 8 is retired.
    const body = document.body.textContent ?? ""
    expect(body).not.toContain("8")
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
      screen.getByText("Brave Search quota", { exact: true }).closest("tr")!
    expect(row.textContent).toContain("900")
    expect(row.textContent).toContain("1000")
  })

  it("uses the canonical remaining_percent headline while retaining native details", async () => {
    renderWithBackend(dashboardFixture({ latest_quota: canonicalQuotasFixture() }))
    await waitFor(() => {
      expect(screen.getByText("Tavily quota", { exact: true })).toBeInTheDocument()
    })

    const row = screen.getByText("Tavily quota", { exact: true }).closest("tr")!
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

    const parallelRow = screen.getByText("Parallel quota", { exact: true }).closest("tr")!
    expect(parallelRow.textContent).toMatch(/budget not configured.*monthly/i)
    expect(parallelRow.textContent).toMatch(/no api-key balance endpoint/i)

    const keenableRow = screen.getByText("Keenable quota", { exact: true }).closest("tr")!
    expect(keenableRow.textContent).toMatch(/hourly quota pending.*Hourly/i)
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

    const tavilyRow = screen.getByText("Tavily quota", { exact: true }).closest("tr")!
    expect(tavilyRow.textContent).toContain("100000.10")
    expect(tavilyRow.textContent).not.toContain("100000.1 ")

    const exaRow = screen.getByText("Exa quota", { exact: true }).closest("tr")!
    expect(exaRow.textContent).toContain("0.00000001")
    expect(exaRow.textContent).not.toContain("1e-8")
  })

  it("renders AUTHORITATIVE credits with a visible confidence badge", async () => {
    renderWithBackend(dashboardFixture({ latest_quota: canonicalQuotasFixture() }))
    await waitFor(() => {
      expect(screen.getByText("Tavily quota", { exact: true })).toBeInTheDocument()
    })

    const row = screen.getByText("Tavily quota", { exact: true }).closest("tr")!
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

    const row = screen.getByText("Brave Search quota", { exact: true }).closest("tr")!
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

    const row = screen.getByText("You.com quota", { exact: true }).closest("tr")!
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

    const row = screen.getByText("Exa quota", { exact: true }).closest("tr")!
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


  it("shows per-provider p95 in the Usage totals grid (shared across operation rows)", async () => {
    renderWithBackend(dashboardFixture({ usage_totals: canonicalTotalsFixture() }))
    await waitFor(() => {
      expect(screen.getAllByText("Tavily", { exact: true }).length).toBeGreaterThanOrEqual(2)
    })

    const section = screen.getByText("Usage totals", { exact: true }).closest("section")!
    const board = section.querySelector("div.overflow-x-auto")!
    const grids = Array.from(board.querySelectorAll(":scope > div"))
    // Header row + one row per triple-keyed total (2 Tavily + Brave + legacy Exa).
    expect(grids.length).toBe(5)
    expect(
      Array.from(grids[0].querySelectorAll("span")).map((s) => s.textContent?.trim() ?? "")
    ).toEqual(["Provider", "Operation", "Unit", "p95", "Total units"])
    // Fixture p95 is 100 + rank*10: Brave 110ms, Tavily 130ms, Exa 140ms.
    const p95Cells = (row: Element) =>
      Array.from(row.querySelectorAll("span"))
        .map((s) => s.textContent?.trim() ?? "")
        .filter((t) => t === "110ms" || t === "130ms" || t === "140ms")
    const bodyRows = grids.slice(1)
    expect(p95Cells(bodyRows[0])).toEqual(["130ms"])
    expect(p95Cells(bodyRows[1])).toEqual(["130ms"])
    expect(p95Cells(bodyRows[2])).toEqual(["110ms"])
    expect(p95Cells(bodyRows[3])).toEqual(["140ms"])
    // Dimension-safe grouping note stays put.
    expect(section.textContent).toMatch(/only within the same unit/i)
  })

  it("renders an em-dash p95 when the provider reports null latency", async () => {
    const providers = allProvidersFixture().map((row) =>
      row.provider_id === "exa" ? { ...row, latency_p95_ms: null } : row
    )
    installFetchStub((req) => {
      if (req.url === "/api/v1/providers" && req.method === "GET") {
        return ok(providers)
      }
      if (req.url === "/api/v1/routing/config" && req.method === "GET") {
        return ok(routingConfigFixture())
      }
      if (req.url.startsWith("/dashboard"))
        return ok(dashboardFixture({ usage_totals: canonicalTotalsFixture() }))
      return err(404, { detail: "unhandled test route" })
    })
    render(
      <FreeSearchProvider>
        <QuotaAnalytics />
      </FreeSearchProvider>
    )
    await waitFor(() => {
      expect(screen.getAllByText("Tavily", { exact: true }).length).toBeGreaterThanOrEqual(2)
    })

    const section = screen.getByText("Usage totals", { exact: true }).closest("section")!
    const board = section.querySelector("div.overflow-x-auto")!
    const bodyRows = Array.from(board.querySelectorAll(":scope > div")).slice(1)
    const exaRow = bodyRows.find((row) => row.textContent?.includes("Exa"))
    expect(exaRow, "legacy Exa totals row must exist").toBeDefined()
    expect(exaRow!.textContent).toContain("\u2014")
    const braveRow = bodyRows.find((row) => row.textContent?.includes("Brave"))
    expect(braveRow!.textContent).toContain("110ms")
  })

  it("flags a Keenable hourly row with a past reset as stale", async () => {
    renderWithBackend(dashboardFixture({ latest_quota: [{
      provider: "keenable", source: "observed", observed_at: "2026-09-11T12:00:00Z",
      remaining: "999", limit: "1000", remaining_percent: "99.9",
      unit_kind: "REQUEST", reset_at: "2000-01-01T00:00:00Z",
    }] }))
    await waitFor(() => {
      expect(screen.getByText("Keenable quota", { exact: true }).closest("tr"))
        .toHaveTextContent("Stale \u2014 refreshes on next use")
    })
  })

  it("does not flag a Keenable hourly row with a future reset", async () => {
    renderWithBackend(dashboardFixture({ latest_quota: [{
      provider: "keenable", source: "observed", observed_at: "2026-09-11T12:00:00Z",
      remaining: "999", limit: "1000", remaining_percent: "99.9",
      unit_kind: "REQUEST", reset_at: "2999-01-01T00:00:00Z",
    }] }))
    await waitFor(() => {
      expect(screen.getByText("Keenable quota", { exact: true })).toBeInTheDocument()
    })
    expect(screen.getByText("Keenable quota", { exact: true }).closest("tr")?.textContent)
      .not.toContain("Stale \u2014 refreshes on next use")
  })
})
