import React from "react"
import { describe, expect, it, vi, beforeEach } from "vitest"
import { act, renderHook } from "@testing-library/react"
import { Provider } from "react-redux"
import { useSearchRunner } from "./useSearchRunner"
import { apiService } from "@/services/api/freesearchApi"
import { ApiError } from "@/shared/api/http"
import { makeStore, type AppStore } from "@/store/store"
import { ADMIN_ACCOUNT_ID } from "@/test/authFixtures"
import { searchResponseFixture } from "@/test/backendFixtures"
import type { ProviderConfig } from "@/domains/providers/model/types"

vi.mock("@/services/api/freesearchApi", () => ({
  apiService: { search: vi.fn() },
}))

/**
 * Tavily terminal 402: the safe out-of-Credits error fails fast before the
 * client fallback walk, while every other provider keeps its fallback.
 */

function provider(id: string, priority: number): ProviderConfig {
  return {
    id,
    name: id,
    description: id,
    baseUrl: "https://example.com",
    isCustom: false,
    capabilities: ["search"],
    enableMask: 7,
    supportMask: 7,
    globalEnabled: true,
    searchEnabled: true,
    fetchEnabled: false,
    priority,
    healthStatus: "healthy",
    circuitBreaker: "closed",
    consecutiveFailures: 0,
    latencyP95Ms: null,
    hasKey: true,
    keyMasked: "—",
    keyVaultStatus: "configured",
    quota: {
      used: null,
      limit: null,
      unit: "units",
      confidence: "estimated",
      resetPeriod: null,
      nextReset: null,
      remaining: null,
      remainingPercent: null,
      unitKind: null,
      displayUnit: null,
      observedAt: null,
      window: null,
    },
  } as ProviderConfig
}

function wrapper(store: AppStore) {
  return function Wrapper({ children }: { children: React.ReactNode }) {
    return React.createElement(Provider, { store, children })
  }
}

function deps(overrides: Record<string, unknown> = {}) {
  return {
    showToast: vi.fn(),
    fallbackEnabled: true,
    catalogNameOf: (id: string) => id,
    refreshDashboard: vi.fn(() => Promise.resolve()),
    prependUsageEvent: vi.fn(),
    providers: [provider("tavily", 1), provider("brave", 2), provider("exa", 3)],
    routingPreset: "priority" as const,
    ...overrides,
  }
}

const searchMock = vi.mocked(apiService.search)

describe("useSearchRunner Tavily 402", () => {
  beforeEach(() => {
    searchMock.mockReset()
  })

  it("fails fast on a Tavily 402 before the fallback walk", async () => {
    searchMock.mockRejectedValueOnce(
      new ApiError(402, "Tavily is out of Credits. Wait until reset or upgrade.", {
        detail: "Tavily is out of Credits. Wait until reset or upgrade.",
        provider: "tavily",
      }),
    )
    const args = deps()
    const { result } = renderHook(() => useSearchRunner(args as never), {
      wrapper: wrapper(makeStore(ADMIN_ACCOUNT_ID)),
    })

    let outcome: unknown
    await act(async () => {
      outcome = await result.current.runSearch({
        query: "hello",
        providerIds: ["tavily"],
        maxResults: 5,
        timeoutMs: 1000,
      })
    })

    expect(outcome).toBeNull()
    expect(searchMock).toHaveBeenCalledTimes(1)
    expect(args.prependUsageEvent).not.toHaveBeenCalled()
    expect(args.refreshDashboard).not.toHaveBeenCalled()
    expect(args.showToast).toHaveBeenCalledTimes(1)
    expect(result.current.searchError).toContain("Tavily is out of Credits")
  })

  it("fails fast when the provider sits under detail", async () => {
    searchMock.mockRejectedValueOnce(
      new ApiError(402, "Tavily is out of Credits. Wait until reset or upgrade.", {
        detail: { provider: "tavily" },
      }),
    )
    const args = deps()
    const { result } = renderHook(() => useSearchRunner(args as never), {
      wrapper: wrapper(makeStore(ADMIN_ACCOUNT_ID)),
    })

    await act(async () => {
      await result.current.runSearch({
        query: "hello",
        providerIds: ["tavily"],
        maxResults: 5,
        timeoutMs: 1000,
      })
    })

    expect(searchMock).toHaveBeenCalledTimes(1)
  })

  it("keeps fallback intact for other providers", async () => {
    searchMock.mockRejectedValueOnce(new ApiError(500, "brave failed", { provider: "brave" }))
    searchMock.mockResolvedValueOnce(searchResponseFixture({ provider: "exa" }) as never)
    const args = deps({ providers: [provider("brave", 1), provider("exa", 2)] })
    const { result } = renderHook(() => useSearchRunner(args as never), {
      wrapper: wrapper(makeStore(ADMIN_ACCOUNT_ID)),
    })

    let outcome: { selectedProviderId: string } | null = null
    await act(async () => {
      outcome = (await result.current.runSearch({
        query: "hello",
        providerIds: ["brave"],
        maxResults: 5,
        timeoutMs: 1000,
      })) as unknown as { selectedProviderId: string }
    })

    expect(searchMock).toHaveBeenCalledTimes(2)
    expect((outcome as unknown as { selectedProviderId: string } | null)?.selectedProviderId).toBe("exa")
    expect(args.prependUsageEvent).toHaveBeenCalledTimes(1)
  })

  it("keeps fallback for a non-402 Tavily error", async () => {
    searchMock.mockRejectedValueOnce(new ApiError(429, "limited", { provider: "tavily" }))
    searchMock.mockResolvedValueOnce(searchResponseFixture({ provider: "brave" }) as never)
    const args = deps({ providers: [provider("tavily", 1), provider("brave", 2)] })
    const { result } = renderHook(() => useSearchRunner(args as never), {
      wrapper: wrapper(makeStore(ADMIN_ACCOUNT_ID)),
    })

    let outcome: { selectedProviderId: string } | null = null
    await act(async () => {
      outcome = (await result.current.runSearch({
        query: "hello",
        providerIds: ["tavily"],
        maxResults: 5,
        timeoutMs: 1000,
      })) as unknown as { selectedProviderId: string }
    })

    expect(searchMock).toHaveBeenCalledTimes(2)
    expect((outcome as unknown as { selectedProviderId: string } | null)?.selectedProviderId).toBe("brave")
  })
})
