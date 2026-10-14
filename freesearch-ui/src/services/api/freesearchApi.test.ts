import { describe, it, expect, afterEach, vi } from "vitest"
import { FreeSearchApiService } from "./freesearchApi"
import { ApiError } from "@/shared/api/http"
import { installFetchStub, ok, err } from "@/test/fetchMock"
import {
  allProvidersFixture,
  routingConfigFixture,
  dashboardFixture,
  searchResponseFixture,
  fetchResponseFixture,
  providerTestFixture,
  secretStatusFixture,
  breakerResetFixture,
  traceDetailFixture,
  traceListFixture,
} from "@/test/backendFixtures"

/**
 * RED rewrite: the mock `FreeSearchApiService` (getEligibleProviders,
 * executeSearch/executeFetch/testConnection, setTimeout latency) is replaced
 * by real HTTP over same-origin RELATIVE paths. Every test stubs the global
 * fetch, asserts the exact wire request (relative URL, method, JSON body with
 * no extra keys, headers), and restores the stub afterwards.
 *
 * Expected service surface (Developer implements in freesearchApi.ts, keeping
 * the class name FreeSearchApiService + singleton apiService):
 * listProviders, getRoutingConfig, updateRoutingConfig, patchProvider,
 * testProvider, resetCircuitBreaker, putSecret, deleteSecret, search,
 * fetchDoc, getDashboard. Old executeSearch/executeFetch/testConnection/
 * getEligibleProviders/generateMock* are REMOVED.
 */
