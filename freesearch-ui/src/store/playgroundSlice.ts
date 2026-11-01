import { createSlice } from "@reduxjs/toolkit"
import type { PayloadAction } from "@reduxjs/toolkit"
import { clampLimit } from "@/domains/execution"
import type { FetchResponse, SearchResponse } from "@/domains/execution"

export type PlaygroundMode = "search" | "fetch"
export type ExecutionStatus = "idle" | "loading" | "succeeded" | "failed"

/**
 * Every persisted playground field: request drafts, request options, the latest
 * mapped search/fetch payloads, and execution status/errors. Derived values
 * (isSearching, hasSearchContent, ...) are selectors, never stored.
 */
export interface PlaygroundState {
  mode: PlaygroundMode
  query: string
  fetchUrl: string
  selectedProviderId: string
  resultCount: number
  activeSearch: SearchResponse | null
  activeFetch: FetchResponse | null
  searchStatus: ExecutionStatus
  fetchStatus: ExecutionStatus
  searchError: string | null
  fetchError: string | null
}

export const initialPlaygroundState: PlaygroundState = {
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
}

/**
 * Minimal store shape this slice's selectors need. Declared here (rather than
 * imported from store.ts) so the slice never depends on the store module.
 */
export interface PlaygroundStateRoot {
  playground: PlaygroundState
}

const playgroundSlice = createSlice({
  name: "playground",
  initialState: initialPlaygroundState,
  reducers: {
    setMode(state, action: PayloadAction<PlaygroundMode>) {
      state.mode = action.payload
    },
    setQuery(state, action: PayloadAction<string>) {
      state.query = action.payload
    },
    setFetchUrl(state, action: PayloadAction<string>) {
      state.fetchUrl = action.payload
    },
    setSelectedProviderId(state, action: PayloadAction<string>) {
      state.selectedProviderId = action.payload
    },
    // The one input contract shared with the search request: finite, 1..100.
    setResultCount(state, action: PayloadAction<number>) {
      state.resultCount = clampLimit(action.payload)
    },

    // A new search clears its error but keeps the last-good result: a failed
    // retry must not blank the results the user is reading.
    searchStarted(state) {
      state.searchStatus = "loading"
      state.searchError = null
    },
    searchSucceeded(state, action: PayloadAction<SearchResponse>) {
      state.activeSearch = action.payload
      state.searchStatus = "succeeded"
      state.searchError = null
    },
    searchFailed(state, action: PayloadAction<string>) {
      state.searchStatus = "failed"
      state.searchError = action.payload
    },
    searchFinished(state) {
      if (state.searchStatus === "loading") state.searchStatus = "idle"
    },
    clearSearch(state) {
      state.activeSearch = null
      state.searchError = null
      state.searchStatus = "idle"
    },

    // A new fetch drops the previous document up front: the Fetch view must not
    // show the old document's content next to the new run.
    fetchStarted(state) {
      state.fetchStatus = "loading"
      state.fetchError = null
      state.activeFetch = null
    },
    fetchSucceeded(state, action: PayloadAction<FetchResponse>) {
      state.activeFetch = action.payload
      state.fetchStatus = "succeeded"
      state.fetchError = null
    },
    fetchFailed(state, action: PayloadAction<string>) {
      state.fetchStatus = "failed"
      state.fetchError = action.payload
    },
    fetchFinished(state) {
      if (state.fetchStatus === "loading") state.fetchStatus = "idle"
    },
    clearFetch(state) {
      state.activeFetch = null
      state.fetchError = null
      state.fetchStatus = "idle"
    },

    /**
     * The scope closed (unmount or project switch) and aborted its requests:
     * a pending run settles to idle, so the persisted snapshot never holds a
     * request that no longer exists. Results and errors stay.
     */
    executionCancelled(state) {
      if (state.searchStatus === "loading") state.searchStatus = "idle"
      if (state.fetchStatus === "loading") state.fetchStatus = "idle"
    },

    /** Explicit cleanup: never invoked on route navigation. */
    clearActiveResults(state) {
      state.activeSearch = null
      state.activeFetch = null
      state.searchError = null
      state.fetchError = null
      state.searchStatus = "idle"
      state.fetchStatus = "idle"
    },
    resetPlayground() {
      return { ...initialPlaygroundState }
    },
  },
})

export const playgroundReducer = playgroundSlice.reducer

export const {
  setMode,
  setQuery,
  setFetchUrl,
  setSelectedProviderId,
  setResultCount,
  searchStarted,
  searchSucceeded,
  searchFailed,
  searchFinished,
  clearSearch,
  fetchStarted,
  fetchSucceeded,
  fetchFailed,
  fetchFinished,
  clearFetch,
  executionCancelled,
  clearActiveResults,
  resetPlayground,
} = playgroundSlice.actions

export const selectPlayground = (state: PlaygroundStateRoot): PlaygroundState =>
  state.playground

export const selectMode = (state: PlaygroundStateRoot): PlaygroundMode =>
  selectPlayground(state).mode
export const selectQuery = (state: PlaygroundStateRoot): string =>
  selectPlayground(state).query
export const selectFetchUrl = (state: PlaygroundStateRoot): string =>
  selectPlayground(state).fetchUrl
export const selectSelectedProviderId = (state: PlaygroundStateRoot): string =>
  selectPlayground(state).selectedProviderId
export const selectResultCount = (state: PlaygroundStateRoot): number =>
  selectPlayground(state).resultCount

export const selectActiveSearch = (state: PlaygroundStateRoot): SearchResponse | null =>
  selectPlayground(state).activeSearch
export const selectActiveFetch = (state: PlaygroundStateRoot): FetchResponse | null =>
  selectPlayground(state).activeFetch
export const selectSearchStatus = (state: PlaygroundStateRoot): ExecutionStatus =>
  selectPlayground(state).searchStatus
export const selectFetchStatus = (state: PlaygroundStateRoot): ExecutionStatus =>
  selectPlayground(state).fetchStatus
export const selectSearchError = (state: PlaygroundStateRoot): string | null =>
  selectPlayground(state).searchError
export const selectFetchError = (state: PlaygroundStateRoot): string | null =>
  selectPlayground(state).fetchError

export const selectIsSearching = (state: PlaygroundStateRoot): boolean =>
  selectSearchStatus(state) === "loading"
export const selectIsFetching = (state: PlaygroundStateRoot): boolean =>
  selectFetchStatus(state) === "loading"

/** Content means results, a pending run, or an error — as the composer layouts expect. */
export const selectHasSearchContent = (state: PlaygroundStateRoot): boolean =>
  selectActiveSearch(state) !== null ||
  selectIsSearching(state) ||
  selectSearchError(state) !== null
export const selectHasFetchContent = (state: PlaygroundStateRoot): boolean =>
  selectActiveFetch(state) !== null ||
  selectIsFetching(state) ||
  selectFetchError(state) !== null
