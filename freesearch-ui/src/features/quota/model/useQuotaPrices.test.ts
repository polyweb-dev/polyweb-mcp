import { renderHook, waitFor } from "@testing-library/react"
import { describe, expect, it, vi } from "vitest"
import { getProviderPrices, type ProviderConfig } from "@/domains/providers"
import { quotaPricedProvider, useQuotaPrices } from "./useQuotaPrices"

vi.mock("@/domains/providers", async (original) => ({ ...await original<typeof import("@/domains/providers")>(), getProviderPrices: vi.fn() }))

describe("quota price catalog", () => {
  it("reads prices through the shared provider price client", async () => {
    const prices = [{ providerType: "keenable", free: true, keyless: true, callCostUsd: { search: "0", fetch: "0" }, keylessCallCostUsd: { search: "0", fetch: "0" } }]
    vi.mocked(getProviderPrices).mockResolvedValue(prices)
    const { result } = renderHook(() => useQuotaPrices())
    await waitFor(() => expect(result.current).toEqual(prices))
    expect(getProviderPrices).toHaveBeenCalledWith(expect.any(AbortSignal))
    const provider = { id: "keenable", callCostUsd: { search: "0.004" } } as ProviderConfig
    expect(quotaPricedProvider(provider, result.current)).toMatchObject({ free: true, callCostUsd: { search: "0", fetch: "0" } })
  })
  it("keeps the existing catalog snapshot when the price read fails", async () => {
    vi.mocked(getProviderPrices).mockRejectedValue(new Error("unavailable"))
    const { result } = renderHook(() => useQuotaPrices())
    await waitFor(() => expect(getProviderPrices).toHaveBeenCalled())
    const provider = { id: "brave", callCostUsd: { search: "0.005" } } as ProviderConfig
    expect(quotaPricedProvider(provider, result.current)).toBe(provider)
  })
})
