import { describe, expect, it } from "vitest"
import { render, screen, within } from "@testing-library/react"
import type { UsdConversionProfile, TierBalance } from "@/domains/dashboard"
import type { TavilyDisplayAdapter } from "../model/tavilyCredits"
import { ProviderTierBars } from "./ProviderTierBars"

/**
 * S0 generic tier bars: synthetic providers only, no vendor prices, exact
 * one-decimal text, unknown capacity never renders as a zero bar.
 */

function makeTier(overrides: Partial<TierBalance> = {}): TierBalance {
  return {
    pool_id: "pool-synth-1",
    tier: "free",
    native_unit: "REQUEST",
    native_remaining: "10",
    native_allowance: "20",
    remaining_usd: "0.005",
    allowance_usd: "0.01",
    reset_rule: "monthly_first",
    reset_at: null,
    funding_mode: "prepaid",
    source: "synth-source",
    confidence: "authoritative",
    transport_available: true,
    label: null,
    ...overrides,
  }
}

describe("ProviderTierBars", () => {
  it("renders free and paid bars with their independent reset notes", () => {
    render(
      <ProviderTierBars
        providerName="Synth A"
        freeTiers={[makeTier({ pool_id: "pool-synth-free", reset_rule: "monthly_first" })]}
        paidTiers={[
          makeTier({
            pool_id: "pool-synth-paid",
            tier: "paid",
            reset_rule: "vendor_period",
          }),
        ]}
        tierSplitKnown
      />,
    )
    expect(screen.getByText("Free tier")).not.toBeNull()
    expect(screen.getByText("Paid tier")).not.toBeNull()
    expect(screen.getByText("Resets on the first of the month")).not.toBeNull()
    expect(screen.getByText("Resets on the vendor period")).not.toBeNull()
  })

  it("renders no row when the vendor split is unknown (UI7-01)", () => {
    const { container } = render(
      <ProviderTierBars
        providerName="Synth A"
        freeTiers={[]}
        paidTiers={[]}
        tierSplitKnown={false}
      />,
    )
    expect(container.textContent).toBe("")
    expect(screen.queryByText("Tier split unavailable")).toBe(null)
  })

  it("formats a fractional Usd amount to one decimal", () => {
    render(
      <ProviderTierBars
        providerName="Synth A"
        freeTiers={[
          makeTier({ remaining_usd: "0.000599", allowance_usd: "0.001" }),
        ]}
        paidTiers={[]}
        tierSplitKnown
      />,
    )
    expect(screen.getByText("$0.000599 of $0.001")).not.toBeNull()
  })

  it("renders no row for unknown capacity and never an invented zero (UI7-01)", () => {
    const { container } = render(
      <ProviderTierBars
        providerName="Synth A"
        freeTiers={[
          makeTier({
            remaining_usd: null,
            allowance_usd: null,
            funding_mode: "prepaid",
          }),
        ]}
        paidTiers={[]}
        tierSplitKnown
      />,
    )
    expect(container.textContent).toBe("")
    expect(screen.queryByText("Unknown")).toBe(null)
    expect(screen.queryByRole("progressbar")).toBe(null)
  })

  it("renders known tier amounts as detail rows with no funds progressbar (UI7-01, UI7-02)", () => {
    render(
      <ProviderTierBars
        providerName="Synth A"
        freeTiers={[makeTier({ remaining_usd: "0.005", allowance_usd: "0.01" })]}
        paidTiers={[
          makeTier({
            pool_id: "pool-synth-paid",
            tier: "paid",
            remaining_usd: "0.005",
            allowance_usd: "0.01",
            reset_rule: "vendor_period",
          }),
        ]}
        tierSplitKnown
      />,
    )
    expect(screen.getAllByText("$0.005 of $0.01")).toHaveLength(2)
    expect(screen.queryByRole("progressbar")).toBe(null)
  })

  it("omits aria-valuenow by rendering no bar when the percent is unknown", () => {
    render(
      <ProviderTierBars
        providerName="Synth A"
        freeTiers={[
          makeTier({ remaining_usd: "0.005", allowance_usd: null }),
        ]}
        paidTiers={[]}
        tierSplitKnown
      />,
    )
    expect(screen.getByText("$0.005")).not.toBeNull()
    expect(screen.queryByRole("progressbar")).toBe(null)
  })

  it("renders nothing when both tiers are empty and the split is known", () => {
    const { container } = render(
      <ProviderTierBars
        providerName="Synth A"
        freeTiers={[]}
        paidTiers={[]}
        tierSplitKnown
      />,
    )
    expect(container.textContent).toBe("")
  })

  it("keeps each bar scoped to its own tier text", () => {
    render(
      <ProviderTierBars
        providerName="Synth A"
        freeTiers={[makeTier({ remaining_usd: "0.005", allowance_usd: "0.01" })]}
        paidTiers={[]}
        tierSplitKnown
      />,
    )
    const freeHeading = screen.getByText("Free tier")
    const barGroup = freeHeading.closest("div")?.parentElement
    expect(barGroup).not.toBe(null)
    expect(within(barGroup as HTMLElement).getByText("$0.005 of $0.01")).not.toBeNull()
    expect(screen.queryByText("Paid tier")).toBe(null)
  })
})

