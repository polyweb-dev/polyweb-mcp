import { describe, it, expect, afterEach, vi } from "vitest"
import { persistStore } from "redux-persist"
import { makeStore } from "./store"
import { initialPlaygroundState, setQuery, setResultCount } from "./playgroundSlice"
import { PLAYGROUND_PERSIST_KEY } from "./playgroundPersistence"

afterEach(() => {
  vi.restoreAllMocks()
  window.localStorage.clear()
})

describe("makeStore reducer map", () => {
  it("exposes exactly the persisted playground slice at the top level", () => {
    const store = makeStore()
    expect(Object.keys(store.getState())).toEqual(["playground"])
    expect(store.getState().playground.query).toBe(initialPlaygroundState.query)
    expect(store.getState().playground.resultCount).toBe(initialPlaygroundState.resultCount)
    expect(store.getState().playground.searchStatus).toBe("idle")
  })

  it("builds an isolated instance per call — never a shared singleton", () => {
    const first = makeStore()
    const second = makeStore()
    expect(first).not.toBe(second)
    expect(first.dispatch).not.toBe(second.dispatch)

    first.dispatch(setQuery("first store draft"))
    expect(first.getState().playground.query).toBe("first store draft")
    expect(second.getState().playground.query).toBe(initialPlaygroundState.query)
  })

  it("processes slice actions and leaves state untouched for unknown actions", () => {
    const store = makeStore()
    store.dispatch(setQuery("hello"))
    store.dispatch(setResultCount(25))
    expect(store.getState().playground.query).toBe("hello")
    expect(store.getState().playground.resultCount).toBe(25)

    const before = store.getState().playground
    store.dispatch({ type: "future-slice/action" })
    expect(store.getState().playground).toEqual(before)
  })
})

describe("makeStore persist lifecycle", () => {
  it("processes the real persist lifecycle without serializability warnings", async () => {
    const error = vi.spyOn(console, "error").mockImplementation(() => {})
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {})
    const store = makeStore()

    // Genuine PERSIST/REHYDRATE/FLUSH flow through the persistor: these actions
    // carry non-serializable metadata, and the store exempts exactly the
    // redux-persist lifecycle action types — nothing else.
    const persistor = persistStore(store)
    await persistor.flush()
    store.dispatch(setQuery("post-rehydrate draft"))
    await persistor.flush()
    expect(store.getState().playground.query).toBe("post-rehydrate draft")
    expect(error).not.toHaveBeenCalled()
    expect(warn).not.toHaveBeenCalled()
  })

  it("accepts serializable slice payloads without warnings", () => {
    const error = vi.spyOn(console, "error").mockImplementation(() => {})
    const store = makeStore()
    store.dispatch(setQuery("clean draft"))
    expect(error).not.toHaveBeenCalled()
  })

  it("purges the namespaced key so test runs start from a clean slate", async () => {
    window.localStorage.setItem(PLAYGROUND_PERSIST_KEY, '{"stale":true}')
    const store = makeStore()
    const persistor = persistStore(store)
    await persistor.purge()
    expect(window.localStorage.getItem(PLAYGROUND_PERSIST_KEY)).toBeNull()
  })
})
