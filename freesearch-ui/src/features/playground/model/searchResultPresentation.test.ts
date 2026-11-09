import { describe, expect, it } from "vitest"
import { toPlaygroundResultView } from "./searchResultPresentation"
import type { SearchResult } from "@/domains/execution"

function playgroundResult(overrides: Partial<SearchResult> = {}): SearchResult {
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
 * toPlaygroundResultView (PLAN §3): one execution result in the shared
 * presentation. The match score stays a percentage and the recorded published
 * date is kept; contributor order is recorded order, never sorted.
 */
describe("toPlaygroundResultView", () => {
  it("keeps the match score as a percent value", () => {
    const view = toPlaygroundResultView(playgroundResult({ relevanceScore: 0.85 }))

    expect(view.score).toEqual({ label: "Score", value: 0.85, format: "percent" })
  })

  it("keeps the recorded published date", () => {
    const view = toPlaygroundResultView(
      playgroundResult({ publishedDate: "2024-05-01" })
    )

    expect(view.publishedDate).toBe("May 1, 2024")
  })

  it("removes markdown from result snippets", () => {
    const view = toPlaygroundResultView(playgroundResult({
      snippet: "## [Title](https://example.com)\n**English:** a *result*",
    }))
    expect(view.snippet).toBe("Title\nEnglish: a result")
  })

  it("omits the published date when the execution recorded none", () => {
    const view = toPlaygroundResultView(playgroundResult())

    expect(view.publishedDate).toBeUndefined()
  })

  it("lists every recorded engine for a multi-source hit", () => {
    const view = toPlaygroundResultView(
      playgroundResult({ providerId: "brave", sources: ["tavily", "exa"] })
    )

    expect(view.providers).toEqual([
      { id: "tavily", name: "Tavily" },
      { id: "exa", name: "Exa" },
    ])
    expect(view.attributionLabel).toBe("Attributed")
  })

  it("keeps the mapped provider for a single-source hit", () => {
    const view = toPlaygroundResultView(
      playgroundResult({ providerId: "exa", sources: undefined })
    )

    expect(view.providers).toEqual([{ id: "exa", name: "Exa" }])
  })

  it("keeps the mapped provider when only one source is recorded", () => {
    const view = toPlaygroundResultView(
      playgroundResult({ providerId: "exa", sources: ["tavily"] })
    )

    expect(view.providers).toEqual([{ id: "exa", name: "Exa" }])
  })

  it("deduplicates multi-source contributors without sorting them", () => {
    const view = toPlaygroundResultView(
      playgroundResult({ providerId: "brave", sources: ["exa", "tavily", "exa"] })
    )

    expect(view.providers).toEqual([
      { id: "exa", name: "Exa" },
      { id: "tavily", name: "Tavily" },
    ])
  })
})
