import React from "react"
import { describe, it, expect } from "vitest"
import { render, screen } from "@testing-library/react"
import { WaterfallPanel } from "./WaterfallPanel"
import type { ProviderWaterfallItem } from "@/domains/execution"

describe("WaterfallPanel", () => {
  it("keeps single-provider timings without an unavailable-trace message", () => {
    const singleWaterfall: ProviderWaterfallItem[] = [
      {
        providerId: "tavily",
        providerName: "Tavily",
        latencyMs: 250,
        status: "success",
        resultsCount: 5,
        costCredits: 1,
      },
    ]

    render(<WaterfallPanel waterfall={singleWaterfall} />)

    expect(screen.getByText("Execution waterfall")).toBeInTheDocument()
    expect(screen.queryByText("Trace unavailable from backend")).not.toBeInTheDocument()
    expect(screen.queryByText(/trace (is )?unavailable|waterfall unavailable/i)).not.toBeInTheDocument()
    expect(screen.queryByText("Live execution trace")).not.toBeInTheDocument()
    expect(screen.getByText("Tavily")).toBeInTheDocument()
    expect(screen.getByText("250ms")).toBeInTheDocument()
  })

  it("renders 'Live execution trace' and individual provider bars for multi-provider responses", () => {
    const multiWaterfall: ProviderWaterfallItem[] = [
      {
        providerId: "brave",
        providerName: "Brave Search",
        latencyMs: 150,
        status: "success",
        resultsCount: 4,
        costCredits: 1,
      },
      {
        providerId: "exa",
        providerName: "Exa",
        latencyMs: 450,
        status: "success",
        resultsCount: 6,
        costCredits: 1,
      },
      {
        providerId: "tavily",
        providerName: "Tavily",
        latencyMs: 300,
        status: "success",
        resultsCount: 5,
        costCredits: 1,
      },
    ]

    render(<WaterfallPanel waterfall={multiWaterfall} />)

    expect(screen.getByText("Execution waterfall")).toBeInTheDocument()
    expect(screen.getByText("Live execution trace")).toBeInTheDocument()
    expect(screen.queryByText("Trace unavailable from backend")).not.toBeInTheDocument()

    expect(screen.getByText("Brave Search")).toBeInTheDocument()
    expect(screen.getByText("150ms")).toBeInTheDocument()

    expect(screen.getByText("Exa")).toBeInTheDocument()
    expect(screen.getByText("450ms")).toBeInTheDocument()

    expect(screen.getByText("Tavily")).toBeInTheDocument()
    expect(screen.getByText("300ms")).toBeInTheDocument()
  })

  it("renders execution lanes through the shared latency waterfall", () => {
    const multiWaterfall: ProviderWaterfallItem[] = [
      {
        providerId: "brave",
        providerName: "Brave Search",
        latencyMs: 150,
        status: "success",
        resultsCount: 4,
        costCredits: 1,
      },
      {
        providerId: "exa",
        providerName: "Exa",
        latencyMs: 450,
        status: "success",
        resultsCount: 6,
        costCredits: 1,
      },
    ]

    render(<WaterfallPanel waterfall={multiWaterfall} />)

    // Shared geometry: one accessible list, a real millisecond axis, and the
    // per-provider result annotations preserved through the extraction.
    expect(
      screen.getByRole("list", { name: "Provider latency waterfall" })
    ).toBeInTheDocument()
    expect(screen.getByText("Timeline scale 0 to 450 milliseconds")).toBeInTheDocument()
    expect(screen.getByText("4 res")).toBeInTheDocument()
    expect(screen.getByText("6 res")).toBeInTheDocument()
  })
})

/**
 * Characterization (PLAN §6.3 item 10): execution rows stay non-selectable
 * after `LatencyWaterfall` gains additive `selected`/`onSelect`. Playground
 * never passes selection handlers, so its lanes keep plain list content and
 * zero-origin geometry. These SHOULD PASS before and after that change.
 */
describe("WaterfallPanel non-selectable contract", () => {
  it("renders execution rows as plain list content, never buttons", () => {
    const waterfall: ProviderWaterfallItem[] = [
      { providerId: "brave", providerName: "Brave Search", latencyMs: 150, status: "success", resultsCount: 4, costCredits: 1 },
      { providerId: "exa", providerName: "Exa", latencyMs: 450, status: "success", resultsCount: 6, costCredits: 1 },
    ]

    render(<WaterfallPanel waterfall={waterfall} />)

    expect(screen.queryByRole("button")).not.toBeInTheDocument()
    expect(screen.getByText("Brave Search")).toBeInTheDocument()
    expect(screen.getByText("Exa")).toBeInTheDocument()
  })

  it("keeps zero-origin bars on the shared axis", () => {
    const waterfall: ProviderWaterfallItem[] = [
      { providerId: "brave", providerName: "Brave Search", latencyMs: 150, status: "success", resultsCount: 4, costCredits: 1 },
    ]

    render(<WaterfallPanel waterfall={waterfall} />)

    const bar = screen
      .getByText("Brave Search")
      .closest("li")!
      .querySelector('span[style*="left"]') as HTMLElement
    expect(bar.style.left).toBe("0%")
    expect(screen.getByText("Timeline scale 0 to 150 milliseconds")).toBeInTheDocument()
  })

  it("renders an empty state instead of crashing for an empty waterfall", () => {
    render(<WaterfallPanel waterfall={[]} />)

    expect(screen.getByText("Execution waterfall")).toBeInTheDocument()
    expect(screen.queryByText("Trace unavailable from backend")).not.toBeInTheDocument()
    expect(screen.getByText("No timing was recorded.")).toBeInTheDocument()
  })
})
