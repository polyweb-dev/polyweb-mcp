import { describe, expect, it, vi } from "vitest"
import { render, screen, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { installFetchStub, ok } from "@/test/fetchMock"
import { isManualQuotaEligible } from "../model/quotaEligibility"
import { manualEligibleProviders } from "../model/quotaRowModel"
import { ProviderLimitsCards } from "./ProviderLimitsCards"
import { KeyBalances } from "./KeyBalances"

vi.mock("../model/useManualQuota", () => ({
  useManualQuota: () => ({
    manual: null,
    estimate: null,
    save: () => Promise.resolve({}),
    remove: () => Promise.resolve({}),
  }),
}))

vi.mock("@/test/fetchMock", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/test/fetchMock")>()
  return { ...actual }
})

/**
 * UI7 card list: reported cards only, per-provider totals, no invented
 * cards for unreported providers. Covers UI7-02 and UI7-05.
 */

function braveEntry() {
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
          native_pool_id: "brave:keyed:usd",
          rate: null,
          budget: null,
          conversion_profile: {
            native_usd_per_unit: "1",
            cost_basis: "priced_native_use",
            price_version: "v2026-09",
            source: "documented",
            estimated: false,
          },
          plan_name: "Brave Search",
          usage_url: null,
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
          conversion_profile: {
            native_usd_per_unit: null,
            cost_basis: "priced_native_use",
            price_version: "",
            source: "",
            estimated: false,
          },
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
          reset_at: null,
          observed_at: null,
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

function exaEntry() {
  const rate = (operation: "search" | "fetch", limit: string) => ({
    published: true,
    windows: [
      {
        bucket_id: `exa:keyed:${operation}:requests`,
        limit,
        window: "1s",
        scope: "team",
        unit: "requests",
        remaining: null,
        reset_at: null,
        source: "documented_team",
        confidence: "observed",
      },
    ],
  })
  const operationRecord = (operation: "search" | "fetch", limit: string) => ({
    provider: "exa",
    operation,
    auth_mode: "keyed",
    supported: true,
    transport_available: true,
    native_pool_id: "exa:keyed:usd",
    rate: rate(operation, limit),
    budget: {
      model: "usd",
      free_allowance: "10",
      allowance_unit: "USD",
      allowance_period: "month",
      cost_per_1k: operation === "search" ? "7" : "1",
      standard_native_cost: operation === "search" ? "0.007" : "0.001",
      usd_per_call: operation === "search" ? "0.007" : "0.001",
      on_exhausted: "http_402",
      usage_api: "https://exa.ai/docs/reference/team-management/get-api-key-usage",
      priced: true,
    },
    conversion_profile: {
      native_usd_per_unit: "1",
      cost_basis: "usd_native",
      price_version: "2026-09",
      source: "documented",
      estimated: false,
    },
    plan_name: "Free $10 monthly grant + bonus",
    usage_url: "https://dashboard.exa.ai/",
    version: 1,
  })
  return {
    provider: "exa",
    active_auth_mode: "keyed",
    auths: [
      {
        auth_mode: "keyed",
        transport_available: true,
        search: operationRecord("search", "10"),
        fetch: operationRecord("fetch", "100"),
        free_tiers: [],
        paid_tiers: [],
        unknown_tiers: [],
        tier_split_known: true,
        aggregate_pool: {
          pool_id: "exa:keyed:usd",
          provider: "exa",
          auth_mode: "keyed",
          native_unit: "USD",
          remaining: "4.500",
          allowance: "10.000",
          actual_spend_usd: "5.500",
          source: "local_ledger",
          confidence: "estimated",
          reset_at: "2026-11-01T00:00:00Z",
          observed_at: "2026-10-14T12:00:00Z",
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
            request_cost_usd: "0.007",
            shared_pool_id: "exa:keyed:usd",
            possible_standard_calls: "642.857142857142857",
            price_version: "2026-09",
            priced: true,
          },
          {
            state: "finite",
            operation: "fetch",
            remaining_usd: "4.5",
            local_remaining_usd: null,
            request_cost_usd: "0.001",
            shared_pool_id: "exa:keyed:usd",
            possible_standard_calls: "4500",
            price_version: "2026-09",
            priced: true,
          },
        ],
        rate_progress: [],
        grants: null,
        detail: {
          plan_name: "Free $10 monthly grant + bonus",
          native_unit: "USD",
          native_balance: "4.500",
          native_allowance: "10.000",
          usd_per_call: null,
          actual_spend_usd: null,
          reset_at: "2026-11-01T00:00:00Z",
          reset_rule: "monthly_first",
          usage_url: "https://dashboard.exa.ai/",
          source: "local_ledger",
          confidence: "estimated",
          last_sync_at: null,
          stale: false,
          price_version: "2026-09",
          balance_split_note: null,
          rate_windows: [],
          tier_split_known: true,
          aggregate_pool_id: "exa:keyed:usd",
        },
      },
    ],
    documented_keyless_operations: [],
    version: 1,
    generated_at: "2026-10-14T12:00:00Z",
  }
}

