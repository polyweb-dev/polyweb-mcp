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
    expect(screen.getByText("/ 1,000")).not.toBeNull()
    expect(screen.getByText("Balance left")).not.toBeNull()
    const bar = screen.getByRole("progressbar", { name: "Tavily native Credits remaining" })
    expect(bar.getAttribute("aria-valuenow")).toBe("99.9")
    expect(screen.getByText("99.9%")).not.toBeNull()
    expect(screen.queryByText("CRD")).toBeNull()
  })

  it("shows the one quiet empty line for keyless access without a Credits quota", () => {
    const { container } = render(
      <ProviderCreditSummary
        providerName="Tavily"
        model={crdModel()}
        credits={credits({ state: "keyless", remaining: null, allowance: null })}
        emptyText="This provider does not report usage"
      />,
    )
    expect(screen.getByText("This provider does not report usage")).not.toBeNull()
    expect(container.textContent).not.toContain("no Credits quota")
    expect(screen.queryByRole("progressbar")).toBeNull()
  })

  it("states an unavailable provider in plain words without inventing funds", () => {
    render(
      <ProviderCreditSummary
        providerName="Tavily"
        model={crdModel()}
        credits={credits({ state: "unavailable", remaining: null, allowance: null })}
      />,
    )
    expect(screen.getByText("Provider unavailable right now")).not.toBeNull()
    expect(screen.queryByText("Transport unavailable")).toBeNull()
  })

  it("states paygo, stale, and local-cap facts in quiet footnotes", () => {
    render(
      <ProviderCreditSummary
        providerName="Tavily"
        model={crdModel()}
        credits={credits({ state: "paygo", paygo: true, stale: true, localCap: "72" })}
      />,
    )
    expect(screen.getByText(/Free credits are used up/)).not.toBeNull()
    expect(screen.getByText("The last provider reading is out of date")).not.toBeNull()
    expect(screen.getByText(/Budget limit/)).not.toBeNull()
  })

  it("shows the amount without a bar or an apology without a reported allowance", () => {
    const { container } = render(
      <ProviderCreditSummary
        providerName="Tavily"
        model={crdModel()}
        credits={credits({ remaining: "999", allowance: null })}
      />,
    )
    expect(screen.getByText("999")).not.toBeNull()
    expect(container.textContent).not.toContain("No allowance is reported")
    expect(screen.queryByRole("progressbar")).toBeNull()
  })
})

describe("ProviderCreditSummary CRD default", () => {
  it("keeps the CRD fraction and USD hover text without native inputs", () => {
    render(<ProviderCreditSummary providerName="Brave" model={crdModel()} />)
    expect(screen.getByText("$4.5")).not.toBeNull()
    expect(screen.getByText("/ $5")).not.toBeNull()
    expect(screen.getByText("USD")).not.toBeNull()
    const value = screen.getByText("$4.5")
    expect(value.getAttribute("title")).toBe("$4.5 left")
    expect(screen.getByRole("progressbar", { name: "Brave balance remaining" })).not.toBeNull()
  })
})

describe("ProviderCreditSummary native bar contract (FIX)", () => {
  it("renders the Credits title with one shared bar and inline percent", () => {
    const { container } = render(
      <ProviderCreditSummary providerName="Tavily" model={crdModel()} credits={credits()} />,
    )
    expect(screen.getByText("Balance left")).not.toBeNull()
    const bars = screen.getAllByRole("progressbar", { name: "Tavily native Credits remaining" })
    expect(bars).toHaveLength(1)
    expect(screen.getByText("99.9%")).not.toBeNull()
    // The percent shares the track row through the shared showPercent path.
    expect(bars[0].closest("div.flex")?.textContent).toContain("99.9%")
    expect(bars[0].getAttribute("aria-valuetext")).toBe("999 of 1,000 Tavily credits left")
    expect(container.textContent).not.toContain("CRD")
  })

  it("renders bodyNotes reset content above the action row", () => {
    render(
      <ProviderCreditSummary
        providerName="Tavily"
        model={crdModel()}
        credits={credits()}
        bodyNotes={<span data-testid="reset-note">Resets Oct 1</span>}
        actions={<button type="button">Card action</button>}
      />,
    )
    const note = screen.getByTestId("reset-note")
    expect(note.textContent).toBe("Resets Oct 1")
    const action = screen.getByRole("button", { name: "Card action" })
    expect((note.compareDocumentPosition(action) & Node.DOCUMENT_POSITION_FOLLOWING) !== 0).toBe(true)
  })

  it("renders the rateBars slot above the action row", () => {
    render(
      <ProviderCreditSummary
        providerName="Tavily"
        model={crdModel()}
        credits={credits()}
        rateBars={<span data-testid="rate-slot">rate content</span>}
        actions={<button type="button">Card action</button>}
      />,
    )
    const slot = screen.getByTestId("rate-slot")
    expect(slot.textContent).toBe("rate content")
    const action = screen.getByRole("button", { name: "Card action" })
    expect((slot.compareDocumentPosition(action) & Node.DOCUMENT_POSITION_FOLLOWING) !== 0).toBe(true)
  })

  it("shows known zero as an empty bar with zero percent", () => {
    render(
      <ProviderCreditSummary
        providerName="Tavily"
        model={crdModel()}
        credits={credits({ remaining: "0", allowance: "1000", state: "finite" })}
      />,
    )
    const bar = screen.getByRole("progressbar", { name: "Tavily native Credits remaining" })
    expect(bar.getAttribute("aria-valuenow")).toBe("0")
    expect(screen.getByText("0%")).not.toBeNull()
    expect(screen.getByText("0")).not.toBeNull()
  })

  it("hides the bar for unknown capacity with no invented percent", () => {
    const { container } = render(
      <ProviderCreditSummary
        providerName="Tavily"
        model={crdModel()}
        credits={credits({ remaining: null, allowance: null, state: "unknown" })}
        fundsControl={<button type="button">Tier control</button>}
      />,
    )
    expect(screen.queryByRole("progressbar")).toBeNull()
    expect(container.textContent).not.toContain("%")
    expect(screen.queryByText("Free")).toBeNull()
    expect(screen.getByRole("button", { name: "Tier control" })).not.toBeNull()
  })

  it("hides the bar for zero allowance while keeping native amounts", () => {
    render(
      <ProviderCreditSummary
        providerName="Tavily"
        model={crdModel()}
        credits={credits({ remaining: "999", allowance: "0" })}
      />,
    )
    expect(screen.getByText("999")).not.toBeNull()
    expect(screen.queryByRole("progressbar")).toBeNull()
  })

  it("hides the bar for PAYGO without capacity while keeping the PAYGO footnote", () => {
    render(
      <ProviderCreditSummary
        providerName="Tavily"
        model={crdModel()}
        credits={credits({ remaining: null, allowance: null, state: "paygo", paygo: true })}
      />,
    )
    expect(screen.queryByRole("progressbar")).toBeNull()
    expect(screen.getByText(/Free credits are used up/)).not.toBeNull()
  })
})
