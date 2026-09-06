import React from "react"
import { describe, expect, it } from "vitest"
import { act, renderHook } from "@testing-library/react"
import { FreeSearchProvider } from "./FreeSearchContext"
import { useFreeSearch } from "./useFreeSearch"

const wrapper = ({ children }: { children: React.ReactNode }) => (
  <FreeSearchProvider>{children}</FreeSearchProvider>
)

describe("FreeSearchContext", () => {
  it("toggles global enablement of a provider", () => {
    const { result } = renderHook(() => useFreeSearch(), { wrapper })

    expect(result.current.providers.find((provider) => provider.id === "brave")?.globalEnabled).toBe(true)

    act(() => {
      result.current.toggleProvider("brave", false)
    })

    expect(result.current.providers.find((provider) => provider.id === "brave")?.globalEnabled).toBe(false)
  })

  it("toggles granular search and fetch capabilities independently", () => {
    const { result } = renderHook(() => useFreeSearch(), { wrapper })

    act(() => {
      result.current.toggleProviderSearch("keenable", false)
    })
    let keenable = result.current.providers.find((provider) => provider.id === "keenable")!
    expect(keenable.searchEnabled).toBe(false)
    expect(keenable.fetchEnabled).toBe(true)

    act(() => {
      result.current.toggleProviderFetch("keenable", false)
    })
    keenable = result.current.providers.find((provider) => provider.id === "keenable")!
    expect(keenable.fetchEnabled).toBe(false)
  })

  it("does not enable an operation unsupported by the provider", () => {
    const { result } = renderHook(() => useFreeSearch(), { wrapper })

    const braveBefore = result.current.providers.find((provider) => provider.id === "brave")!
    expect(braveBefore.capabilities).not.toContain("fetch")
    expect(braveBefore.fetchEnabled).toBe(false)

    act(() => {
      result.current.toggleProviderFetch("brave", true)
    })

    expect(result.current.providers.find((provider) => provider.id === "brave")?.fetchEnabled).toBe(false)
  })

  it("saves only a trimmed masked key and marks the vault configured", () => {
    const { result } = renderHook(() => useFreeSearch(), { wrapper })

    act(() => {
      result.current.saveProviderKey("youcom", "  yc_live_secret_key_6789  ")
    })

    const youcom = result.current.providers.find((provider) => provider.id === "youcom")!
    expect(youcom.hasKey).toBe(true)
    expect(youcom.keyVaultStatus).toBe("configured")
    expect(youcom.keyMasked).toBe("yc_l_••••••••6789")
    expect("unmaskedKeyOnce" in youcom).toBe(false)
  })

  it("ignores blank credentials without changing an existing vault state", () => {
    const { result } = renderHook(() => useFreeSearch(), { wrapper })
    const before = result.current.providers.find((provider) => provider.id === "youcom")!

    act(() => {
      result.current.saveProviderKey("youcom", "   ")
    })

    const after = result.current.providers.find((provider) => provider.id === "youcom")!
    expect(after.hasKey).toBe(before.hasKey)
    expect(after.keyVaultStatus).toBe(before.keyVaultStatus)
    expect(after.keyMasked).toBe(before.keyMasked)
  })

  it("updates the selected routing preset", () => {
    const { result } = renderHook(() => useFreeSearch(), { wrapper })

    act(() => {
      result.current.setRoutingPreset("quality_first")
    })

    expect(result.current.routingPreset).toBe("quality_first")
  })

  it("updates fallback configuration without dropping other policies", () => {
    const { result } = renderHook(() => useFreeSearch(), { wrapper })
    expect(result.current.fallbackConfig).toMatchObject({
      enabled: true,
      maxAttempts: 3,
      fallbackOnRateLimit: true,
      fallbackOnTimeout: true,
      fallbackOnServerError: true,
    })

    act(() => {
      result.current.updateFallbackConfig({ enabled: false, maxAttempts: 5 })
    })

    expect(result.current.fallbackConfig).toEqual({
      enabled: false,
      maxAttempts: 5,
      fallbackOnRateLimit: true,
      fallbackOnTimeout: true,
      fallbackOnServerError: true,
    })
  })

  it("removes a provider through the retained removeProvider API", () => {
    const { result } = renderHook(() => useFreeSearch(), { wrapper })
    const initialCount = result.current.providers.length

    act(() => {
      result.current.removeProvider("parallel")
    })

    expect(result.current.providers).toHaveLength(initialCount - 1)
    expect(result.current.providers.some((provider) => provider.id === "parallel")).toBe(false)
  })
})
