import React from "react"
import { describe, it, expect } from "vitest"
import { render, screen } from "@testing-library/react"
import { WaterfallPanel } from "./WaterfallPanel"
import type { ProviderWaterfallItem } from "@/domains/execution"

describe("WaterfallPanel", () => {
  it("renders 'Trace unavailable from backend' for single-provider responses", () => {
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
    expect(screen.getByText("Trace unavailable from backend")).toBeInTheDocument()
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
})
