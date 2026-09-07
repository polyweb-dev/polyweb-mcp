import { describe, it, expect } from "vitest"
import {
  toBackendId,
  toUiId,
  mapSearchResponse,
  mapFetchResponse,
  mergeProviderStatus,
  mapBackendHealth,
  mapDashboardUsage,
  mapRoutingConfig,
} from "./mappers"
import {
  catalogNameOf,
  searchResponseFixture,
  minimalSearchResponseFixture,
  fetchResponseFixture,
  dashboardFixture,
  providerStatus,
} from "@/test/backendFixtures"

/**
 * RED: `src/services/api/mappers.ts` does not exist yet. The Developer
 * implements the pure wire→UI mappers exactly per the integration plan:
 * deterministic ids (no Date.now), score/published_at/source fallbacks,
 * single-entry waterfall, Decimal-string costs, you↔youcom id mapping,
 * breaker-open → circuit_broken override, dashboard UsageEvent projection.
 */

describe("toBackendId / toUiId", () => {
  it("maps youcom to the backend id 'you' and leaves every other id alone", () => {
    expect(toBackendId("youcom")).toBe("you")
    for (const id of ["brave", "keenable", "tavily", "exa", "firecrawl", "parallel"]) {
      expect(toBackendId(id)).toBe(id)
    }
  })

  it("maps backend 'you' back to UI id 'youcom' and leaves others alone", () => {
    expect(toUiId("you")).toBe("youcom")
    for (const id of ["brave", "keenable", "tavily", "exa", "firecrawl", "parallel"]) {
      expect(toUiId(id)).toBe(id)
    }
  })

  it("round-trips UI ids through the backend mapping", () => {
    for (const id of ["brave", "keenable", "tavily", "exa", "firecrawl", "youcom", "parallel"]) {
      expect(toUiId(toBackendId(id))).toBe(id)
    }
  })
})

describe("mapSearchResponse", () => {
  const wallClockMs = 250

  it("maps a full wire response to the UI SearchResponse contract", () => {
    const mapped = mapSearchResponse(searchResponseFixture() as never, {
      wallClockMs,
      catalogNameOf,
    })

    expect(mapped.query).toBe("live backend query")
    expect(mapped.totalResults).toBe(2)
    expect(mapped.selectedProviderId).toBe("tavily")
    expect(mapped.fallbackChain).toEqual(["tavily"])
    expect(mapped.executionTimeMs).toBe(187)
    expect(mapped.costEstimateCredits).toBe(1)
    expect(mapped.timestamp).toBe("2026-09-06T10:02:00Z")

    expect(mapped.results).toHaveLength(2)
    const [first, second] = mapped.results
    expect(first.title).toBe("Live backend result one")
    expect(first.url).toBe("https://example.com/one")
    expect(first.snippet).toBe("First live snippet.")
    expect(first.relevanceScore).toBe(0.92)
    expect(first.publishedDate).toBe("2026-09-05")
    expect(first.providerId).toBe("tavily")
    expect(first.providerName).toBe("Example Source")

    // Null wire fields fall back: score→0, no publishedDate, providerName→provider id label
    expect(second.relevanceScore).toBe(0)
    expect(second.publishedDate).toBeUndefined()
    expect(second.providerName).toBe("tavily")
  })

  it("builds a SINGLE-entry waterfall from usage (never multi-hop)", () => {
    const mapped = mapSearchResponse(searchResponseFixture() as never, {
      wallClockMs,
      catalogNameOf,
    })

    expect(mapped.waterfall).toHaveLength(1)
    expect(mapped.waterfall[0]).toMatchObject({
      providerId: "tavily",
      providerName: "Tavily",
      latencyMs: 187,
      status: "success",
      resultsCount: 2,
      costCredits: 1,
    })
  })

  it("forces decimal-string usage units '1' to numeric cost 1", () => {
    const mapped = mapSearchResponse(searchResponseFixture() as never, {
      wallClockMs,
      catalogNameOf,
    })

    expect(mapped.costEstimateCredits).toBe(1)
    expect(mapped.waterfall[0].costCredits).toBe(1)
  })

  it("parses fractional decimal strings such as '0.001'", () => {
    const wire = searchResponseFixture({
      usage: {
        provider: "tavily",
        operation: "search",
        units: "0.001",
        observed_at: "2026-09-06T10:02:00Z",
        request_id: null,
        metadata: {},
        latency_ms: 50,
        status: "success",
      },
    })
    const mapped = mapSearchResponse(wire as never, { wallClockMs, catalogNameOf })

    expect(mapped.costEstimateCredits).toBeCloseTo(0.001, 6)
    expect(mapped.waterfall[0].costCredits).toBeCloseTo(0.001, 6)
  })

  it("falls back to wallClockMs and zero cost when usage is null", () => {
    const mapped = mapSearchResponse(minimalSearchResponseFixture() as never, {
      wallClockMs,
      catalogNameOf,
    })

    expect(mapped.query).toBe("minimal query")
    expect(mapped.results).toEqual([])
    expect(mapped.selectedProviderId).toBe("youcom")
    expect(mapped.fallbackChain).toEqual(["youcom"])
    expect(mapped.executionTimeMs).toBe(wallClockMs)
    expect(mapped.costEstimateCredits).toBe(0)
    expect(mapped.waterfall).toHaveLength(1)
    expect(mapped.waterfall[0]).toMatchObject({
      providerId: "youcom",
      latencyMs: wallClockMs,
      status: "success",
      resultsCount: 0,
      costCredits: 0,
    })
    expect(typeof mapped.timestamp).toBe("string")
    expect(mapped.timestamp.length).toBeGreaterThan(0)
  })

  it("is deterministic: repeated calls produce identical result ids (no Date.now)", () => {
    const wire = searchResponseFixture()
    const first = mapSearchResponse(wire as never, { wallClockMs, catalogNameOf })
    const second = mapSearchResponse(wire as never, { wallClockMs, catalogNameOf })

    expect(first.results.map((r) => r.id)).toEqual(second.results.map((r) => r.id))
    for (const result of first.results) {
      expect(typeof result.id).toBe("string")
      expect(result.id.length).toBeGreaterThan(0)
    }
    const ids = new Set(first.results.map((r) => r.id))
    expect(ids.size).toBe(first.results.length)
  })
})

