import type {
  FallbackConfig,
  FetchRequest,
  FetchResponse,
  FetchedDocument,
  ProviderConfig,
  ProviderWaterfallItem,
  SearchRequest,
  SearchResponse,
  SearchResult,
} from "@/types/freesearch"

export class FreeSearchApiService {
  /**
   * Filter and order providers eligible for an operation (search or fetch)
   */
  getEligibleProviders(
    providers: ProviderConfig[],
    operation: "search" | "fetch",
    targetProviderIds?: string[]
  ): ProviderConfig[] {
    return providers
      .filter((p) => {
        if (!p.globalEnabled) return false
        if (p.circuitBreaker === "open") return false
        if (operation === "search") {
          if (!p.searchEnabled || !p.capabilities.includes("search")) return false
        } else {
          if (!p.fetchEnabled || !p.capabilities.includes("fetch")) return false
        }
        if (targetProviderIds && targetProviderIds.length > 0) {
          return targetProviderIds.includes(p.id)
        }
        return true
      })
      .sort((a, b) => a.priority - b.priority)
  }

  /**
   * Execute multi-provider search with fallback routing
   */
  async executeSearch(
    request: SearchRequest,
    providers: ProviderConfig[],
    fallbackConfig: FallbackConfig
  ): Promise<SearchResponse> {
    const eligible = this.getEligibleProviders(providers, "search", request.providerIds)

    if (eligible.length === 0) {
      throw new Error(
        "No active providers available for search. Please enable at least one search-capable provider in Settings."
      )
    }

    const waterfall: ProviderWaterfallItem[] = []
    const fallbackChain: string[] = []
    let finalResults: SearchResult[] = []
    let selectedProvider: ProviderConfig | null = null

    // Determine how many providers to query (parallel race for balanced/deep or primary with fallback)
    const providersToAttempt = fallbackConfig.enabled
      ? eligible.slice(0, Math.min(eligible.length, fallbackConfig.maxAttempts || 3))
      : [eligible[0]]

    let totalCost = 0
    const startTime = performance.now()

    for (let i = 0; i < providersToAttempt.length; i++) {
      const provider = providersToAttempt[i]
      fallbackChain.push(provider.id)

      // Simulate network latency tailored to provider's p95
      const simulatedLatency = Math.round(provider.latencyP95Ms * (0.8 + Math.random() * 0.35))
      await new Promise((resolve) => setTimeout(resolve, Math.min(simulatedLatency, 180)))

      // Simulated edge case: if provider is degraded or circuit breaker tripped
      const isRateLimited = provider.healthStatus === "rate_limited" && !provider.hasKey
      if (isRateLimited) {
        waterfall.push({
          providerId: provider.id,
          providerName: provider.name,
          latencyMs: simulatedLatency,
          status: "rate_limited",
          resultsCount: 0,
          costCredits: 0,
          error: "Rate limit exceeded (HTTP 429). Public tier window exhausted.",
        })

        if (!fallbackConfig.enabled) {
          throw new Error(`Provider ${provider.name} rate limited and fallbacks are disabled.`)
        }
        continue // cascade to next fallback
      }

      // Successful search generation
      selectedProvider = provider
      const resultsCount = Math.min(request.maxResults, 6)
      const cost = provider.capabilities.includes("keyless_tier") ? 0 : 1
      totalCost += cost

      const providerResults = this.generateMockSearchResults(request.query, provider, resultsCount)
      finalResults = providerResults

      waterfall.push({
        providerId: provider.id,
        providerName: provider.name,
        latencyMs: simulatedLatency,
        status: "success",
        resultsCount: providerResults.length,
        costCredits: cost,
      })

      // If we found results, we don't need further fallbacks
      break
    }

    if (!selectedProvider || finalResults.length === 0) {
      throw new Error("All attempted search providers failed to return results.")
    }

    const totalDuration = Math.round(performance.now() - startTime)

    return {
      query: request.query,
      results: finalResults,
      totalResults: finalResults.length,
      selectedProviderId: selectedProvider.id,
      fallbackChain,
      waterfall,
      executionTimeMs: totalDuration,
      costEstimateCredits: totalCost,
      timestamp: new Date().toISOString(),
    }
  }

