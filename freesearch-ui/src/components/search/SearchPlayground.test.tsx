import React from "react"
import { describe, it, expect, afterEach, vi } from "vitest"
import { render, screen, fireEvent, waitFor } from "@testing-library/react"
import { FreeSearchProvider } from "@/context/FreeSearchContext"
import { PlaygroundPage as SearchPlayground } from "@/features/playground/ui/PlaygroundPage"
import { installFetchStub, ok, err } from "@/test/fetchMock"
import {
  allProvidersFixture,
  routingConfigFixture,
  dashboardFixture,
  searchResponseFixture,
  fetchResponseFixture,
} from "@/test/backendFixtures"

/**
 * RED update: search now flows through the live backend (mocked fetch).
 * Results show real mapped fixture titles with a SINGLE-entry waterfall plus
 * an honest per-attempt-trace-unavailable note; failures show a banner while
 * keeping the last-good results.
 */
function renderWithBackend(
  searchHandler?: (req: { url: string }) => Response,
  fetchHandler?: (req: { url: string }) => Response
) {
  const stub = installFetchStub((req) => {
    if (req.url === "/api/v1/providers" && req.method === "GET") {
      return ok(allProvidersFixture())
    }
    if (req.url === "/api/v1/routing/config" && req.method === "GET") {
      return ok(routingConfigFixture())
    }
    if (req.url.startsWith("/dashboard")) return ok(dashboardFixture())
    if (req.url === "/search" && req.method === "POST") {
      return searchHandler ? searchHandler(req) : ok(searchResponseFixture())
    }
    if (req.url === "/fetch" && req.method === "POST") {
      return fetchHandler ? fetchHandler(req) : ok(fetchResponseFixture())
    }
    return err(404, { detail: "unhandled test route" })
  })
  const view = render(
    <FreeSearchProvider>
      <SearchPlayground />
    </FreeSearchProvider>
  )
  return { stub, ...view }
}

async function submitQuery(query: string) {
  const input = screen.getByPlaceholderText(
    /Search across all providers/i
  ) as HTMLInputElement
  fireEvent.change(input, { target: { value: query } })
  fireEvent.submit(input.closest("form")!)
}

