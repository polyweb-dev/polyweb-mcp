import { describe, expect, it } from "vitest"
import { render, screen, within } from "@testing-library/react"
import type { TierBalance } from "@/domains/dashboard"
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
    remaining_crd: "5",
    allowance_crd: "10",
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

  it("shows the unknown split note when the vendor split is unknown", () => {
    render(
      <ProviderTierBars
        providerName="Synth A"
        freeTiers={[]}
        paidTiers={[]}
        tierSplitKnown={false}
      />,
    )
    expect(screen.getAllByText("Tier split unavailable")).toHaveLength(2)
  })

  it("formats a fractional CRD amount to one decimal", () => {
    render(
      <ProviderTierBars
        providerName="Synth A"
        freeTiers={[
          makeTier({ remaining_crd: "0.599", allowance_crd: "1" }),
        ]}
        paidTiers={[]}
        tierSplitKnown
      />,
    )
    expect(screen.getByText("≈0.6 CRD of 1 CRD")).not.toBeNull()
  })

  it("renders unknown capacity as text with no zero bar", () => {
    render(
      <ProviderTierBars
        providerName="Synth A"
        freeTiers={[
          makeTier({
            remaining_crd: null,
            allowance_crd: null,
            funding_mode: "prepaid",
          }),
        ]}
        paidTiers={[]}
        tierSplitKnown
      />,
    )
    expect(screen.getByText("Unknown")).not.toBeNull()
    expect(screen.queryByRole("progressbar")).toBe(null)
  })

  it("labels each progressbar with provider plus tier", () => {
    render(
      <ProviderTierBars
        providerName="Synth A"
        freeTiers={[makeTier({ remaining_crd: "5", allowance_crd: "10" })]}
        paidTiers={[
          makeTier({
            pool_id: "pool-synth-paid",
            tier: "paid",
            remaining_crd: "5",
            allowance_crd: "10",
            reset_rule: "vendor_period",
          }),
        ]}
        tierSplitKnown
      />,
    )
    const freeBar = screen.getByRole("progressbar", {
      name: "Synth A free tier credit units remaining",
    })
    const paidBar = screen.getByRole("progressbar", {
      name: "Synth A paid tier credit units remaining",
    })
    expect(freeBar.getAttribute("aria-valuenow")).toBe("50")
    expect(paidBar.getAttribute("aria-valuenow")).toBe("50")
  })

  it("omits aria-valuenow by rendering no bar when the percent is unknown", () => {
    render(
      <ProviderTierBars
        providerName="Synth A"
        freeTiers={[
          makeTier({ remaining_crd: "5", allowance_crd: null }),
        ]}
        paidTiers={[]}
        tierSplitKnown
      />,
    )
    expect(screen.getByText("5 CRD")).not.toBeNull()
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
        freeTiers={[makeTier({ remaining_crd: "5", allowance_crd: "10" })]}
        paidTiers={[]}
        tierSplitKnown
      />,
    )
    const freeHeading = screen.getByText("Free tier")
    const barGroup = freeHeading.closest("div")?.parentElement
    expect(barGroup).not.toBe(null)
    expect(within(barGroup as HTMLElement).getByText("5 CRD of 10 CRD")).not.toBeNull()
    expect(screen.queryByText("Paid tier")).toBe(null)
  })
})
