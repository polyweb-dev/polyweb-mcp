import type { ReactNode } from "react"
import { afterEach, describe, expect, it, vi } from "vitest"
import { act, renderHook } from "@testing-library/react"
import { Provider } from "react-redux"
import { ProjectExecutionProvider } from "./ProjectExecutionProvider"
import { useProjectExecution } from "./useProjectExecution"
import { makeStore } from "@/store/store"
import type { AppStore } from "@/store/store"
import { deferred, installFetchStub, ok } from "@/test/fetchMock"
import { ADMIN_ACCOUNT_ID } from "@/test/authFixtures"
import { PROJECT_ALPHA_ID } from "@/test/accessFixtures"
import { fetchResponseFixture, searchResponseFixture } from "@/test/backendFixtures"

function wrapperFor(store: AppStore, showToast = vi.fn()) {
  return function Wrapper({ children }: { children: ReactNode }) {
    return (
      <Provider store={store}>
        <ProjectExecutionProvider
          projectId={PROJECT_ALPHA_ID}
          showToast={showToast}
          catalogNameOf={() => undefined}
        >
          {children}
        </ProjectExecutionProvider>
      </Provider>
    )
  }
}

describe("ProjectExecutionProvider", () => {
  afterEach(() => vi.unstubAllGlobals())

  it("exposes the URL project and both commands, and sends project_id", async () => {
    const stub = installFetchStub(() => ok(searchResponseFixture()))
    const store = makeStore(ADMIN_ACCOUNT_ID, PROJECT_ALPHA_ID)
    const { result } = renderHook(() => useProjectExecution(), { wrapper: wrapperFor(store) })

    expect(result.current.projectId).toBe(PROJECT_ALPHA_ID)
    await act(async () => {
      await result.current.runSearch({ query: "q", maxResults: 3, timeoutMs: 1000 })
    })
    expect(stub.requestsTo("/search")[0]?.body).toMatchObject({ project_id: PROJECT_ALPHA_ID })
    expect(store.getState().playground.searchStatus).toBe("succeeded")
  })

  it("aborts both in-flight commands on unmount and dispatches nothing afterwards", async () => {
    const search = deferred<Response>()
    const fetchDoc = deferred<Response>()
    const stub = installFetchStub((req) => (req.url === "/search" ? search.promise : fetchDoc.promise))
    const store = makeStore(ADMIN_ACCOUNT_ID, PROJECT_ALPHA_ID)
    const showToast = vi.fn()
    const { result, unmount } = renderHook(() => useProjectExecution(), {
      wrapper: wrapperFor(store, showToast),
    })

    let pending: Promise<unknown>[] = []
    act(() => {
      pending = [
        result.current.runSearch({ query: "q", maxResults: 3, timeoutMs: 10_000 }),
        result.current.runFetch({ url: "https://example.com", format: "markdown", timeoutMs: 10_000 }),
      ]
    })
    await vi.waitFor(() => expect(stub.requests).toHaveLength(2))
    unmount()
    expect(stub.requests.every((req) => req.signal?.aborted === true)).toBe(true)

    const before = store.getState().playground
    await act(async () => {
      search.resolve(ok(searchResponseFixture()))
      fetchDoc.resolve(ok(fetchResponseFixture()))
      await Promise.all(pending)
    })
    expect(store.getState().playground).toBe(before)
    expect(showToast).not.toHaveBeenCalled()
  })

  it("rejects a consumer outside the provider", () => {
    expect(() => renderHook(() => useProjectExecution())).toThrow(/ProjectExecutionProvider/)
  })
})
