import { describe, it, expect } from "vitest"
import type { FetchResponse, SearchResponse } from "@/domains/execution"
import {
  clearActiveResults,
  clearFetch,
  clearSearch,
  fetchFailed,
  fetchFinished,
  fetchStarted,
  fetchSucceeded,
  initialPlaygroundState,
  playgroundReducer,
  resetPlayground,
  searchFailed,
  searchFinished,
  searchStarted,
  searchSucceeded,
  selectActiveFetch,
  selectActiveSearch,
  selectFetchError,
  selectFetchStatus,
  selectFetchUrl,
  selectHasFetchContent,
  selectHasSearchContent,
  selectIsFetching,
  selectIsSearching,
  selectMode,
  selectPlayground,
  selectQuery,
  selectResultCount,
  selectSearchError,
  selectSearchStatus,
  selectSelectedProviderId,
  setFetchUrl,
  setMode,
  setQuery,
  setResultCount,
  setSelectedProviderId,
} from "./playgroundSlice"
import type { PlaygroundStateRoot } from "./playgroundSlice"

function searchResponse(overrides: Partial<SearchResponse> = {}): SearchResponse {
  return {
    query: "slice query",
    results: [
      {
        id: "brave-0",
        providerId: "brave",
        providerName: "Brave",
        title: "Slice result",
        url: "https://example.com/slice",
        snippet: "A snippet.",
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
        latencyMs: 120,
        status: "success",
        resultsCount: 1,
        costCredits: 1,
      },
    ],
    executionTimeMs: 120,
    costEstimateCredits: 1,
    timestamp: "2026-09-29T00:00:00.000Z",
    ...overrides,
  }
}

function fetchResponse(overrides: Partial<FetchResponse> = {}): FetchResponse {
  return {
    document: {
      url: "https://example.com/doc",
      title: "Slice document",
      content: "# Slice\n\nBody.",
      markdown: "# Slice\n\nBody.",
      providerId: "keenable",
      providerName: "Keenable",
      statusCode: null,
      contentLength: 15,
      executionTimeMs: 80,
    },
    providerId: "keenable",
    fallbackChain: ["keenable"],
    costEstimateCredits: 2,
    executionTimeMs: 80,
    timestamp: "2026-09-29T00:00:00.000Z",
    ...overrides,
  }
}

function rootOf(partial: Partial<ReturnType<typeof playgroundReducer>> = {}): PlaygroundStateRoot {
  return { playground: { ...initialPlaygroundState, ...partial } }
}

describe("playgroundSlice initial state", () => {
  it("starts with empty drafts, auto provider, six results, and idle statuses", () => {
    expect(initialPlaygroundState).toEqual({
      mode: "search",
      query: "",
      fetchUrl: "",
      selectedProviderId: "auto",
      resultCount: 6,
      activeSearch: null,
      activeFetch: null,
      searchStatus: "idle",
      fetchStatus: "idle",
      searchError: null,
      fetchError: null,
    })
  })

  it("returns the initial state for unknown actions", () => {
    expect(playgroundReducer(undefined, { type: "unknown/action" })).toEqual(
      initialPlaygroundState
    )
  })
})

describe("playgroundSlice drafts and options", () => {
  it("stores mode, query, fetch URL, and provider drafts", () => {
    let state = playgroundReducer(initialPlaygroundState, setMode("fetch"))
    expect(state.mode).toBe("fetch")
    state = playgroundReducer(state, setQuery("typed query"))
    expect(state.query).toBe("typed query")
    state = playgroundReducer(state, setFetchUrl("https://example.com/x"))
    expect(state.fetchUrl).toBe("https://example.com/x")
    state = playgroundReducer(state, setSelectedProviderId("brave"))
    expect(state.selectedProviderId).toBe("brave")
  })

  it("keeps in-range result counts and clamps malformed/out-of-range values to 1..100", () => {
    expect(playgroundReducer(initialPlaygroundState, setResultCount(25)).resultCount).toBe(25)
    expect(playgroundReducer(initialPlaygroundState, setResultCount(1)).resultCount).toBe(1)
    expect(playgroundReducer(initialPlaygroundState, setResultCount(100)).resultCount).toBe(100)
    expect(playgroundReducer(initialPlaygroundState, setResultCount(0)).resultCount).toBe(1)
    expect(playgroundReducer(initialPlaygroundState, setResultCount(-4)).resultCount).toBe(1)
    expect(playgroundReducer(initialPlaygroundState, setResultCount(125)).resultCount).toBe(100)
    expect(playgroundReducer(initialPlaygroundState, setResultCount(25.9)).resultCount).toBe(25)
    expect(playgroundReducer(initialPlaygroundState, setResultCount(NaN)).resultCount).toBe(1)
    expect(playgroundReducer(initialPlaygroundState, setResultCount(Infinity)).resultCount).toBe(1)
  })
})