describe("mapFetchResponse", () => {
  const wallClockMs = 300

  it("maps document fields with a null status and measured length", () => {
    const mapped = mapFetchResponse(fetchResponseFixture() as never, { wallClockMs })

    expect(mapped.document.url).toBe("https://example.com/doc")
    expect(mapped.document.title).toBe("Live document title")
    expect(mapped.document.content).toBe("# Live document\n\nFetched markdown body.")
    expect(mapped.document.markdown).toBe("# Live document\n\nFetched markdown body.")
    // Truth: the backend never returns a status — the field stays null
    // (type number | null). Byte-length rendering is computed UI-side.
    expect("statusCode" in mapped.document).toBe(true)
    expect(mapped.document.statusCode).toBeNull()
    expect(mapped.document.contentLength).toBe("# Live document\n\nFetched markdown body.".length)
    expect(mapped.providerId).toBe("firecrawl")
    expect(mapped.executionTimeMs).toBe(412)
    expect(mapped.timestamp).toBe("2026-09-06T10:03:01Z")
  })

  it("falls back to the URL when the wire title is null", () => {
    const wire = fetchResponseFixture({
      document: {
        url: "https://example.com/untitled",
        content: "body",
        title: null,
        content_type: null,
        fetched_at: "2026-09-06T10:03:00Z",
        metadata: {},
      },
      usage: null,
    })
    const mapped = mapFetchResponse(wire as never, { wallClockMs })

    expect(mapped.document.title).toBe("https://example.com/untitled")
    expect(mapped.document.contentLength).toBe(4)
    expect(mapped.executionTimeMs).toBe(wallClockMs)
  })
})

describe("mapBackendHealth", () => {
  it.each([
    ["healthy", "healthy"],
    ["degraded", "degraded"],
    ["unavailable", "offline"],
    ["unknown", "degraded"],
    [null, "offline"],
  ] as const)("maps backend %j to UI %j with a closed breaker", (backend, ui) => {
    expect(mapBackendHealth(backend, "closed")).toBe(ui)
  })

  it("overrides any backend health with circuit_broken when the breaker is open", () => {
    for (const health of ["healthy", "degraded", "unavailable", "unknown", null] as const) {
      expect(mapBackendHealth(health, "open")).toBe("circuit_broken")
    }
  })

  it("does not override health when the breaker is half_open", () => {
    expect(mapBackendHealth("healthy", "half_open")).toBe("healthy")
    expect(mapBackendHealth("degraded", "half_open")).toBe("degraded")
  })
})

