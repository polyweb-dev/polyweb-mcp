import React from "react"
import { describe, expect, it, vi, beforeEach } from "vitest"
import { act, renderHook } from "@testing-library/react"
import { Provider } from "react-redux"
import { fetchBody, useFetchRunner } from "./useFetchRunner"
import { apiService } from "@/services/api/polywebApi"
import { ApiError } from "@/shared/api/http"
import { makeStore, type AppStore } from "@/store/store"
import { ADMIN_ACCOUNT_ID } from "@/test/authFixtures"
import { PROJECT_ALPHA_ID } from "@/test/accessFixtures"
import { fetchResponseFixture } from "@/test/backendFixtures"

vi.mock("@/services/api/polywebApi", () => ({
  apiService: { fetchDoc: vi.fn() },
}))

function wrapper(store: AppStore) {
  return function Wrapper({ children }: { children: React.ReactNode }) {
    return React.createElement(Provider, { store, children })
  }
}

const fetchMock = vi.mocked(apiService.fetchDoc)

describe("useFetchRunner project request", () => {
  beforeEach(() => {
    fetchMock.mockReset()
  })

  it("sends the URL project with server-side fallback", () => {
    const request = { url: " https://example.com ", format: "markdown" as const, timeoutMs: 1000 }
    expect(fetchBody(PROJECT_ALPHA_ID, request)).toEqual({
      project_id: PROJECT_ALPHA_ID,
      url: "https://example.com",
      max_chars: null,
      routing: { mode: "auto", providers: [], allow_fallback: true },
    })
    expect(fetchBody(PROJECT_ALPHA_ID, { ...request, providerId: "youcom" }).routing).toEqual({
      mode: "require",
      providers: ["you"],
      allow_fallback: true,
    })
  })

  it("publishes fetch loading, then the mapped document, through the store", async () => {
    let resolveFetch: (value: unknown) => void = () => {}
    fetchMock.mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          resolveFetch = resolve
        }) as never
    )
    const store = makeStore(ADMIN_ACCOUNT_ID, PROJECT_ALPHA_ID)
    const { result } = renderHook(
      () => useFetchRunner({ projectId: PROJECT_ALPHA_ID, showToast: vi.fn() }),
      { wrapper: wrapper(store) }
    )

    let pending: Promise<unknown> = Promise.resolve()
    act(() => {
      pending = result.current({ url: "https://example.com", format: "markdown", timeoutMs: 1000 })
    })
    expect(store.getState().playground.fetchStatus).toBe("loading")

    await act(async () => {
      resolveFetch(fetchResponseFixture())
      await pending
    })
    expect(store.getState().playground.fetchStatus).toBe("succeeded")
    expect(store.getState().playground.activeFetch?.document.url).toBeTruthy()
  })

  it("shows the backend message once on failure", async () => {
    fetchMock.mockRejectedValueOnce(new ApiError(403, "Missing fetch.execute", null))
    const store = makeStore(ADMIN_ACCOUNT_ID, PROJECT_ALPHA_ID)
    const showToast = vi.fn()
    const { result } = renderHook(() => useFetchRunner({ projectId: PROJECT_ALPHA_ID, showToast }), {
      wrapper: wrapper(store),
    })

    await act(async () => {
      await result.current({ url: "https://example.com", format: "markdown", timeoutMs: 1000 })
    })

    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(showToast).toHaveBeenCalledWith("Missing fetch.execute", "error")
    expect(store.getState().playground.fetchError).toBe("Missing fetch.execute")
  })

  it("aborts the in-flight fetch on unmount and never dispatches its late result", async () => {
    let resolveFetch: (value: unknown) => void = () => {}
    let signal: AbortSignal | undefined
    fetchMock.mockImplementationOnce((_body, requestSignal) => {
      signal = requestSignal
      return new Promise((resolve) => {
        resolveFetch = resolve
      }) as never
    })
    const store = makeStore(ADMIN_ACCOUNT_ID, PROJECT_ALPHA_ID)
    const { result, unmount } = renderHook(
      () => useFetchRunner({ projectId: PROJECT_ALPHA_ID, showToast: vi.fn() }),
      { wrapper: wrapper(store) }
    )

    let pending: Promise<unknown> = Promise.resolve()
    act(() => {
      pending = result.current({ url: "https://example.com", format: "markdown", timeoutMs: 10_000 })
    })
    unmount()
    expect(signal?.aborted).toBe(true)

    const before = store.getState().playground
    await act(async () => {
      resolveFetch(fetchResponseFixture())
      await pending
    })
    expect(store.getState().playground).toBe(before)
    expect(store.getState().playground.activeFetch).toBeNull()
  })
})
