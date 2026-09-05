import React from "react"
import { describe, it, expect } from "vitest"
import { renderHook, act } from "@testing-library/react"
import { FreeSearchProvider } from "./FreeSearchContext"
import { useFreeSearch } from "./useFreeSearch"

describe("FreeSearchContext", () => {
  const wrapper = ({ children }: { children: React.ReactNode }) => (
    <FreeSearchProvider>{children}</FreeSearchProvider>
  )

  it("toggles global enablement of a provider", () => {
    const { result } = renderHook(() => useFreeSearch(), { wrapper })

    const braveBefore = result.current.providers.find((p) => p.id === "brave")!
    expect(braveBefore.globalEnabled).toBe(true)

    act(() => {
      result.current.toggleProvider("brave", false)
    })

    const braveAfter = result.current.providers.find((p) => p.id === "brave")!
    expect(braveAfter.globalEnabled).toBe(false)
  })

  it("toggles granular search and fetch capabilities independently", () => {
    const { result } = renderHook(() => useFreeSearch(), { wrapper })

    // Keenable supports both search and fetch
    act(() => {
      result.current.toggleProviderSearch("keenable", false)
    })
    let keenable = result.current.providers.find((p) => p.id === "keenable")!
    expect(keenable.searchEnabled).toBe(false)
    expect(keenable.fetchEnabled).toBe(true)

    act(() => {
      result.current.toggleProviderFetch("keenable", false)
    })
    keenable = result.current.providers.find((p) => p.id === "keenable")!
    expect(keenable.fetchEnabled).toBe(false)
  })

  it("prevents enabling operations that a provider does not support", () => {
    const { result } = renderHook(() => useFreeSearch(), { wrapper })

    // Brave does not support fetch
    const braveBefore = result.current.providers.find((p) => p.id === "brave")!
    expect(braveBefore.capabilities).not.toContain("fetch")
    expect(braveBefore.fetchEnabled).toBe(false)

    act(() => {
      result.current.toggleProviderFetch("brave", true)
    })

    const braveAfter = result.current.providers.find((p) => p.id === "brave")!
    expect(braveAfter.fetchEnabled).toBe(false)
  })

  it("handles one-time view API keys and burns plaintext upon request", () => {
    const { result } = renderHook(() => useFreeSearch(), { wrapper })

    act(() => {
      result.current.saveProviderKey("youcom", "yc_live_secret_key_123456789")
    })

    let youcom = result.current.providers.find((p) => p.id === "youcom")!
    expect(youcom.hasKey).toBe(true)
    expect(youcom.keyVaultStatus).toBe("revealed_once")
    expect(youcom.unmaskedKeyOnce).toBe("yc_live_secret_key_123456789")
    expect(youcom.keyMasked).toContain("••••••••")

    // Burn the one-time key view
    act(() => {
      result.current.burnOneTimeKey("youcom")
    })

    youcom = result.current.providers.find((p) => p.id === "youcom")!
    expect(youcom.keyVaultStatus).toBe("configured")
    expect(youcom.unmaskedKeyOnce).toBeUndefined()
  })

  it("allows adding and removing custom providers dynamically", () => {
    const { result } = renderHook(() => useFreeSearch(), { wrapper })

    const initialCount = result.current.providers.length

    act(() => {
      result.current.addProvider({
        id: "searxng-local",
        name: "SearXNG Local",
        description: "Local metasearch engine instance",
        baseUrl: "http://localhost:8888",
        capabilities: ["search"],
        globalEnabled: true,
        searchEnabled: true,
        fetchEnabled: false,
        priority: initialCount + 1,
        healthStatus: "healthy",
        circuitBreaker: "closed",
        consecutiveFailures: 0,
        latencyP95Ms: 120,
        hasKey: false,
        keyMasked: "Keyless Local",
        keyVaultStatus: "keyless_public",
        quota: {
          used: 0,
          limit: null,
          unit: "queries",
          confidence: "authoritative",
          resetPeriod: "Unlimited",
          nextReset: "None",
        },
      })
    })

    expect(result.current.providers.length).toBe(initialCount + 1)
    const added = result.current.providers.find((p) => p.id === "searxng-local")!
    expect(added).toBeDefined()
    expect(added.isCustom).toBe(true)

    // Now remove it
    act(() => {
      result.current.removeProvider("searxng-local")
    })
    expect(result.current.providers.length).toBe(initialCount)
  })

  it("updates fallback configuration", () => {
    const { result } = renderHook(() => useFreeSearch(), { wrapper })

    expect(result.current.fallbackConfig.enabled).toBe(true)

    act(() => {
      result.current.updateFallbackConfig({ enabled: false })
    })

    expect(result.current.fallbackConfig.enabled).toBe(false)
  })
})