function exaEntryWithoutPoolBalance() {
  const entry = exaEntry()
  const auth = entry.auths[0]
  if (auth === undefined || auth.detail === null) throw new Error("Exa auth fixture is incomplete")
  return {
    ...entry,
    auths: [
      {
        ...auth,
        aggregate_pool: null,
        detail: {
          ...auth.detail,
          native_balance: null,
          native_allowance: null,
          aggregate_pool_id: null,
        },
      },
    ],
  }
}

describe("ProviderLimitsCards", () => {
  it("offers refresh for a connected OAuth provider with no balance yet", () => {
    const entry = braveEntry()
    const auth = entry.auths[0]
    if (auth === undefined) throw new Error("Missing auth fixture")
    auth.aggregate_pool.remaining = null as never
    auth.usd_views = []
    render(
      <ProviderLimitsCards
        providers={[{ id: "brave", name: "Brave" }] as never}
        providerLimits={[entry] as never}
        usdUsageTotals={[]}
        refreshDashboard={() => Promise.resolve()}
        manualEligible={new Set<string>()}
        refreshableProviders={new Set(["brave"])}
      />,
    )
    expect(screen.getByRole("button", { name: "Refresh limits for Brave" })).toBeInTheDocument()
  })

  it("shows an unpriced native balance and its refresh action in the compact list", () => {
    const entry = braveEntry()
    const auth = entry.auths[0]
    if (auth === undefined) throw new Error("Missing auth fixture")
    auth.aggregate_pool.native_unit = "CREDIT"
    auth.aggregate_pool.remaining = "1320"
    auth.aggregate_pool.source = "vendor_api"
    auth.search.conversion_profile.native_usd_per_unit = null as never
    auth.usd_views = []
    render(
      <ProviderLimitsCards
        providers={[{ id: "brave", name: "Brave" }] as never}
        providerLimits={[entry] as never}
        usdUsageTotals={[]}
        refreshDashboard={() => Promise.resolve()}
        manualEligible={new Set<string>()}
      />,
    )
    expect(screen.getByText("1,320 credits left")).toBeInTheDocument()
    expect(screen.queryByText("Provider balance not reported")).toBeNull()
    expect(screen.getByRole("button", { name: /refresh/i })).toBeInTheDocument()
  })

  it("renders the reported Brave card with its own totals only (UI7-02, final-polish 3c)", () => {
    render(
      <ProviderLimitsCards
        providers={[{ id: "brave", name: "Brave" }, { id: "parallel", name: "Parallel" }] as never}
        providerLimits={[braveEntry()] as never}
        usdUsageTotals={[
          { provider: "brave", operation: "search", spend_usd: "0.005", attempt_count: 1, volume_count: 1 },
        ]}
        refreshDashboard={() => Promise.resolve()}
        manualEligible={new Set(["brave"])}
      />,
    )
    expect(screen.queryByText("1 reported")).toBeNull()
    expect(screen.getByText("Allowance left")).not.toBeNull()
    // CARD-3: no "Usd left" label; the fraction "4500 / 5000 Usd" renders as split spans.
    expect(screen.queryByText("Usd left")).toBe(null)
    expect(screen.queryByText("USD left")).toBe(null)
    expect(screen.getByText("$4.5")).not.toBeNull()
    expect(screen.getByText("/ $5")).not.toBeNull()
    expect(screen.getByText("USD")).not.toBeNull()
    expect(screen.queryByText("4500 Usd")).toBe(null)
    const usdValue = screen.getByText("$4.5")
    expect(usdValue.getAttribute("title")).toBe("$4.5 left")
    expect(usdValue.getAttribute("aria-label")).toBe("$4.5 left")
    expect(screen.queryByText("USD use (priced)")).toBe(null)
    expect(screen.queryByText("Parallel")).toBe(null)
  })

  it("holds logo, name, statement, ordered actions, and trailing fraction (CARD-3)", () => {
    render(
      <ProviderLimitsCards
        providers={[{ id: "brave", name: "Brave" }, { id: "parallel", name: "Parallel" }] as never}
        providerLimits={[braveEntry()] as never}
        usdUsageTotals={[
          { provider: "brave", operation: "search", spend_usd: "0.005", attempt_count: 1, volume_count: 1 },
        ]}
        refreshDashboard={() => Promise.resolve()}
        manualEligible={new Set(["brave"])}
      />,
    )
    expect(screen.getByTestId("provider-logo-brave")).not.toBeNull()
    expect(screen.getByRole("heading", { name: "Brave" })).not.toBeNull()
    expect(screen.getByText("Reported by provider")).not.toBeNull()
    expect(screen.getByRole("button", { name: "Actions for Brave" })).not.toBeNull()
    const creditRow = screen.getByText("$4.5").closest("span")?.parentElement?.parentElement
    const children = Array.from(creditRow?.children ?? [])
    expect(children.length).toBe(1)
    expect(children[0]?.textContent?.replace(/\s+/g, "")).toContain("$4.5/$5USD")
    const bar = screen.getByRole("progressbar", { name: "Brave balance remaining" })
    expect((bar.compareDocumentPosition(creditRow as Node) & Node.DOCUMENT_POSITION_FOLLOWING) !== 0).toBe(true)
  })

  it("shows an honest empty state with no invented card (UI7-05)", () => {
    render(
      <ProviderLimitsCards
        providers={[{ id: "brave", name: "Brave" }] as never}
        providerLimits={[]}
        usdUsageTotals={[]}
        refreshDashboard={() => Promise.resolve()}
        manualEligible={new Set<string>()}
      />,
    )
    expect(screen.getByText("No provider usage yet")).not.toBeNull()
    expect(screen.getByText("Add a system key to see usage")).not.toBeNull()
    expect(screen.queryByRole("progressbar")).toBe(null)
  })

  it("renders Exa's USD balance entry and Usd budget limit controls", async () => {
    const user = userEvent.setup()
    const exaProvider = { id: "exa", name: "Exa" }
    const estimatedQuota = {
      provider: "exa",
      remaining: "4.500",
      remainingPercent: "45",
      limit: "10.000",
      observed_at: "2026-10-14T12:00:00Z",
      source: "estimated",
      unitKind: "USD",
      displayUnit: "USD",
      resetAt: "2026-11-01T00:00:00Z",
      window: "monthly",
    }
    const manualEligible = manualEligibleProviders(
      [exaProvider as never],
      [estimatedQuota as never],
      isManualQuotaEligible,
    )
    render(
      <ProviderLimitsCards
        providers={[exaProvider] as never}
        providerLimits={[exaEntry()] as never}
        usdUsageTotals={[]}
        refreshDashboard={() => Promise.resolve()}
        manualEligible={manualEligible}
        dashboardQuotas={[estimatedQuota] as never}
      />,
    )

    expect(screen.getByRole("heading", { name: "Exa" })).not.toBeNull()
    expect(screen.getByTestId("provider-logo-exa")).not.toBeNull()
    expect(screen.queryByRole("button", { name: "Refresh limits for Exa" })).toBeNull()
    await user.click(screen.getByRole("button", { name: "Actions for Exa" }))
    expect(await screen.findByRole("button", { name: "Set balance" })).not.toBeNull()
    expect(screen.getByRole("button", { name: "Budget limit" })).not.toBeNull()
    expect(screen.getByRole("button", { name: "Balance history" })).not.toBeNull()
    await user.keyboard("{Escape}")

    await user.click(screen.getByTestId("credit-info-exa"))
    expect(screen.getByText("Search rate limit")).not.toBeNull()
    expect(screen.getByText("Fetch rate limit")).not.toBeNull()
    expect(screen.getByText("10 requests per second")).not.toBeNull()
    expect(screen.getByText("100 requests per second")).not.toBeNull()
    expect(screen.getByText("Search cost (USD)")).not.toBeNull()
    expect(screen.getByText("Fetch cost (USD)")).not.toBeNull()
    expect(screen.getByText("$0.0070")).not.toBeNull()
    expect(screen.getByText("$0.0010")).not.toBeNull()
    await user.click(screen.getByTestId("credit-info-exa"))

    await user.click(screen.getByRole("button", { name: "Actions for Exa" }))
    await user.click(await screen.findByRole("button", { name: "Set balance" }))
    const allowance = screen.getByLabelText<HTMLInputElement>("Allowance (USD)")
    const remaining = screen.getByLabelText<HTMLInputElement>("Balance remaining (USD)")
    expect(allowance.value).toBe("10.00")
    expect(remaining.value).toBe("4.50")
    expect(allowance.disabled).toBe(false)
    expect(remaining.disabled).toBe(false)
    await user.clear(remaining)
    await user.type(remaining, "4.25")
    expect(remaining.value).toBe("4.25")

    await user.click(screen.getByTestId("manual-quota-cancel"))
    await user.click(screen.getByRole("button", { name: "Actions for Exa" }))
    await user.click(await screen.findByRole("button", { name: "Budget limit" }))
    expect(screen.getByLabelText("Search budget (USD)")).not.toBeNull()
    expect(screen.getByLabelText("Fetch budget (USD)")).not.toBeNull()
  })

  it("uses Exa's declared USD unit without guessing a balance when its pool is empty", async () => {
    const user = userEvent.setup()
    const exaProvider = { id: "exa", name: "Exa" }
    render(
      <ProviderLimitsCards
        providers={[exaProvider] as never}
        providerLimits={[exaEntryWithoutPoolBalance()] as never}
        usdUsageTotals={[]}
        refreshDashboard={() => Promise.resolve()}
        manualEligible={new Set(["exa"])}
      />,
    )

    await user.click(screen.getByRole("button", { name: "Actions for Exa" }))
    await user.click(await screen.findByRole("button", { name: "Set balance" }))
    expect(screen.getByLabelText<HTMLInputElement>("Allowance (USD)").value).toBe("")
    expect(screen.getByLabelText<HTMLInputElement>("Balance remaining (USD)").value).toBe("")
  })
})

