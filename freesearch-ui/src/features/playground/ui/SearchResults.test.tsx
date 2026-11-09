import { describe, expect, it, vi } from "vitest"
import { render, screen, within } from "@testing-library/react"
import { SearchResults } from "./SearchResults"
import type { SearchResponse } from "@/domains/execution"

/**
 * Search result unit labels: a response that names its unit kind shows the
 * unit with the amount; otherwise Tavily native usage reads as `Credits` while
 * every other provider keeps `Units`.
 */

function controller() {
  return {
    selectedResultForPreview: null,
    setSelectedResultForPreview: vi.fn(),
    showJsonInspector: false,
    setShowJsonInspector: vi.fn(),
    copied: false,
    copyToClipboard: vi.fn(),
    isSearching: false,
    isFetching: false,
    canFetch: true,
    handleFetchResult: vi.fn(() => Promise.resolve()),
  }
}

function result(providerId: string): SearchResponse {
  return {
    query: "hello",
    results: [
      {
        id: providerId + "-0",
        providerId,
        providerName: providerId,
        title: "Result one",
        url: "https://example.com/one",
        snippet: "Snippet one.",
        relevanceScore: 0.9,
      },
    ],
    totalResults: 1,
    selectedProviderId: providerId,
    fallbackChain: [providerId],
    waterfall: [],
    executionTimeMs: 187,
    costEstimateCredits: 7,
    timestamp: "2026-09-06T10:02:00Z",
  }
}

describe("SearchResults usage label", () => {
  it("shows per-result attribution only when the response contains multiple providers", () => {
    const search = result("tavily")
    const { rerender } = render(<SearchResults controller={controller() as never} result={search} />)
    expect(within(screen.getByRole("button", { name: /^Result one/ })).queryByText("Tavily")).toBeNull()
    rerender(<SearchResults controller={controller() as never} result={{ ...search,
      results: [...search.results, { ...search.results[0]!, id: "brave-0", title: "Result two", providerId: "brave" }],
    }} />)
    expect(within(screen.getByRole("button", { name: /^Result one/ })).getByText("Tavily")).toBeInTheDocument()
    expect(within(screen.getByRole("button", { name: /^Result two/ })).getByText("Brave Search")).toBeInTheDocument()
  })
  it("labels Tavily native usage as Credits", () => {
    render(<SearchResults controller={controller() as never} result={result("tavily")} />)
    expect(screen.getByText("Credits")).not.toBeNull()
    expect(screen.queryByText("Units")).toBeNull()
    expect(screen.getByText("7")).not.toBeNull()
  })

  it("labels other providers as Units", () => {
    render(<SearchResults controller={controller() as never} result={result("brave")} />)
    expect(screen.getByText("Units")).not.toBeNull()
    expect(screen.queryByText("Credits")).toBeNull()
  })

  it("shows the unit with the amount when the response names its unit kind", () => {
    render(
      <SearchResults
        controller={controller() as never}
        result={{ ...result("exa"), costEstimateCredits: 0.007, costUnitKind: "USD" }}
      />
    )
    expect(screen.getByText("Usage")).not.toBeNull()
    expect(screen.getByText("0.007 USD")).not.toBeNull()
    expect(screen.queryByText("Units")).toBeNull()
  })

  it("names a keyless call Free instead of a zero amount", () => {
    render(
      <SearchResults
        controller={controller() as never}
        result={{ ...result("keenable"), costEstimateCredits: 0, costUnitKind: "FREE" }}
      />
    )
    expect(screen.getByText("Free")).not.toBeNull()
  })

  it("uses shared buttons for the raw JSON toggle and no list-level selection hint", () => {
    render(<SearchResults controller={controller() as never} result={result("brave")} />)
    const toggle = screen.getByRole("button", { name: "Inspect raw JSON" })
    expect(toggle).toHaveAttribute("data-slot", "button")
    expect(screen.queryByText("Select item to inspect")).toBeNull()
  })
})
