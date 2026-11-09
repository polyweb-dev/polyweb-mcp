import { describe, expect, it } from "vitest"
import { render, screen, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import type {
  UsdConversionProfile,
  ProviderAuthLimits,
  ProviderLimitDetail,
  TierBalance,
} from "@/domains/dashboard"
import { providerInfo } from "../model/providerInfo"
import { displayAdapterOf } from "../model/tavilyCredits"
import { ProviderInfoPopover } from "./ProviderInfoPopover"

describe("ProviderInfoPopover table trigger", () => {
  it("opens details from the separate info button", async () => {
    const auth = tavilyAuth()
    render(<ProviderInfoPopover providerId="tavily" providerName="Tavily"
      auth={auth} info={providerInfo(auth, "tavily")} />)
    const trigger = screen.getByRole("button", { name: "Credit details for Tavily" })
    await userEvent.click(trigger)
    expect(screen.getByText("Quota details")).toBeInTheDocument()
  })
})

/**
 * Tavily info popover: complete fact order, nested native precision and tier
 * vocab, Usd/USD disclosure only while open, keyboard behavior, narrow view.
 */

function tavilyProfile(): UsdConversionProfile {
  return {
    native_usd_per_unit: "0.008",
    cost_basis: "paygo_reference",
    price_version: "paygo-reference",
    source: "documented",
    estimated: true,
  }
}

function tier(overrides: Partial<TierBalance> = {}): TierBalance {
  return {
    pool_id: "tavily:keyed:free",
    tier: "free",
    native_unit: "CREDIT",
    native_remaining: "600",
    native_allowance: "1000",
    remaining_usd: "4.8",
    allowance_usd: "8",
    reset_rule: "monthly_first",
    reset_at: "2026-10-01T00:00:00Z",
    funding_mode: "prepaid",
    source: "vendor_api",
    confidence: "observed",
    transport_available: true,
    label: null,
    ...overrides,
  }
}

function detail(overrides: Partial<ProviderLimitDetail> = {}): ProviderLimitDetail {
  return {
    plan_name: null,
    native_unit: "CREDIT",
    native_balance: null,
    native_allowance: null,
    usd_per_call: null,
    actual_spend_usd: "0.050000000",
    reset_at: "2026-10-01T00:00:00Z",
    reset_rule: "monthly_first",
    usage_url: "https://app.tavily.com/usage",
    source: "vendor_api",
    confidence: "observed",
    last_sync_at: "2026-09-06T10:05:00Z",
    stale: false,
    price_version: "v2",
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
    retry_after_seconds: 12,
    ...overrides,
  } as ProviderLimitDetail
}

function tavilyAuth(): ProviderAuthLimits {
  const record = (operation: "search" | "fetch", cost: string) => ({
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
      standard_native_cost: cost,
      usd_per_call: null,
      on_exhausted: "402",
      usage_api: "/usage",
      priced: true,
    },
    conversion_profile: tavilyProfile(),
    plan_name: "Tavily",
    usage_url: null,
    version: 2,
  })
  return {
    auth_mode: "keyed",
    transport_available: true,
    search: record("search", "1") as never,
    fetch: record("fetch", "0.2") as never,
    free_tiers: [tier()],
    paid_tiers: [],
    unknown_tiers: [],
    tier_split_known: true,
    aggregate_pool: null,
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
        request_cost_usd: "0.001600000",
        shared_pool_id: "tavily:keyed:credits",
        possible_standard_calls: "999",
        price_version: "paygo-reference",
        priced: true,
      },
    ] as never,
    rate_progress: [],
    grants: {
      provider: "tavily",
      auth_mode: "keyed",
      period: "month" as const,
      version: 3,
      search_granted_usd: "0.008",
      search_consumed_usd: "0",
      search_reserved_usd: "0",
      fetch_granted_usd: "0.016",
      fetch_consumed_usd: "0",
      fetch_reserved_usd: "0",
    } as never,
    detail: detail(),
  }
}

function renderPopover() {
  const auth = tavilyAuth()
  const info = providerInfo(auth, "tavily")
  const nativeDisplay = displayAdapterOf("tavily", auth)
  render(
    <ProviderInfoPopover
      providerId="tavily"
      providerName="Tavily"
      info={info}
      auth={auth}
      {...(nativeDisplay === null ? {} : { nativeDisplay })}
    />,
  )
  return { auth, info }
}