/**
 * FIX list: ProviderLimitsCards forwards the Tavily-only renderRateTier slot
 * to the card while credential/auth selection and OAuth composition stay
 * intact.
 */

describe("ProviderLimitsCards rate-tier slot (FIX)", () => {
  function tavilyEntry() {
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
      native_pool_id: "tavily:keyed:credits",
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
          ],
          rate_progress: [],
          grants: null,
          detail: null,
        },
      ],
      documented_keyless_operations: [],
      version: 2,
      generated_at: "2026-09-06T10:05:00Z",
    }
  }

  it("renders the tier slot inside the Tavily card only with OAuth intact", () => {
    const calls: string[] = []
    let confirmedKind = "missing"
    render(
      <ProviderLimitsCards
        providers={[{ id: "tavily", name: "Tavily" }, { id: "brave", name: "Brave" }] as never}
        providerLimits={[tavilyEntry(), braveEntry()] as never}
        usdUsageTotals={[]}
        refreshDashboard={() => Promise.resolve()}
        manualEligible={new Set<string>()}
        renderOAuthActions={({ providerId }) => (
          <button type="button" data-testid={"oauth-" + providerId}>
            Connect
          </button>
        )}
        renderRateTier={(args) => {
          calls.push(args.providerId)
          confirmedKind = typeof args.onConfirmed
          return <span data-testid="tier-slot">Tier</span>
        }}
      />,
    )
    expect([...new Set(calls)]).toEqual(["tavily"])
    expect(confirmedKind).toBe("function")
    const tavilyArticle = screen.getByRole("heading", { name: "Tavily" }).closest("article") as HTMLElement
    expect(tavilyArticle.querySelector('[data-testid="tier-slot"]')).not.toBeNull()
    const braveArticle = screen.getByRole("heading", { name: "Brave" }).closest("article") as HTMLElement
    expect(braveArticle.querySelector('[data-testid="tier-slot"]')).toBeNull()
    expect(screen.getByTestId("oauth-tavily")).not.toBeNull()
    expect(screen.getByTestId("oauth-brave")).not.toBeNull()
  })

  it("uses the Tavily backend mode for history when browser key status disagrees", async () => {
    const stub = installFetchStub(() => ok({ events: [], next_cursor: null }))
    const limits = tavilyEntry()
    const keyed = limits.auths[0]
    const keyless = { ...keyed, auth_mode: "keyless" as const }
    render(
      <ProviderLimitsCards
        providers={[
          {
            id: "tavily",
            name: "Tavily",
            hasKey: true,
            keyVaultStatus: "configured",
            capabilities: ["search", "fetch"],
          },
        ] as never}
        providerLimits={[
          { ...limits, active_auth_mode: "keyless", auths: [keyed, keyless] },
        ] as never}
        usdUsageTotals={[]}
        refreshDashboard={() => Promise.resolve()}
        manualEligible={new Set<string>()}
      />,
    )

    const user = userEvent.setup()
    await user.click(screen.getByRole("button", { name: "Actions for Tavily" }))
    await user.click(await screen.findByRole("button", { name: "Balance history" }))
    expect(await screen.findByRole("dialog", { name: "Balance history for Tavily" })).not.toBeNull()
    expect(stub.requestsTo(/limits\/history/).some(({ url }) => url.includes("auth_mode=keyless"))).toBe(true)
    vi.unstubAllGlobals()
  })
})

