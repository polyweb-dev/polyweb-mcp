import React from "react"
import { describe, expect, it, vi, beforeEach } from "vitest"
import { act, renderHook } from "@testing-library/react"
import { Provider } from "react-redux"
import { searchBody, useSearchRunner } from "./useSearchRunner"
import { apiService } from "@/services/api/freesearchApi"
import { ApiError } from "@/shared/api/http"
import { makeStore, type AppStore } from "@/store/store"
import { ADMIN_ACCOUNT_ID } from "@/test/authFixtures"
import { PROJECT_ALPHA_ID } from "@/test/accessFixtures"
import { searchResponseFixture } from "@/test/backendFixtures"

vi.mock("@/services/api/freesearchApi", () => ({
  apiService: { search: vi.fn() },
}))

/**
 * Project search runner: every body carries the URL project, the server owns
 * provider fallback (no client retry, a Tavily 402 included), and an unmount
 * aborts the request so a late result never lands.
 */

function wrapper(store: AppStore) {
  return function Wrapper({ children }: { children: React.ReactNode }) {
    return React.createElement(Provider, { store, children })
  }
}

function deps() {
  return {
    projectId: PROJECT_ALPHA_ID,
    showToast: vi.fn(),
    catalogNameOf: (id: string) => id,
  }
}

function freshStore(): AppStore {
  return makeStore(ADMIN_ACCOUNT_ID, PROJECT_ALPHA_ID)
}

const searchMock = vi.mocked(apiService.search)

describe("useSearchRunner Tavily 402", () => {
  beforeEach(() => {
    searchMock.mockReset()
  })

  it("fails fast on a Tavily 402 with the backend message and no retry", async () => {
    searchMock.mockRejectedValueOnce(
      new ApiError(402, "Tavily is out of Credits. Wait until reset or upgrade.", {
        detail: "Tavily is out of Credits. Wait until reset or upgrade.",
        provider: "tavily",
      }),
    )
    const args = deps()
    const store = freshStore()
    const { result } = renderHook(() => useSearchRunner(args), { wrapper: wrapper(store) })

    let outcome: unknown
    await act(async () => {
      outcome = await result.current({
        query: "hello",
        providerIds: ["tavily"],
        maxResults: 5,
        timeoutMs: 1000,
      })
    })

    expect(outcome).toBeNull()
    expect(searchMock).toHaveBeenCalledTimes(1)
    expect(args.showToast).toHaveBeenCalledTimes(1)
    expect(store.getState().playground.searchError).toContain("Tavily is out of Credits")
  })

  it("never retries another provider on the client after a failure", async () => {
    searchMock.mockRejectedValueOnce(new ApiError(500, "brave failed", { provider: "brave" }))
    searchMock.mockResolvedValueOnce(searchResponseFixture({ provider: "exa" }) as never)
    const store = freshStore()
    const { result } = renderHook(() => useSearchRunner(deps()), { wrapper: wrapper(store) })

    let outcome: unknown
    await act(async () => {
      outcome = await result.current({
        query: "hello",
        providerIds: ["brave"],
        maxResults: 5,
        timeoutMs: 1000,
      })
    })

    expect(outcome).toBeNull()
    expect(searchMock).toHaveBeenCalledTimes(1)
    expect(store.getState().playground.searchStatus).toBe("failed")
  })
})