describe("mergeProviderStatus", () => {
  const catalogEntry = {
    id: "tavily",
    backendId: "tavily",
    name: "Tavily",
    description: "AI-native search engine.",
    baseUrl: "https://api.tavily.com",
    authHeaderName: "Authorization",
    capabilities: ["search", "fetch", "extract"],
  } as never

  it("merges wire status over the static catalog entry", () => {
    const merged = mergeProviderStatus(catalogEntry, providerStatus("tavily") as never)

    expect(merged.id).toBe("tavily")
    expect(merged.name).toBe("Tavily")
    expect(merged.baseUrl).toBe("https://api.tavily.com")
    expect(merged.globalEnabled).toBe(true)
    expect(merged.priority).toBe(3)
    expect(merged.circuitBreaker).toBe("closed")
    expect(merged.healthStatus).toBe("healthy")
    expect(merged.latencyP95Ms).toBe(130)
    expect(merged.hasKey).toBe(true)
    expect(merged.keyVaultStatus).toBe("configured")
    expect(merged.keyMasked).toBe("—")
  })

  it("renders null p95 latency (never NaN) and marks keyless tiers as keyed", () => {
    const keenableEntry = {
      id: "keenable",
      backendId: "keenable",
      name: "Keenable",
      description: "Keyless tier.",
      baseUrl: "https://api.keenable.ai/v1",
      authHeaderName: "X-API-Key",
      capabilities: ["search", "fetch", "keyless_tier"],
    } as never
    const merged = mergeProviderStatus(
      keenableEntry,
      providerStatus("keenable", { latency_p95_ms: null }) as never
    )

    expect(merged.latencyP95Ms).toBeNull()
    expect(merged.hasKey).toBe(true)
    expect(merged.keyVaultStatus).toBe("keyless_public")
  })

  it("marks missing secrets as keyless-false and trips open breakers", () => {
    const merged = mergeProviderStatus(
      catalogEntry,
      providerStatus("tavily", {
        health: "healthy",
        circuit_breaker: { state: "open", updated_at: "2026-09-06T00:00:00Z" },
        secret_presence: "missing",
      }) as never
    )

    expect(merged.hasKey).toBe(false)
    expect(merged.keyVaultStatus).toBe("missing")
    expect(merged.circuitBreaker).toBe("open")
    expect(merged.healthStatus).toBe("circuit_broken")
  })

  it("projects quota from free-tier estimates with null limit and estimated confidence", () => {
    const merged = mergeProviderStatus(catalogEntry, providerStatus("tavily") as never)

    expect(merged.quota.limit).toBeNull()
    expect(merged.quota.confidence).toBe("estimated")
  })

  it("P3(a): leaves quota used unknown (null) instead of fabricating zero", () => {
    // Honest placeholder: the backend exposes no authoritative usage total,
    // so unknown usage must render as "—/∞", never "0/∞" (which misreads as
    // "nothing consumed"). RED until the Developer flips mappers.ts used: 0 → null.
    const merged = mergeProviderStatus(catalogEntry, providerStatus("tavily") as never)

    expect(merged.quota.used).toBeNull()
  })
})

describe("mapDashboardUsage", () => {
  it("projects recent usage into UsageEvents with deterministic ids", () => {
    const events = mapDashboardUsage(dashboardFixture() as never, catalogNameOf)

    expect(events).toHaveLength(2)
    const [first, second] = events
    expect(first.id).toBe("2026-09-06T10:00:00Z-tavily-0")
    expect(first.queryOrUrl).toBe("")
    expect(first.operation).toBe("search")
    expect(first.providerId).toBe("tavily")
    expect(first.providerName).toBe("Tavily")
    expect(first.latencyMs).toBe(230)
    expect(first.costCredits).toBe(1)
    expect(first.status).toBe("success")
    expect(first.routeReason).toBe("Recorded search via tavily")
    expect(first.fallbackChain).toEqual(["tavily"])

    // failure → error, null latency preserved, fractional units parsed
    expect(second.id).toBe("2026-09-06T09:55:00Z-brave-1")
    expect(second.status).toBe("error")
    expect(second.latencyMs).toBeNull()
    expect(second.costCredits).toBeCloseTo(0.001, 6)
    expect(second.routeReason).toBe("Recorded fetch via brave")
  })

  it("returns an empty list for an empty dashboard", () => {
    expect(
      mapDashboardUsage(dashboardFixture({ recent_usage: [] }) as never, catalogNameOf)
    ).toEqual([])
  })

  it("never leaks request targets: queryOrUrl is always empty", () => {
    const events = mapDashboardUsage(dashboardFixture() as never, catalogNameOf)
    for (const event of events) {
      expect(event.queryOrUrl).toBe("")
    }
  })
})

describe("mapRoutingConfig", () => {
  it("maps chained policy to enabled fallbacks", () => {
    expect(
      mapRoutingConfig({ fallback_policy: "chained", max_attempts: 3 } as never)
    ).toEqual({ enabled: true, maxAttempts: 3 })
  })

  it("maps first_only policy to disabled fallbacks", () => {
    expect(
      mapRoutingConfig({ fallback_policy: "first_only", max_attempts: 1 } as never)
    ).toEqual({ enabled: false, maxAttempts: 1 })
  })
})
