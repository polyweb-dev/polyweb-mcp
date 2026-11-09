import { describe, it, expect, afterEach, vi } from "vitest"
import { persistStore } from "redux-persist"
import { makeStore } from "./store"
import { initialPlaygroundState, setQuery, setResultCount } from "./playgroundSlice"
import { playgroundPersistKey } from "./playgroundPersistence"
import { ADMIN_ACCOUNT_ID, AGENT_ACCOUNT_ID } from "@/test/authFixtures"
import { PROJECT_ALPHA_ID, PROJECT_BETA_ID } from "@/test/accessFixtures"

afterEach(() => {
  vi.restoreAllMocks()
  window.localStorage.clear()
})

describe("makeStore reducer map", () => {
  it("exposes exactly the persisted playground slice at the top level", () => {
    const store = makeStore(ADMIN_ACCOUNT_ID, PROJECT_ALPHA_ID)
    expect(Object.keys(store.getState())).toEqual(["playground"])
    expect(store.getState().playground.query).toBe(initialPlaygroundState.query)
    expect(store.getState().playground.resultCount).toBe(initialPlaygroundState.resultCount)
    expect(store.getState().playground.searchStatus).toBe("idle")
  })

  it("builds an isolated instance per call — never a shared singleton", () => {
    const first = makeStore(ADMIN_ACCOUNT_ID, PROJECT_ALPHA_ID)
    const second = makeStore(ADMIN_ACCOUNT_ID, PROJECT_ALPHA_ID)
    expect(first).not.toBe(second)
    expect(first.dispatch).not.toBe(second.dispatch)

    first.dispatch(setQuery("first store draft"))
    expect(first.getState().playground.query).toBe("first store draft")
    expect(second.getState().playground.query).toBe(initialPlaygroundState.query)
  })

  it("processes slice actions and leaves state untouched for unknown actions", () => {
    const store = makeStore(ADMIN_ACCOUNT_ID, PROJECT_ALPHA_ID)
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
    const store = makeStore(ADMIN_ACCOUNT_ID, PROJECT_ALPHA_ID)

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
    const store = makeStore(ADMIN_ACCOUNT_ID, PROJECT_ALPHA_ID)
    store.dispatch(setQuery("clean draft"))
    expect(error).not.toHaveBeenCalled()
  })

  it("purges the namespaced key so test runs start from a clean slate", async () => {
    const accountKey = playgroundPersistKey(ADMIN_ACCOUNT_ID, PROJECT_ALPHA_ID)
    window.localStorage.setItem(accountKey, '{"stale":true}')
    const store = makeStore(ADMIN_ACCOUNT_ID, PROJECT_ALPHA_ID)
    const persistor = persistStore(store)
    await persistor.purge()
    expect(window.localStorage.getItem(accountKey)).toBeNull()
  })

  it("keeps isolated playground state for different account IDs with different persist keys", async () => {
    const adminKey = playgroundPersistKey(ADMIN_ACCOUNT_ID, PROJECT_ALPHA_ID)
    const agentKey = playgroundPersistKey(AGENT_ACCOUNT_ID, PROJECT_ALPHA_ID)
    expect(adminKey).not.toBe(agentKey)

    const adminStore = makeStore(ADMIN_ACCOUNT_ID, PROJECT_ALPHA_ID)
    const agentStore = makeStore(AGENT_ACCOUNT_ID, PROJECT_ALPHA_ID)

    adminStore.dispatch(setQuery("admin draft"))
    expect(adminStore.getState().playground.query).toBe("admin draft")
    expect(agentStore.getState().playground.query).toBe(initialPlaygroundState.query)

    agentStore.dispatch(setQuery("agent draft"))
    expect(agentStore.getState().playground.query).toBe("agent draft")
    expect(adminStore.getState().playground.query).toBe("admin draft")
  })

  it("keeps isolated playground state for two projects of one account", () => {
    const alphaKey = playgroundPersistKey(ADMIN_ACCOUNT_ID, PROJECT_ALPHA_ID)
    const betaKey = playgroundPersistKey(ADMIN_ACCOUNT_ID, PROJECT_BETA_ID)
    expect(alphaKey).not.toBe(betaKey)

    const alphaStore = makeStore(ADMIN_ACCOUNT_ID, PROJECT_ALPHA_ID)
    const betaStore = makeStore(ADMIN_ACCOUNT_ID, PROJECT_BETA_ID)
    alphaStore.dispatch(setQuery("alpha draft"))
    expect(betaStore.getState().playground.query).toBe(initialPlaygroundState.query)
  })
})