describe("useSearchRunner project request", () => {
  beforeEach(() => {
    searchMock.mockReset()
  })

  it("sends the URL project with server-side fallback for every routing mode", () => {
    const base = { query: " hello ", maxResults: 5, timeoutMs: 1000 }
    expect(searchBody(PROJECT_ALPHA_ID, base)).toEqual({
      project_id: PROJECT_ALPHA_ID,
      query: "hello",
      limit: 5,
      language: null,
      country_code: null,
      domains: [],
      routing: { mode: "auto", providers: [], allow_fallback: true },
    })
    expect(searchBody(PROJECT_ALPHA_ID, { ...base, providerIds: ["youcom"] }).routing).toEqual({
      mode: "require",
      providers: ["you"],
      allow_fallback: true,
    })
    expect(
      searchBody(PROJECT_ALPHA_ID, { ...base, providerIds: ["brave", "exa"], fanout: true }),
    ).toMatchObject({
      routing: { mode: "fanout", providers: ["brave", "exa"], allow_fallback: true },
      fanout: true,
    })
  })

  it("stores the mapped response of a successful search", async () => {
    searchMock.mockResolvedValueOnce(searchResponseFixture({ provider: "exa" }) as never)
    const store = freshStore()
    const { result } = renderHook(() => useSearchRunner(deps()), { wrapper: wrapper(store) })

    await act(async () => {
      await result.current({ query: "hello", maxResults: 5, timeoutMs: 1000 })
    })

    expect(searchMock.mock.calls[0]?.[0]).toMatchObject({ project_id: PROJECT_ALPHA_ID })
    expect(store.getState().playground.searchStatus).toBe("succeeded")
    expect(store.getState().playground.activeSearch?.selectedProviderId).toBe("exa")
  })

  it("aborts the in-flight search on unmount and never dispatches its late result", async () => {
    let resolveSearch: (value: unknown) => void = () => {}
    let signal: AbortSignal | undefined
    searchMock.mockImplementationOnce((_body, requestSignal) => {
      signal = requestSignal
      return new Promise((resolve) => {
        resolveSearch = resolve
      }) as never
    })
    const store = freshStore()
    const args = deps()
    const { result, unmount } = renderHook(() => useSearchRunner(args), {
      wrapper: wrapper(store),
    })

    let pending: Promise<unknown> = Promise.resolve()
    act(() => {
      pending = result.current({ query: "hello", maxResults: 5, timeoutMs: 10_000 })
    })
    expect(store.getState().playground.searchStatus).toBe("loading")

    unmount()
    expect(signal?.aborted).toBe(true)

    const before = store.getState().playground
    await act(async () => {
      resolveSearch(searchResponseFixture({ provider: "exa" }))
      await pending
    })

    expect(store.getState().playground).toBe(before)
    expect(store.getState().playground.activeSearch).toBeNull()
    expect(args.showToast).not.toHaveBeenCalled()
  })

  it("keeps the UI id of a pinned provider and the last-good result after a failure", async () => {
    searchMock.mockResolvedValueOnce(searchResponseFixture({ provider: "you" }) as never)
    searchMock.mockRejectedValueOnce(new ApiError(503, "no provider is configured", null))
    const store = freshStore()
    const { result } = renderHook(() => useSearchRunner(deps()), { wrapper: wrapper(store) })

    await act(async () => {
      await result.current({ query: "first", providerIds: ["youcom"], maxResults: 500, timeoutMs: 1000 })
    })
    expect(searchMock.mock.calls[0]?.[0]).toMatchObject({
      limit: 100,
      routing: { mode: "require", providers: ["you"], allow_fallback: true },
    })
    expect(store.getState().playground.activeSearch?.selectedProviderId).toBe("youcom")

    await act(async () => {
      await result.current({ query: "second", maxResults: 6, timeoutMs: 1000 })
    })
    expect(store.getState().playground.activeSearch?.selectedProviderId).toBe("youcom")
    expect(store.getState().playground.searchError).toContain("no provider is configured")
    expect(store.getState().playground.searchStatus).toBe("failed")
  })

  it("reports a timeout as a friendly error instead of a silent cancel", async () => {
    searchMock.mockImplementationOnce(
      (_body, signal) =>
        new Promise((_resolve, reject) => {
          signal?.addEventListener("abort", () => {
            reject(new DOMException("The operation was aborted due to timeout", "TimeoutError"))
          })
        }) as never,
    )
    const store = freshStore()
    const { result } = renderHook(() => useSearchRunner(deps()), { wrapper: wrapper(store) })

    await act(async () => {
      await result.current({ query: "hung query", maxResults: 6, timeoutMs: 20 })
    })

    expect(store.getState().playground.searchStatus).toBe("failed")
    expect(store.getState().playground.searchError).toMatch(/timed out|timeout/i)
    expect(store.getState().playground.searchError).not.toMatch(/was aborted|AbortError|DOMException/i)
  })
})
