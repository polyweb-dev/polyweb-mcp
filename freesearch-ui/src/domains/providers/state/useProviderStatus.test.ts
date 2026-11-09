import { describe, it, expect, vi, beforeEach } from "vitest"
import { renderHook, act } from "@testing-library/react"
import { useProviderStatus } from "./useProviderStatus"
import { apiService } from "@/services/api/freesearchApi"
import { allProvidersFixture, providerStatus } from "@/test/backendFixtures"
import type { ProviderConfig } from "@/domains/providers/model/types"

function stateHarness(initial: ProviderConfig[] = []) {
  let providersState = initial
  const setProviders = vi.fn((update: React.SetStateAction<ProviderConfig[]>) => {
    providersState =
      typeof update === "function"
        ? (update as (prev: ProviderConfig[]) => ProviderConfig[])(providersState)
        : update
  })
  const setProvidersLoading = vi.fn()
  const setProvidersError = vi.fn()
  const showToast = vi.fn()
  const getState = () => providersState
  return { setProviders, setProvidersLoading, setProvidersError, showToast, getState }
}

describe("useProviderStatus database authority", () => {
  beforeEach(() => {
    localStorage.clear()
    vi.restoreAllMocks()
  })

  it("refreshes provider state from backend masks", async () => {
    const harness = stateHarness()
    vi.spyOn(apiService, "listProviders").mockResolvedValue(allProvidersFixture() as never)

    const { result } = renderHook(() =>
      useProviderStatus({
        setProviders: harness.setProviders,
        setProvidersLoading: harness.setProvidersLoading,
        setProvidersError: harness.setProvidersError,
        showToast: harness.showToast,
        canReadControls: true,
      }),
    )

    await act(async () => {
      await result.current.refreshProviders()
    })

    const providers = harness.getState()
    expect(providers).toHaveLength(8)
    const brave = providers.find((p) => p.id === "brave")!
    expect(brave.enableMask).toBe(7)
    expect(brave.supportMask).toBe(3)
    expect(brave.globalEnabled).toBe(true)
    expect(brave.searchEnabled).toBe(true)
    // Raw admin fetch choice stays ON even though Brave cannot fetch.
    expect(brave.fetchEnabled).toBe(true)
    const exa = providers.find((p) => p.id === "exa")!
    expect(exa.enableMask).toBe(7)
    expect(exa.supportMask).toBe(7)
  })

  it("ignores stale localStorage operation toggles on refresh", async () => {
    localStorage.setItem(
      "provider-operation-toggles",
      JSON.stringify({ exa: { searchEnabled: false } }),
    )
    localStorage.setItem("OPERATION_TOGGLES_STORAGE_KEY", "invalid-json{{")

    const harness = stateHarness()
    vi.spyOn(apiService, "listProviders").mockResolvedValue(allProvidersFixture() as never)

    const { result } = renderHook(() =>
      useProviderStatus({
        setProviders: harness.setProviders,
        setProvidersLoading: harness.setProvidersLoading,
        setProvidersError: harness.setProvidersError,
        showToast: harness.showToast,
        canReadControls: true,
      }),
    )

    await act(async () => {
      await result.current.refreshProviders()
    })

    const exa = harness.getState().find((p) => p.id === "exa")!
    expect(exa.searchEnabled).toBe(true)
    expect(exa.enableMask).toBe(7)
  })

  it("toggleProvider PATCHes one global bit and applies the response state", async () => {
    const harness = stateHarness()
    vi.spyOn(apiService, "listProviders").mockResolvedValue(allProvidersFixture() as never)
    const patchSpy = vi
      .spyOn(apiService, "patchProvider")
      .mockResolvedValue(providerStatus("brave", { enable_mask: 6 }) as never)

    const { result } = renderHook(() =>
      useProviderStatus({
        setProviders: harness.setProviders,
        setProvidersLoading: harness.setProvidersLoading,
        setProvidersError: harness.setProvidersError,
        showToast: harness.showToast,
        canReadControls: true,
      }),
    )

    await act(async () => {
      await result.current.refreshProviders()
    })
    expect(harness.getState().find((p) => p.id === "brave")?.globalEnabled).toBe(true)

    await act(async () => {
      await result.current.toggleProvider("brave", false)
    })

    expect(patchSpy).toHaveBeenCalledWith("brave", { enabled: false })
    const brave = harness.getState().find((p) => p.id === "brave")!
    expect(brave.enableMask).toBe(6)
    expect(brave.globalEnabled).toBe(false)
    // Global OFF preserves the raw tool choices.
    expect(brave.searchEnabled).toBe(true)
    expect(brave.fetchEnabled).toBe(true)
  })

  it("toggleProviderSearch PATCHes one search bit and applies the response state", async () => {
    const harness = stateHarness()
    vi.spyOn(apiService, "listProviders").mockResolvedValue(allProvidersFixture() as never)
    const patchSpy = vi
      .spyOn(apiService, "patchProvider")
      .mockResolvedValue(providerStatus("exa", { enable_mask: 5 }) as never)

    const { result } = renderHook(() =>
      useProviderStatus({
        setProviders: harness.setProviders,
        setProvidersLoading: harness.setProvidersLoading,
        setProvidersError: harness.setProvidersError,
        showToast: harness.showToast,
        canReadControls: true,
      }),
    )

    await act(async () => {
      await result.current.refreshProviders()
    })

    await act(async () => {
      await result.current.toggleProviderSearch("exa", false)
    })

    expect(patchSpy).toHaveBeenCalledWith("exa", { search_enabled: false })
    const exa = harness.getState().find((p) => p.id === "exa")!
    expect(exa.enableMask).toBe(5)
    expect(exa.searchEnabled).toBe(false)
    expect(exa.fetchEnabled).toBe(true)
    expect(exa.globalEnabled).toBe(true)
  })

  it("toggleProviderFetch PATCHes one fetch bit and applies the response state", async () => {
    const harness = stateHarness()
    vi.spyOn(apiService, "listProviders").mockResolvedValue(allProvidersFixture() as never)
    const patchSpy = vi
      .spyOn(apiService, "patchProvider")
      .mockResolvedValue(providerStatus("exa", { enable_mask: 3 }) as never)

    const { result } = renderHook(() =>
      useProviderStatus({
        setProviders: harness.setProviders,
        setProvidersLoading: harness.setProvidersLoading,
        setProvidersError: harness.setProvidersError,
        showToast: harness.showToast,
        canReadControls: true,
      }),
    )

    await act(async () => {
      await result.current.refreshProviders()
    })

    await act(async () => {
      await result.current.toggleProviderFetch("exa", false)
    })

    expect(patchSpy).toHaveBeenCalledWith("exa", { fetch_enabled: false })
    const exa = harness.getState().find((p) => p.id === "exa")!
    expect(exa.enableMask).toBe(3)
    expect(exa.searchEnabled).toBe(true)
    expect(exa.fetchEnabled).toBe(false)
  })

  it("preserves previous state and toasts on PATCH failure", async () => {
    const harness = stateHarness()
    vi.spyOn(apiService, "listProviders").mockResolvedValue(allProvidersFixture() as never)
    vi.spyOn(apiService, "patchProvider").mockRejectedValue(new Error("db down"))

    const { result } = renderHook(() =>
      useProviderStatus({
        setProviders: harness.setProviders,
        setProvidersLoading: harness.setProvidersLoading,
        setProvidersError: harness.setProvidersError,
        showToast: harness.showToast,
        canReadControls: true,
      }),
    )

    await act(async () => {
      await result.current.refreshProviders()
    })
    const before = harness.getState()

    await act(async () => {
      await result.current.toggleProviderSearch("exa", false)
    })

    expect(harness.getState()).toEqual(before)
    expect(harness.showToast).toHaveBeenCalledWith(expect.stringContaining("db down"), "error")
  })

  it("returns an empty catalog with clear flags when canReadControls is false", async () => {
    let providersState: ProviderConfig[] = [
      {
        id: "exa",
        name: "Exa",
        capabilities: ["search", "fetch"],
        globalEnabled: true,
        searchEnabled: true,
        fetchEnabled: true,
        hasKey: true,
      } as ProviderConfig,
    ]

    const setProviders = vi.fn((update: React.SetStateAction<ProviderConfig[]>) => {
      if (typeof update === "function") {
        providersState = (update as (prev: ProviderConfig[]) => ProviderConfig[])(providersState)
      } else {
        providersState = update
      }
    })
    const setProvidersLoading = vi.fn()
    const setProvidersError = vi.fn()
    const showToast = vi.fn()

    const listProvidersSpy = vi.spyOn(apiService, "listProviders")

    const { result } = renderHook(() =>
      useProviderStatus({
        setProviders,
        setProvidersLoading,
        setProvidersError,
        showToast,
        canReadControls: false,
      })
    )

    await act(async () => {
      await result.current.refreshProviders()
    })

    expect(listProvidersSpy).not.toHaveBeenCalled()
    expect(providersState).toEqual([])
    expect(setProvidersLoading).toHaveBeenCalledWith(false)
    expect(setProvidersError).toHaveBeenCalledWith(null)
  })
})