describe("SearchPlayground (live backend)", () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it("renders mode toggles and search form", async () => {
    renderWithBackend()
    await waitFor(() => {
      expect(screen.getByPlaceholderText(/Search across all providers/i)).toBeInTheDocument()
    })
    expect(screen.getAllByText("Search").length).toBeGreaterThanOrEqual(1)
    expect(screen.getByText("Fetch")).toBeInTheDocument()
  })

  it("executes search and displays the real mapped results", async () => {
    renderWithBackend()
    await waitFor(() => {
      expect(screen.getByPlaceholderText(/Search across all providers/i)).toBeInTheDocument()
    })

    await submitQuery("live backend query")

    await waitFor(() => {
      expect(screen.getByText("Live backend result one")).toBeInTheDocument()
    })
    expect(screen.getByText("Live backend result two")).toBeInTheDocument()
    // Mock-template copy must never appear for live results
    expect(document.body.textContent).not.toContain("Comprehensive Architecture")
  })

  it("renders exactly ONE waterfall entry plus a trace-unavailable note", async () => {
    renderWithBackend()
    await waitFor(() => {
      expect(screen.getByPlaceholderText(/Search across all providers/i)).toBeInTheDocument()
    })

    await submitQuery("live backend query")

    await waitFor(() => {
      expect(screen.getByText("Live backend result one")).toBeInTheDocument()
    })
    // Single-entry waterfall: the raw JSON inspector carries exactly one entry
    const inspectorToggle = screen.getByText(/Inspect raw JSON/i)
    fireEvent.click(inspectorToggle)
    await waitFor(() => {
      const occurrences = (document.body.textContent?.match(/resultsCount/g) ?? []).length
      expect(occurrences).toBe(1)
    })
    // Honest note: per-attempt fallback trace is unavailable from the backend
    expect(screen.getByText(/trace (is )?unavailable|waterfall unavailable/i)).toBeInTheDocument()
    // Never fake multi-hop cascade text for a single-attempt response
    expect(document.body.textContent).not.toMatch(/[2-9]\d* hops evaluated/)
  })

  it("shows an error banner on search failure", async () => {
    renderWithBackend(() => err(503, { detail: "no provider is configured" }))
    await waitFor(() => {
      expect(screen.getByPlaceholderText(/Search across all providers/i)).toBeInTheDocument()
    })

    await submitQuery("live backend query")

    await waitFor(() => {
      expect(screen.getByText(/no provider is configured/i)).toBeInTheDocument()
    })
    expect(screen.queryByText("Live backend result one")).not.toBeInTheDocument()
  })

  it("keeps the last-good results visible when a later search fails", async () => {
    let shouldFail = false
    renderWithBackend(() =>
      shouldFail ? err(503, { detail: "backend went away" }) : ok(searchResponseFixture())
    )
    await waitFor(() => {
      expect(screen.getByPlaceholderText(/Search across all providers/i)).toBeInTheDocument()
    })

    await submitQuery("first query")
    await waitFor(() => {
      expect(screen.getByText("Live backend result one")).toBeInTheDocument()
    })

    shouldFail = true
    await submitQuery("second query")

    await waitFor(() => {
      expect(screen.getByText(/backend went away/i)).toBeInTheDocument()
    })
    expect(screen.getByText("Live backend result one")).toBeInTheDocument()
  })

  it("resets an ineligible search-only provider when switching to Fetch", async () => {
    const { stub } = renderWithBackend()
    await waitFor(() => {
      expect(screen.getByPlaceholderText(/Search across all providers/i)).toBeInTheDocument()
    })

    // Brave is search-only: pick it in the search provider filter. The
    // catalog arrives asynchronously, so wait for its option first.
    await screen.findByRole("option", { name: "Brave Search" })
    const searchSelect = screen.getByRole("combobox") as HTMLSelectElement
    fireEvent.change(searchSelect, { target: { value: "brave" } })
    expect(searchSelect.value).toBe("brave")

    // Switching operations must clear the selected-provider state because
    // Brave cannot serve fetches.
    fireEvent.click(screen.getByRole("tab", { name: "Fetch", exact: true }))

    const fetchSelect = screen.getByRole("combobox") as HTMLSelectElement
    expect(fetchSelect).toHaveValue("auto")

    const urlInput = screen.getByPlaceholderText(
      /Enter a URL to fetch/i
    ) as HTMLInputElement
    fireEvent.change(urlInput, { target: { value: "https://example.com/doc" } })
    fireEvent.submit(urlInput.closest("form")!)

    await waitFor(() => {
      expect(stub.requestsTo("/fetch")).toHaveLength(1)
    })
    expect(stub.requestsTo("/fetch")[0].body).toEqual({
      url: "https://example.com/doc",
      max_chars: null,
      routing: { mode: "auto", providers: [], allow_fallback: true },
    })
  })

  it("labels telemetry in Units, never Cost/credits", async () => {
    renderWithBackend()
    await waitFor(() => {
      expect(screen.getByPlaceholderText(/Search across all providers/i)).toBeInTheDocument()
    })

    await submitQuery("live backend query")

    await waitFor(() => {
      expect(screen.getByText("Live backend result one")).toBeInTheDocument()
    })
    expect(screen.getByText(/Units/i)).toBeInTheDocument()
    expect(document.body.textContent).not.toMatch(/Cost|credits/i)
  })

  it("renders fetch content length as UTF-8 bytes, not JS chars", async () => {
    const content = "héllo 日本語 world"
    const expectedBytes = new TextEncoder().encode(content).length
    // Sanity: the fixture is genuinely multi-byte (bytes > chars).
    expect(expectedBytes).toBeGreaterThan(content.length)

    renderWithBackend(
      undefined,
      () =>
        ok(
          fetchResponseFixture({
            document: {
              url: "https://example.com/doc",
              content,
              title: "Byte doc",
              content_type: "text/markdown",
              fetched_at: "2026-09-06T10:03:00Z",
              metadata: {},
            },
          })
        )
    )
    await waitFor(() => {
      expect(screen.getByPlaceholderText(/Search across all providers/i)).toBeInTheDocument()
    })

    fireEvent.click(screen.getByRole("tab", { name: "Fetch", exact: true }))

    const urlInput = screen.getByPlaceholderText(
      /Enter a URL to fetch/i
    ) as HTMLInputElement
    fireEvent.change(urlInput, { target: { value: "https://example.com/doc" } })
    fireEvent.submit(urlInput.closest("form")!)

    await waitFor(() => {
      expect(screen.getByText("Byte doc")).toBeInTheDocument()
    })
    expect(screen.getByText(`${expectedBytes} bytes`)).toBeInTheDocument()
  })

  it("executes fanout search across all providers when All Providers is selected", async () => {
    let capturedBody: unknown = null
    renderWithBackend((req) => {
      capturedBody = (req as unknown as { body: unknown }).body
      return ok({
        query: "fanout test",
        provider: "aggregated",
        total_results: 1,
        results: [
          {
            title: "Fused Multi-Engine Hit",
            url: "https://example.com/consensus",
            snippet: "Verified snippet content",
            score: 0.95,
            source: "exa, brave",
            metadata: {
              sources: ["exa", "brave"],
              source_ranks: { exa: 1, brave: 2 },
              rrf_score: 0.032,
            },
          },
        ],
        participating_providers: ["exa", "brave"],
      })
    })

    await waitFor(() => {
      expect(screen.getByPlaceholderText(/Search across all providers/i)).toBeInTheDocument()
    })

    const select = screen.getByRole("combobox") as HTMLSelectElement
    fireEvent.change(select, { target: { value: "all" } })
    expect(select.value).toBe("all")

    await submitQuery("fanout test")

    await waitFor(() => {
      expect(screen.getByText("Fused Multi-Engine Hit")).toBeInTheDocument()
    })
    expect(capturedBody).toMatchObject({
      query: "fanout test",
      fanout: true,
      routing: { mode: "fanout" },
    })
    expect(screen.getByText(/2 engines/)).toBeInTheDocument()
    expect(screen.getByText(/All Providers \(2 fused\)/i)).toBeInTheDocument()
  })
})
