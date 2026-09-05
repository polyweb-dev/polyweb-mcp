import { describe, it, expect } from "vitest"
import { FreeSearchApiService } from "./freesearchApi"
import { DEFAULT_PROVIDERS } from "./defaultProviders"
import type { FallbackConfig, ProviderConfig } from "@/types/freesearch"

describe("FreeSearchApiService", () => {
  const service = new FreeSearchApiService()

  const sampleFallbackConfig: FallbackConfig = {
    enabled: true,
    maxAttempts: 3,
    fallbackOnRateLimit: true,
    fallbackOnTimeout: true,
    fallbackOnServerError: true,
  }

  describe("getEligibleProviders", () => {
    it("filters providers that have search capability and searchEnabled = true for search", () => {
      const eligible = service.getEligibleProviders(DEFAULT_PROVIDERS, "search")
      expect(eligible.length).toBeGreaterThan(0)
      for (const p of eligible) {
        expect(p.globalEnabled).toBe(true)
        expect(p.searchEnabled).toBe(true)
        expect(p.capabilities).toContain("search")
        expect(p.circuitBreaker).not.toBe("open")
      }
    })

    it("filters providers that have fetch capability and fetchEnabled = true for fetch", () => {
      const eligible = service.getEligibleProviders(DEFAULT_PROVIDERS, "fetch")
      expect(eligible.length).toBeGreaterThan(0)
      for (const p of eligible) {
        expect(p.globalEnabled).toBe(true)
        expect(p.fetchEnabled).toBe(true)
        expect(p.capabilities).toContain("fetch")
        expect(p.circuitBreaker).not.toBe("open")
      }

      // Brave is search-only, so it must not be eligible for fetch
      const brave = eligible.find((p) => p.id === "brave")
      expect(brave).toBeUndefined()
    })

    it("excludes circuit-broken providers", () => {
      const modified: ProviderConfig[] = DEFAULT_PROVIDERS.map((p) =>
        p.id === "brave" ? { ...p, circuitBreaker: "open" } : p
      )
      const eligible = service.getEligibleProviders(modified, "search")
      expect(eligible.find((p) => p.id === "brave")).toBeUndefined()
    })

    it("sorts eligible providers in ascending priority rank order", () => {
      const eligible = service.getEligibleProviders(DEFAULT_PROVIDERS, "search")
      for (let i = 0; i < eligible.length - 1; i++) {
        expect(eligible[i].priority).toBeLessThanOrEqual(eligible[i + 1].priority)
      }
    })
  })

  describe("executeSearch", () => {
    it("executes search and returns standardized SearchResponse with waterfall", async () => {
      const response = await service.executeSearch(
        {
          query: "vector search",
          mode: "fast",
          maxResults: 5,
          timeoutMs: 2000,
        },
        DEFAULT_PROVIDERS,
        sampleFallbackConfig
      )

      expect(response).toBeDefined()
      expect(response.query).toBe("vector search")
      expect(response.results.length).toBeGreaterThan(0)
      expect(response.waterfall.length).toBeGreaterThan(0)
      expect(response.selectedProviderId).toBeTruthy()
      expect(response.executionTimeMs).toBeGreaterThan(0)
      expect(response.results[0]).toHaveProperty("snippet")
      expect(response.results[0]).toHaveProperty("relevanceScore")
    })

    it("throws error when no eligible providers are active", async () => {
      const disabledProviders = DEFAULT_PROVIDERS.map((p) => ({ ...p, globalEnabled: false }))
      await expect(
        service.executeSearch(
          {
            query: "test",
            mode: "fast",
            maxResults: 5,
            timeoutMs: 2000,
          },
          disabledProviders,
          sampleFallbackConfig
        )
      ).rejects.toThrow("No active providers available for search")
    })
  })

  describe("executeFetch", () => {
    it("executes document fetch and returns normalized markdown document", async () => {
      const response = await service.executeFetch(
        {
          url: "https://docs.freesearch.dev/getting-started",
          format: "markdown",
          timeoutMs: 2000,
        },
        DEFAULT_PROVIDERS,
        sampleFallbackConfig
      )

      expect(response).toBeDefined()
      expect(response.document.url).toBe("https://docs.freesearch.dev/getting-started")
      expect(response.document.markdown).toContain("Documentation:")
      expect(response.document.statusCode).toBe(200)
    })
  })

  describe("testConnection", () => {
    it("returns success for a healthy provider", async () => {
      const brave = DEFAULT_PROVIDERS.find((p) => p.id === "brave")!
      const res = await service.testConnection(brave)
      expect(res.success).toBe(true)
      expect(res.latencyMs).toBeGreaterThan(0)
    })

    it("returns failure when provider is offline", async () => {
      const parallel = DEFAULT_PROVIDERS.find((p) => p.id === "parallel")!
      const res = await service.testConnection(parallel)
      expect(res.success).toBe(false)
      expect(res.message).toContain("Connection refused")
    })
  })
})