describe("FreeSearchApiService (live HTTP)", () => {
  const service = new FreeSearchApiService()

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it("exposes the live-backend method surface and drops the mock API", () => {
    for (const method of [
      "listProviders",
      "getRoutingConfig",
      "updateRoutingConfig",
      "patchProvider",
      "testProvider",
      "resetCircuitBreaker",
      "putSecret",
      "deleteSecret",
      "search",
      "fetchDoc",
      "getDashboard",
    ]) {
      expect(typeof (service as unknown as Record<string, unknown>)[method]).toBe(
        "function"
      )
    }
    for (const removed of [
      "getEligibleProviders",
      "executeSearch",
      "executeFetch",
      "testConnection",
      "generateMockSearchResults",
      "generateMockFetchedDocument",
    ]) {
      expect(
        (service as unknown as Record<string, unknown>)[removed]
      ).toBeUndefined()
    }
  })

  it("search() POSTs the exact BackendSearchRequest to relative /search", async () => {
    const wire = searchResponseFixture()
    const stub = installFetchStub((req) => {
      expect(req.url).toBe("/search")
      expect(req.method).toBe("POST")
      return ok(wire)
    })

    const body = {
      query: "live backend query",
      limit: 10,
      language: null,
      country_code: null,
      domains: [],
      routing: { mode: "prefer", providers: ["tavily"], allow_fallback: true },
    }
    const result = await service.search(body as never)

    expect(stub.requests).toHaveLength(1)
    expect(stub.requests[0].body).toEqual(body)
    expect(stub.requests[0].headers["content-type"]).toContain("application/json")
    expect(result).toEqual(wire)
  })

  it("fetchDoc() POSTs the exact BackendFetchRequest to relative /fetch", async () => {
    const wire = fetchResponseFixture()
    const stub = installFetchStub(() => ok(wire))

    const body = {
      url: "https://example.com/doc",
      max_chars: null,
      routing: { mode: "auto", providers: ["firecrawl"], allow_fallback: true },
    }
    const result = await service.fetchDoc(body as never)

    expect(stub.requests).toHaveLength(1)
    expect(stub.requests[0].url).toBe("/fetch")
    expect(stub.requests[0].method).toBe("POST")
    expect(stub.requests[0].body).toEqual(body)
    expect(result).toEqual(wire)
  })

  it("listProviders() GETs relative /api/v1/providers with no body", async () => {
    const wire = allProvidersFixture()
    const stub = installFetchStub(() => ok(wire))

    const result = await service.listProviders()

    expect(stub.requests).toHaveLength(1)
    expect(stub.requests[0].url).toBe("/api/v1/providers")
    expect(stub.requests[0].method).toBe("GET")
    expect(stub.requests[0].bodyText).toBeUndefined()
    expect(result).toEqual(wire)
  })

  it("getRoutingConfig() GETs relative /api/v1/routing/config", async () => {
    const wire = routingConfigFixture()
    const stub = installFetchStub(() => ok(wire))

    const result = await service.getRoutingConfig()

    expect(stub.requests[0].url).toBe("/api/v1/routing/config")
    expect(stub.requests[0].method).toBe("GET")
    expect(result).toEqual(wire)
  })

  it("updateRoutingConfig() PUTs the full routing object (never all-null)", async () => {
    const wire = routingConfigFixture({ fallback_policy: "first_only", max_attempts: 1 })
    const stub = installFetchStub(() => ok(wire))

    const full = {
      fallback_policy: "first_only",
      cost_optimization_preset: "balanced",
      max_attempts: 1,
    }
    const result = await service.updateRoutingConfig(full as never)

    expect(stub.requests[0].url).toBe("/api/v1/routing/config")
    expect(stub.requests[0].method).toBe("PUT")
    expect(stub.requests[0].body).toEqual(full)
    expect(result).toEqual(wire)
  })

  it("patchProvider() PATCHes ONLY the set keys (strict bools/ints, no extras)", async () => {
    const updated = { ...allProvidersFixture()[0], enabled: false }
    const stub = installFetchStub(() => ok(updated))

    await service.patchProvider("brave", { enabled: false } as never)

    expect(stub.requests[0].url).toBe("/api/v1/providers/brave")
    expect(stub.requests[0].method).toBe("PATCH")
    expect(stub.requests[0].body).toEqual({ enabled: false })
    expect(JSON.parse(stub.requests[0].bodyText!)).toEqual({ enabled: false })
  })

  it("patchProvider() sends a real-int priority without coercion", async () => {
    const stub = installFetchStub(() => ok(allProvidersFixture()[3]))

    await service.patchProvider("exa", { priority: 2 } as never)

    expect(stub.requests[0].body).toEqual({ priority: 2 })
    expect(typeof (stub.requests[0].body as { priority: unknown }).priority).toBe(
      "number"
    )
  })

  it("patchProvider() sends one-bit search and fetch bodies", async () => {
    const searchStub = installFetchStub(() => ok(allProvidersFixture()[3]))
    await service.patchProvider("exa", { search_enabled: false } as never)
    expect(searchStub.requests[0].url).toBe("/api/v1/providers/exa")
    expect(searchStub.requests[0].method).toBe("PATCH")
    expect(searchStub.requests[0].body).toEqual({ search_enabled: false })
    vi.unstubAllGlobals()

    const fetchStub = installFetchStub(() => ok(allProvidersFixture()[3]))
    await service.patchProvider("exa", { fetch_enabled: true } as never)
    expect(fetchStub.requests[0].body).toEqual({ fetch_enabled: true })
    vi.unstubAllGlobals()
  })

  it("patchProvider() sends a complete enable_mask replacement as one key", async () => {
    const stub = installFetchStub(() => ok(allProvidersFixture()[0]))
    await service.patchProvider("brave", { enable_mask: 6 } as never)
    expect(stub.requests[0].body).toEqual({ enable_mask: 6 })
    expect(typeof (stub.requests[0].body as { enable_mask: unknown }).enable_mask).toBe(
      "number",
    )
  })

  it("patchProvider() never sends support_mask or unknown keys", async () => {
    const stub = installFetchStub(() => ok(allProvidersFixture()[0]))
    await service.patchProvider(
      "brave",
      { enabled: false, support_mask: 7, extra: true } as never,
    )
    expect(stub.requests[0].body).toEqual({ enabled: false })
    expect("support_mask" in (stub.requests[0].body as object)).toBe(false)
    expect("extra" in (stub.requests[0].body as object)).toBe(false)
  })

  it("patchProvider() sends the whitelisted tavily_key_environment field", async () => {
    const updated = { ...allProvidersFixture()[2], tavily_key_environment: "prod" }
    const stub = installFetchStub(() => ok(updated))

    const result = await service.patchProvider("tavily", { tavily_key_environment: "prod" } as never)

    expect(stub.requests[0].url).toBe("/api/v1/providers/tavily")
    expect(stub.requests[0].method).toBe("PATCH")
    expect(stub.requests[0].body).toEqual({ tavily_key_environment: "prod" })
    expect(JSON.parse(stub.requests[0].bodyText!)).toEqual({ tavily_key_environment: "prod" })
    expect(result).toEqual(updated)
  })

  it("patchProvider() PATCHes the exact Tavily path with a dev-only partial body", async () => {
    const updated = { ...allProvidersFixture()[2], tavily_key_environment: "dev" }
    const stub = installFetchStub(() => ok(updated))

    await service.patchProvider("tavily", { tavily_key_environment: "dev" } as never)

    expect(stub.requests).toHaveLength(1)
    expect(stub.requests[0].url).toBe("/api/v1/providers/tavily")
    expect(stub.requests[0].method).toBe("PATCH")
    expect(Object.keys(stub.requests[0].body as object)).toEqual(["tavily_key_environment"])
  })

  it("patchProvider() omits unset fields so stored values survive a tier change", async () => {
    const stub = installFetchStub(() => ok(allProvidersFixture()[2]))

    await service.patchProvider("tavily", { tavily_key_environment: "prod" } as never)

    const body = stub.requests[0].body as Record<string, unknown>
    expect(body).toEqual({ tavily_key_environment: "prod" })
    for (const preserved of ["enable_mask", "enabled", "search_enabled", "fetch_enabled", "priority"]) {
      expect(preserved in body).toBe(false)
    }
  })

  it("patchProvider() keeps access and priority patches free of the tier field", async () => {
    const accessStub = installFetchStub(() => ok(allProvidersFixture()[0]))
    await service.patchProvider("brave", { enabled: false } as never)
    expect(accessStub.requests[0].body).toEqual({ enabled: false })
    vi.unstubAllGlobals()

    const priorityStub = installFetchStub(() => ok(allProvidersFixture()[3]))
    await service.patchProvider("exa", { priority: 2 } as never)
    expect(priorityStub.requests[0].body).toEqual({ priority: 2 })
    vi.unstubAllGlobals()
  })

  it("testProvider() POSTs relative /api/v1/providers/{id}/test", async () => {
    const wire = providerTestFixture()
    const stub = installFetchStub(() => ok(wire))

    const result = await service.testProvider("brave")

    expect(stub.requests[0].url).toBe("/api/v1/providers/brave/test")
    expect(stub.requests[0].method).toBe("POST")
    expect(result).toEqual(wire)
  })

  it("resetCircuitBreaker() POSTs relative .../circuit-breaker/reset", async () => {
    const wire = breakerResetFixture("brave")
    const stub = installFetchStub(() => ok(wire))

    const result = await service.resetCircuitBreaker("brave")

    expect(stub.requests[0].url).toBe(
      "/api/v1/providers/brave/circuit-breaker/reset"
    )
    expect(stub.requests[0].method).toBe("POST")
    expect(result).toEqual(wire)
  })

  it("putSecret() PUTs exactly {key} to relative .../secret", async () => {
    const wire = secretStatusFixture()
    const stub = installFetchStub(() => ok(wire))

    const result = await service.putSecret("tavily", "tvly-live-key-123")

    expect(stub.requests[0].url).toBe("/api/v1/providers/tavily/secret")
    expect(stub.requests[0].method).toBe("PUT")
    expect(stub.requests[0].body).toEqual({ key: "tvly-live-key-123" })
    expect(Object.keys(stub.requests[0].body as object)).toEqual(["key"])
    expect(result).toEqual(wire)
  })

  it("deleteSecret() DELETEs relative .../secret (idempotent)", async () => {
    const wire = secretStatusFixture({ presence: "missing", fingerprint: null })
    const stub = installFetchStub(() => ok(wire))

    const result = await service.deleteSecret("tavily")

    expect(stub.requests[0].url).toBe("/api/v1/providers/tavily/secret")
    expect(stub.requests[0].method).toBe("DELETE")
    expect(result).toEqual(wire)
  })

  it("getDashboard() defaults to limit=50 and honors explicit limits", async () => {
    const wire = dashboardFixture()
    const stub = installFetchStub(() => ok(wire))

    await service.getDashboard()
    expect(stub.requests[0].url).toBe("/dashboard?limit=50")
    expect(stub.requests[0].method).toBe("GET")

    await service.getDashboard(10)
    expect(stub.requests[1].url).toBe("/dashboard?limit=10")
  })

  it("never calls an absolute backend host literal in any method", async () => {
    installFetchStub((req) => {
      if (req.url.startsWith("/search")) return ok(searchResponseFixture())
      if (req.url.startsWith("/fetch")) return ok(fetchResponseFixture())
      if (req.url.startsWith("/dashboard")) return ok(dashboardFixture())
      if (req.url === "/api/v1/routing/config") return ok(routingConfigFixture())
      if (req.url === "/api/v1/providers") return ok(allProvidersFixture())
      if (req.url.endsWith("/test")) return ok(providerTestFixture())
      if (req.url.endsWith("/reset")) return ok(breakerResetFixture())
      if (req.url.endsWith("/secret"))
        return ok(req.method === "DELETE"
          ? secretStatusFixture({ presence: "missing" })
          : secretStatusFixture())
      return ok(allProvidersFixture()[0])
    })

    await service.search({
      query: "q",
      limit: 5,
      language: null,
      country_code: null,
      domains: [],
      routing: { mode: "auto", providers: [], allow_fallback: true },
    } as never)
    await service.fetchDoc({
      url: "https://example.com/doc",
      max_chars: null,
      routing: { mode: "auto", providers: [], allow_fallback: true },
    } as never)
    await service.listProviders()
    await service.getRoutingConfig()
    await service.updateRoutingConfig({
      fallback_policy: "chained",
      cost_optimization_preset: "balanced",
      max_attempts: 3,
    } as never)
    await service.patchProvider("brave", { enabled: true } as never)
    await service.testProvider("brave")
    await service.resetCircuitBreaker("brave")
    await service.putSecret("brave", "k")
    await service.deleteSecret("brave")
    await service.getDashboard()

    const fetchMock = vi.mocked(globalThis.fetch)
    for (const call of fetchMock.mock.calls) {
      const url = String(call[0])
      expect(url).not.toContain("127.0.0.1")
      expect(url.startsWith("/")).toBe(true)
    }
  })

  it("maps FastAPI 422 to ApiError with joined 'loc: msg' detail", async () => {
    installFetchStub(() =>
      err(422, {
        detail: [{ loc: ["body", "limit"], msg: "Input should be less than or equal to 100" }],
      })
    )

    const failure = await service
      .search({
        query: "q",
        limit: 500,
        language: null,
        country_code: null,
        domains: [],
        routing: { mode: "auto", providers: [], allow_fallback: true },
      } as never)
      .then(
        () => null,
        (error: unknown) => error as ApiError
      )

    expect(failure).toBeInstanceOf(ApiError)
    expect(failure!.status).toBe(422)
    expect(failure!.detail).toBe("body.limit: Input should be less than or equal to 100")
  })

  it("maps 503/404/500 string details to ApiError with status and detail", async () => {
    for (const [status, detail] of [
      [503, "provider brave is disabled; enable it before testing"],
      [404, "unknown provider 'nope'"],
      [500, "adapter exploded"],
    ] as const) {
      installFetchStub(() => err(status, { detail }))
      const failure = await service.listProviders().then(
        () => null,
        (error: unknown) => error as ApiError
      )
      expect(failure).toBeInstanceOf(ApiError)
      expect(failure!.status).toBe(status)
      expect(failure!.detail).toBe(detail)
      vi.unstubAllGlobals()
    }
  })

  it("maps a network TypeError to ApiError status 0", async () => {
    installFetchStub(() => {
      throw new TypeError("fetch failed")
    })

    const failure = await service.listProviders().then(
      () => null,
      (error: unknown) => error as ApiError
    )

    expect(failure).toBeInstanceOf(ApiError)
    expect(failure!.status).toBe(0)
    expect(failure!.detail).toContain("API unreachable")
  })
})

