import { renderHook, waitFor } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { useFreeProvider } from "./useFreeProvider"

const mocks = vi.hoisted(() => ({ prices: vi.fn() }))
vi.mock("@/domains/providers", async (original) => ({ ...await original<typeof import("@/domains/providers")>(), getProviderPrices: mocks.prices }))

beforeEach(() => {
  mocks.prices.mockReset().mockResolvedValue([
    { providerType: "tinyfish", free: true }, { providerType: "keenable", free: true },
    { providerType: "brave", free: false }, { providerType: "you", free: false },
    { providerType: "tavily", free: false },
  ])
})

describe("useFreeProvider", () => {
  it.each([
    ["tinyfish", true], ["keenable", true], ["brave", false],
    ["you", false], ["tavily", false], ["exa", false],
  ])("reads the price-only catalog for %s without system permissions", async (provider, free) => {
    const { result } = renderHook(() => useFreeProvider(provider))
    await waitFor(() => expect(mocks.prices).toHaveBeenCalled())
    await waitFor(() => expect(result.current).toBe(free))
  })

  it("keeps unknown prices non-free when the catalog read fails", async () => {
    mocks.prices.mockRejectedValue(new Error("unavailable"))
    const { result } = renderHook(() => useFreeProvider("tinyfish"))
    await waitFor(() => expect(mocks.prices).toHaveBeenCalled())
    expect(result.current).toBe(false)
  })
})
