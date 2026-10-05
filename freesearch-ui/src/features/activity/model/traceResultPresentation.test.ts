import { describe, expect, it } from "vitest"
import { toTraceResultView } from "./traceResultPresentation"
import type { TraceSearchResult } from "@/domains/activity"

function traceResult(overrides: Partial<TraceSearchResult> = {}): TraceSearchResult {
  return {
    title: "Distributed consensus explained",
    url: "https://www.example.com/consensus",
    snippet: "A practical guide to distributed consensus algorithms.",
    source: "tavily",
    score: 0.68,
    ...overrides,
  }
}

/**
 * toTraceResultView (PLAN §3): one recorded trace result in the shared
 * presentation. Rank and recorded order are the identity, never the URL. A
 * missing score stays missing and a missing contributor list stays empty.
 */
describe("toTraceResultView", () => {
  it("deduplicates, trims, and normalizes fusion contributors without sorting", () => {
    const view = toTraceResultView({
      result: traceResult({ source: "tavily, exa, tavily , you" }),
      rank: 1,
      total: 6,
      mode: "fusion",
      providerId: null,
    })

    expect(view.providers).toEqual([
      { id: "tavily", name: "Tavily" },
      { id: "exa", name: "Exa" },
      { id: "youcom", name: "You.com" },
    ])
    expect(view.attributionLabel).toBe("Contributing providers")
  })

  it("keeps fusion contributor order instead of sorting it", () => {
    const view = toTraceResultView({
      result: traceResult({ source: "tavily, exa, brave" }),
      rank: 1,
      total: 3,
      mode: "fusion",
      providerId: null,
    })

    expect(view.providers.map((provider) => provider.id)).toEqual([
      "tavily",
      "exa",
      "brave",
    ])
  })

  it("returns an empty provider list for a null fusion source without inventing one", () => {
    const view = toTraceResultView({
      result: traceResult({ source: null }),
      rank: 2,
      total: 6,
      mode: "fusion",
      providerId: "exa",
    })

    expect(view.providers).toEqual([])
  })

  it("scopes a single-provider result to the attempt identity, not the source text", () => {
    const view = toTraceResultView({
      result: traceResult({ source: null, score: null }),
      rank: 1,
      total: 2,
      mode: "provider",
      providerId: "exa",
    })

    expect(view.providers).toEqual([{ id: "exa", name: "Exa" }])
    expect(view.attributionLabel).toBe("Provider")
  })

  it("returns an empty provider list when the scope records no provider", () => {
    const view = toTraceResultView({
      result: traceResult({ source: "exa" }),
      rank: 1,
      total: 2,
      mode: "provider",
      providerId: null,
    })

    expect(view.providers).toEqual([])
  })

  it("keeps a null fusion score null with the Fusion score label", () => {
    const view = toTraceResultView({
      result: traceResult({ score: null }),
      rank: 1,
      total: 6,
      mode: "fusion",
      providerId: null,
    })

    expect(view.score).toEqual({ label: "Fusion score", value: null, format: "decimal" })
  })

  it("keeps a null provider score null with the Provider score label", () => {
    const view = toTraceResultView({
      result: traceResult({ score: null }),
      rank: 1,
      total: 2,
      mode: "provider",
      providerId: "exa",
    })

    expect(view.score).toEqual({ label: "Provider score", value: null, format: "decimal" })
  })

  it("keeps a recorded decimal score with its mode label", () => {
    const view = toTraceResultView({
      result: traceResult({ score: 0.68 }),
      rank: 1,
      total: 2,
      mode: "provider",
      providerId: "exa",
    })

    expect(view.score).toEqual({ label: "Provider score", value: 0.68, format: "decimal" })
  })

  it("uses the rank string as the identity, not the URL", () => {
    const first = toTraceResultView({
      result: traceResult({ url: "https://www.example.com/dupe" }),
      rank: 1,
      total: 2,
      mode: "fusion",
      providerId: null,
    })
    const second = toTraceResultView({
      result: traceResult({ url: "https://www.example.com/dupe" }),
      rank: 2,
      total: 2,
      mode: "fusion",
      providerId: null,
    })

    expect(first.id).toBe("1")
    expect(second.id).toBe("2")
    expect(first.rank).toBe(1)
    expect(second.rank).toBe(2)
    expect(first.total).toBe(2)
  })
})