/**
 * Display order: providers that report usage become cards, least remaining
 * first; providers that report nothing collapse into one compact list.
 * Display-only: Settings registry priority (dispatch order) is untouched.
 */
describe("ProviderLimitsCards display order", () => {
  function entryFor(providerId: string, remaining: string) {
    const entry = JSON.parse(JSON.stringify(braveEntry()).replaceAll("brave", providerId))
    entry.auths[0].aggregate_pool.remaining = remaining
    return entry
  }

  it("orders reporting cards by least remaining first", () => {
    const providers = [
      { id: "parallel", name: "Parallel" },
      { id: "exa", name: "Exa" },
      { id: "firecrawl", name: "Firecrawl" },
    ]
    const remaining: Record<string, string> = { parallel: "4.500", exa: "1.000", firecrawl: "3.000" }
    render(
      <ProviderLimitsCards
        providers={providers as never}
        providerLimits={providers.map((provider) => entryFor(provider.id, remaining[provider.id] ?? "0")) as never}
        usdUsageTotals={[]}
        refreshDashboard={() => Promise.resolve()}
        manualEligible={new Set<string>()}
      />,
    )

    expect(screen.getAllByRole("article")).toHaveLength(3)
    const visible = screen
      .getAllByRole("heading")
      .map((heading) => heading.textContent)
      .filter((text) => ["Parallel", "Exa", "Firecrawl"].includes(text ?? ""))
    expect(visible).toEqual(["Exa", "Firecrawl", "Parallel"])
  })

  it("collapses a provider that reports nothing into one compact row", () => {
    const empty = JSON.parse(JSON.stringify(braveEntry()))
    empty.auths[0].aggregate_pool = null
    empty.auths[0].usd_views = []
    empty.auths[0].rate_progress = []
    render(
      <ProviderLimitsCards
        providers={[{ id: "brave", name: "Brave" }] as never}
        providerLimits={[empty] as never}
        usdUsageTotals={[]}
        refreshDashboard={() => Promise.resolve()}
        manualEligible={new Set<string>()}
        renderOAuthActions={() => <button type="button">Connect</button>}
      />,
    )
    expect(screen.queryByRole("article")).toBeNull()
    const list = screen.getByRole("table", { name: "Key balances" })
    expect(list.textContent).toContain("Brave")
    expect(list.textContent).not.toContain("Provider balance not reported")
    expect(screen.queryByRole("button", { name: "Refresh limits for Brave" })).toBeNull()
    expect(screen.getByRole("button", { name: "Actions for Brave" })).not.toBeNull()
    expect(screen.getByRole("button", { name: "Connect" })).toBeVisible()
  })

  it("puts bonus balances in the compact list without a denominator or progress bar", () => {
    render(
      <ProviderLimitsCards
        providers={[{ id: "brave", name: "Brave" }] as never}
        providerLimits={[entryFor("brave", "6.000")] as never}
        usdUsageTotals={[]}
        refreshDashboard={() => Promise.resolve()}
        manualEligible={new Set<string>()}
      />,
    )
    expect(screen.queryByRole("article")).toBeNull()
    expect(screen.getByRole("table").textContent).toContain("$6.00 left")
    expect(screen.queryByRole("progressbar")).toBeNull()
    expect(screen.getByTestId("provider-logo-brave")).toBeVisible()
  })
})


