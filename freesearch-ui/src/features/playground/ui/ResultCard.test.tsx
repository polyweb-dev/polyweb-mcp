import { describe, expect, it, vi } from "vitest"
import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { ResultCard } from "./ResultCard"
import type { SearchResult } from "@/domains/execution"

function searchResult(overrides: Partial<SearchResult> = {}): SearchResult {
  return {
    id: "r1",
    providerId: "tavily",
    providerName: "Tavily",
    title: "Distributed consensus explained",
    url: "https://www.example.com/consensus",
    snippet: "A practical guide to distributed consensus algorithms.",
    relevanceScore: 0.85,
    ...overrides,
  }
}

function selectedButton(container: HTMLElement): HTMLElement {
  const button = container.querySelector("button[aria-pressed]")
  if (button === null || !(button instanceof HTMLElement)) {
    throw new Error("selection button not found")
  }
  return button
}

/**
 * ResultCard (PLAN §5): a thin adapter to the shared card. The card owns the
 * visual structure; fetch and external-link actions stay Playground-owned and
 * sit outside the selection button with the current disable conditions.
 */
describe("ResultCard", () => {
  it("renders title, URL, snippet, provider badge, and match score", () => {
    const { container } = render(
      <ResultCard
        result={searchResult()}
        selected={false}
        isSearching={false}
        isFetching={false}
        onSelect={() => {}}
        onFetch={() => {}}
      />
    )

    expect(container).toHaveTextContent("Distributed consensus explained")
    expect(container).toHaveTextContent("https://www.example.com/consensus")
    expect(container).toHaveTextContent(
      "A practical guide to distributed consensus algorithms."
    )
    expect(screen.getByText("Tavily")).toBeInTheDocument()
    expect(screen.getByText("85% match")).toBeInTheDocument()
  })

  it("keeps the fetch button and the external link outside the selection button", () => {
    const { container } = render(
      <ResultCard
        result={searchResult()}
        selected={false}
        isSearching={false}
        isFetching={false}
        onSelect={() => {}}
        onFetch={() => {}}
      />
    )

    const selection = selectedButton(container)
    const fetchButton = screen.getByTestId("fetch-result-r1")
    const externalLink = screen.getByTitle("Open external link")
    expect(selection.contains(fetchButton)).toBe(false)
    expect(selection.contains(externalLink)).toBe(false)
  })

  it("selects the card with the recorded result", async () => {
    const user = userEvent.setup()
    const onSelect = vi.fn()
    const result = searchResult()
    const { container } = render(
      <ResultCard
        result={result}
        selected={false}
        isSearching={false}
        isFetching={false}
        onSelect={onSelect}
        onFetch={() => {}}
      />
    )
    await user.click(selectedButton(container))
    expect(onSelect).toHaveBeenCalledTimes(1)
    expect(onSelect).toHaveBeenCalledWith(result)
  })

  it("fetches the recorded result without selecting the card", async () => {
    const user = userEvent.setup()
    const onSelect = vi.fn()
    const onFetch = vi.fn()
    const result = searchResult()
    render(
      <ResultCard
        result={result}
        selected={false}
        isSearching={false}
        isFetching={false}
        onSelect={onSelect}
        onFetch={onFetch}
      />
    )

    await user.click(screen.getByTestId("fetch-result-r1"))
    expect(onFetch).toHaveBeenCalledTimes(1)
    expect(onFetch).toHaveBeenCalledWith(result)
    expect(onSelect).not.toHaveBeenCalled()
  })

  it("disables fetch while a search is running", () => {
    render(
      <ResultCard
        result={searchResult()}
        selected={false}
        isSearching
        isFetching={false}
        onSelect={() => {}}
        onFetch={() => {}}
      />
    )

    expect(screen.getByTestId("fetch-result-r1")).toBeDisabled()
  })

  it("disables fetch while a fetch is running", () => {
    render(
      <ResultCard
        result={searchResult()}
        selected={false}
        isSearching={false}
        isFetching
        onSelect={() => {}}
        onFetch={() => {}}
      />
    )

    expect(screen.getByTestId("fetch-result-r1")).toBeDisabled()
  })

  it("enables fetch when neither a search nor a fetch is running", () => {
    render(
      <ResultCard
        result={searchResult()}
        selected={false}
        isSearching={false}
        isFetching={false}
        onSelect={() => {}}
        onFetch={() => {}}
      />
    )

    expect(screen.getByTestId("fetch-result-r1")).toBeEnabled()
  })
})
