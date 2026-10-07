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
} from "@/test/fixtures"

/**
 * UI7 shell: QuotaAnalytics is a compatibility shell over QuotaPage.
 * Legacy native rows left the page (UI7-05); one credit bar, CRD totals,
 * and one price footer remain (UI7-02, UI7-06). Exact assertions only.
 */

function braveCreditEntry(): Record<string, unknown> {
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
          rate: null,
          budget: null,
          native_pool_id: "brave:keyed:usd",
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
          rate: null,
          budget: null,
          native_pool_id: null,
          conversion_profile: { ...profile, native_usd_per_unit: null },
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
          reset_at: "2026-10-01T00:00:00Z",
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

function renderShell(dashboard: Record<string, unknown>) {
  installFetchStub((req) => {
    if (req.url === "/api/v1/providers" && req.method === "GET") {
      return ok(allProvidersFixture())
    }
    if (req.url === "/api/v1/routing/config" && req.method === "GET") {
      return ok(routingConfigFixture())
    }
    if (req.url.startsWith("/dashboard")) return ok(dashboard)
    if (req.url.endsWith("/manual-quota") && req.method === "GET") {
      return err(404, { detail: "no manual quota configured" })
    }
    return err(404, { detail: "unhandled test route" })
  })
  return render(
    <FreeSearchProvider>
      <QuotaAnalytics />
    </FreeSearchProvider>
  )
}

describe("QuotaAnalytics shell (UI7)", () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it("renders the new page sections with no legacy grid and no action section (UI7-05, NUDGE-5)", async () => {
    renderShell(dashboardFixture() as unknown as Record<string, unknown>)
    await waitFor(() => {
      expect(screen.getByText("Usage")).toBeInTheDocument()
    })
    expect(screen.getByText("Provider credit units")).toBeInTheDocument()
    expect(screen.getByText("Usage totals")).toBeInTheDocument()
    expect(screen.getByText("How credit units are priced")).toBeInTheDocument()
    // NUDGE-5: the Provider actions section left the page in full.
    expect(screen.queryByText("Provider actions")).toBe(null)
    expect(screen.queryByText("Provider quota view")).toBe(null)
  })

  it("shows one Brave credit bar with 90 percent and exact funds (UI7-02)", async () => {
    renderShell({
      ...(dashboardFixture() as unknown as Record<string, unknown>),
      provider_limits: [braveCreditEntry()],
      crd_usage_totals: [],
    })
    await waitFor(() => {
      expect(
        screen.getByRole("progressbar", { name: "Brave Search credit units remaining" }),
      ).toBeInTheDocument()
    })
    // CARD-3: credit fraction "4500 / 5000 CRD" renders as split spans; no single "4500 CRD" node.
    expect(screen.getByText("4500")).toBeInTheDocument()
    expect(screen.getByText("/ 5000")).toBeInTheDocument()
    expect(screen.getByText("CRD")).toBeInTheDocument()
    expect(screen.queryByText("4500 CRD")).toBe(null)
    expect(screen.queryByText("CRD left")).toBe(null)
    expect(screen.getByText("4500").closest("span")?.parentElement?.textContent?.replace(/\s+/g, "")).toBe("4500/5000CRD")
    expect(screen.queryByText("n/a")).toBe(null)
    expect(document.body.textContent ?? "").not.toContain("∞")
  })

  it("places card actions at the leading edge and the fraction at the trailing edge below the bar (CARD-3)", async () => {
    renderShell({
      ...(dashboardFixture() as unknown as Record<string, unknown>),
      provider_limits: [braveCreditEntry()],
      crd_usage_totals: [],
    })
    await waitFor(() => {
      expect(
        screen.getByRole("progressbar", { name: "Brave Search credit units remaining" }),
      ).toBeInTheDocument()
    })
    const card = screen.getByRole("heading", { name: "Brave Search" }).closest("article") as HTMLElement
    expect(card.querySelector('[data-testid="provider-logo-brave"]')).not.toBeNull()
    expect(screen.getByText("Observed from the vendor API")).toBeInTheDocument()
    const buttons = Array.from(card.querySelectorAll("button")).map((button) => button.textContent)
    expect(buttons.slice(0, 4)).toEqual(["Sync", "Provider Balance", "Budget Limit", "History"])
    const creditRow = screen.getByText("4500").closest("span")?.parentElement?.parentElement
    const children = Array.from(creditRow?.children ?? [])
    expect(children.length).toBe(2)
    expect(children[0]?.textContent).toContain("Sync")
    expect(children[1]?.textContent?.replace(/\s+/g, "")).toContain("4500/5000CRD")
    const bar = screen.getByRole("progressbar", { name: "Brave Search credit units remaining" })
    expect((bar.compareDocumentPosition(creditRow as Node) & Node.DOCUMENT_POSITION_FOLLOWING) !== 0).toBe(true)
  })

  it("keeps an honest empty credit state with no invented rows (UI7-05)", async () => {
    renderShell(dashboardFixture() as unknown as Record<string, unknown>)
    await waitFor(() => {
      expect(screen.getByText("No provider limit data reported by the backend.")).toBeInTheDocument()
    })
    expect(screen.queryByRole("progressbar")).toBe(null)
    expect(document.body.textContent ?? "").not.toContain("∞")
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

  it("exposes no invented cache numbers on the new page (UI7-05)", async () => {
    renderShell(dashboardFixture() as unknown as Record<string, unknown>)
    await waitFor(() => {
      expect(screen.getByText("Usage")).toBeInTheDocument()
    })
    const body = document.body.textContent ?? ""
    for (const invented of ["248", "814", "342"]) {
      expect(body).not.toContain(invented)
    }
    expect(body).not.toMatch(/\$[\d.]+ saved this cycle/)
  })

  it("lists one Brave price row with no fetch row in the footer (UI7-04, UI7-06)", async () => {
    renderShell({
      ...(dashboardFixture() as unknown as Record<string, unknown>),
      provider_limits: [braveCreditEntry()],
      crd_usage_totals: [],
    })
    await waitFor(() => {
      expect(
        screen.getByRole("progressbar", { name: "Brave Search credit units remaining" }),
      ).toBeInTheDocument()
    })
    expect(screen.getByText("0.005 USD")).toBeInTheDocument()
    expect(screen.getByText("5 CRD")).toBeInTheDocument()
  })

  it("keeps dashboard fixture type compatibility", () => {
    const wire: WireDashboard = dashboardFixture()
    expect(wire.latest_quota).toEqual([])
  })
})