describe("Quotas review r4b", () => {
  it("places each key balance on its own row without assigning a provider balance to multiple keys", async () => {
    const key = (id: string, balance: unknown) => ({
      key_id: id, label: id, owner_email: "owner@example.com", auth_mode: "api_key", oauth_connected: null, balance,
    })
    installFetchStub((request) => {
      if (request.url.includes("/limits/keys")) return ok([
        key("First key", { remaining: "4500", native_unit: "CREDIT", observed_at: "2026-01-01T12:00:00Z" }),
        key("Second key", null),
      ])
      return ok([])
    })
    const entry = braveEntry()
    entry.auths[0]!.aggregate_pool.manual_anchor = true
    entry.auths[0]!.usd_views = []
    render(<ProviderLimitsCards providers={[{ id: "brave", name: "Brave" }] as never}
      providerLimits={[entry] as never} usdUsageTotals={[]} refreshDashboard={() => Promise.resolve()}
      manualEligible={new Set(["brave"])} refreshableProviders={new Set(["brave"])}
      renderKeyBalances={(providerId, providerName) => <KeyBalances providerId={providerId} providerName={providerName}
        accountId="account" isAdmin email={null} refreshDashboard={() => Promise.resolve()} />} />)
    const first = (await screen.findByText("First key")).closest("tr") as HTMLElement
    const second = screen.getByText("Second key").closest("tr") as HTMLElement
    expect(within(first).getByText("4,500 credits left")).toBeInTheDocument()
    expect(within(second).getByText("Not refreshed yet")).toBeInTheDocument()
    expect(within(second).queryByText(/\$4\.50/)).toBeNull()
    expect(within(first).getByRole("button", { name: "Refresh Brave balances" })).toBeInTheDocument()
    vi.unstubAllGlobals()
  })
  it("shows a manual provider balance on its sole key", async () => {
    installFetchStub((request) => request.url.includes("/limits/keys")
      ? ok([{ key_id: "you-key", label: "You key", owner_email: "owner@example.com", auth_mode: "api_key",
        oauth_connected: null, balance: null }]) : ok([]))
    const entry = braveEntry()
    entry.provider = "youcom"
    entry.auths[0]!.aggregate_pool.remaining = "100"
    entry.auths[0]!.aggregate_pool.manual_anchor = true
    entry.auths[0]!.usd_views = []
    render(<ProviderLimitsCards providers={[{ id: "youcom", name: "You.com" }] as never}
      providerLimits={[entry] as never} usdUsageTotals={[]} refreshDashboard={() => Promise.resolve()}
      manualEligible={new Set(["youcom"])}
      renderKeyBalances={(providerId, providerName) => <KeyBalances providerId={providerId} providerName={providerName}
        accountId="account" isAdmin email={null} refreshDashboard={() => Promise.resolve()} />} />)
    const row = (await screen.findByText("You key")).closest("tr") as HTMLElement
    expect(within(row).getByText(/\$100\.00 left.*manual/)).toBeInTheDocument()
    vi.unstubAllGlobals()
  })
  it("includes stored keys even when the active rail is keyless", async () => {
    installFetchStub((request) => request.url.includes("/limits/keys") && request.url.includes("tinyfish")
      ? ok([{ key_id: "tiny-key", label: "Tinyfish key", owner_email: "owner@example.com", auth_mode: "api_key",
        oauth_connected: null, balance: null }]) : ok([]))
    const entry = braveEntry()
    entry.provider = "tinyfish"
    entry.active_auth_mode = "keyless"
    entry.auths[0]!.auth_mode = "keyless"
    render(<ProviderLimitsCards providers={[{ id: "tinyfish", name: "Tinyfish" }] as never}
      providerLimits={[entry] as never} usdUsageTotals={[]} refreshDashboard={() => Promise.resolve()}
      manualEligible={new Set()}
      renderKeyBalances={(providerId, providerName) => <KeyBalances providerId={providerId} providerName={providerName}
        accountId="account" isAdmin email={null} refreshDashboard={() => Promise.resolve()} />} />)
    const row = (await screen.findByText("Tinyfish key")).closest("tr") as HTMLElement
    expect(within(row).getAllByText("—")).toHaveLength(2)
    vi.unstubAllGlobals()
  })
  it("uses catalog prices in the popover and hides budgets for free providers", async () => {
    const entry = { ...braveEntry(), provider: "keenable" }
    render(<ProviderLimitsCards providers={[{ id: "keenable", name: "Keenable", callCostUsd: { search: "0", fetch: "0" } }] as never}
      providerLimits={[entry] as never} usdUsageTotals={[]} refreshDashboard={() => Promise.resolve()} manualEligible={new Set(["keenable"])} />)
    await userEvent.click(screen.getByRole("button", { name: "Credit details for Keenable" }))
    expect(screen.getByText("Search cost")).toBeInTheDocument()
    expect(screen.getAllByText("Free").length).toBeGreaterThan(0)
    expect(screen.queryByText("$0.005")).toBeNull()
    await userEvent.keyboard("{Escape}")
    expect(screen.queryByRole("button", { name: "Actions for Keenable" })).toBeNull()
    expect(screen.queryByRole("menuitem", { name: "Budget limit" })).toBeNull()
    expect(screen.getByText("Free")).toBeInTheDocument()
  })
  it("puts unreported providers in a single table with three columns", () => {
    const empty = { ...braveEntry(), auths: braveEntry().auths.map((auth) => ({ ...auth, aggregate_pool: null, usd_views: [], rate_progress: [] })) }
    render(<ProviderLimitsCards providers={[{ id: "brave", name: "Brave Search" }] as never} providerLimits={[empty] as never}
      usdUsageTotals={[]} refreshDashboard={() => Promise.resolve()} manualEligible={new Set()} />)
    const table = screen.getByRole("table", { name: "Key balances" })
    expect(Array.from(table.querySelectorAll("th")).map((cell) => cell.textContent)).toEqual(["Provider", "Key", "Balance", "Last refresh", "Provider controls"])
    expect(screen.queryByText("Not reported")).toBeNull()
  })
})

