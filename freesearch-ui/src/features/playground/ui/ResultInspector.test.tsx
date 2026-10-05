import { describe, expect, it } from "vitest"
import { render, screen } from "@testing-library/react"
import { ResultInspector } from "./ResultInspector"
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

/**
 * ResultInspector (PLAN §5): a thin adapter to the shared inspector. The
 * Playground match score stays a percentage under the Attributed label, with
 * the target URL before the snippet summary.
 */
describe("ResultInspector", () => {
  it("shows attribution, score, target URL, and snippet summary in order", () => {
    const { container } = render(<ResultInspector result={searchResult()} />)
    const html = container.innerHTML

    const attributedIndex = html.indexOf("Attributed")
    const scoreIndex = html.indexOf("Score")
    const urlIndex = html.indexOf("Target URL")
    const snippetIndex = html.indexOf("Snippet summary")

    expect(attributedIndex).toBeGreaterThanOrEqual(0)
    expect(scoreIndex).toBeGreaterThanOrEqual(0)
    expect(urlIndex).toBeGreaterThanOrEqual(0)
    expect(snippetIndex).toBeGreaterThanOrEqual(0)
    expect(attributedIndex).toBeLessThan(snippetIndex)
    expect(scoreIndex).toBeLessThan(snippetIndex)
    expect(urlIndex).toBeLessThan(snippetIndex)
  })

  it("shows the provider badge and the percent match score", () => {
    render(<ResultInspector result={searchResult()} />)

    expect(screen.getByText("Tavily")).toBeInTheDocument()
    expect(screen.getByText("Score")).toBeInTheDocument()
    expect(screen.getByText("85% match")).toBeInTheDocument()
  })

  it("shows the target host while the link keeps the full URL", () => {
    const url = "https://www.example.com/consensus"
    render(<ResultInspector result={searchResult({ url })} />)

    const link = screen.getByRole("link", { name: url })
    expect(link).toHaveTextContent("www.example.com")
    expect(link).toHaveAttribute("href", url)
  })

  it("shows the empty state when no result is selected", () => {
    render(<ResultInspector result={null} />)

    expect(
      screen.getByText(
        "Select a search result from the list to inspect full metadata and snippet extraction."
      )
    ).toBeInTheDocument()
  })
})