  /**
   * Execute document fetch / content extraction
   */
  async executeFetch(
    request: FetchRequest,
    providers: ProviderConfig[],
    fallbackConfig: FallbackConfig
  ): Promise<FetchResponse> {
    const eligible = this.getEligibleProviders(
      providers,
      "fetch",
      request.providerId ? [request.providerId] : undefined
    )

    if (eligible.length === 0) {
      throw new Error(
        "No active providers available for document fetch. Verify fetch-capable providers (e.g. Keenable, Tavily, Firecrawl) are enabled."
      )
    }

    const fallbackChain: string[] = []
    let selectedProvider: ProviderConfig | null = null
    const startTime = performance.now()

    const providersToAttempt = fallbackConfig.enabled ? eligible : [eligible[0]]

    for (let i = 0; i < providersToAttempt.length; i++) {
      const provider = providersToAttempt[i]
      fallbackChain.push(provider.id)

      const simulatedLatency = Math.round(provider.latencyP95Ms * (0.9 + Math.random() * 0.4))
      await new Promise((resolve) => setTimeout(resolve, Math.min(simulatedLatency, 220)))

      selectedProvider = provider
      break
    }

    if (!selectedProvider) {
      throw new Error("Failed to fetch document through available providers.")
    }

    const document = this.generateMockFetchedDocument(request.url, selectedProvider, request.format)
    const totalDuration = Math.round(performance.now() - startTime)

    return {
      document,
      providerId: selectedProvider.id,
      fallbackChain,
      costEstimateCredits: selectedProvider.capabilities.includes("keyless_tier") ? 0 : 2,
      executionTimeMs: totalDuration,
      timestamp: new Date().toISOString(),
    }
  }

  /**
   * Test connection to a provider
   */
  async testConnection(
    provider: ProviderConfig
  ): Promise<{ success: boolean; latencyMs: number; message: string }> {
    const latency = Math.round(provider.latencyP95Ms * (0.8 + Math.random() * 0.4))
    await new Promise((resolve) => setTimeout(resolve, Math.min(latency, 200)))

    if (provider.healthStatus === "offline") {
      return {
        success: false,
        latencyMs: latency,
        message: `Connection refused: Host at ${provider.baseUrl} is unreachable.`,
      }
    }

    if (!provider.hasKey && !provider.capabilities.includes("keyless_tier")) {
      return {
        success: false,
        latencyMs: latency,
        message: "Missing API Key. Please configure credentials in the Key Vault.",
      }
    }

    return {
      success: true,
      latencyMs: latency,
      message: `Handshake verified. 200 OK via ${provider.name}.`,
    }
  }