/**
 * Trace read API: the Activity list stays summary-only while detail carries
 * the disclosed query, results, and stage timeline. Exact relative URLs,
 * query encoding, AbortSignal forwarding, and 404/error mapping.
 */
describe("FreeSearchApiService traces", () => {
  const service = new FreeSearchApiService()

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it("listTraces() GETs relative /api/v1/traces with no query by default", async () => {
    const wire = traceListFixture()
    const stub = installFetchStub(() => ok(wire))

    const result = await service.listTraces()

    expect(stub.requests).toHaveLength(1)
    expect(stub.requests[0].url).toBe("/api/v1/traces")
    expect(stub.requests[0].method).toBe("GET")
    expect(stub.requests[0].bodyText).toBeUndefined()
    expect(result).toEqual(wire)
  })

  it("listTraces() encodes limit/operation/outcome filters as query params", async () => {
    const stub = installFetchStub(() => ok(traceListFixture()))

    await service.listTraces({ limit: 50, operation: "fetch", outcome: "error" })

    expect(stub.requests[0].url).toBe(
      "/api/v1/traces?limit=50&operation=fetch&outcome=error"
    )
    expect(stub.requests[0].method).toBe("GET")
  })

  it("listTraces() forwards the AbortSignal", async () => {
    const stub = installFetchStub(() => ok(traceListFixture()))
    const controller = new AbortController()

    await service.listTraces({ limit: 10 }, controller.signal)

    expect(stub.requests[0].url).toBe("/api/v1/traces?limit=10")
    expect(stub.requests[0].signal).toBe(controller.signal)
  })

  it("getTrace() GETs the URL-encoded detail path", async () => {
    const wire = traceDetailFixture()
    const stub = installFetchStub((req) => {
      expect(req.url).toBe(
        `/api/v1/traces/${encodeURIComponent("e1c2d3a4b5c6d7e8f9012345678abcde")}`
      )
      expect(req.method).toBe("GET")
      return ok(wire)
    })

    const result = await service.getTrace("e1c2d3a4b5c6d7e8f9012345678abcde")

    expect(stub.requests).toHaveLength(1)
    expect(result).toEqual(wire)
  })

  it("getTrace() encodes hostile trace ids instead of building path segments", async () => {
    const stub = installFetchStub(() => ok(traceDetailFixture()))

    await service.getTrace("a/b?c=d&e=f")

    expect(stub.requests[0].url).toBe(`/api/v1/traces/${encodeURIComponent("a/b?c=d&e=f")}`)
    expect(stub.requests[0].url).not.toContain("?")
  })

  it("getTrace() forwards the AbortSignal", async () => {
    const stub = installFetchStub(() => ok(traceDetailFixture()))
    const controller = new AbortController()

    await service.getTrace("e1c2d3a4b5c6d7e8f9012345678abcde", controller.signal)

    expect(stub.requests[0].signal).toBe(controller.signal)
  })

  it("maps a 404 detail miss to ApiError with status and detail", async () => {
    installFetchStub(() => err(404, { detail: "unknown trace 'deadbeef'" }))

    const failure = await service.getTrace("deadbeef").then(
      () => null,
      (error: unknown) => error as ApiError
    )

    expect(failure).toBeInstanceOf(ApiError)
    expect(failure!.status).toBe(404)
    expect(failure!.detail).toContain("unknown trace")
  })

  it("maps a 500 trace failure to ApiError", async () => {
    installFetchStub(() => err(500, { detail: "trace store unavailable" }))

    const failure = await service.listTraces().then(
      () => null,
      (error: unknown) => error as ApiError
    )

    expect(failure).toBeInstanceOf(ApiError)
    expect(failure!.status).toBe(500)
    expect(failure!.detail).toBe("trace store unavailable")
  })

  it("never calls an absolute backend host literal for trace routes", async () => {
    installFetchStub(() => ok(traceListFixture()))

    await service.listTraces({ limit: 50 })
    await service.getTrace("e1c2d3a4b5c6d7e8f9012345678abcde")

    const fetchMock = vi.mocked(globalThis.fetch)
    for (const call of fetchMock.mock.calls) {
      const url = String(call[0])
      expect(url).not.toContain("127.0.0.1")
      expect(url.startsWith("/")).toBe(true)
    }
  })
})