describe("ProviderInfoPopover order", () => {
  it("shows native costs, counts, Usd costs, and rate before Retry-After and nested rows", async () => {
    renderPopover()
    const user = userEvent.setup()
    await user.click(screen.getByRole("button", { name: "Credit details for Tavily" }))
    expect(await screen.findByText("Quota details")).not.toBeNull()
    const labels = ["Search cost", "Fetch cost", "Searches left", "Fetches left",
      "Search cost (USD)", "Fetch cost (USD)", "Search and fetch rate limit", "Retry after"]
    const elements = labels.map((label) => screen.getByText(label))
    for (let index = 1; index < elements.length; index += 1) {
      const position = elements[index - 1].compareDocumentPosition(elements[index])
      expect(position & Node.DOCUMENT_POSITION_FOLLOWING).not.toBe(0)
    }
    expect(screen.getByText("Free")).not.toBeNull()
    expect(screen.getByText("Search budget limit")).not.toBeNull()
    expect(screen.getByText("Fetch budget limit")).not.toBeNull()
    expect(screen.getByRole("link", { name: "Tavily usage page" })).not.toBeNull()
  })

  it("names Monthly Tavily Credits in the header", async () => {
    renderPopover()
    const user = userEvent.setup()
    await user.click(screen.getByRole("button", { name: "Credit details for Tavily" }))
    expect(await screen.findByText("Monthly Tavily credits")).not.toBeNull()
  })
})

describe("ProviderInfoPopover precision", () => {
  it("floors native amounts and keeps Usd/USD fractions inside the disclosure", async () => {
    renderPopover()
    const user = userEvent.setup()
    await user.click(screen.getByRole("button", { name: "Credit details for Tavily" }))
    expect(await screen.findByText("1 Tavily credit per 5 URLs")).not.toBeNull()
    expect(screen.getByText("$0.0016")).not.toBeNull()
    expect(screen.getByText("$0.0080")).not.toBeNull()
  })

  it("shows native integer tier vocab with trimmed USD spend", async () => {
    renderPopover()
    const user = userEvent.setup()
    await user.click(screen.getByRole("button", { name: "Credit details for Tavily" }))
    expect(await screen.findByText("600 Tavily credits of 1,000 Tavily credits")).not.toBeNull()
    expect(screen.getByText("$0.00 of $0.008 this month")).not.toBeNull()
    expect(screen.getByText("0.05")).not.toBeNull()
  })
})

describe("ProviderInfoPopover disclosure", () => {
  it("keeps USD and detail text absent while closed and shows them when open", async () => {
    renderPopover()
    expect(screen.queryByText("Quota details")).toBe(null)
    expect(screen.queryByText("$0.0080")).toBe(null)
    expect(screen.queryByText("600 Tavily credits of 1,000 Tavily credits")).toBe(null)
    const user = userEvent.setup()
    await user.click(screen.getByRole("button", { name: "Credit details for Tavily" }))
    expect(await screen.findByText("Quota details")).not.toBeNull()
    expect(screen.getByText("$0.0080")).not.toBeNull()
    expect(screen.getByText("600 Tavily credits of 1,000 Tavily credits")).not.toBeNull()
  })

  it("renders no popover element while closed", () => {
    renderPopover()
    expect(screen.queryByText("Quota details")).toBe(null)
    expect(screen.queryByText("Search cost")).toBe(null)
  })
})

describe("ProviderInfoPopover keyboard", () => {
  it("opens with keyboard activation", async () => {
    renderPopover()
    const user = userEvent.setup()
    const trigger = screen.getByRole("button", { name: "Credit details for Tavily" })
    trigger.focus()
    await user.keyboard("{Enter}")
    expect(await screen.findByText("Quota details")).not.toBeNull()
  })

  it("closes with Escape and returns focus to the trigger", async () => {
    renderPopover()
    const user = userEvent.setup()
    const trigger = screen.getByRole("button", { name: "Credit details for Tavily" })
    await user.click(trigger)
    expect(await screen.findByText("Quota details")).not.toBeNull()
    await user.keyboard("{Escape}")
    expect(screen.queryByText("Quota details")).toBe(null)
    expect(document.activeElement).toBe(trigger)
  })
})

describe("ProviderInfoPopover viewport", () => {
  it("keeps Credits values visible at a narrow viewport", async () => {
    const previousWidth = window.innerWidth
    Object.defineProperty(window, "innerWidth", { value: 360, configurable: true })
    window.dispatchEvent(new Event("resize"))
    try {
      renderPopover()
      const user = userEvent.setup()
      await user.click(screen.getByRole("button", { name: "Credit details for Tavily" }))
      expect(await screen.findByText("Quota details")).not.toBeNull()
      const dialog = screen.getByText("Quota details").closest("div")?.parentElement
      expect(dialog).not.toBe(null)
      expect(within(dialog as HTMLElement).getByText("1 Tavily credit per 5 URLs")).not.toBeNull()
      expect(within(dialog as HTMLElement).getByText("600 Tavily credits of 1,000 Tavily credits")).not.toBeNull()
    } finally {
      Object.defineProperty(window, "innerWidth", { value: previousWidth, configurable: true })
      window.dispatchEvent(new Event("resize"))
    }
  })
})