/**
 * Tavily native tier rows: native fields first, valid conversion fallback,
 * unknown facts stay absent, generic formatting unchanged without the input.
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

function nativeAdapter(profile: UsdConversionProfile | null): TavilyDisplayAdapter {
  return {
    credits: {
      remaining: "999",
      allowance: "1000",
      unit: "Credits",
      state: "finite",
      source: "vendor_api",
      stale: false,
      localCap: null,
      paygo: false,
      resetAt: null,
      rateHeadroom: null,
      retryAfterSeconds: null,
    },
    profile,
  }
}

function tavilyTier(overrides: Partial<TierBalance> = {}): TierBalance {
  return makeTier({
    pool_id: "tavily:keyed:free",
    tier: "free",
    native_unit: "CREDIT",
    native_remaining: "600",
    native_allowance: "1000",
    remaining_usd: "4.8",
    allowance_usd: "8",
    ...overrides,
  })
}

describe("ProviderTierBars nativeDisplay", () => {
  it("shows native integer Tavily Credits first", () => {
    render(
      <ProviderTierBars
        providerName="Tavily"
        freeTiers={[tavilyTier()]}
        paidTiers={[]}
        tierSplitKnown
        nativeDisplay={nativeAdapter(tavilyProfile())}
      />,
    )
    expect(screen.getByText("600 Tavily credits of 1,000 Tavily credits")).not.toBeNull()
    expect(screen.queryByText("4800 Usd")).toBe(null)
  })

  it("uses the singular Tavily Credit word for one unit", () => {
    render(
      <ProviderTierBars
        providerName="Tavily"
        freeTiers={[tavilyTier({ native_remaining: "1", native_allowance: "1" })]}
        paidTiers={[]}
        tierSplitKnown
        nativeDisplay={nativeAdapter(tavilyProfile())}
      />,
    )
    expect(screen.getByText("1 Tavily credit of 1 Tavily credit")).not.toBeNull()
  })

  it("floors fractional native tier amounts to whole units", () => {
    render(
      <ProviderTierBars
        providerName="Tavily"
        freeTiers={[tavilyTier({ native_remaining: "999.9", native_allowance: "1000.9" })]}
        paidTiers={[]}
        tierSplitKnown
        nativeDisplay={nativeAdapter(tavilyProfile())}
      />,
    )
    expect(screen.getByText("999 Tavily credits of 1,000 Tavily credits")).not.toBeNull()
  })

  it("converts Usd-only tier values through a valid profile", () => {
    render(
      <ProviderTierBars
        providerName="Tavily"
        freeTiers={[
          tavilyTier({
            native_unit: "USD",
            native_remaining: null,
            native_allowance: null,
            remaining_usd: "0.008",
            allowance_usd: "0.016",
          }),
        ]}
        paidTiers={[]}
        tierSplitKnown
        nativeDisplay={nativeAdapter(tavilyProfile())}
      />,
    )
    expect(screen.getByText("1 Tavily credit of 2 Tavily credits")).not.toBeNull()
  })

  it("keeps generic Usd formatting without a valid conversion profile", () => {
    render(
      <ProviderTierBars
        providerName="Tavily"
        freeTiers={[
          tavilyTier({
            native_unit: "USD",
            native_remaining: null,
            native_allowance: null,
            remaining_usd: "0.005",
            allowance_usd: "0.01",
          }),
        ]}
        paidTiers={[]}
        tierSplitKnown
        nativeDisplay={nativeAdapter(null)}
      />,
    )
    expect(screen.getByText("$0.005 of $0.01")).not.toBeNull()
    expect(screen.queryByText(/Tavily credit/)).toBe(null)
  })

  it("renders no native row for unknown facts without an invented zero", () => {
    const { container } = render(
      <ProviderTierBars
        providerName="Tavily"
        freeTiers={[
          tavilyTier({
            native_remaining: null,
            native_allowance: null,
            remaining_usd: null,
            allowance_usd: null,
          }),
        ]}
        paidTiers={[]}
        tierSplitKnown
        nativeDisplay={nativeAdapter(tavilyProfile())}
      />,
    )
    expect(container.textContent).toBe("")
  })
})
