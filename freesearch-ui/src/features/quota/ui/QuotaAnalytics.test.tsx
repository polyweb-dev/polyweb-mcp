import React from "react"
import { describe, it, expect, afterEach, vi } from "vitest"
import { fireEvent, render as renderUi, screen, waitFor, within } from "@testing-library/react"
import { MemoryRouter } from "react-router"
import userEvent from "@testing-library/user-event"
import { FreeSearchProvider } from "@/context/FreeSearchContext"
import { QuotaAnalytics } from "./QuotaAnalytics"
import { installFetchStub, ok, err } from "@/test/fetchMock"
import { ADMIN_ACCOUNT_ID, DEVELOPER_ACCOUNT_ID } from "@/test/authFixtures"
import {
  allProvidersFixture,
  routingConfigFixture,
  dashboardFixture,
} from "@/test/fixtures"

import {
  allProvidersFixture as manualAllProvidersFixture,
  routingConfigFixture as manualRoutingConfigFixture,
  dashboardFixture as manualDashboardFixture,
  type WireDashboardQuota,
} from "@/test/backendFixtures"

function render(ui: React.ReactElement) {
  return renderUi(ui, { wrapper: MemoryRouter })
}

/**
 * UI7 shell: QuotaAnalytics is a compatibility shell over QuotaPage.
 * Legacy native rows left the page (UI7-05); one credit bar, Usd totals,
 * and one price footer remain (UI7-02, UI7-06). Exact assertions only.
 */