  private generateMockSearchResults(
    query: string,
    provider: ProviderConfig,
    count: number
  ): SearchResult[] {
    const cleanQuery = query.trim() || "modern web architecture"
    const templates = [
      {
        titleSuffix: "- Comprehensive Architecture and Technical Reference",
        snippet: `In-depth analysis of ${cleanQuery}. Evaluates performance bottlenecks, asynchronous pipelines, and multi-provider reliability strategies in production environments.`,
        domain: "docs.freesearch.dev",
      },
      {
        titleSuffix: "Deep Dive: Best Practices and Benchmark Comparisons",
        snippet: `Comparing response times, precision, and cost structures for ${cleanQuery}. Includes empirical latency waterfalls and error-handling benchmarks.`,
        domain: "engineering.latency.tech",
      },
      {
        titleSuffix: "Specification, Protocols, and Resilience Patterns",
        snippet: `Protocol definitions and provider-neutral schemas relating to ${cleanQuery}. Focuses on graceful circuit breaker degradation and rate-limit mitigation.`,
        domain: "rfc.distributed-systems.org",
      },
      {
        titleSuffix: "Guide: Implementation and Edge Deployment Strategies",
        snippet: `Step-by-step walkthrough for orchestrating ${cleanQuery} at scale. Explores keyless fallback tiers, local caching, and request normalization.`,
        domain: "cloudnative.io",
      },
      {
        titleSuffix: "Community Discussion and Case Studies",
        snippet: `Real-world telemetry reports from teams implementing ${cleanQuery}. Highlights quota management and zero-downtime provider rollover.`,
        domain: "discuss.searchgateway.org",
      },
      {
        titleSuffix: "Official API Documentation and SDK Examples",
        snippet: `Reference documentation for ${cleanQuery} with Python, TypeScript, and Go SDK examples. Details headers, query parameters, and schema contracts.`,
        domain: "developer.gateway.io",
      },
    ]

    return templates.slice(0, count).map((t, idx) => ({
      id: `${provider.id}-${Date.now()}-${idx}`,
      providerId: provider.id,
      providerName: provider.name,
      title: `${cleanQuery} ${t.titleSuffix}`,
      url: `https://${t.domain}/${encodeURIComponent(cleanQuery.toLowerCase().replace(/\s+/g, "-"))}/guide-${idx + 1}`,
      snippet: t.snippet,
      relevanceScore: Math.round((0.98 - idx * 0.05) * 100) / 100,
      publishedDate: new Date(Date.now() - idx * 86400000 * 4).toISOString().split("T")[0],
      author: ["Elena Vance", "Marcus Shaw", "Devin Chen", "Aria Novak"][idx % 4],
      contentPreview: `# ${cleanQuery}\n\n${t.snippet}\n\n### Key Takeaways\n- Standardized provider-neutral contract\n- Circuit breaker protection enabled\n- Sub-second roundtrip across distributed nodes`,
    }))
  }

  private generateMockFetchedDocument(
    url: string,
    provider: ProviderConfig,
    format: "markdown" | "text" | "html"
  ): FetchedDocument {
    let hostname: string
    try {
      hostname = new URL(url).hostname
    } catch {
      hostname = url.replace(/https?:\/\//, "").split("/")[0] || "example.com"
    }

    const title = `Documentation: ${hostname.toUpperCase()} Technical Report`
    const markdown = `# ${title}

Extracted by **${provider.name}** via ${provider.capabilities.includes("live_crawl") ? "Live Dynamic Crawl" : "Scrape & Extract Engine"}.

## Executive Summary
This document was fetched directly from \`${url}\`. All superfluous scripts, tracking pixels, and navigation chrome were stripped, producing clean semantic markdown.

## Core Content
FreeSearch normalized this document through its shared \`FetchedDocument\` adapter contract.

\`\`\`typescript
interface FetchedDocument {
  url: "${url}";
  providerId: "${provider.id}";
  statusCode: 200;
  contentLength: 4812;
}
\`\`\`

### Extracted Highlights
1. **Full Text Fidelity**: 99.4% precision against original DOM tree.
2. **Media Handling**: SVGs and inline images converted to standard markdown tags.
3. **Latency**: Provider completed processing in ${provider.latencyP95Ms}ms.

---
*Timestamp: ${new Date().toUTCString()}*
`

    return {
      url,
      title,
      content: format === "html" ? `<h1>${title}</h1><p>Fetched from ${url}</p>` : markdown,
      markdown,
      extractedAuthor: "FreeSearch Scraper Engine",
      extractedDate: new Date().toISOString().split("T")[0],
      providerId: provider.id,
      providerName: provider.name,
      statusCode: 200,
      contentLength: markdown.length,
      executionTimeMs: provider.latencyP95Ms,
    }
  }
}

export const apiService = new FreeSearchApiService()
