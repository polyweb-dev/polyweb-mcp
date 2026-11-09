import { describe, expect, it } from "vitest"
import { render, screen } from "@testing-library/react"
import { SearchResultInspector } from "./SearchResultInspector"
import type { SearchResultView } from "./searchResultView"

const LONG_SNIPPET =
  "First sentence of the recorded snippet. " +
  "Second sentence of the recorded snippet. ".repeat(40)

function inspectorResult(overrides: Partial<SearchResultView> = {}): SearchResultView {
  return {
    id: "1",
    title: "Distributed consensus explained",
    url: "https://docs.example.com/some/deep/path?x=1",
    snippet: LONG_SNIPPET,
    providers: [
      { id: "tavily", name: "Tavily" },
      { id: "exa", name: "Exa" },
    ],
    attributionLabel: "Contributing providers",
    score: { label: "Fusion score", value: 0.7, format: "decimal" },
    rank: 1,
    total: 6,
    ...overrides,
  }
}

/**
 * SearchResultInspector (PLAN §4 R1): recorded metadata (rank, attribution,
 * score, target host) comes first so a long snippet can never push it below
 * the fold; the snippet keeps its own bounded scroll region.
 */
describe("SearchResultInspector", () => {
  it("places rank, attribution, score, and target URL before the snippet summary", () => {
    const { container } = render(<SearchResultInspector result={inspectorResult()} />)
    const html = container.innerHTML

    const rankIndex = html.indexOf("Result 1 of 6")
    const attributionIndex = html.indexOf("Contributing providers")
    const scoreIndex = html.indexOf("Fusion score")
    const urlIndex = html.indexOf("Target URL")
    const snippetIndex = html.indexOf("Snippet summary")

    expect(rankIndex).toBeGreaterThanOrEqual(0)
    expect(attributionIndex).toBeGreaterThanOrEqual(0)
    expect(scoreIndex).toBeGreaterThanOrEqual(0)
    expect(urlIndex).toBeGreaterThanOrEqual(0)
    expect(snippetIndex).toBeGreaterThanOrEqual(0)
    expect(rankIndex).toBeLessThan(snippetIndex)
    expect(attributionIndex).toBeLessThan(snippetIndex)
    expect(scoreIndex).toBeLessThan(snippetIndex)
    expect(urlIndex).toBeLessThan(snippetIndex)
  })

  it("shows the default empty state when no result is selected", () => {
    render(<SearchResultInspector result={null} />)

    expect(screen.getByText("Select a result to see its details")).toBeInTheDocument()
  })

  it("titles a selected result Result details in sentence case", () => {
    render(<SearchResultInspector result={inspectorResult()} />)

    expect(screen.getByRole("heading", { name: "Result details" })).toBeInTheDocument()
    expect(screen.queryByText("Result Inspector")).not.toBeInTheDocument()
  })

  it("shows a custom empty state when the caller provides one", () => {
    render(
      <SearchResultInspector result={null} emptyState={<p>No trace result chosen</p>} />
    )

    expect(screen.getByText("No trace result chosen")).toBeInTheDocument()
    expect(screen.queryByText("Select a result to see its details")).not.toBeInTheDocument()
  })

  it("keeps the full snippet inside a bounded scroll region", () => {
    render(<SearchResultInspector result={inspectorResult()} />)

    const snippet = screen.getByText(/First sentence of the recorded snippet\./)
    expect(snippet.textContent).toBe(LONG_SNIPPET)
    expect(snippet).toHaveClass("max-h-[18rem]")
    expect(snippet).toHaveClass("overflow-y-auto")
  })

  it("shows the URL host while the link keeps the full URL", () => {
    const url = "https://docs.example.com/some/deep/path?x=1"
    render(<SearchResultInspector result={inspectorResult({ url })} />)

    const link = screen.getByRole("link", { name: url })
    expect(link).toHaveTextContent("docs.example.com")
    expect(link).toHaveAttribute("href", url)
    expect(link).toHaveAttribute("title", url)
    expect(link).toHaveAttribute("aria-label", url)
  })

  it("omits the score row when no score was recorded", () => {
    const { rerender } = render(
      <SearchResultInspector
        result={inspectorResult({ score: { label: "Provider score", value: null, format: "decimal" } })}
      />
    )

    expect(screen.queryByText("Provider score")).not.toBeInTheDocument()
    expect(screen.queryByText("Unavailable")).not.toBeInTheDocument()
    expect(screen.queryByText("0.00")).not.toBeInTheDocument()

    rerender(
      <SearchResultInspector
        result={inspectorResult({ score: { label: "Score", value: 0, format: "percent" } })}
      />
    )

    expect(screen.queryByText("Score")).not.toBeInTheDocument()
    expect(screen.queryByText("0% match")).not.toBeInTheDocument()
  })

  it("never shows Source or Source not recorded text", () => {
    render(<SearchResultInspector result={inspectorResult({ providers: [] })} />)

    expect(screen.queryByText("Source")).not.toBeInTheDocument()
    expect(screen.queryByText("Source not recorded")).not.toBeInTheDocument()
  })

  it("labels the header external link with the Open target URL tooltip", () => {
    const url = "https://docs.example.com/some/deep/path?x=1"
    render(<SearchResultInspector result={inspectorResult({ url })} />)

    const links = screen.getAllByRole("link")
    const opener = links.find(
      (link) => link.getAttribute("title") === "Open target URL"
    )!
    expect(opener).toBeInTheDocument()
    expect(opener).toHaveAttribute("href", url)
    expect(screen.queryByTitle("Open source")).not.toBeInTheDocument()
  })
})