describe("playgroundSlice search lifecycle", () => {
  it("moves idle -> loading and clears the previous error on start", () => {
    const failed = playgroundReducer(initialPlaygroundState, searchFailed("old boom"))
    const started = playgroundReducer(failed, searchStarted())
    expect(started.searchStatus).toBe("loading")
    expect(started.searchError).toBeNull()
  })

  it("stores the mapped response and clears the error on success", () => {
    const response = searchResponse()
    const state = playgroundReducer(
      playgroundReducer(initialPlaygroundState, searchStarted()),
      searchSucceeded(response)
    )
    expect(state.activeSearch).toEqual(response)
    expect(state.searchStatus).toBe("succeeded")
    expect(state.searchError).toBeNull()
  })

  it("keeps the last-good result while recording the error when a later search fails", () => {
    const good = searchResponse()
    const succeeded = playgroundReducer(
      playgroundReducer(initialPlaygroundState, searchStarted()),
      searchSucceeded(good)
    )
    const failed = playgroundReducer(
      playgroundReducer(succeeded, searchStarted()),
      searchFailed("backend went away")
    )
    expect(failed.activeSearch).toEqual(good)
    expect(failed.searchStatus).toBe("failed")
    expect(failed.searchError).toBe("backend went away")
  })

  it("searchFinished only settles a live loading run back to idle", () => {
    const loading = playgroundReducer(initialPlaygroundState, searchStarted())
    expect(playgroundReducer(loading, searchFinished()).searchStatus).toBe("idle")
    const succeeded = playgroundReducer(loading, searchSucceeded(searchResponse()))
    expect(playgroundReducer(succeeded, searchFinished()).searchStatus).toBe("succeeded")
    const failed = playgroundReducer(loading, searchFailed("boom"))
    expect(playgroundReducer(failed, searchFinished()).searchStatus).toBe("failed")
  })

  it("clearSearch drops the result, error, and status without touching drafts", () => {
    const dirty = {
      ...playgroundReducer(
        playgroundReducer(initialPlaygroundState, searchSucceeded(searchResponse())),
        searchFailed("stale")
      ),
      query: "kept draft",
    }
    const cleared = playgroundReducer({ ...initialPlaygroundState, ...dirty }, clearSearch())
    expect(cleared.activeSearch).toBeNull()
    expect(cleared.searchError).toBeNull()
    expect(cleared.searchStatus).toBe("idle")
    expect(cleared.query).toBe("kept draft")
  })
})

describe("playgroundSlice fetch lifecycle", () => {
  it("drops the previous document up front when a new fetch starts", () => {
    const old = fetchResponse()
    const withOld = { ...initialPlaygroundState, activeFetch: old, fetchStatus: "succeeded" as const }
    const started = playgroundReducer(withOld, fetchStarted())
    expect(started.activeFetch).toBeNull()
    expect(started.fetchStatus).toBe("loading")
    expect(started.fetchError).toBeNull()
  })

  it("stores the mapped document and clears the error on success", () => {
    const response = fetchResponse()
    const state = playgroundReducer(
      playgroundReducer(initialPlaygroundState, fetchStarted()),
      fetchSucceeded(response)
    )
    expect(state.activeFetch).toEqual(response)
    expect(state.fetchStatus).toBe("succeeded")
    expect(state.fetchError).toBeNull()
  })

  it("records the fetch error while leaving the dropped document empty", () => {
    const state = playgroundReducer(
      playgroundReducer(initialPlaygroundState, fetchStarted()),
      fetchFailed("fetch exploded")
    )
    expect(state.activeFetch).toBeNull()
    expect(state.fetchStatus).toBe("failed")
    expect(state.fetchError).toBe("fetch exploded")
  })

  it("fetchFinished only settles a live loading run back to idle", () => {
    const loading = playgroundReducer(initialPlaygroundState, fetchStarted())
    expect(playgroundReducer(loading, fetchFinished()).fetchStatus).toBe("idle")
    const succeeded = playgroundReducer(loading, fetchSucceeded(fetchResponse()))
    expect(playgroundReducer(succeeded, fetchFinished()).fetchStatus).toBe("succeeded")
  })

  it("clearFetch drops the document, error, and status without touching the search side", () => {
    const search = searchResponse()
    const dirty = {
      ...initialPlaygroundState,
      activeSearch: search,
      searchStatus: "succeeded" as const,
      activeFetch: fetchResponse(),
      fetchStatus: "failed" as const,
      fetchError: "stale fetch",
    }
    const cleared = playgroundReducer(dirty, clearFetch())
    expect(cleared.activeFetch).toBeNull()
    expect(cleared.fetchError).toBeNull()
    expect(cleared.fetchStatus).toBe("idle")
    expect(cleared.activeSearch).toEqual(search)
    expect(cleared.searchStatus).toBe("succeeded")
  })
})

