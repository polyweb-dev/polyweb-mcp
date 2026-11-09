import { describe, expect, it, vi } from "vitest"
import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { SearchResultCard } from "./SearchResultCard"
import type { SearchResultView } from "./searchResultView"

function cardResult(overrides: Partial<SearchResultView> = {}): SearchResultView {
  return {
    id: "1",
    title: "Distributed consensus explained",
    url: "https://www.example.com/consensus",
    snippet: "A practical guide to distributed consensus algorithms.",
    providers: [{ id: "tavily", name: "Tavily" }],
    attributionLabel: "Provider",
    score: { label: "Provider score", value: 0.68, format: "decimal" },
    rank: 1,
    total: 42,
    ...overrides,
  }
}

/**
 * SearchResultCard (PLAN §4 R1): one shared hit — title, URL, two-line
 * snippet, badges, and the recorded score. The text block is the selection
 * button; caller actions stay separate controls.
 */
describe("SearchResultCard", () => {
  it("marks the selection button pressed when selected and calls onSelect on click", async () => {
    const user = userEvent.setup()
    const onSelect = vi.fn()
    render(<SearchResultCard result={cardResult()} selected onSelect={onSelect} />)

    const button = screen.getByRole("button", { name: /Distributed consensus explained/ })
    expect(button).toHaveAttribute("aria-pressed", "true")

    await user.click(button)
    expect(onSelect).toHaveBeenCalledTimes(1)
  })

  it("marks the selection button unpressed when not selected", () => {
    render(<SearchResultCard result={cardResult()} selected={false} onSelect={() => {}} />)

    expect(
      screen.getByRole("button", { name: /Distributed consensus explained/ })
    ).toHaveAttribute("aria-pressed", "false")
  })

  it("keeps caller actions outside the selection button", () => {
    const { container } = render(
      <SearchResultCard
        result={cardResult()}
        selected={false}
        onSelect={() => {}}
        actions={<button type="button">Fetch this page</button>}
      />
    )

    const selectionButton = container.querySelector("button[aria-pressed]")
    const actionButton = screen.getByRole("button", { name: "Fetch this page" })
    expect(selectionButton).not.toBeNull()
    expect(selectionButton?.contains(actionButton)).toBe(false)
  })

  it("clamps the snippet to two lines", () => {
    render(<SearchResultCard result={cardResult()} selected={false} onSelect={() => {}} />)

    const snippet = screen.getByText("A practical guide to distributed consensus algorithms.")
    expect(snippet).toHaveClass("line-clamp-2")
  })

  it("shows provider badges and the recorded score", () => {
    render(
      <SearchResultCard
        result={cardResult({
          providers: [
            { id: "tavily", name: "Tavily" },
            { id: "exa", name: "Exa" },
          ],
          score: { label: "Fusion score", value: 0.7, format: "decimal" },
        })}
        selected={false}
        onSelect={() => {}}
      />
    )

    expect(screen.getByText("Tavily")).toBeInTheDocument()
    expect(screen.getByText("Exa")).toBeInTheDocument()
    expect(screen.getByText("2 engines")).toBeInTheDocument()
    expect(screen.getByText("70% match")).toBeInTheDocument()
    // The metadata row shares one font size; nothing in it drops a level.
    const meta = screen.getByText("2 engines").closest("div")!
    expect(meta.querySelectorAll('[class*="text-[11px]"]')).toHaveLength(0)
  })

  it("shows the published date when the view records one", () => {
    render(
      <SearchResultCard
        result={cardResult({ publishedDate: "2024-05-01" })}
        selected={false}
        onSelect={() => {}}
      />
    )

    expect(screen.getByText("2024-05-01")).toBeInTheDocument()
  })

  it("omits the published date when the view records none", () => {
    const result = cardResult()
    delete result.publishedDate
    render(<SearchResultCard result={result} selected={false} onSelect={() => {}} />)

    expect(screen.getByText("Distributed consensus explained")).toBeInTheDocument()
    expect(screen.queryByText("2024-05-01")).not.toBeInTheDocument()
  })
})
