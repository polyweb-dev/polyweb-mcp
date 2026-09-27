import { describe, it, expect, vi, beforeEach } from "vitest"
import { renderHook, act } from "@testing-library/react"
import {
  useProviderStatus,
  loadOperationToggles,
  saveOperationToggle,
  OPERATION_TOGGLES_STORAGE_KEY,
} from "./useProviderStatus"
import { apiService } from "@/services/api/freesearchApi"
import { allProvidersFixture } from "@/test/backendFixtures"
import type { ProviderConfig } from "@/domains/providers/model/types"

describe("useProviderStatus operation toggle persistence", () => {
  beforeEach(() => {
    localStorage.clear()
    vi.restoreAllMocks()
  })

  describe("saveOperationToggle and loadOperationToggles", () => {
    it("returns empty object when nothing has been stored", () => {
      expect(loadOperationToggles()).toEqual({})
    })

    it("saves and loads operation toggles for providers", () => {
      saveOperationToggle("exa", { searchEnabled: false })
      expect(loadOperationToggles()).toEqual({
        exa: { searchEnabled: false },
      })

      // Updates without overwriting existing keys
      saveOperationToggle("exa", { fetchEnabled: true })
      expect(loadOperationToggles()).toEqual({
        exa: { searchEnabled: false, fetchEnabled: true },
      })
    })

    it("handles corrupted localStorage gracefully", () => {
      localStorage.setItem(OPERATION_TOGGLES_STORAGE_KEY, "invalid-json{{")
      expect(loadOperationToggles()).toEqual({})
    })
  })

  describe("useProviderStatus hook hydration and toggles", () => {
    it("hydrates search and fetch toggles from localStorage upon refreshProviders", async () => {
      // Pre-save toggles in localStorage: Exa search is OFF
      saveOperationToggle("exa", { searchEnabled: false })

      let providersState: ProviderConfig[] = []
      const setProviders = vi.fn((update) => {
        if (typeof update === "function") {
          providersState = update(providersState)
        } else {
          providersState = update
        }
      })
      const setProvidersLoading = vi.fn()
      const setProvidersError = vi.fn()
      const showToast = vi.fn()

      vi.spyOn(apiService, "listProviders").mockResolvedValue(allProvidersFixture() as any)

      const { result } = renderHook(() =>
        useProviderStatus({
          setProviders,
          setProvidersLoading,
          setProvidersError,
          showToast,
        })
      )

      await act(async () => {
        await result.current.refreshProviders()
      })

      const exa = providersState.find((p) => p.id === "exa")
      expect(exa?.searchEnabled).toBe(false)
      expect(exa?.fetchEnabled).toBe(true)

      const brave = providersState.find((p) => p.id === "brave")
      expect(brave?.searchEnabled).toBe(true)
    })

    it("persists toggles to localStorage when toggleProviderSearch is invoked", async () => {
      let providersState: ProviderConfig[] = [
        {
          id: "exa",
          name: "Exa",
          capabilities: ["search", "fetch"],
          priority: 1,
          globalEnabled: true,
          searchEnabled: true,
          fetchEnabled: true,
          hasKey: true,
        } as ProviderConfig,
      ]

      const setProviders = vi.fn((update) => {
        if (typeof update === "function") {
          providersState = update(providersState)
        } else {
          providersState = update
        }
      })
      const setProvidersLoading = vi.fn()
      const setProvidersError = vi.fn()
      const showToast = vi.fn()

      const { result } = renderHook(() =>
        useProviderStatus({
          setProviders,
          setProvidersLoading,
          setProvidersError,
          showToast,
        })
      )

      act(() => {
        result.current.toggleProviderSearch("exa", false)
      })

      expect(loadOperationToggles().exa?.searchEnabled).toBe(false)
      expect(providersState[0].searchEnabled).toBe(false)

      act(() => {
        result.current.toggleProviderFetch("exa", false)
      })

      expect(loadOperationToggles().exa?.fetchEnabled).toBe(false)
      expect(providersState[0].fetchEnabled).toBe(false)
    })
  })
})
