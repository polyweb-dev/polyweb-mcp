import { describe, expect, it, vi } from "vitest"
import { render, screen } from "@testing-library/react"
import { SearchResults } from "./SearchResults"
import type { SearchResponse } from "@/domains/execution"

/**
 * Search result unit labels: Tavily native usage reads as `Credits` while
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
})
