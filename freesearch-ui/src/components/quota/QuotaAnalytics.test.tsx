import React from "react"
import { describe, it, expect, afterEach, vi } from "vitest"
import { render, screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { FreeSearchProvider } from "@/context/FreeSearchContext"
import { QuotaAnalytics } from "./QuotaAnalytics"
import { installFetchStub, ok, err } from "@/test/fetchMock"
import { ADMIN_ACCOUNT_ID } from "@/test/authFixtures"
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
    <FreeSearchProvider accountId={ADMIN_ACCOUNT_ID} canReadControls canEditControls>
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
    expect(buttons.slice(0, 4)).toEqual(["Refresh Limits", "Provider Balance", "Budget Limit", "History"])
    const creditRow = screen.getByText("4500").closest("span")?.parentElement?.parentElement
    const children = Array.from(creditRow?.children ?? [])
    expect(children.length).toBe(2)
    expect(children[0]?.textContent).toContain("Refresh Limits")
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
      <FreeSearchProvider accountId={ADMIN_ACCOUNT_ID} canReadControls canEditControls>
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
    const bravePriceRow = within(screen.getByRole("table")).getByRole("row", {
      name: /Brave Search/,
    })
    expect(within(bravePriceRow).getByText("0.005 USD")).toBeInTheDocument()
    expect(within(bravePriceRow).getByText("5 CRD")).toBeInTheDocument()
  })

  it("keeps dashboard fixture type compatibility", () => {
    const wire: WireDashboard = dashboardFixture()
    expect(wire.latest_quota).toEqual([])
  })
})

/**
 * FIX shell: QuotaAnalytics composes the Tavily-only tier slot through the
 * page, the card list, and the card action row with actual provider state,
 * role access, and current refresh callbacks. OAuth composition stays intact.
 */

