import { describe, expect, it, vi } from "vitest"
import { render, screen, within } from "@testing-library/react"
import { SearchResults } from "./SearchResults"
import type { SearchResponse } from "@/domains/execution"

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
  it("shows an unknown cost when no unit kind is recorded", () => {
    render(<SearchResults controller={controller() as never} result={result("tavily")} />)
    expect(screen.getByText("Cost")).toBeInTheDocument()
    expect(screen.getByText("—")).toBeInTheDocument()
    expect(screen.queryByText("Credits")).toBeNull()
    expect(screen.queryByText("Units")).toBeNull()
  })

  it("does not present native provider credits as dollars", () => {
    render(<SearchResults controller={controller() as never} result={{ ...result("tavily"), costUnitKind: "CREDIT" }} />)
    expect(screen.getByText("—")).toBeInTheDocument()
    expect(screen.queryByText("Credits")).toBeNull()
  })

  it("formats a recorded dollar cost per call", () => {
    render(
      <SearchResults
        controller={controller() as never}
        result={{ ...result("exa"), costEstimateCredits: 0.007, costUnitKind: "USD" }}
      />
    )
    expect(screen.getByText("Cost")).toBeInTheDocument()
    expect(screen.getByText("$0.0070")).toBeInTheDocument()
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

  it("keeps a recorded zero dollar charge distinct from a free provider", () => {
    render(<SearchResults controller={controller() as never} result={{ ...result("exa"), costEstimateCredits: 0, costUnitKind: "USD" }} />)
    expect(screen.getByText("$0.0000")).toBeInTheDocument()
  })

  it("uses shared buttons for the raw JSON toggle and no list-level selection hint", () => {
    render(<SearchResults controller={controller() as never} result={result("brave")} />)
    const toggle = screen.getByRole("button", { name: "Inspect raw JSON" })
    expect(toggle).toHaveAttribute("data-slot", "button")
    expect(screen.queryByText("Select item to inspect")).toBeNull()
  })
})