it("keeps disconnected OAuth controls on their key row and fixes the balance dialog provider", async () => {
  installFetchStub((request) => request.url.includes("/limits/keys") ? ok([
    { key_id: "api", label: "dev-parallel", owner_email: "owner@example.com", auth_mode: "api_key", oauth_connected: null, balance: null },
    { key_id: "oauth", label: "Capture OAuth", owner_email: "owner@example.com", auth_mode: "oauth", oauth_connected: false, balance: null },
  ]) : ok([]))
  const entry = { ...braveEntry(), provider: "parallel" }
  render(<ProviderLimitsCards providers={[{ id: "parallel", name: "Parallel" }] as never}
    providerLimits={[entry] as never} usdUsageTotals={[]} refreshDashboard={() => Promise.resolve()}
    manualEligible={new Set(["parallel"])}
    renderOAuthActions={() => <a href="/account/keys">Connect in Keys and pools</a>}
    renderKeyBalances={(providerId, providerName) => <KeyBalances providerId={providerId} providerName={providerName}
      accountId="account" isAdmin email={null} refreshDashboard={() => Promise.resolve()} />} />)
  const first = (await screen.findByText("dev-parallel")).closest("tr") as HTMLElement
  const oauth = screen.getByText("Capture OAuth").closest("tr") as HTMLElement
  expect(within(first).queryByText("Disconnected")).toBeNull()
  expect(within(first).queryByRole("link")).toBeNull()
  expect(within(oauth).getByText("Disconnected")).toBeInTheDocument()
  expect(within(oauth).getByRole("link", { name: "Connect in Keys and pools" })).toHaveAttribute("href", "/account/keys")
  expect(within(oauth).queryByRole("button", { name: "Actions for Parallel" })).toBeNull()
  await userEvent.click(within(first).getByRole("button", { name: "Actions for Parallel" }))
  await userEvent.click(await screen.findByRole("button", { name: "Set balance" }))
  const dialog = await screen.findByRole("dialog", { name: "Balance for Parallel" })
  expect(within(dialog).queryByRole("combobox", { name: "Provider" })).toBeNull()
  expect(within(dialog).getAllByText("$")).toHaveLength(2)
  expect(within(dialog).getAllByText("Enter a date, for example Nov 1, 2026")).toHaveLength(1)
  expect(within(dialog).getByRole("button", { name: "Save balance" })).toBeEnabled()
  vi.unstubAllGlobals()
})
