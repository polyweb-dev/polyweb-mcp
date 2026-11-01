import React from "react"
import { describe, it, expect, vi } from "vitest"
import { renderHook, act } from "@testing-library/react"
import { Provider } from "react-redux"
import { usePlaygroundController } from "./usePlaygroundController"
import type { PlaygroundScope } from "./usePlaygroundController"
import type { ProjectProvider } from "@/domains/providers"
import { makeStore } from "@/store/store"
import type { AppStore } from "@/store/store"
import { AppStoreProvider } from "@/store/AppStoreProvider"
import { PlaygroundPersistGate } from "@/store/PlaygroundPersistGate"
import { ADMIN_ACCOUNT_ID } from "@/test/authFixtures"
import { PROJECT_ALPHA_ID } from "@/test/accessFixtures"

const mockProviders: ProjectProvider[] = [
  { id: "brave", name: "Brave Search", available: true, enabled: true, effectiveOperations: ["search"] },
  {
    id: "keenable",
    name: "Keenable",
    available: true,
    enabled: true,
    effectiveOperations: ["search", "fetch"],
  },
  { id: "exa", name: "Exa", available: true, enabled: false, effectiveOperations: [] },
]

let currentProviders = [...mockProviders]

vi.mock("@/domains/execution/state/useProjectExecution", () => ({
  useProjectExecution: () => ({ projectId: PROJECT_ALPHA_ID, runSearch: vi.fn(), runFetch: vi.fn() }),
}))

function scopeOf(overrides: Partial<PlaygroundScope> = {}): PlaygroundScope {
  return {
    providers: currentProviders,
    providersLoading: false,
    canSearch: true,
    canFetch: true,
    ...overrides,
  }
}

function freshStore(): AppStore {
  return makeStore(ADMIN_ACCOUNT_ID, PROJECT_ALPHA_ID)
}

/** One isolated Redux store per test — never shared across tests. */
function isolatedWrapper(store: AppStore) {
  return function Wrapper({ children }: { children: React.ReactNode }) {
    return React.createElement(Provider, { store, children })
  }
}

describe("usePlaygroundController project provider eligibility", () => {
  it("offers only the providers whose project effective operations hold the mode", () => {
    currentProviders = [...mockProviders]
    const { result } = renderHook(() => usePlaygroundController(scopeOf()), {
      wrapper: isolatedWrapper(freshStore()),
    })

    const eligibleIds = result.current.eligibleProviders.map((p) => p.id)
    expect(eligibleIds).toContain("brave")
    expect(eligibleIds).toContain("keenable")
    expect(eligibleIds).not.toContain("exa")

    act(() => {
      result.current.switchMode("fetch")
    })
    expect(result.current.eligibleProviders.map((p) => p.id)).toEqual(["keenable"])
  })

  it("offers no provider without a readable project view", () => {
    currentProviders = []
    const { result } = renderHook(() => usePlaygroundController(scopeOf()), {
      wrapper: isolatedWrapper(freshStore()),
    })
    expect(result.current.eligibleProviders).toEqual([])
  })

  it("falls back to the permitted mode and refuses to switch into a denied one", () => {
    currentProviders = [...mockProviders]
    const store = freshStore()
    const { result } = renderHook(() => usePlaygroundController(scopeOf({ canSearch: false })), {
      wrapper: isolatedWrapper(store),
    })
    expect(result.current.mode).toBe("fetch")
    expect(result.current.canSearch).toBe(false)

    act(() => {
      result.current.switchMode("search")
    })
    expect(result.current.mode).toBe("fetch")
  })

  it("resets selectedProviderId to auto when the selected provider loses its binding", () => {
    currentProviders = [
      ...mockProviders.map((p) =>
        p.id === "exa" ? { ...p, effectiveOperations: ["search" as const] } : p
      ),
    ]
    const store = freshStore()
    const { result, rerender } = renderHook(() => usePlaygroundController(scopeOf()), {
      wrapper: isolatedWrapper(store),
    })

    act(() => {
      result.current.setSelectedProviderId("exa")
    })
    expect(result.current.selectedProviderId).toBe("exa")

    currentProviders = [...mockProviders]
    rerender()

    expect(result.current.selectedProviderId).toBe("auto")
    expect(store.getState().playground.selectedProviderId).toBe("auto")
  })
})

describe("usePlaygroundController Redux ownership (PLAN §4.1.4)", () => {
  it("dispatches draft and option setters into the store", () => {
    currentProviders = [...mockProviders]
    const store = freshStore()
    const { result } = renderHook(() => usePlaygroundController(scopeOf()), {
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
    const store = freshStore()
    const wrapper = isolatedWrapper(store)
    const first = renderHook(() => usePlaygroundController(scopeOf()), { wrapper })

    act(() => {
      first.result.current.setQuery("surviving draft")
      first.result.current.setResultCount(12)
      first.result.current.switchMode("fetch")
    })
    expect(first.result.current.query).toBe("surviving draft")
    first.unmount()

    const second = renderHook(() => usePlaygroundController(scopeOf()), { wrapper })
    expect(second.result.current.query).toBe("surviving draft")
    expect(second.result.current.resultCount).toBe(12)
    expect(second.result.current.mode).toBe("fetch")
  })

  it("starts each isolated store from the initial drafts", () => {
    currentProviders = [...mockProviders]
    const { result } = renderHook(() => usePlaygroundController(scopeOf()), {
      wrapper: isolatedWrapper(freshStore()),
    })
    expect(result.current.query).toBe("")
    expect(result.current.mode).toBe("search")
    expect(result.current.resultCount).toBe(6)
  })

  it("maps all to auto when switching to Fetch, preserving current behavior", () => {
    currentProviders = [...mockProviders]
    const { result } = renderHook(() => usePlaygroundController(scopeOf()), {
      wrapper: isolatedWrapper(freshStore()),
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
    const { result } = renderHook(() => usePlaygroundController(scopeOf()), {
      wrapper: ({ children }: { children: React.ReactNode }) =>
        React.createElement(AppStoreProvider, {
          accountId: ADMIN_ACCOUNT_ID,
          projectId: PROJECT_ALPHA_ID,
          children: React.createElement(PlaygroundPersistGate, { children }),
        }),
    })
    // PersistGate rehydrates asynchronously; the controller appears after it.
    await vi.waitFor(() => {
      expect(result.current.query).toBe("")
    })
    expect(result.current.mode).toBe("search")
  })
})
