import React from "react"
import { describe, it, expect, vi } from "vitest"
import { renderHook, act } from "@testing-library/react"
import { Provider } from "react-redux"
import { usePlaygroundController } from "./usePlaygroundController"
import type { ProviderConfig } from "@/domains/providers"
import { makeStore } from "@/store/store"
import type { AppStore } from "@/store/store"
import { AppStoreProvider } from "@/store/AppStoreProvider"
import { ADMIN_ACCOUNT_ID } from "@/test/authFixtures"

const mockProviders: ProviderConfig[] = [
  {
    id: "brave",
    name: "Brave",
    capabilities: ["search"],
    priority: 1,
    globalEnabled: true,
    searchEnabled: true,
    fetchEnabled: false,
    hasKey: true,
  } as ProviderConfig,
  {
    id: "keenable",
    name: "Keenable",
    capabilities: ["search", "fetch", "keyless_tier"],
    priority: 2,
    globalEnabled: true,
    searchEnabled: true,
    fetchEnabled: true,
    hasKey: false,
  } as ProviderConfig,
  {
    id: "exa",
    name: "Exa",
    capabilities: ["search", "fetch"],
    priority: 3,
    globalEnabled: true,
    searchEnabled: true,
    fetchEnabled: true,
    hasKey: false,
  } as ProviderConfig,
]

let currentProviders = [...mockProviders]

vi.mock("@/context/useFreeSearch", () => ({
  useFreeSearch: () => ({
    providers: currentProviders,
    providersLoading: false,
    activeSearch: null,
    activeFetch: null,
    isSearching: false,
    isFetching: false,
    searchError: null,
    fetchError: null,
    runSearch: vi.fn(),
    runFetch: vi.fn(),
  }),
}))

/** One isolated Redux store per test — never shared across tests. */
function isolatedWrapper(store: AppStore) {
  return function Wrapper({ children }: { children: React.ReactNode }) {
    return React.createElement(Provider, { store, children })
  }
}

describe("usePlaygroundController credential eligibility", () => {
  it("filters out providers without a key and without keyless_tier", () => {
    currentProviders = [...mockProviders]
    const { result } = renderHook(() => usePlaygroundController(), {
      wrapper: isolatedWrapper(makeStore(ADMIN_ACCOUNT_ID)),
    })

    const eligibleIds = result.current.eligibleProviders.map((p) => p.id)
    expect(eligibleIds).toContain("brave")
    expect(eligibleIds).toContain("keenable")
    expect(eligibleIds).not.toContain("exa")
  })

  it("resets selectedProviderId to auto when the selected provider loses its key", () => {
    currentProviders = [
      ...mockProviders.map((p) => (p.id === "exa" ? { ...p, hasKey: true } : p)),
    ]
    const store = makeStore(ADMIN_ACCOUNT_ID)
    const { result, rerender } = renderHook(() => usePlaygroundController(), {
      wrapper: isolatedWrapper(store),
    })

    act(() => {
      result.current.setSelectedProviderId("exa")
    })
    expect(result.current.selectedProviderId).toBe("exa")

    currentProviders = [
      ...mockProviders.map((p) => (p.id === "exa" ? { ...p, hasKey: false } : p)),
    ]
    rerender()

    expect(result.current.selectedProviderId).toBe("auto")
    expect(store.getState().playground.selectedProviderId).toBe("auto")
  })
})

describe("usePlaygroundController Redux ownership (PLAN §4.1.4)", () => {
  it("dispatches draft and option setters into the store", () => {
    currentProviders = [...mockProviders]
    const store = makeStore(ADMIN_ACCOUNT_ID)
    const { result } = renderHook(() => usePlaygroundController(), {
      wrapper: isolatedWrapper(store),
    })

    act(() => {
      result.current.setQuery("redux draft")
      result.current.setFetchUrl("https://example.com/redux")
      result.current.setSelectedProviderId("brave")
      result.current.setResultCount(25)
    })

    expect(result.current.query).toBe("redux draft")
    expect(result.current.fetchUrl).toBe("https://example.com/redux")
    expect(result.current.selectedProviderId).toBe("brave")
    expect(result.current.resultCount).toBe(25)
    expect(store.getState().playground.query).toBe("redux draft")
    expect(store.getState().playground.fetchUrl).toBe("https://example.com/redux")
    expect(store.getState().playground.selectedProviderId).toBe("brave")
    expect(store.getState().playground.resultCount).toBe(25)
  })

  it("keeps controller state across unmount/remount with the same store", () => {
    currentProviders = [...mockProviders]
    const store = makeStore(ADMIN_ACCOUNT_ID)
    const wrapper = isolatedWrapper(store)
    const first = renderHook(() => usePlaygroundController(), { wrapper })

    act(() => {
      first.result.current.setQuery("surviving draft")
      first.result.current.setResultCount(12)
      first.result.current.switchMode("fetch")
    })
    expect(first.result.current.query).toBe("surviving draft")
    first.unmount()

    const second = renderHook(() => usePlaygroundController(), { wrapper })
    expect(second.result.current.query).toBe("surviving draft")
    expect(second.result.current.resultCount).toBe(12)
    expect(second.result.current.mode).toBe("fetch")
  })

  it("starts each isolated store from the initial drafts", () => {
    currentProviders = [...mockProviders]
    const { result } = renderHook(() => usePlaygroundController(), {
      wrapper: isolatedWrapper(makeStore(ADMIN_ACCOUNT_ID)),
    })
    expect(result.current.query).toBe("")
    expect(result.current.mode).toBe("search")
    expect(result.current.resultCount).toBe(6)
  })

  it("maps all to auto when switching to Fetch, preserving current behavior", () => {
    currentProviders = [...mockProviders]
    const { result } = renderHook(() => usePlaygroundController(), {
      wrapper: isolatedWrapper(makeStore(ADMIN_ACCOUNT_ID)),
    })

    act(() => {
      result.current.setSelectedProviderId("all")
    })
    expect(result.current.selectedProviderId).toBe("all")

    act(() => {
      result.current.switchMode("fetch")
    })
    expect(result.current.mode).toBe("fetch")
    expect(result.current.selectedProviderId).toBe("auto")
  })

  it("mounts through the real AppStoreProvider without crashing", async () => {
    currentProviders = [...mockProviders]
    const { result } = renderHook(() => usePlaygroundController(), {
      wrapper: ({ children }: { children: React.ReactNode }) =>
        React.createElement(AppStoreProvider, { accountId: ADMIN_ACCOUNT_ID, children }),
    })
    // PersistGate rehydrates asynchronously; the controller appears after it.
    await vi.waitFor(() => {
      expect(result.current.query).toBe("")
    })
    expect(result.current.mode).toBe("search")
  })
})