function braveCreditEntry(): Record<string, unknown> {
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
      return ok(null)
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

  it.each(["connected", "disconnected", "empty", "api-only"] as const)(
    "shows Parallel refresh only for a %s OAuth key",
    async (status) => {
      const entry = JSON.parse(JSON.stringify(braveCreditEntry()).replaceAll("brave", "parallel")) as {
        auths: { aggregate_pool: null; usd_views: unknown[] }[]
      }
      const auth = entry.auths[0]
      if (auth === undefined) throw new Error("Missing auth fixture")
      auth.aggregate_pool = null
      auth.usd_views = []
      const stub = installFetchStub((req) => {
        if (req.url === "/api/v1/providers") return ok(allProvidersFixture())
        if (req.url === "/api/v1/routing/config") return ok(routingConfigFixture())
        if (req.url.startsWith("/dashboard")) {
          return ok({ ...dashboardFixture(), provider_limits: [entry], spend_totals: [] })
        }
        if (req.url === "/api/v1/providers/parallel/limits/keys") {
          if (status === "empty") return ok([])
          return ok([
            { key_id: "api-key", label: "API key", owner_email: "admin@example.com", auth_mode: "api_key", oauth_connected: null, balance: null },
            ...(status === "api-only" ? [] : [
              { key_id: "other-key", label: "Team key", owner_email: "other@example.com", auth_mode: "oauth", oauth_connected: status === "connected", balance: null },
            ]),
          ])
        }
        return err(404, null)
      })
      render(
        <FreeSearchProvider accountId={ADMIN_ACCOUNT_ID} canReadControls canEditControls>
          <QuotaAnalytics />
        </FreeSearchProvider>,
      )
      await waitFor(() => expect(stub.requests.some((req) => req.url === "/api/v1/providers/parallel/limits/keys")).toBe(true))
      if (status === "connected" || status === "disconnected") {
        expect(await screen.findByText("Team key")).toBeInTheDocument()
      }
      if (status === "connected") {
        expect(await screen.findByRole("button", { name: "Refresh Parallel balances" })).toBeInTheDocument()
        expect(screen.queryByRole("link", { name: "Connect in Keys and pools" })).toBeNull()
      } else {
        expect(screen.queryByRole("button", { name: "Refresh Parallel balances" })).toBeNull()
        if (status === "api-only" || status === "empty") {
          expect(screen.queryByRole("link", { name: "Connect in Keys and pools" })).toBeNull()
          if (status === "empty") expect(await screen.findByText("No keys")).toBeInTheDocument()
        } else {
          expect(await screen.findByRole("link", { name: "Connect in Keys and pools" })).toHaveAttribute("href", "/account/keys")
        }
      }
      expect(stub.requests.some((req) => req.url.includes("/account/vault/keys"))).toBe(false)
    },
  )

  it("renders the new page sections with no legacy grid and no action section (UI7-05, NUDGE-5)", async () => {
    renderShell(dashboardFixture() as unknown as Record<string, unknown>)
    await waitFor(() => {
      expect(screen.getByRole("heading", { name: "Quotas" })).toBeInTheDocument()
    })
    expect(screen.getByText("Allowance left")).toBeInTheDocument()
    expect(screen.getByText("Usage totals")).toBeInTheDocument()
    expect(screen.queryByText("How credit units are priced")).toBeNull()
    // NUDGE-5: the Provider actions section left the page in full.
    expect(screen.queryByText("Provider actions")).toBe(null)
    expect(screen.queryByText("Provider quota view")).toBe(null)
  })

  it("shows one Brave credit bar with 90 percent and exact funds (UI7-02)", async () => {
    renderShell({
      ...(dashboardFixture() as unknown as Record<string, unknown>),
      provider_limits: [braveCreditEntry()],
      spend_totals: [],
    })
    await waitFor(() => {
      expect(
        screen.getByRole("progressbar", { name: "Brave Search balance remaining" }),
      ).toBeInTheDocument()
    })
    // CARD-3: credit fraction "4500 / 5000 Usd" renders as split spans; no single "4500 Usd" node.
    expect(screen.getByText("$4.50")).toBeInTheDocument()
    expect(screen.getByText("/ $5.00")).toBeInTheDocument()
    expect(screen.getByText("USD")).toBeInTheDocument()
    expect(screen.queryByText("4500 Usd")).toBe(null)
    expect(screen.queryByText("Usd left")).toBe(null)
    expect(screen.getByText("$4.50").closest("span")?.parentElement?.textContent?.replace(/\s+/g, "")).toBe("$4.50/$5.00USD")
    expect(screen.queryByText("n/a")).toBe(null)
    expect(document.body.textContent ?? "").not.toContain("∞")
  })

  it("places card actions at the leading edge and the fraction at the trailing edge below the bar (CARD-3)", async () => {
    renderShell({
      ...(dashboardFixture() as unknown as Record<string, unknown>),
      provider_limits: [braveCreditEntry()],
      spend_totals: [],
    })
    await waitFor(() => {
      expect(
        screen.getByRole("progressbar", { name: "Brave Search balance remaining" }),
      ).toBeInTheDocument()
    })
    const card = screen.getByRole("heading", { name: "Brave Search" }).closest("article") as HTMLElement
    expect(card.querySelector('[data-testid="provider-logo-brave"]')).not.toBeNull()
    expect(screen.getByText("Reported by provider")).toBeInTheDocument()
    expect(within(card).getByRole("button", { name: "Actions for Brave Search" })).toBeInTheDocument()
    expect(within(card).queryByRole("button", { name: /Provider Balance/ })).toBeNull()
    const creditRow = screen.getByText("$4.50").closest("span")?.parentElement?.parentElement
    const children = Array.from(creditRow?.children ?? [])
    expect(children.length).toBe(1)
    expect(children[0]?.textContent?.replace(/\s+/g, "")).toContain("$4.50/$5.00USD")
    const bar = screen.getByRole("progressbar", { name: "Brave Search balance remaining" })
    expect((bar.compareDocumentPosition(creditRow as Node) & Node.DOCUMENT_POSITION_FOLLOWING) !== 0).toBe(true)
  })

  it("keeps an honest empty credit state with no invented rows (UI7-05)", async () => {
    renderShell(dashboardFixture() as unknown as Record<string, unknown>)
    await waitFor(() => {
      expect(screen.getByText("No provider usage yet")).toBeInTheDocument()
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
      expect(screen.getByRole("heading", { name: "Quotas" })).toBeInTheDocument()
    })
    const body = document.body.textContent ?? ""
    for (const invented of ["248", "814", "342"]) {
      expect(body).not.toContain(invented)
    }
    expect(body).not.toMatch(/\$[\d.]+ saved this cycle/)
  })

  it("shows recorded Brave spend in USD (UI7-04, UI7-06)", async () => {
    renderShell({
      ...(dashboardFixture() as unknown as Record<string, unknown>),
      provider_limits: [braveCreditEntry()],
      spend_totals: [{ provider: "brave", operation: "search", spend_usd: "0.005", attempt_count: 1, volume_count: 1 }],
    })
    await waitFor(() => {
      expect(
        screen.getByRole("progressbar", { name: "Brave Search balance remaining" }),
      ).toBeInTheDocument()
    })
    const table = await screen.findByRole("table", { name: "Usage totals" })
    const bravePriceRow = within(table).getByRole("row", {
      name: /Brave Search/,
    })
    expect(within(bravePriceRow).getByText("$0.005")).toBeInTheDocument()
  })

})

