import { describe, expect, it } from "vitest"
import { render, screen } from "@testing-library/react"
import type { CreditCardModel } from "../model/crdCardModel"
import type { TavilyCreditsDisplay } from "../model/tavilyCredits"
import { ProviderCreditSummary } from "./ProviderCreditSummary"

/**
 * Tavily native credit summary: Credits fraction and honest state footnotes
 * with unchanged CRD defaults for every other rail.
 */

function crdModel(overrides: Partial<CreditCardModel> = {}): CreditCardModel {
  return {
    state: "finite",
    remainingCRD: "4500",
    allowanceCRD: "5000",
    percentRemaining: 90,
    remainingUSD: "4.500",
    pricedUseUSD: null,
    provenanceNote: null,
    poolIds: ["brave:keyed:usd"],
    ...overrides,
  }
}

function credits(overrides: Partial<TavilyCreditsDisplay> = {}): TavilyCreditsDisplay {
  return {
    remaining: "999",
    allowance: "1000",
    unit: "Credits",
    state: "finite",
    source: "vendor_api",
    stale: false,
    localCap: null,
    paygo: false,
    resetAt: "2026-10-01T00:00:00Z",
    rateHeadroom: "95/100",
    retryAfterSeconds: null,
    ...overrides,
  }
}

describe("ProviderCreditSummary native Credits", () => {
  it("shows the native 999/1000 Credits fraction with a native bar", () => {
    render(<ProviderCreditSummary providerName="Tavily" model={crdModel()} credits={credits()} />)
    expect(screen.getByText("999")).not.toBeNull()
    expect(screen.getByText("/ 1000")).not.toBeNull()
    expect(screen.getByText("Credits")).not.toBeNull()
    const bar = screen.getByRole("progressbar", { name: "Tavily native Credits remaining" })
    expect(bar.getAttribute("aria-valuenow")).toBe("99.9")
    expect(screen.getByText("99.9%")).not.toBeNull()
    expect(screen.queryByText("CRD")).toBeNull()
  })

  it("states keyless access without a Credits quota", () => {
    render(
      <ProviderCreditSummary
        providerName="Tavily"
        model={crdModel()}
        credits={credits({ state: "keyless", remaining: null, allowance: null })}
      />,
    )
    expect(screen.getByText("Keyless access (no Credits quota is reported)")).not.toBeNull()
  })

  it("states transport unavailable without inventing funds", () => {
    render(
      <ProviderCreditSummary
        providerName="Tavily"
        model={crdModel()}
        credits={credits({ state: "unavailable", remaining: null, allowance: null })}
      />,
    )
    expect(screen.getByText("Transport unavailable")).not.toBeNull()
  })

  it("states paygo, stale, and local-cap facts in quiet footnotes", () => {
    render(
      <ProviderCreditSummary
        providerName="Tavily"
        model={crdModel()}
        credits={credits({ state: "paygo", paygo: true, stale: true, localCap: "72" })}
      />,
    )
    expect(screen.getByText(/Free Credits are spent/)).not.toBeNull()
    expect(screen.getByText("The last vendor read is stale.")).not.toBeNull()
    expect(screen.getByText(/Local grant ceiling/)).not.toBeNull()
  })

  it("shows no percentage text without a reported allowance", () => {
    render(
      <ProviderCreditSummary
        providerName="Tavily"
        model={crdModel()}
        credits={credits({ remaining: "999", allowance: null })}
      />,
    )
    expect(screen.getByText("999")).not.toBeNull()
    expect(screen.getByText("No allowance is reported, so this card shows no percentage.")).not.toBeNull()
    expect(screen.queryByRole("progressbar")).toBeNull()
  })
})

describe("ProviderCreditSummary CRD default", () => {
  it("keeps the CRD fraction and USD hover text without native inputs", () => {
    render(<ProviderCreditSummary providerName="Brave" model={crdModel()} />)
    expect(screen.getByText("4500")).not.toBeNull()
    expect(screen.getByText("/ 5000")).not.toBeNull()
    expect(screen.getByText("CRD")).not.toBeNull()
    const value = screen.getByText("4500")
    expect(value.getAttribute("title")).toBe("$4.5 left")
    expect(screen.getByRole("progressbar", { name: "Brave credit units remaining" })).not.toBeNull()
  })
})
