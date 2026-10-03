import React from "react"
import { describe, it, expect, afterEach, vi } from "vitest"
import { render, screen, fireEvent, waitFor } from "@testing-library/react"
import { FreeSearchProvider } from "@/context/FreeSearchContext"
import { PlaygroundPage } from "./PlaygroundPage"
import { installFetchStub, ok, err } from "@/test/fetchMock"
import type { FetchStub } from "@/test/fetchMock"
import {
  allProvidersFixture,
  routingConfigFixture,
  dashboardFixture,
  searchResponseFixture,
  fetchResponseFixture,
} from "@/test/backendFixtures"
import { PLAYGROUND_PERSIST_KEY } from "@/store/playgroundPersistence"
import { initialPlaygroundState } from "@/store/playgroundSlice"
import type { SearchResponse } from "@/domains/execution"

/**
 * PLAN §4.2.6: component rehydration/remount/no-refetch coverage.
 *
 * - Seeded storage rehydrates drafts, options, mapped results, and error
 *   banners through FreeSearchProvider with zero /search|/fetch traffic.
 * - Fixture-backed runs survive a page remount under the same root store.
 * - A recreated root provider reloads completed state from localStorage
 *   through PersistGate without issuing /search|/fetch.
 * - Assertions stay on user-visible roles/placeholders/text; Redux internals
 *   are never inspected from component assertions.
 */

function persistedSearch(): SearchResponse {
  return {
    query: "seeded query",
    results: [
      {
        id: "brave-0",
        providerId: "brave",
        providerName: "Brave",
        title: "Seeded result title",
        url: "https://example.com/seeded",
        snippet: "Seeded snippet.",
        relevanceScore: 0.9,
      },
    ],
    totalResults: 1,
    selectedProviderId: "brave",
    fallbackChain: ["brave"],
    waterfall: [
      {
        providerId: "brave",
        providerName: "Brave",
        latencyMs: 187,
        status: "success",
        resultsCount: 1,
        costCredits: 1,
      },
    ],
    executionTimeMs: 187,
    costEstimateCredits: 1,
    timestamp: "2026-09-06T10:02:00.000Z",
  }
}

/** Mirrors the persistoid envelope: every field value serialized on its own. */
function seedStorage(state: Record<string, unknown>): void {
  const encoded: Record<string, string> = {}
  for (const [field, value] of Object.entries({
    ...initialPlaygroundState,
    ...state,
    _persist: { version: 1, rehydrated: false },
  })) {
    encoded[field] = JSON.stringify(value)
  }
  window.localStorage.setItem(PLAYGROUND_PERSIST_KEY, JSON.stringify(encoded))
}

