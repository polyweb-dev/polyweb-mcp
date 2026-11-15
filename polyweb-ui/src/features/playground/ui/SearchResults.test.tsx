import { beforeEach, describe, expect, it, vi } from "vitest"
import { render, screen, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { SearchResults } from "./SearchResults"
import type { SearchResponse } from "@/domains/execution"
import type { TraceDetailsRequest } from "../model/traceDetailsSlot"

const prices = vi.hoisted(() => vi.fn())
vi.mock("@/domains/providers", async (importOriginal) => ({
  ...await importOriginal<typeof import("@/domains/providers")>(),
  getProviderPrices: prices,
}))
beforeEach(() => {
  prices.mockReset().mockImplementation(() => new Promise(() => {}))
  renderTraceDetails.mockClear()
})

const renderTraceDetails = vi.fn(({ traceId, onClose }: TraceDetailsRequest) => (
  <div role="dialog" aria-label="Trace detail">
    <span>trace {traceId ?? "none"}</span>
    <button type="button" onClick={onClose}>Close</button>
  </div>
))

function controller() {
  return {
    selectedResultForPreview: null,
    setSelectedResultForPreview: vi.fn(),
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
    const { rerender } = render(<SearchResults controller={controller() as never} renderTraceDetails={renderTraceDetails} result={search} />)
    expect(within(screen.getByRole("button", { name: /^Result one/ })).queryByText("Tavily")).toBeNull()
    rerender(<SearchResults controller={controller() as never} renderTraceDetails={renderTraceDetails} result={{ ...search,
      results: [...search.results, { ...search.results[0]!, id: "brave-0", title: "Result two", providerId: "brave" }],
    }} />)
    expect(within(screen.getByRole("button", { name: /^Result one/ })).getByText("Tavily")).toBeInTheDocument()
    expect(within(screen.getByRole("button", { name: /^Result two/ })).getByText("Brave Search")).toBeInTheDocument()
  })
  it("shows an unknown cost when no unit kind is recorded", () => {
    render(<SearchResults controller={controller() as never} renderTraceDetails={renderTraceDetails} result={result("tavily")} />)
    expect(screen.getByText("Cost")).toBeInTheDocument()
    expect(screen.getByText("—")).toBeInTheDocument()
    expect(screen.queryByText("Credits")).toBeNull()
    expect(screen.queryByText("Units")).toBeNull()
  })

  it("does not present native provider credits as dollars", () => {
    render(<SearchResults controller={controller() as never} renderTraceDetails={renderTraceDetails} result={{ ...result("tavily"), costUnitKind: "CREDIT" }} />)
    expect(screen.getByText("—")).toBeInTheDocument()
    expect(screen.queryByText("Credits")).toBeNull()
  })

  it("formats a recorded dollar cost per call", () => {
    render(
      <SearchResults
        controller={controller() as never}
        renderTraceDetails={renderTraceDetails}
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
        renderTraceDetails={renderTraceDetails}
        result={{ ...result("keenable"), costEstimateCredits: 0, costUnitKind: "FREE" }}
      />
    )
    expect(screen.getByText("Free")).not.toBeNull()
  })

  it("shows a recorded zero dollar charge as free", () => {
    render(<SearchResults controller={controller() as never} renderTraceDetails={renderTraceDetails} result={{ ...result("exa"), costEstimateCredits: 0, costUnitKind: "USD" }} />)
    expect(screen.getByText("Free")).toBeInTheDocument()
  })

  it("uses the catalog price when the call did not record dollars", async () => {
    prices.mockResolvedValue([{ providerType: "tavily", free: false, callCostUsd: { search: "0.008" } }])
    render(<SearchResults controller={controller() as never} renderTraceDetails={renderTraceDetails} result={result("tavily")} />)
    expect(await screen.findByText("$0.0080")).toBeInTheDocument()
  })

  it("uses Free for a free catalog provider without recorded dollars", async () => {
    prices.mockResolvedValue([{ providerType: "keenable", free: true, callCostUsd: {} }])
    render(<SearchResults controller={controller() as never} renderTraceDetails={renderTraceDetails} result={result("keenable")} />)
    expect(await screen.findByText("Free")).toBeInTheDocument()
  })

  it("uses a shared View details button and no list-level selection hint", () => {
    render(<SearchResults controller={controller() as never} renderTraceDetails={renderTraceDetails} result={result("brave")} />)
    const button = screen.getByRole("button", { name: "View details" })
    expect(button).toHaveAttribute("data-slot", "button")
    expect(button).toHaveAttribute("aria-haspopup", "dialog")
    expect(screen.queryByRole("button", { name: /raw JSON/i })).toBeNull()
    expect(screen.queryByRole("group", { name: "Raw search response" })).toBeNull()
    expect(screen.queryByText("Select item to inspect")).toBeNull()
  })
})

describe("SearchResults View details", () => {
  const TRACE_ID = "a".repeat(32)

  it("opens the trace inspector for the call's trace id and closes it", async () => {
    const user = userEvent.setup()
    render(<SearchResults controller={controller() as never} renderTraceDetails={renderTraceDetails} result={{ ...result("brave"), traceId: TRACE_ID }} />)
    expect(renderTraceDetails).not.toHaveBeenCalled()

    await user.click(screen.getByRole("button", { name: "View details" }))
    expect(within(screen.getByRole("dialog", { name: "Trace detail" })).getByText(`trace ${TRACE_ID}`)).toBeInTheDocument()

    await user.click(screen.getByRole("button", { name: "Close" }))
    expect(screen.queryByRole("dialog", { name: "Trace detail" })).toBeNull()
    expect(screen.getByText("Result one")).toBeInTheDocument()
  })

  it.each([
    ["absent", undefined],
    ["null", null],
    ["not a string", 42 as unknown as string],
  ])("hands the inspector no trace id when the stored id is %s", async (_label, traceId) => {
    const user = userEvent.setup()
    render(<SearchResults controller={controller() as never} renderTraceDetails={renderTraceDetails} result={{ ...result("brave"), traceId }} />)
    await user.click(screen.getByRole("button", { name: "View details" }))
    expect(screen.getByText("trace none")).toBeInTheDocument()
  })
})
