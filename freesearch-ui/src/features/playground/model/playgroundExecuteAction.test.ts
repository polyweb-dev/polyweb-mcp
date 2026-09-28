import { describe, it, expect, vi } from "vitest"
import {
  resolvePinnedProvider,
  resolveSearchProviderIds,
  createExecuteHandler,
} from "./playgroundExecuteAction"
import type { ProviderConfig } from "@/domains/providers"

const mockEligibleProviders: ProviderConfig[] = [
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
    id: "tavily",
    name: "Tavily",
    capabilities: ["search", "fetch"],
    priority: 2,
    globalEnabled: true,
    searchEnabled: true,
    fetchEnabled: true,
    hasKey: true,
  } as ProviderConfig,
]

describe("playgroundExecuteAction helpers", () => {
  describe("resolvePinnedProvider", () => {
    it("returns undefined for 'auto' and 'all'", () => {
      expect(resolvePinnedProvider("auto", mockEligibleProviders)).toBeUndefined()
      expect(resolvePinnedProvider("all", mockEligibleProviders)).toBeUndefined()
    })

    it("returns provider id when provider is in eligibleProviders", () => {
      expect(resolvePinnedProvider("brave", mockEligibleProviders)).toBe("brave")
      expect(resolvePinnedProvider("tavily", mockEligibleProviders)).toBe("tavily")
    })

    it("returns undefined when provider is not in eligibleProviders (e.g. disabled)", () => {
      expect(resolvePinnedProvider("exa", mockEligibleProviders)).toBeUndefined()
    })
  })

  describe("resolveSearchProviderIds", () => {
    it("returns [selectedProvider] when a provider is pinned", () => {
      expect(resolveSearchProviderIds("brave", false, mockEligibleProviders)).toEqual(["brave"])
    })

    it("returns eligible provider IDs when isFanout is true", () => {
      const ids = resolveSearchProviderIds(undefined, true, mockEligibleProviders)
      expect(ids).toEqual(["brave", "tavily"])
    })

    it("returns undefined in auto mode (not pinned, not fanout)", () => {
      expect(resolveSearchProviderIds(undefined, false, mockEligibleProviders)).toBeUndefined()
    })
  })

  describe("createExecuteHandler", () => {
    it("executes fanout search with 15000ms timeout and eligible provider IDs", async () => {
      const runSearch = vi.fn().mockResolvedValue({
        results: [{ title: "Result 1", url: "https://example.com" }],
      })
      const runFetch = vi.fn()
      const showResult = vi.fn()

      const handler = createExecuteHandler({
        mode: "search",
        query: "quantum computing",
        fetchUrl: "",
        selectedProviderId: "all",
        resultCount: 10,
        eligibleProviders: mockEligibleProviders,
        runSearch,
        runFetch,
        showResult,
      })

      await handler()

      expect(runSearch).toHaveBeenCalledWith({
        query: "quantum computing",
        providerIds: ["brave", "tavily"],
        fanout: true,
        maxResults: 10,
        timeoutMs: 15000,
      })
      expect(showResult).toHaveBeenCalledWith({ title: "Result 1", url: "https://example.com" })
    })

    it("executes single-provider search with 5000ms timeout", async () => {
      const runSearch = vi.fn().mockResolvedValue({
        results: [],
      })
      const runFetch = vi.fn()
      const showResult = vi.fn()

      const handler = createExecuteHandler({
        mode: "search",
        query: "test single",
        fetchUrl: "",
        selectedProviderId: "brave",
        resultCount: 6,
        eligibleProviders: mockEligibleProviders,
        runSearch,
        runFetch,
        showResult,
      })

      await handler()

      expect(runSearch).toHaveBeenCalledWith({
        query: "test single",
        providerIds: ["brave"],
        fanout: false,
        maxResults: 6,
        timeoutMs: 5000,
      })
      expect(showResult).toHaveBeenCalledWith(null)
    })

    it("does not execute when query is whitespace", async () => {
      const runSearch = vi.fn()
      const runFetch = vi.fn()
      const showResult = vi.fn()

      const handler = createExecuteHandler({
        mode: "search",
        query: "   ",
        fetchUrl: "",
        selectedProviderId: "all",
        resultCount: 6,
        eligibleProviders: mockEligibleProviders,
        runSearch,
        runFetch,
        showResult,
      })

      await handler()
      expect(runSearch).not.toHaveBeenCalled()
    })
  })
})