function stubBackend(
  searchHandler?: (req: { url: string }) => Response,
  fetchHandler?: (req: { url: string }) => Response
): FetchStub {
  return installFetchStub((req) => {
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
}

function refuseNetwork(): FetchStub {
  return stubBackend(
    () => err(503, { detail: "refetch forbidden" }),
    () => err(503, { detail: "refetch forbidden" })
  )
}

async function submitSearch(query: string): Promise<void> {
  const input = await screen.findByPlaceholderText(/Search across all providers/i)
  fireEvent.change(input, { target: { value: query } })
  fireEvent.submit(input.closest("form")!)
}

async function openFetchTab(): Promise<void> {
  fireEvent.click(screen.getByRole("tab", { name: "Fetch", exact: true }))
  await screen.findByPlaceholderText(/Enter a URL to fetch/i)
}

async function submitFetch(url: string): Promise<void> {
  const input = await screen.findByPlaceholderText(/Enter a URL to fetch/i)
  fireEvent.change(input, { target: { value: url } })
  fireEvent.submit(input.closest("form")!)
}

describe("PlaygroundPage persistence", () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it("rehydrates drafts, options, results, and errors from storage without network execution", async () => {
    seedStorage({
      mode: "search",
      query: "seeded query",
      fetchUrl: "https://example.com/seeded-doc",
      selectedProviderId: "brave",
      resultCount: 25,
      activeSearch: persistedSearch(),
      activeFetch: null,
      searchStatus: "succeeded",
      fetchStatus: "failed",
      searchError: null,
      fetchError: "seeded fetch boom",
    })
    const stub = refuseNetwork()
    render(
      <FreeSearchProvider>
        <PlaygroundPage />
      </FreeSearchProvider>
    )

    // Search tab: rehydrated draft, options, and mapped result.
    expect(await screen.findByPlaceholderText(/Search across all providers/i)).toHaveValue(
      "seeded query"
    )
    expect(screen.getByRole("spinbutton", { name: "Number of results" })).toHaveValue(25)
    // The provider catalog arrives asynchronously; the persisted pin only
    // displays once its option exists.
    await screen.findByRole("option", { name: "Brave Search" })
    expect(screen.getByRole("combobox")).toHaveValue("brave")
    expect(await screen.findByText("Seeded result title")).toBeInTheDocument()

    // Fetch tab: rehydrated URL draft and the persisted error banner.
    await openFetchTab()
    expect(screen.getByPlaceholderText(/Enter a URL to fetch/i)).toHaveValue(
      "https://example.com/seeded-doc"
    )
    expect(await screen.findByText("seeded fetch boom")).toBeInTheDocument()

    // Rehydration never executed a request.
    expect(stub.requestsTo("/search")).toHaveLength(0)
    expect(stub.requestsTo("/fetch")).toHaveLength(0)
  })

  it("keeps executed search and fetch state across a page remount with the same root store", async () => {
    const stub = stubBackend()
    const { rerender } = render(
      <FreeSearchProvider>
        <PlaygroundPage />
      </FreeSearchProvider>
    )

    await submitSearch("remount probe")
    await screen.findByText("Live backend result one")
    await openFetchTab()
    await submitFetch("https://example.com/remount-doc")
    await screen.findByText("Parsed Markdown Document")

    // Remount the page while the root provider (and its store) stays mounted.
    rerender(
      <FreeSearchProvider>
        <span data-testid="interstitial" />
      </FreeSearchProvider>
    )
    expect(await screen.findByTestId("interstitial")).toBeInTheDocument()
    rerender(
      <FreeSearchProvider>
        <PlaygroundPage />
      </FreeSearchProvider>
    )

    // Fetch tab state survived (mode persisted as fetch).
    expect(await screen.findByPlaceholderText(/Enter a URL to fetch/i)).toHaveValue(
      "https://example.com/remount-doc"
    )
    expect(await screen.findByText("Parsed Markdown Document")).toBeInTheDocument()

    // Search tab state survived too.
    fireEvent.click(screen.getByRole("tab", { name: "Search", exact: true }))
    expect(await screen.findByPlaceholderText(/Search across all providers/i)).toHaveValue(
      "remount probe"
    )
    expect(await screen.findByText("Live backend result one")).toBeInTheDocument()

    // One execution each — the remount issued no new request.
    expect(stub.requestsTo("/search")).toHaveLength(1)
    expect(stub.requestsTo("/fetch")).toHaveLength(1)
  })

  it("reloads executed state in a recreated provider from localStorage without refetching", async () => {
    const liveStub = stubBackend()
    const first = render(
      <FreeSearchProvider>
        <PlaygroundPage />
      </FreeSearchProvider>
    )

    await submitSearch("reload probe")
    await screen.findByText("Live backend result one")

    // Wait for the bounded storage adapter to flush the completed run to disk.
    await waitFor(
      () => {
        expect(window.localStorage.getItem(PLAYGROUND_PERSIST_KEY) ?? "").toContain(
          "reload probe"
        )
      },
      { timeout: 5000 }
    )
    first.unmount()

    // Fresh root provider (a browser reload): completed state must appear
    // through PersistGate with no /search or /fetch request.
    const stub = refuseNetwork()
    render(
      <FreeSearchProvider>
        <PlaygroundPage />
      </FreeSearchProvider>
    )
    expect(await screen.findByPlaceholderText(/Search across all providers/i)).toHaveValue(
      "reload probe"
    )
    expect(await screen.findByText("Live backend result one")).toBeInTheDocument()
    expect(stub.requestsTo("/search")).toHaveLength(0)
    expect(stub.requestsTo("/fetch")).toHaveLength(0)
    expect(liveStub.requestsTo("/search")).toHaveLength(1)
  })
})