describe("QuotaAnalytics rate-tier slot (FIX)", () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  function tavilyCreditEntry(): Record<string, unknown> {
    const profile = {
      reference_usd_per_crd: "0.001",
      native_usd_per_unit: "0.008",
      cost_basis: "paygo_reference",
      price_version: "paygo-reference",
      source: "documented",
      estimated: true,
    }
    const record = (operation: string, nativeCost: string) => ({
      provider: "tavily",
      operation,
      auth_mode: "keyed",
      supported: true,
      transport_available: true,
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
      native_pool_id: "tavily:keyed:credits",
      conversion_profile: profile,
      plan_name: "Tavily",
      usage_url: null,
      version: 2,
    })
    return {
      provider: "tavily",
      active_auth_mode: "keyed",
      auths: [
        {
          auth_mode: "keyed",
          transport_available: true,
          search: record("search", "1"),
          fetch: record("fetch", "0.2"),
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
            tier_split_known: true,
            aggregate_pool_id: "tavily:keyed:credits",
          },
        },
      ],
      documented_keyless_operations: ["search", "fetch"],
      version: 2,
      generated_at: "2026-09-06T10:05:00Z",
    }
  }

  function tierServer() {
    return (allProvidersFixture() as unknown as Record<string, unknown>[]).map((row) =>
      row["provider_id"] === "tavily" ? { ...row, tavily_key_environment: "dev" } : { ...row },
    )
  }

  function renderTierShell(
    server: Record<string, unknown>[],
    dashboard: Record<string, unknown>,
    canEdit = true,
  ) {
    const stub = installFetchStub((req) => {
      if (req.url === "/api/v1/providers" && req.method === "GET") {
        return ok(server)
      }
      if (req.url === "/api/v1/routing/config" && req.method === "GET") {
        return ok(routingConfigFixture())
      }
      if (req.url.startsWith("/dashboard")) return ok(dashboard)
      if (req.method === "PATCH" && req.url.startsWith("/api/v1/providers/")) {
        const backendId = req.url.split("/").at(-1) ?? "unknown"
        const entry = server.find((row) => row["provider_id"] === backendId)
        if (entry === undefined) return err(404, { detail: "unknown provider" })
        const patch = ((req.body as Record<string, unknown> | null) ?? {}) as Record<string, unknown>
        const next = { ...entry }
        if (patch["tavily_key_environment"] === "dev" || patch["tavily_key_environment"] === "prod") {
          next["tavily_key_environment"] = patch["tavily_key_environment"]
        }
        server[server.indexOf(entry)] = next
        return ok(next)
      }
      if (req.url.endsWith("/manual-quota") && req.method === "GET") {
        return err(404, { detail: "no manual quota configured" })
      }
      return err(404, { detail: "unhandled test route" })
    })
    render(
      <FreeSearchProvider accountId={ADMIN_ACCOUNT_ID} canReadControls canEditControls={canEdit}>
        <QuotaAnalytics />
      </FreeSearchProvider>,
    )
    return stub
  }

  function tierDashboard(): Record<string, unknown> {
    return {
      ...(dashboardFixture() as unknown as Record<string, unknown>),
      provider_limits: [braveCreditEntry(), tavilyCreditEntry()],
      crd_usage_totals: [],
    }
  }

  async function waitForTavilyCard() {
    await waitFor(() => {
      expect(screen.getByRole("heading", { name: "Tavily" })).toBeInTheDocument()
    })
  }

  it("renders the compact tier control for the Tavily card only", async () => {
    renderTierShell(tierServer(), tierDashboard())
    await waitForTavilyCard()
    const tavilyArticle = screen.getByRole("heading", { name: "Tavily" }).closest("article") as HTMLElement
    const select = within(tavilyArticle).getByRole("combobox", {
      name: "Tavily rate tier (key environment)",
      exact: true,
    })
    expect(select).toHaveValue("dev")
    expect(Array.from(select.querySelectorAll("option")).map((o) => o.textContent)).toEqual([
      "Development",
      "Production",
    ])
    expect(select.textContent).not.toContain("100")
    const braveArticle = screen.getByRole("heading", { name: "Brave Search" }).closest("article") as HTMLElement
    expect(
      within(braveArticle).queryByRole("combobox", {
        name: "Tavily rate tier (key environment)",
        exact: true,
      }),
    ).toBeNull()
    expect(braveArticle.querySelector("select")).toBeNull()
  })

  it("saves the card tier through one PATCH and refreshes providers and dashboard", async () => {
    const user = userEvent.setup()
    const stub = renderTierShell(tierServer(), tierDashboard())
    await waitForTavilyCard()
    const tavilyArticle = screen.getByRole("heading", { name: "Tavily" }).closest("article") as HTMLElement
    await user.selectOptions(
      within(tavilyArticle).getByRole("combobox", {
        name: "Tavily rate tier (key environment)",
        exact: true,
      }),
      "prod",
    )
    await waitFor(() => {
      expect(stub.requestsTo("/api/v1/providers/tavily")).toHaveLength(1)
    })
    expect(stub.requestsTo("/api/v1/providers/tavily")[0].body).toEqual({
      tavily_key_environment: "prod",
    })
    await waitFor(() => {
      expect(
        within(tavilyArticle).getByRole("combobox", {
          name: "Tavily rate tier (key environment)",
          exact: true,
        }),
      ).toHaveValue("prod")
    })
    // Both current refresh callbacks run after the confirmed save.
    await waitFor(() => {
      expect(stub.requestsTo("/api/v1/providers").filter((r) => r.method === "GET").length).toBeGreaterThan(1)
    })
    await waitFor(() => {
      expect(stub.requests.filter((r) => r.url.startsWith("/dashboard")).length).toBeGreaterThan(1)
    })
  })

  it("shows the confirmed ceiling in the card popover before the deferred dashboard confirms it", async () => {
    const user = userEvent.setup()
    renderTierShell(tierServer(), tierDashboard())
    await waitForTavilyCard()
    const tavilyArticle = screen.getByRole("heading", { name: "Tavily" }).closest("article") as HTMLElement
    await user.selectOptions(
      within(tavilyArticle).getByRole("combobox", {
        name: "Tavily rate tier (key environment)",
        exact: true,
      }),
      "prod",
    )
    await user.click(
      within(tavilyArticle).getByRole("button", { name: "Credit details for Tavily" }),
    )
    expect(await screen.findByText("unknown/1000 requests per minute")).not.toBeNull()
  })

  it("shows read-only tier text with zero writes for reader roles", async () => {
    const stub = renderTierShell(tierServer(), tierDashboard(), false)
    await waitForTavilyCard()
    const tavilyArticle = screen.getByRole("heading", { name: "Tavily" }).closest("article") as HTMLElement
    expect(
      within(tavilyArticle).queryByRole("combobox", {
        name: "Tavily rate tier (key environment)",
        exact: true,
      }),
    ).toBeNull()
    expect(within(tavilyArticle).getByText("Development", { exact: true })).toBeInTheDocument()
    expect(
      stub.requests.filter((r) => r.method === "PATCH" || r.method === "PUT" || r.method === "POST"),
    ).toHaveLength(0)
  })

  it("keeps non-parallel cards free of OAuth pairing controls", async () => {
    renderTierShell(tierServer(), tierDashboard())
    await waitForTavilyCard()
    const tavilyArticle = screen.getByRole("heading", { name: "Tavily" }).closest("article") as HTMLElement
    expect(within(tavilyArticle).queryByText(/connect/i)).toBeNull()
    const braveArticle = screen.getByRole("heading", { name: "Brave Search" }).closest("article") as HTMLElement
    expect(within(braveArticle).queryByText(/connect/i)).toBeNull()
  })
})