/**
 * FIX shell: QuotaAnalytics composes the Tavily-only tier slot through the
 * page, the card list, and the card action row with actual provider state,
 * role access, and current refresh callbacks. No card pairs OAuth (U3).
 */

describe("QuotaAnalytics rate-tier slot (FIX)", () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  function tavilyCreditEntry(): Record<string, unknown> {
    const profile = {
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
          usd_views: [
            {
              state: "finite",
              operation: "search",
              remaining_usd: "7.992",
              local_remaining_usd: null,
              request_cost_usd: "0.008",
              shared_pool_id: "tavily:keyed:credits",
              possible_standard_calls: "999",
              price_version: "paygo-reference",
              priced: true,
            },
            {
              state: "finite",
              operation: "fetch",
              remaining_usd: "7.992",
              local_remaining_usd: null,
              request_cost_usd: "0.008",
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
            balance_split_note: null,
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
        return ok(null)
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
      spend_totals: [],
    }
  }

  async function waitForTavilyCard() {
    await waitFor(() => {
      expect(screen.getByRole("heading", { name: "Tavily" })).toBeInTheDocument()
    })
  }

  it("renders the compact tier control for the Tavily card only", async () => {
    const user = userEvent.setup()
    renderTierShell(tierServer(), tierDashboard())
    await waitForTavilyCard()
    const tavilyArticle = screen.getByRole("heading", { name: "Tavily" }).closest("article") as HTMLElement
    const select = within(tavilyArticle).getByRole("combobox", {
      name: "Tavily rate tier (key environment)",
      exact: true,
    })
    expect(select).toHaveTextContent("Development")
    expect(select.textContent).not.toContain("100")
    await user.click(select)
    const options = await screen.findAllByRole("option")
    expect(options.map((o) => o.textContent)).toEqual(["Development", "Production"])
    await user.keyboard("{Escape}")
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
    await user.click(
      within(tavilyArticle).getByRole("combobox", {
        name: "Tavily rate tier (key environment)",
        exact: true,
      }),
    )
    await user.click(await screen.findByRole("option", { name: "Production" }))
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
      ).toHaveTextContent("Production")
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
    await user.click(
      within(tavilyArticle).getByRole("combobox", {
        name: "Tavily rate tier (key environment)",
        exact: true,
      }),
    )
    await user.click(await screen.findByRole("option", { name: "Production" }))
    await user.click(
      within(tavilyArticle).getByRole("button", { name: "Credit details for Tavily" }),
    )
    expect(await screen.findByText("Limit 1,000 requests per minute")).not.toBeNull()
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

  it("mounts no Parallel OAuth pairing and calls no provider OAuth route", async () => {
    const stub = renderTierShell(tierServer(), tierDashboard())
    await waitForTavilyCard()
    expect(screen.queryByRole("button", { name: /^Connect .* balance$/ })).toBeNull()
    expect(screen.queryByTestId("oauth-device-open-parallel")).toBeNull()
    expect(stub.requests.filter((r) => r.url.includes("/oauth"))).toHaveLength(0)
  })
})


describe("QuotaAnalyticsManualQuota.test.tsx", () => {
const allProvidersFixture = manualAllProvidersFixture
const routingConfigFixture = manualRoutingConfigFixture
const dashboardFixture = manualDashboardFixture
/**
 * UI7 manual entry through the shell: card buttons read
 * "Provider Balance", the dialog keeps native-anchor transport, and the
 * card USD path translates balance to usage (see useQuotaForm tests
 * for the 5.00/4.12 to 0.88 contract). Covers UI7-07.
 *
 * NUDGE-5: the Provider actions section left the page, and Brave is no
 * longer manual-eligible (its vendor snapshot reports remaining 999 of
 * limit 1000). Manual assertions anchor on the Exa/Tinyfish cards, and
 * Brave keeps no Provider Balance control.
 */

/** One card-level limit entry with no vendor funds, so the card mounts. */
function limitEntry(provider: string): Record<string, unknown> {
  const profile = {
    native_usd_per_unit: "1",
    cost_basis: "priced_native_use",
    price_version: "v2026-09",
    source: "documented",
    estimated: false,
  }
  return {
    provider,
    active_auth_mode: "keyed",
    auths: [
      {
        auth_mode: "keyed",
        transport_available: true,
        search: {
          provider,
          operation: "search",
          auth_mode: "keyed",
          supported: true,
          transport_available: true,
          rate: null,
          budget: null,
          native_pool_id: null,
          conversion_profile: profile,
          plan_name: null,
          usage_url: null,
          version: 1,
        },
        fetch: {
          provider,
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
        aggregate_pool: null,
        usd_views: [],
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

/**
 * Dashboard rows for the manual suite: Brave carries a vendor snapshot
 * (remaining 999 of limit 1000, so no manual entry), Exa carries a null
 * snapshot (eligible), Parallel carries a null snapshot but stays ineligible
 * (its prepaid USD balance comes from the OAuth Account API, never a manual
 * seed), and Tinyfish has no row (eligible).
 */
function manualQuotaRows(): WireDashboardQuota[] {
  return [
    {
      provider: "brave",
      source: "observed",
      observed_at: "2026-09-06T18:05:00Z",
      remaining: "999",
      limit: "1000",
      reset_at: "2026-10-01T00:00:00Z",
      unit_kind: "REQUEST",
      display_unit: "requests",
    },
    {
      provider: "exa",
      source: "estimated",
      observed_at: "2026-09-06T18:15:00Z",
      remaining: null,
      limit: null,
      reset_at: null,
      unit_kind: null,
      display_unit: null,
    },
    {
      provider: "parallel",
      source: "estimated",
      observed_at: "2026-09-06T18:20:00Z",
      remaining: null,
      limit: null,
      reset_at: null,
      unit_kind: "USD",
      display_unit: "USD",
    },
  ]
}

function renderWithManualStub(latestQuota = manualQuotaRows()) {
  const stub = installFetchStub((req) => {
    if (req.url === "/api/v1/providers" && req.method === "GET") {
      return ok(allProvidersFixture())
    }
    if (req.url === "/api/v1/routing/config" && req.method === "GET") {
      return ok(routingConfigFixture())
    }
    if (req.url.endsWith("/manual-quota") && req.method === "GET") {
      return ok(null)
    }
    if (req.url.endsWith("/manual-quota") && req.method === "PUT") {
      const provider = req.url.split("/providers/")[1]?.split("/manual-quota")[0] ?? "unknown"
      const body = req.body as Record<string, string>
      return ok({ provider, ...body, updated_at: "2026-09-06T12:00:00Z" })
    }
    if (req.url.startsWith("/dashboard")) {
      return ok({
        ...(dashboardFixture({ latest_quota: latestQuota }) as unknown as Record<string, unknown>),
        provider_limits: [
          limitEntry("brave"),
          limitEntry("exa"),
          limitEntry("parallel"),
          limitEntry("tavily"),
          limitEntry("tinyfish"),
        ],
      })
    }
    return err(404, { detail: "unhandled test route" })
  })
  render(
    <FreeSearchProvider accountId={ADMIN_ACCOUNT_ID} canReadControls canEditControls>
      <QuotaAnalytics />
    </FreeSearchProvider>
  )
  return stub
}

type User = ReturnType<typeof userEvent.setup>

/** The labels of one card's `…` menu; the menu closes again afterwards. */
async function menuLabels(user: User, providerName: string): Promise<string[]> {
  await user.click(screen.getByRole("button", { name: "Actions for " + providerName }))
  await screen.findByRole("button", { name: "Set budget" })
  const labels = ["Set balance", "Set budget", "View balance history"].filter(
    (label) => screen.queryByRole("button", { name: label }) !== null,
  )
  await user.keyboard("{Escape}")
  return labels
}

/** Open one dialog through the card `…` menu. */
async function openCardAction(user: User, providerName: string, label: string): Promise<void> {
  await user.click(screen.getByRole("button", { name: "Actions for " + providerName }))
  await user.click(await screen.findByRole("button", { name: label }))
}

async function waitForCard(providerName: string): Promise<void> {
  await waitFor(() => {
    expect(screen.getByRole("button", { name: "Actions for " + providerName })).toBeInTheDocument()
  })
}

describe("QuotaAnalytics manual billing entry (UI7)", () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it("offers Set balance on Exa and Tinyfish, never on Brave, Parallel, or Tavily (UI7-07, NUDGE-5)", async () => {
    const user = userEvent.setup()
    renderWithManualStub()
    await waitForCard("Tinyfish")
    expect(await menuLabels(user, "Tinyfish")).toContain("Set balance")
    expect(await menuLabels(user, "Exa")).toContain("Set balance")
    // Parallel stays out: its prepaid USD balance comes from the OAuth Account
    // API (AUTHORITATIVE snapshot), never from a manual seed.
    expect(await menuLabels(user, "Parallel")).not.toContain("Set balance")
    // NUDGE-5 lock: Brave reports a vendor budget, so its card keeps no entry control.
    const keyBalances = screen.getByRole("table", { name: "Key balances" })
    expect(within(keyBalances).getByRole("row", { name: /Brave Search/ })).toBeInTheDocument()
    expect(await menuLabels(user, "Brave Search")).not.toContain("Set balance")
    expect(await menuLabels(user, "Tavily")).not.toContain("Set balance")
    // NUDGE-5 lock: the Provider actions section left the page.
    expect(screen.queryByText("Provider actions")).toBe(null)
  })

  it("opens the native-anchor dialog for Tinyfish while its budget stays unconfigured (UI7-07)", async () => {
    const user = userEvent.setup()
    const stub = renderWithManualStub()
    await waitForCard("Tinyfish")
    await openCardAction(user, "Tinyfish", "Set balance")
    const dialog = await screen.findByRole("dialog")
    expect(dialog).toHaveTextContent("Tinyfish")
    expect(dialog).not.toHaveTextContent(/error|failed/i)
    expect(stub.requestsTo("/api/v1/providers/tinyfish/manual-quota").map((request) => request.method)).toContain("GET")
  })

  it("loads an empty manual entry without an error", async () => {
    const consoleError = vi.spyOn(console, "error").mockImplementation(() => {})
    try {
      const stub = renderWithManualStub()
      await waitFor(() => {
        expect(stub.requestsTo("/api/v1/providers/tinyfish/manual-quota")).not.toHaveLength(0)
      })
      await waitForCard("Tinyfish")
      expect(screen.queryByTestId("manual-quota-error")).toBeNull()
      expect(consoleError).not.toHaveBeenCalled()
    } finally {
      consoleError.mockRestore()
    }
  })

  it("accepts Exa balance in USD and stores exact USD allowance and usage", async () => {
    const user = userEvent.setup()
    const stub = renderWithManualStub()
    await waitForCard("Exa")

    await openCardAction(user, "Exa", "Set balance")
    expect(screen.getByLabelText<HTMLInputElement>("Allowance (USD)").value).toBe("")
    expect(screen.getByLabelText<HTMLInputElement>("Balance remaining (USD)").value).toBe("")
    fireEvent.change(screen.getByLabelText("Billing start"), {
      target: { value: "2026-10-01" },
    })
    fireEvent.change(screen.getByLabelText("Billing end"), {
      target: { value: "2026-10-31" },
    })
    fireEvent.change(screen.getByTestId("manual-quota-allowance"), {
      target: { value: "5.00" },
    })
    fireEvent.change(screen.getByTestId("manual-quota-usage"), {
      target: { value: "4.12" },
    })
    await user.click(screen.getByTestId("manual-quota-save"))

    await waitFor(() => {
      expect(stub.requestsTo("/api/v1/providers/exa/manual-quota").map((request) => request.method)).toContain("PUT")
    })
    expect(
      stub.requestsTo("/api/v1/providers/exa/manual-quota").find((request) => request.method === "PUT")?.body,
    ).toEqual({
      billing_start: "2026-10-01",
      billing_end: "2026-10-31",
      allowance: "5.00",
      current_usage: "0.88",
    })
  })

  it("saves a Tinyfish balance as usage in the native payload (UI7-07)", async () => {
    const user = userEvent.setup()
    const stub = renderWithManualStub()
    await waitForCard("Tinyfish")

    await openCardAction(user, "Tinyfish", "Set balance")
    fireEvent.change(screen.getByLabelText("Billing start"), {
      target: { value: "2026-09-01" },
    })
    fireEvent.change(screen.getByLabelText("Billing end"), {
      target: { value: "2026-09-30" },
    })
    fireEvent.change(screen.getByTestId("manual-quota-allowance"), {
      target: { value: "5.00" },
    })
    fireEvent.change(screen.getByTestId("manual-quota-usage"), {
      target: { value: "0.88" },
    })
    await user.click(screen.getByTestId("manual-quota-save"))

    await waitFor(() => {
      const puts = stub.requestsTo("/api/v1/providers/tinyfish/manual-quota")
      expect(puts.map((request) => request.method)).toContain("PUT")
    })
    const puts = stub.requestsTo("/api/v1/providers/tinyfish/manual-quota")
    expect(puts.find((request) => request.method === "PUT")?.body).toEqual({
      billing_start: "2026-09-01",
      billing_end: "2026-09-30",
      allowance: "5.00",
      current_usage: "4.12",
    })
  })

  it("locks the sentence-case menu wording and no legacy labels (CARD-3)", async () => {
    const user = userEvent.setup()
    renderWithManualStub()
    await waitForCard("Tinyfish")
    expect(await menuLabels(user, "Tinyfish")).toEqual(["Set balance", "Set budget", "View balance history"])
    expect(screen.queryByText("Provider Balance")).toBe(null)
    expect(screen.queryByText("Balance entry")).toBe(null)
    expect(screen.queryByText("Manual entry")).toBe(null)
  })

  it("shows no legacy overlay row and no action section on the new page (UI7-05, NUDGE-5)", async () => {
    renderWithManualStub()
    const keyBalances = await screen.findByRole("table", { name: "Key balances" })
    expect(within(keyBalances).getByRole("row", { name: /Tinyfish/ })).toBeInTheDocument()
    expect(screen.queryByText("Provider actions")).toBe(null)
    expect(screen.queryByText("Provider quota view")).toBe(null)
    expect(screen.queryByTestId("manual-quota-estimate-brave")).toBe(null)
    expect(screen.queryByTestId("manual-quota-open-brave")).toBe(null)
  })
})

/**
 * Developer role (control read without control edit): the card controls stay
 * visible, but every mutation is rejected with 403. The stub serves reads
 * plus 403 on both PUT paths. Each failed save keeps its alert and its open
 * modal, and nothing persists.
 */
describe("QuotaAnalytics Developer read-only", () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it("shows Balance and Spend controls but rejects Developer saves with 403 and keeps no data", async () => {
    const stub = installFetchStub((req) => {
      if (req.url === "/api/v1/providers" && req.method === "GET") {
        return ok(allProvidersFixture())
      }
      if (req.url === "/api/v1/routing/config" && req.method === "GET") {
        return ok(routingConfigFixture())
      }
      if (req.url.endsWith("/manual-quota") && req.method === "GET") {
        return ok(null)
      }
      if (req.url.endsWith("/manual-quota") && req.method === "PUT") {
        return err(403, { detail: "insufficient role" })
      }
      if (req.url.includes("/budgets/") && req.method === "PUT") {
        return err(403, { detail: "insufficient role" })
      }
      if (req.url.startsWith("/dashboard")) {
        return ok({
          ...(dashboardFixture({ latest_quota: manualQuotaRows() }) as unknown as Record<
            string,
            unknown
          >),
          provider_limits: [
            limitEntry("brave"),
            limitEntry("exa"),
            limitEntry("parallel"),
            limitEntry("tinyfish"),
          ],
        })
      }
      return err(404, { detail: "unhandled test route" })
    })
    render(
      <FreeSearchProvider
        accountId={DEVELOPER_ACCOUNT_ID}
        canReadControls
        canEditControls={false}
      >
        <QuotaAnalytics />
      </FreeSearchProvider>
    )
    const user = userEvent.setup()

    // Controls stay visible for Developer reads.
    await waitForCard("Tinyfish")
    expect(await menuLabels(user, "Tinyfish")).toEqual(["Set balance", "Set budget", "View balance history"])

    // Manual save attempt rejects with 403, keeps the alert and the open modal.
    await openCardAction(user, "Tinyfish", "Set balance")
    await screen.findByRole("dialog")
    fireEvent.change(screen.getByLabelText("Billing start"), {
      target: { value: "2026-09-01" },
    })
    fireEvent.change(screen.getByLabelText("Billing end"), {
      target: { value: "2026-09-30" },
    })
    fireEvent.change(screen.getByTestId("manual-quota-allowance"), {
      target: { value: "5.00" },
    })
    fireEvent.change(screen.getByTestId("manual-quota-usage"), {
      target: { value: "0.88" },
    })
    await user.click(screen.getByTestId("manual-quota-save"))
    const manualAlert = await screen.findByTestId("manual-quota-error")
    expect(manualAlert).toHaveTextContent("insufficient role")
    expect(screen.getByRole("dialog")).toBeInTheDocument()
    expect(
      stub.requestsTo("/api/v1/providers/tinyfish/manual-quota").map((request) => request.method)
    ).toContain("PUT")

    // Close the manual modal before the grant attempt.
    await user.click(screen.getByTestId("manual-quota-cancel"))
    await waitFor(() => {
      expect(screen.queryByRole("dialog")).toBeNull()
    })

    // Grant save attempt rejects with 403, keeps the alert and the open modal.
    await openCardAction(user, "Tinyfish", "Set budget")
    await screen.findByRole("dialog")
    await user.clear(screen.getByLabelText("Search budget (USD)"))
    await user.type(screen.getByLabelText("Search budget (USD)"), "5")
    await user.click(screen.getByRole("button", { name: "Save budget" }))
    const grantAlert = await screen.findByRole("alert")
    expect(grantAlert).toHaveTextContent("insufficient role")
    expect(screen.getByRole("dialog")).toBeInTheDocument()
    expect(
      stub.requestsTo(/\/budgets\//).map((request) => request.method)
    ).toContain("PUT")

    // Nothing persists: no estimate appears and no dashboard refresh follows a rejection.
    expect(screen.queryByTestId("manual-quota-estimate-tinyfish")).toBeNull()
    expect(stub.requestsTo(/\/dashboard/).length).toBe(1)
  })
})

})
