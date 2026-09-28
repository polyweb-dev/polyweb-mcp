import { describe, it, expect, vi } from "vitest"
import { renderHook, act } from "@testing-library/react"
import { usePlaygroundController } from "./usePlaygroundController"
import type { ProviderConfig } from "@/domains/providers"

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

describe("usePlaygroundController credential eligibility", () => {
  it("filters out providers without a key and without keyless_tier", () => {
    currentProviders = [...mockProviders]
    const { result } = renderHook(() => usePlaygroundController())

    const eligibleIds = result.current.eligibleProviders.map((p) => p.id)
    expect(eligibleIds).toContain("brave")
    expect(eligibleIds).toContain("keenable")
    expect(eligibleIds).not.toContain("exa")
  })

  it("resets selectedProviderId to auto when the selected provider loses its key", () => {
    currentProviders = [
      ...mockProviders.map((p) => (p.id === "exa" ? { ...p, hasKey: true } : p)),
    ]
    const { result, rerender } = renderHook(() => usePlaygroundController())

    act(() => {
      result.current.setSelectedProviderId("exa")
    })
    expect(result.current.selectedProviderId).toBe("exa")

    currentProviders = [
      ...mockProviders.map((p) => (p.id === "exa" ? { ...p, hasKey: false } : p)),
    ]
    rerender()

    expect(result.current.selectedProviderId).toBe("auto")
  })
})
