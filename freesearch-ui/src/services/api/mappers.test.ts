import { describe, it, expect } from "vitest"
import {
  toBackendId,
  toUiId,
  mapSearchResponse,
  mapFetchResponse,
  mergeProviderStatus,
  mapBackendHealth,
  mapDashboardUsage,
  mapDashboardTotals,
  mapDashboardQuotas,
  mapRoutingConfig,
  normalizeUnitKind,
  unitLabel,
} from "./mappers"
import {
  catalogNameOf,
  searchResponseFixture,
  minimalSearchResponseFixture,
  fetchResponseFixture,
  dashboardFixture,
  canonicalQuotasFixture,
  canonicalTotalsFixture,
  canonicalRecentUsageFixture,
  providerStatus,
} from "@/test/fixtures"

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

  it("maps aggregated fanout wire to multi-source results with participating providers", () => {
    const wire = searchResponseFixture({
      provider: "aggregated",
      total_results: 1,
      results: [
        {
          title: "Fused Multi-Engine Hit",
          url: "https://example.com/consensus",
          snippet: "Verified snippet content",
          published_at: null,
          source: null,
          score: 0.95,
          metadata: {
            sources: ["exa", "brave"],
            source_ranks: { exa: 1, brave: 2 },
            rrf_score: 0.032,
          },
        },
      ],
      participating_providers: ["exa", "brave"],
    })
    const mapped = mapSearchResponse(wire as never, { wallClockMs, catalogNameOf })

    expect(mapped.selectedProviderId).toBe("aggregated")
    expect(mapped.participatingProviders).toEqual(["exa", "brave"])
    expect(mapped.results).toHaveLength(1)
    const [fused] = mapped.results
    // aggregated resolves to the primary source via toUiId
    expect(fused.providerId).toBe("exa")
    expect(fused.providerName).toBe("exa, brave")
    expect(fused.sources).toEqual(["exa", "brave"])
    expect(fused.relevanceScore).toBe(0.95)
    expect(fused.rawMetadata).toMatchObject({ rrf_score: 0.032 })
  })

  it("maps multi-provider wire waterfall trace items when provided", () => {
    const wire = {
      ...searchResponseFixture(),
      provider: "aggregated",
      waterfall: [
        {
          provider: "brave",
          latency_ms: 320,
          status: "success",
          results_count: 5,
        },
        {
          provider: "exa",
          latency_ms: 1200,
          status: "success",
          results_count: 4,
        },
      ],
    }
    const mapped = mapSearchResponse(wire as never, { wallClockMs, catalogNameOf })
    expect(mapped.waterfall).toHaveLength(2)
    expect(mapped.waterfall[0]).toMatchObject({
      providerId: "brave",
      providerName: "Brave Search",
      latencyMs: 320,
      status: "success",
      resultsCount: 5,
    })
    expect(mapped.waterfall[1]).toMatchObject({
      providerId: "exa",
      providerName: "Exa",
      latencyMs: 1200,
      status: "success",
      resultsCount: 4,
    })
  })

  it("falls back to result.sources when metadata.sources is absent", () => {
    const wire = searchResponseFixture({
      provider: "tavily",
      total_results: 1,
      results: [
        {
          title: "Single-engine hit",
          url: "https://example.com/solo",
          snippet: "Solo snippet.",
          published_at: null,
          source: null,
          score: 0.5,
          metadata: {},
          sources: ["tavily"],
        },
      ],
    })
    const mapped = mapSearchResponse(wire as never, { wallClockMs, catalogNameOf })

    expect(mapped.results).toHaveLength(1)
    const [solo] = mapped.results
    expect(solo.providerId).toBe("tavily")
    expect(solo.providerName).toBe("tavily")
    expect(solo.sources).toEqual(["tavily"])
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
    // so unknown usage must render as "—/—", never "0/—" (which misreads as
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

describe("normalizeUnitKind (QUOTA.md Option A)", () => {
  it("passes through the four canonical uppercase kinds", () => {
    expect(normalizeUnitKind("REQUEST")).toBe("REQUEST")
    expect(normalizeUnitKind("CREDIT")).toBe("CREDIT")
    expect(normalizeUnitKind("USD")).toBe("USD")
    expect(normalizeUnitKind("FREE")).toBe("FREE")
  })

  it("tolerates lowercase wire values via case-insensitive normalization", () => {
    expect(normalizeUnitKind("credit")).toBe("CREDIT")
    expect(normalizeUnitKind("request")).toBe("REQUEST")
    expect(normalizeUnitKind("usd")).toBe("USD")
    expect(normalizeUnitKind("free")).toBe("FREE")
    expect(normalizeUnitKind("Credit")).toBe("CREDIT")
  })

  it("maps unknown, null, undefined, and non-string inputs to null (legacy)", () => {
    expect(normalizeUnitKind("TOKENS")).toBeNull()
    expect(normalizeUnitKind("")).toBeNull()
    expect(normalizeUnitKind(null)).toBeNull()
    expect(normalizeUnitKind(undefined)).toBeNull()
    expect(normalizeUnitKind(42)).toBeNull()
    expect(normalizeUnitKind({})).toBeNull()
  })

  it("never throws for absent wire fields (unit_kind omitted → null)", () => {
    expect(normalizeUnitKind(({} as { unit_kind?: unknown }).unit_kind)).toBeNull()
  })
})

describe("unitLabel", () => {
  it("prefers the explicit display_unit over the kind default", () => {
    expect(unitLabel("CREDIT", "credits")).toBe("credits")
    expect(unitLabel("REQUEST", "requests")).toBe("requests")
    expect(unitLabel(null, "custom-label")).toBe("custom-label")
  })

  it("falls back to kind defaults and legacy for null kind", () => {
    expect(unitLabel("REQUEST", null)).toBe("requests")
    expect(unitLabel("CREDIT", null)).toBe("credits")
    expect(unitLabel("USD", null)).toBe("USD")
    expect(unitLabel("FREE", null)).toBe("free")
    expect(unitLabel(null, null)).toBe("legacy")
  })
})

describe("mapDashboardTotals (triple-keyed, QUOTA.md AC-3)", () => {
  it("keys by (provider, operation, unit_kind): same provider+operation with different kinds stay separate", () => {
    const totals = mapDashboardTotals(
      dashboardFixture({ usage_totals: canonicalTotalsFixture() }) as never
    )

    expect(totals).toHaveLength(4)
    const tavilySearch = totals.filter(
      (t) => t.provider === "tavily" && t.operation === "search"
    )
    expect(tavilySearch).toHaveLength(2)
    const kinds = tavilySearch.map((t) => t.unitKind).sort()
    expect(kinds).toEqual(["CREDIT", "USD"])
    expect(tavilySearch.find((t) => t.unitKind === "CREDIT")?.total_units).toBe("3.5")
    expect(tavilySearch.find((t) => t.unitKind === "USD")?.total_units).toBe("0.007")
  })

  it("preserves total_units verbatim as strings and keeps event counts", () => {
    const totals = mapDashboardTotals(
      dashboardFixture({ usage_totals: canonicalTotalsFixture() }) as never
    )

    for (const total of totals) {
      expect(typeof total.total_units).toBe("string")
    }
    expect(totals.find((t) => t.provider === "tavily" && t.unitKind === "CREDIT")).toMatchObject({
      total_units: "3.5",
      eventCount: 4,
    })
    expect(totals.find((t) => t.provider === "brave")).toMatchObject({
      total_units: "12",
      unitKind: "REQUEST",
      eventCount: 12,
    })
  })

  it("projects a legacy null-kind row without merging it into a known dimension", () => {
    const totals = mapDashboardTotals(
      dashboardFixture({ usage_totals: canonicalTotalsFixture() }) as never
    )

    const legacy = totals.find((t) => t.provider === "exa")
    expect(legacy).toBeDefined()
    expect(legacy?.unitKind).toBeNull()
    expect(legacy?.total_units).toBe("9")
    expect(legacy?.eventCount).toBe(9)
    // Legacy rows never share a key with a known dimension.
    expect(totals.filter((t) => t.provider === "exa")).toHaveLength(1)
  })

  it("maps backend 'you' to UI 'youcom' in totals", () => {
    const totals = mapDashboardTotals(
      dashboardFixture({
        usage_totals: [
          { provider: "you", operation: "search", total_units: "4.75", event_count: 7, unit_kind: "USD" },
        ],
      }) as never
    )

    expect(totals).toHaveLength(1)
    expect(totals[0].provider).toBe("youcom")
    expect(totals[0].unitKind).toBe("USD")
    expect(totals[0].total_units).toBe("4.75")
  })

  it("defaults a missing unit_kind to null (legacy) instead of guessing", () => {
    const totals = mapDashboardTotals(
      dashboardFixture({
        usage_totals: [
          { provider: "tavily", operation: "search", total_units: "3.5", event_count: 4 },
        ],
      }) as never
    )

    expect(totals[0].unitKind).toBeNull()
  })
})

describe("mapDashboardQuotas (confidence/reset passthrough, RF1 verbatim limits)", () => {
  it("passes confidence source, reset_at, unitKind, and displayUnit through untouched", () => {
    const quotas = mapDashboardQuotas(
      dashboardFixture({ latest_quota: canonicalQuotasFixture() }) as never
    )

    expect(quotas).toHaveLength(4)
    expect(quotas.find((q) => q.provider === "tavily")).toMatchObject({
      source: "authoritative",
      unitKind: "CREDIT",
      displayUnit: "credits",
      remainingPercent: "90.00005",
      resetAt: null,
      observed_at: "2026-09-06T18:00:00Z",
    })
    expect(quotas.find((q) => q.provider === "brave")).toMatchObject({
      source: "observed",
      unitKind: "REQUEST",
      displayUnit: "requests",
      remainingPercent: "95",
      resetAt: "2026-10-01T00:00:00Z",
    })
    expect(quotas.find((q) => q.provider === "youcom")).toMatchObject({
      source: "estimated",
      unitKind: "USD",
      displayUnit: "USD",
      limit: null,
    })
  })

  it("RF1: preserves exact limit strings verbatim ('100000.10' stays, '0.00000001' never becomes 1e-8)", () => {
    const quotas = mapDashboardQuotas(
      dashboardFixture({ latest_quota: canonicalQuotasFixture() }) as never
    )

    const tavily = quotas.find((q) => q.provider === "tavily")!
    expect(typeof tavily.limit).toBe("string")
    expect(tavily.limit).toBe("100000.10")
    expect(tavily.limit).not.toBe("100000.1")

    const legacy = quotas.find((q) => q.provider === "exa")!
    expect(typeof legacy.limit).toBe("string")
    expect(legacy.limit).toBe("0.00000001")
    expect(String(legacy.limit)).not.toContain("e-")
    expect(legacy.limit).not.toBe("1e-8")
    expect(legacy.remaining).toBe("0.00000005")
  })

  it("keeps You.com ESTIMATED limit null (never fabricates a hard cap)", () => {
    const quotas = mapDashboardQuotas(
      dashboardFixture({ latest_quota: canonicalQuotasFixture() }) as never
    )

    const you = quotas.find((q) => q.provider === "youcom")!
    expect(you.limit).toBeNull()
    expect(you.remaining).toBe("4.75")
    expect(you.source).toBe("estimated")
  })

  it("projects the null-kind legacy quota row with null unitKind/displayUnit", () => {
    const quotas = mapDashboardQuotas(
      dashboardFixture({ latest_quota: canonicalQuotasFixture() }) as never
    )

    const legacy = quotas.find((q) => q.provider === "exa")!
    expect(legacy.unitKind).toBeNull()
    expect(legacy.displayUnit).toBeNull()
    expect(legacy.source).toBe("estimated")
  })

  it("maps backend 'you' to UI 'youcom' in quotas", () => {
    const quotas = mapDashboardQuotas(
      dashboardFixture({ latest_quota: canonicalQuotasFixture() }) as never
    )

    expect(quotas.map((q) => q.provider)).not.toContain("you")
    expect(quotas.map((q) => q.provider)).toContain("youcom")
  })

  it("returns an empty list when the dashboard carries no quota snapshots", () => {
    expect(mapDashboardQuotas(dashboardFixture({ latest_quota: [] }) as never)).toEqual([])
  })
})

describe("mapDashboardUsage (canonical units)", () => {
  it("passes unitKind/displayUnit through for CREDIT, REQUEST, and USD rows", () => {
    const events = mapDashboardUsage(
      dashboardFixture({ recent_usage: canonicalRecentUsageFixture() }) as never,
      catalogNameOf
    )

    expect(events).toHaveLength(4)
    expect(events[0]).toMatchObject({ providerId: "tavily", unitKind: "CREDIT", displayUnit: "credits" })
    expect(events[1]).toMatchObject({ providerId: "brave", unitKind: "REQUEST", displayUnit: "requests" })
    expect(events[2]).toMatchObject({ providerId: "youcom", unitKind: "USD", displayUnit: "USD" })
  })

  it("projects a legacy row with null unitKind/displayUnit for missing wire fields", () => {
    const events = mapDashboardUsage(
      dashboardFixture({ recent_usage: canonicalRecentUsageFixture() }) as never,
      catalogNameOf
    )

    const legacy = events.find((e) => e.providerId === "exa")!
    expect(legacy.unitKind).toBeNull()
    expect(legacy.displayUnit).toBeNull()
  })

  it("carries canonical kinds on the default dashboard fixture (gap lock-in)", () => {
    const events = mapDashboardUsage(dashboardFixture() as never, catalogNameOf)

    expect(events[0].unitKind).toBe("CREDIT")
    expect(events[0].displayUnit).toBe("credits")
    expect(events[1].unitKind).toBe("REQUEST")
    expect(events[1].displayUnit).toBe("requests")
  })
})