describe("playgroundSlice explicit cleanup", () => {
  it("clearActiveResults clears both results/errors/statuses while keeping drafts and options", () => {
    const dirty = {
      ...initialPlaygroundState,
      mode: "fetch" as const,
      query: "kept",
      fetchUrl: "https://example.com/kept",
      selectedProviderId: "brave",
      resultCount: 25,
      activeSearch: searchResponse(),
      activeFetch: fetchResponse(),
      searchStatus: "failed" as const,
      fetchStatus: "failed" as const,
      searchError: "search boom",
      fetchError: "fetch boom",
    }
    const cleared = playgroundReducer(dirty, clearActiveResults())
    expect(cleared).toEqual({
      ...dirty,
      activeSearch: null,
      activeFetch: null,
      searchStatus: "idle",
      fetchStatus: "idle",
      searchError: null,
      fetchError: null,
    })
  })

  it("resetPlayground restores every field to the initial state", () => {
    const dirty = {
      ...initialPlaygroundState,
      mode: "fetch" as const,
      query: "dirty",
      activeSearch: searchResponse(),
      searchStatus: "failed" as const,
      searchError: "boom",
    }
    expect(playgroundReducer(dirty, resetPlayground())).toEqual(initialPlaygroundState)
  })
})

describe("playgroundSlice selectors", () => {
  it("selects the slice and every stored field", () => {
    const search = searchResponse()
    const fetch = fetchResponse()
    const root = rootOf({
      mode: "fetch",
      query: "q",
      fetchUrl: "https://example.com/u",
      selectedProviderId: "brave",
      resultCount: 12,
      activeSearch: search,
      activeFetch: fetch,
      searchStatus: "succeeded",
      fetchStatus: "failed",
      searchError: null,
      fetchError: "fetch boom",
    })
    expect(selectPlayground(root)).toBe(root.playground)
    expect(selectMode(root)).toBe("fetch")
    expect(selectQuery(root)).toBe("q")
    expect(selectFetchUrl(root)).toBe("https://example.com/u")
    expect(selectSelectedProviderId(root)).toBe("brave")
    expect(selectResultCount(root)).toBe(12)
    expect(selectActiveSearch(root)).toBe(search)
    expect(selectActiveFetch(root)).toBe(fetch)
    expect(selectSearchStatus(root)).toBe("succeeded")
    expect(selectFetchStatus(root)).toBe("failed")
    expect(selectSearchError(root)).toBeNull()
    expect(selectFetchError(root)).toBe("fetch boom")
  })

  it("derives loading flags from status only", () => {
    expect(selectIsSearching(rootOf({ searchStatus: "loading" }))).toBe(true)
    expect(selectIsSearching(rootOf({ searchStatus: "succeeded" }))).toBe(false)
    expect(selectIsFetching(rootOf({ fetchStatus: "loading" }))).toBe(true)
    expect(selectIsFetching(rootOf({ fetchStatus: "idle" }))).toBe(false)
  })

  it("treats results, pending runs, and errors as content", () => {
    expect(selectHasSearchContent(rootOf())).toBe(false)
    expect(selectHasSearchContent(rootOf({ activeSearch: searchResponse() }))).toBe(true)
    expect(selectHasSearchContent(rootOf({ searchStatus: "loading" }))).toBe(true)
    expect(selectHasSearchContent(rootOf({ searchError: "boom" }))).toBe(true)
    expect(selectHasFetchContent(rootOf())).toBe(false)
    expect(selectHasFetchContent(rootOf({ activeFetch: fetchResponse() }))).toBe(true)
    expect(selectHasFetchContent(rootOf({ fetchStatus: "loading" }))).toBe(true)
    expect(selectHasFetchContent(rootOf({ fetchError: "boom" }))).toBe(true)
  })
})

describe("playgroundSlice serializability", () => {
  it("keeps every reducer output JSON-serializable", () => {
    const states = [
      playgroundReducer(initialPlaygroundState, setMode("fetch")),
      playgroundReducer(initialPlaygroundState, setQuery("q")),
      playgroundReducer(initialPlaygroundState, setResultCount(25)),
      playgroundReducer(initialPlaygroundState, searchStarted()),
      playgroundReducer(initialPlaygroundState, searchSucceeded(searchResponse())),
      playgroundReducer(initialPlaygroundState, searchFailed("boom")),
      playgroundReducer(initialPlaygroundState, fetchStarted()),
      playgroundReducer(initialPlaygroundState, fetchSucceeded(fetchResponse())),
      playgroundReducer(initialPlaygroundState, fetchFailed("boom")),
      playgroundReducer(initialPlaygroundState, clearActiveResults()),
      playgroundReducer(initialPlaygroundState, resetPlayground()),
    ]
    for (const state of states) {
      expect(JSON.parse(JSON.stringify(state))).toEqual(state)
    }
  })
})
